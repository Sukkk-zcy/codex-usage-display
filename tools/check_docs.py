"""Check local Markdown destinations and decode documentation image assets."""
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    errors = []
    docs = list(ROOT.glob('*.md')) + list((ROOT/'docs').rglob('*.md'))
    for doc in docs:
        for link in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', doc.read_text(encoding='utf-8')):
            path = urlsplit(link.strip('<>')).path
            if not path or urlsplit(link).scheme:
                continue
            target = (doc.parent/unquote(path)).resolve()
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f'{doc.relative_to(ROOT)}: missing local destination {link}')
    assets = list((ROOT/'docs/images').glob('*')) + list((ROOT/'preview/magpie_dashboard').glob('*'))
    for asset in assets:
        if asset.suffix == '.svg':
            ET.parse(asset)
        elif asset.suffix.lower() in ('.png', '.jpg', '.gif'):
            with Image.open(asset) as image:
                image.verify()
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f'Checked {len(docs)} Markdown files and {len(assets)} image assets.')


if __name__ == '__main__':
    main()
