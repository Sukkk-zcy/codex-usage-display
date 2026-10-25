"""Package the built EXE with project and installed dependency licenses.

Run with the interpreter used to build the EXE:
  companion/.venv/Scripts/python.exe tools/package_windows.py
"""
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    exe = ROOT/'dist/MagpieDisplay.exe'
    if not exe.is_file():
        raise SystemExit('Build the desktop client first.')
    output = ROOT/'dist/MagpieDisplay-1.3.1-windows-x64.zip'
    package_root = 'MagpieDisplay-1.3.1'
    python_license = Path(sys.base_prefix)/'LICENSE.txt'
    tk_license = Path(sys.base_prefix)/'tcl/tk8.6/license.terms'
    if not python_license.exists() or not tk_license.exists():
        raise SystemExit('Cannot find Python/Tk licenses in the build interpreter.')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        def add(path, destination):
            archive.write(path, f'{package_root}/{destination}')

        add(exe, 'MagpieDisplay.exe')
        for name in ('LICENSE','LICENSE.magpie-usage-display','LICENSE.dashboard-font',
                     'THIRD_PARTY_NOTICES.md','README.md','README.en.md','CHANGELOG.md'):
            add(ROOT/name, name)
        for path in (ROOT/'docs').rglob('*'):
            if path.is_file():
                add(path, path.relative_to(ROOT).as_posix())
        for path in (ROOT/'preview/magpie_dashboard').glob('*'):
            if path.is_file():
                add(path, path.relative_to(ROOT).as_posix())
        for path in (ROOT/'LICENSES').glob('*'):
            add(path, path.relative_to(ROOT).as_posix())
        add(python_license, 'LICENSES/Python-LICENSE.txt')
        add(tk_license, 'LICENSES/Tk-license.terms')
        dependencies = []
        for dist in metadata.distributions():
            name = dist.metadata['Name']
            dependencies.append({'name': name, 'version': dist.version})
            for path in dist.files or []:
                if any(word in path.name.lower() for word in ('license','copying','notice')):
                    source = Path(dist.locate_file(path))
                    if source.is_file():
                        # Normalize traversing paths from wheel RECORD entries.
                        relative = '/'.join(part for part in path.parts if part not in ('.','..'))
                        add(source, f'LICENSES/dependencies/{name}/{relative}')
        archive.writestr(f'{package_root}/BUILD-DEPENDENCIES.json',
                         json.dumps({'python': sys.version.split()[0],
                                     'packages': sorted(dependencies, key=lambda x:x['name'].lower())}, indent=2))
        archive.writestr(f'{package_root}/START-HERE.txt',
                         'Magpie Display 1.3.1 - Windows x64\n\n'
                         'Extract this entire folder, keep the license files, and run MagpieDisplay.exe.\n'
                         'Run a compatible Magpie Agent at http://127.0.0.1:3425.\n'
                         'First pair Magpie Display in Windows Bluetooth Settings using the code on the display.\n'
                         'Then click Start sync in the client.\n\n'
                         'Documentation and source: https://github.com/Sukkk-zcy/codex-usage-display\n'
                         'Firmware must be built/flashed separately with PlatformIO; see the repository README.\n'
                         'The EXE is unsigned. See docs/VALIDATION.md for hardware verification limits.\n')
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(f'{checksum}  {output.name}\n', encoding='ascii')
    print(f'{output.name}: {output.stat().st_size:,} bytes; SHA256 {checksum}')


if __name__ == '__main__':
    main()
