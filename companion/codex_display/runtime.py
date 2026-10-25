"""Shared desktop/CLI settings and exclusive ownership of the BLE service."""
import json
import os
from pathlib import Path


def data_directory():
    directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MagpieUsageDisplay"
    directory.mkdir(parents=True, exist_ok=True)
    # Store-distributed Python redirects AppData; return the physical path so
    # Explorer's log-folder button opens the same files Python actually writes.
    return directory.resolve()


class AlreadyRunningError(RuntimeError):
    pass


class ServiceLock:
    def __init__(self, path=None, name="Local\\MagpieUsageDisplaySync"):
        self.path = Path(path) if path else data_directory() / "sync.lock"
        self._native = os.name == "nt" and path is None
        self._handle = None
        self._name = name
        self.file = None

    def __enter__(self):
        if self._native:
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateMutexW(None, False, self._name)
            error = ctypes.get_last_error()
            if not handle:
                raise ctypes.WinError(error)
            if error == 183:
                kernel.CloseHandle(handle)
                raise AlreadyRunningError("已有同步程序在运行，请先停止旧程序或关闭原来的命令窗口。")
            self._kernel, self._handle = kernel, handle
            return self
        self.file = self.path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            self.file = None
            raise AlreadyRunningError("已有同步程序在运行，请先停止旧程序或关闭原来的命令窗口。") from error
        return self

    def __exit__(self, *_):
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None
        if self.file:
            self.file.close()
            self.file = None


def load_settings():
    try:
        value = json.loads((data_directory() / "settings.json").read_text(encoding="utf-8"))
        return {key: value[key] for key in ("url", "device") if isinstance(value.get(key), str)}
    except (OSError, ValueError, AttributeError):
        return {}


def save_settings(url, device):
    path = data_directory() / "settings.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"url": url, "device": device}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
