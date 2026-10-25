"""Windows desktop controller; all Tk calls remain on the main thread."""
import argparse
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

from .constants import DEVICE_NAME
from .desktop_worker import DesktopWorker
from .magpie_client import MagpieClient
from .runtime import data_directory, load_settings, save_settings

BG = "#0b141b"
CARD = "#14232e"
TRACK = "#263b49"
TEXT = "#edf3f5"
MUTED = "#94a8b5"
TEAL = "#46dbbf"
BLUE = "#839fff"
AMBER = "#ffc46b"
RED = "#ff7987"
TITLE = "Magpie Display · 额度看板"


def countdown(reset_at, now=None):
    if not reset_at:
        return "等待重置时间"
    seconds = reset_at - (int(time.time()) if now is None else now)
    if seconds <= 0:
        return "已到重置时刻，等待接口更新"
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days} 天 {hours} 小时后重置"
    if hours:
        return f"{hours} 小时 {minutes} 分后重置"
    return f"{minutes} 分 {seconds % 60} 秒后重置"


def startup_command():
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable, "--start", "--minimized"])
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    entry = Path(__file__).resolve().parents[1] / "desktop_entry.py"
    return subprocess.list2cmdline([str(pythonw), str(entry), "--start", "--minimized"])


def startup_enabled():
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "MagpieUsageDisplay")
        return True
    except OSError:
        return legacy_startup_path().exists()


def legacy_startup_path():
    return Path(os.environ.get("APPDATA", str(Path.home()))) / "Microsoft/Windows/Start Menu/Programs/Startup/Magpie Usage Display.lnk"


