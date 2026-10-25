import asyncio
import platform
import os
import subprocess
from typing import Awaitable, Callable, Tuple


async def _run(*args: str) -> Tuple[bool, str]:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if platform.system() == "Windows" else {}
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **options,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    except (asyncio.CancelledError, asyncio.TimeoutError) as error:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        if isinstance(error, asyncio.CancelledError):
            raise
        return False, "ACTION TIMED OUT"
    if process.returncode == 0:
        return True, ""
    return False, stderr.decode("utf-8", errors="replace").strip()


async def perform_action(
    action: str, refresh: Callable[[], Awaitable[None]]
) -> Tuple[bool, str]:
    if action not in {"refresh", "focus_magpie"}:
        return False, "NOT ALLOWED"

    if action == "refresh":
        await refresh()
        return True, "UPDATED"

    if platform.system() == "Windows":
        # Only target the running Magpie application. No arbitrary command from BLE.
        script = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MagpieWindow {
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
$p = Get-Process -Name 'magpie','magpie-windows-*' -ErrorAction SilentlyContinue |
     Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -eq 'magpie' } |
     Select-Object -First 1
if ($null -eq $p) { exit 2 }
[MagpieWindow]::ShowWindowAsync($p.MainWindowHandle, 9) | Out-Null
if (-not [MagpieWindow]::SetForegroundWindow($p.MainWindowHandle)) { exit 3 }
'''
        powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                  "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        ok, _ = await _run(powershell, "-NoProfile", "-NonInteractive", "-Command", script)
        return (True, "FOCUSED") if ok else (False, "OPEN MAGPIE ON PC")

    if platform.system() != "Darwin":
        return False, "UNSUPPORTED OS"

    if action == "focus_magpie":
        ok, _ = await _run("open", "-a", "magpie")
        return (True, "FOCUSED") if ok else (False, "APP NOT FOUND")

    raise AssertionError("allowlisted action was not handled")
