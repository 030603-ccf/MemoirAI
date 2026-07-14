"""Runtime hook: copy api-ms-win-crt-*.dll from Windows downlevel dir to _MEIPASS.

On Windows 10/11, api-ms-win-crt-*.dll (Universal CRT API set shims) are in
C:\\Windows\\System32\\downlevel\\ not in System32\\. When PyInstaller freezes
a torch-dependent exe, shm.dll / torch_cpu.dll / torch_python.dll / etc. can't
find these shims and return [WinError 127] proc not found. Copy them to _MEIPASS
so the frozen process can find them alongside the torch DLLs.
"""
import os
import shutil
import sys

if getattr(sys, "frozen", False):
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        src = r"C:\Windows\System32\downlevel"
        if os.path.isdir(src):
            for name in os.listdir(src):
                if name.startswith("api-ms-win-crt-") and name.endswith(".dll"):
                    dst = os.path.join(meipass, name)
                    if not os.path.exists(dst):
                        try:
                            shutil.copy(os.path.join(src, name), dst)
                        except OSError:
                            pass