def set_startup(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled:
            winreg.SetValueEx(key, "MagpieUsageDisplay", 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, "MagpieUsageDisplay")
            except FileNotFoundError:
                pass
    # Replace the earlier CLI startup configuration when the user toggles this.
    legacy_startup_path().unlink(missing_ok=True)


class QuotaCard(tk.Canvas):
    def __init__(self, parent, title, subtitle, accent):
        super().__init__(parent, bg=CARD, highlightthickness=0, height=244)
        self.title, self.subtitle, self.accent = title, subtitle, accent
        self.percent, self.reset_at, self.stale = -1, 0, False
        self.display_percent = 0.0
        self.bind("<Configure>", lambda _: self.draw())

    def draw(self):
        self.delete("all")
        w = max(self.winfo_width(), 280)
        x, y, radius = 87, 123, 57
        color = MUTED if self.stale or self.percent < 0 else RED if self.percent <= 20 else self.accent
        self.create_text(22, 25, text=self.title, anchor="w", fill=TEXT, font=("Microsoft YaHei UI", 13, "bold"))
        self.create_text(w-20, 25, text=self.subtitle, anchor="e", fill=MUTED, font=("Segoe UI", 10))
        box = (x-radius, y-radius, x+radius, y+radius)
        self.create_arc(box, start=-60, extent=300, style="arc", outline=TRACK, width=9)
        if self.percent >= 0 and self.display_percent > 0:
            self.create_arc(box, start=240, extent=-3*self.display_percent, style="arc", outline=color, width=9)
        value = "--" if self.percent < 0 else str(round(self.display_percent))
        self.create_text(x, y-5, text=value, fill=TEXT, font=("Segoe UI", 34, "bold"))
        self.create_text(x, y+30, text="剩余 %" if self.percent >= 0 else "额度未知", fill=color, font=("Microsoft YaHei UI", 10))
        self.create_text(167, 91, text="重置时间", anchor="w", fill=MUTED, font=("Microsoft YaHei UI", 10))
        reset = time.localtime(self.reset_at) if self.reset_at else None
        date = time.strftime("%m 月 %d 日", reset) if reset else "-- 月 -- 日"
        clock = time.strftime("%H:%M", reset) if reset else "--:--"
        self.create_text(167, 118, text=clock, anchor="w", fill=TEXT, font=("Segoe UI", 24, "bold"))
        self.create_text(167, 149, text=date, anchor="w", fill=MUTED, font=("Microsoft YaHei UI", 10))
        self.create_line(22, 199, w-22, 199, fill=TRACK)
        self.create_text(22, 220, text=countdown(self.reset_at), anchor="w", fill=color, font=("Microsoft YaHei UI", 10))

    def tick(self):
        target = max(0, self.percent)
        if abs(self.display_percent-target) < 0.2:
            self.display_percent = float(target)
        else:
            self.display_percent += (target-self.display_percent)*0.18
        self.draw()


class DesktopApp:
    def __init__(self, root, args):
        self.root = root
        self.events = queue.Queue()
        self.worker = DesktopWorker(self.events)
        self.closing = False
        self.stopping = False
        self.pairing_mode = False
        self.pairing_requested = False
        self.last_snapshot = None
        self.api_ok = False
        self.ble_phase = "stopped"
        settings = load_settings()
        self.url = tk.StringVar(value=settings.get("url", "http://127.0.0.1:3425"))
        self.device = tk.StringVar(value=settings.get("device", DEVICE_NAME))
        self.autostart = tk.BooleanVar(value=startup_enabled())
        self.status = tk.StringVar(value="尚未开始同步")
        self.detail = tk.StringVar(value="打开 Magpie Agent 后，点击开始同步。")
        self.updated = tk.StringVar(value="正在读取本机额度…")
        root.title(TITLE)
        root.geometry("820x780")
        root.minsize(780, 780)
        root.configure(bg=BG)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "assets")) / "magpie.ico"
        if icon.exists():
            root.iconbitmap(str(icon))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._styles()
        self._layout()
        self.worker.probe(self.url.get())
        root.after(100, self.poll)
        if args.start:
            root.after(300, self.start)
        if args.minimized:
            root.after(400, root.iconify)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(16, 9), background=TRACK, foreground=TEXT, borderwidth=0)
        style.map("TButton", background=[("active", "#355065"), ("disabled", "#17252e")], foreground=[("disabled", "#5b7180")])
        style.configure("Accent.TButton", background=TEAL, foreground=BG, font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#6aead0"), ("disabled", "#233d3d")], foreground=[("disabled", MUTED)])
        style.configure("TEntry", fieldbackground=BG, foreground=TEXT, bordercolor=TRACK, insertcolor=TEXT, padding=8)
        style.map("TEntry", fieldbackground=[("disabled", CARD)], foreground=[("disabled", MUTED)])
        style.configure("TCheckbutton", background=BG, foreground=MUTED, font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", BG)], foreground=[("active", TEXT)])

    def label(self, parent, text=None, variable=None, size=10, color=MUTED, bold=False, **kw):
        label = tk.Label(parent, text=text, textvariable=variable, font=("Microsoft YaHei UI", size, "bold" if bold else "normal"), fg=color, bg=parent["bg"], **kw)
        return label

    def _layout(self):
        shell = tk.Frame(self.root, bg=BG)
        shell.pack(fill="both", expand=True, padx=28, pady=22)
        heading = tk.Frame(shell, bg=BG)
        heading.pack(fill="x")
        self.label(heading, "●", size=20, color=TEAL).pack(side="left", padx=(0, 10))
        self.label(heading, "magpie", size=24, color=TEXT, bold=True).pack(side="left")
        self.label(heading, "DISPLAY / CODEX · 1.3.1", size=10).pack(side="right", pady=(13, 0))
        self.label(shell, "你的用量，一眼可见。", size=11).pack(anchor="w", pady=(2, 18))
        cards = tk.Frame(shell, bg=BG)
        cards.pack(fill="x")
        cards.columnconfigure((0, 1), weight=1, uniform="quota")
        self.short = QuotaCard(cards, "5 小时额度", "5H", TEAL)
        self.week = QuotaCard(cards, "每周额度", "WEEK", BLUE)
        self.short.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.week.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.label(shell, variable=self.updated, size=9).pack(anchor="w", pady=(9, 17))
        state = tk.Frame(shell, bg=CARD, padx=18, pady=14)
        state.pack(fill="x")
        line = tk.Frame(state, bg=CARD)
        line.pack(fill="x")
        self.indicator = self.label(line, "●", size=12, color=AMBER)
        self.indicator.pack(side="left", padx=(0, 8))
        self.label(line, variable=self.status, size=12, color=TEXT, bold=True).pack(side="left")
        self.api_label = self.label(line, "API · 检查中", size=9)
        self.api_label.pack(side="right")
        self.label(state, variable=self.detail, size=9, anchor="w", justify="left", wraplength=674).pack(fill="x", pady=(7, 0))
        settings = tk.Frame(shell, bg=BG)
        settings.pack(fill="x", pady=(17, 0))
        settings.columnconfigure(1, weight=1)
        self.label(settings, "Magpie 地址").grid(row=0, column=0, sticky="w", padx=(0, 16), pady=5)
        self.url_entry = ttk.Entry(settings, textvariable=self.url, font=("Segoe UI", 10))
        self.url_entry.grid(row=0, column=1, sticky="ew", pady=5)
        self.label(settings, "蓝牙设备名").grid(row=1, column=0, sticky="w", padx=(0, 16), pady=5)
        self.device_entry = ttk.Entry(settings, textvariable=self.device, font=("Segoe UI", 10))
        self.device_entry.grid(row=1, column=1, sticky="ew", pady=5)
        controls = tk.Frame(shell, bg=BG)
        controls.pack(fill="x", pady=(16, 12))
        self.start_button = ttk.Button(controls, text="开始同步", command=self.start, style="Accent.TButton")
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="停止同步", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=9)
        ttk.Button(controls, text="立即刷新", command=self.refresh).pack(side="left")
        ttk.Button(controls, text="日志", command=self.open_logs).pack(side="right")
        ttk.Button(controls, text="配对 / 蓝牙设置", command=self.bluetooth).pack(side="right", padx=9)
        ttk.Checkbutton(shell, text="登录 Windows 后自动同步", variable=self.autostart, command=self.toggle_startup).pack(anchor="w")
        self.label(shell, "最小化后继续同步 · 关闭窗口停止同步 · 首次配对请在 Windows 蓝牙设置输入屏幕验证码", size=9).pack(anchor="w", pady=(10, 0))

    def start(self):
        if self.closing or self.worker.running:
            return
        try:
            url, device = self.url.get().strip().rstrip("/"), self.device.get().strip()
            MagpieClient(url)
            if not device:
                raise ValueError("请填写显示屏的蓝牙设备名。")
            save_settings(url, device)
            self.pairing_mode = self.pairing_requested = False
            self.worker.start(url, device)
            self.stopping = False
            self.status.set("正在启动同步")
            self.detail.set("检查本机 Magpie 接口，并搜索附近的显示器。")
            self.set_controls(True)
        except Exception as error:
            self.status.set("无法启动")
            self.detail.set(str(error))

    def stop(self):
        self.stopping = True
        self.worker.stop()
        self.stop_button.configure(state="disabled")
        self.status.set("正在停止同步…")
        self.detail.set("正在断开蓝牙连接，请稍候。")

    def set_controls(self, running):
        self.start_button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running and not self.stopping else "disabled")
        for entry in (self.url_entry, self.device_entry):
            entry.configure(state="disabled" if running else "normal")

    def refresh(self):
        if self.closing or self.stopping:
            return
        if not self.worker.refresh():
            self.worker.probe(self.url.get().strip())

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "snapshot":
                    self.last_snapshot = value
                    self.short.percent, self.short.reset_at = value.short_remaining_percent, value.short_reset_at
                    self.week.percent, self.week.reset_at = value.weekly_remaining_percent, value.weekly_reset_at
                elif kind == "api":
                    self.api_ok, message = value
                    self.api_label.configure(text="API · 正常" if self.api_ok else "API · 不可用", fg=TEAL if self.api_ok else RED)
                    if not self.api_ok:
                        self.detail.set("Magpie 接口不可用，请确认 Agent 已运行。" + message[:160])
                elif kind == "ble" and not self.stopping and not self.closing and not self.pairing_mode:
                    self.ble_phase, message = value
                    titles = {"scanning": "正在寻找显示器", "connecting": "正在连接显示器", "reconnecting": "正在恢复显示器连接", "recovering": "正在恢复重启后的连接", "waiting": "等待显示器上线", "connected": "正在同步", "disconnected": "等待重新连接", "error": "蓝牙连接异常"}
                    self.status.set(titles.get(self.ble_phase, message))
                    self.detail.set("显示器已连接，每 15 秒更新；中键也可刷新。" if self.ble_phase == "connected" else message[:220])
                    self.indicator.configure(fg=TEAL if self.ble_phase == "connected" else AMBER)
                elif kind == "running" and not value:
                    self.set_controls(False)
                    if self.stopping:
                        self.status.set("同步已停止")
                        self.detail.set("点击开始同步即可重新连接。")
                    self.stopping = False
                    self.indicator.configure(fg=MUTED)
                    if self.pairing_requested and not self.closing:
                        self.enter_pairing_mode()
                elif kind == 'pairing':
                    self.pairing_mode = True
                    self.status.set('自动连接已暂停')
                    self.detail.set(str(value))
                    self.indicator.configure(fg=AMBER)
                elif kind == "error":
                    self.status.set("同步已停止")
                    self.detail.set(str(value))
                    self.indicator.configure(fg=RED)
        except queue.Empty:
            pass
        snapshot = self.last_snapshot
        stale = not self.api_ok or snapshot is None or time.time()-snapshot.generated_at >= 60
        self.short.stale = self.week.stale = stale
        if snapshot:
            clock = time.strftime("%H:%M:%S", time.localtime(snapshot.generated_at))
            self.updated.set(f"{'数据已过期' if stale else '最近读取'} {clock} · 重置时间使用本机时区 · 百分比为剩余额度")
        self.short.tick()
        self.week.tick()
        if self.closing and not self.worker.running:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        if self.worker.running:
            self.stop()
        else:
            self.root.destroy()

    def toggle_startup(self):
        try:
            set_startup(self.autostart.get())
        except OSError as error:
            self.autostart.set(startup_enabled())
            messagebox.showerror("无法修改登录启动设置", str(error), parent=self.root)

    def open_logs(self):
        os.startfile(str(data_directory()))

    def bluetooth(self):
        self.pairing_mode = True
        self.pairing_requested = True
        if self.worker.running:
            self.stop()
            self.status.set('正在释放蓝牙连接…')
            self.detail.set('同步停止后将打开 Windows 配对设置。')
        else:
            self.enter_pairing_mode()

    def enter_pairing_mode(self):
        self.pairing_requested = False
        self.pairing_mode = True
        self.status.set('配对模式 · 同步已暂停')
        self.detail.set('请在 Windows 完成配对；验证码会显示在硬件屏幕上。配对后点击“开始同步”。')
        self.indicator.configure(fg=AMBER)
        os.startfile('ms-settings:bluetooth')


def main():
    parser = argparse.ArgumentParser(description="Magpie Display desktop controller")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--minimized", action="store_true")
    args = parser.parse_args()
    directory = data_directory()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[RotatingFileHandler(directory / "desktop.log", maxBytes=1024*1024, backupCount=2, encoding="utf-8")], force=True)
    logging.info('Desktop client 1.3.1 started; log directory: %s', directory)
    # Prevent multiple windows from competing for configuration and BLE ownership.
    mutex = None
    if sys.platform == "win32":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        mutex = kernel.CreateMutexW(None, False, "Local\\MagpieUsageDisplayDesktop")
        if ctypes.get_last_error() == 183:
            if mutex:
                kernel.CloseHandle(mutex)
            ctypes.windll.user32.MessageBoxW(None, "Magpie Display 已经打开，请在任务栏中找到它。", "Magpie Display", 0x40)
            return
    try:
        root = tk.Tk()
        DesktopApp(root, args)
        root.mainloop()
    except Exception:
        logging.exception("Desktop application failed")
        raise
    finally:
        if mutex:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
