"""Open the real desktop widgets with synthetic data and no API/BLE access.

Run from the repository root: python tools/preview_desktop.py
This preview never loads user settings or enables Windows startup.
"""
import argparse
from dataclasses import replace
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from companion.codex_display.desktop import DesktopApp, TEAL
from companion.codex_display.metrics import build_snapshot


def main():
    with patch('companion.codex_display.desktop.load_settings', return_value={}), \
         patch('companion.codex_display.desktop.startup_enabled', return_value=False), \
         patch('companion.codex_display.desktop.DesktopWorker.probe'), \
         patch('companion.codex_display.desktop.DesktopWorker.start'), \
         patch('companion.codex_display.desktop.save_settings'), \
         patch('companion.codex_display.desktop.set_startup'), \
         patch('companion.codex_display.desktop.os.startfile'):
        root = tk.Tk()
        app = DesktopApp(root, argparse.Namespace(start=False, minimized=False))
        root.title('Magpie Display - Documentation Preview')
        app.status.set('文档预览 · 示例数据')
        app.detail.set('此窗口使用真实客户端组件；未连接 API 或蓝牙，所有数值均为演示。')
        app.api_label.configure(text='API · 演示', fg=TEAL)
        app.indicator.configure(fg=TEAL)
        app.api_ok = True

        def sample():
            now = int(time.time())
            snapshot = replace(build_snapshot({}, {}, now=now),
                               short_remaining_percent=51, short_reset_at=now+7260,
                               weekly_remaining_percent=92, weekly_reset_at=now+259200)
            app.events.put(('snapshot', snapshot))
            root.after(15000, sample)

        sample()
        root.mainloop()


if __name__ == '__main__':
    main()
