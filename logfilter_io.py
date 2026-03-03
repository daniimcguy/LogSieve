# logfilter_io.py
from __future__ import annotations

import os
import subprocess


def safe_read_text(path: str) -> str:
    # même logique que ton script actuel (utf-8 puis latin-1 replace) :contentReference[oaicite:2]{index=2}
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


def safe_write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def open_in_vscode(path: str) -> None:
    """Try:
    1) `code` in PATH
    2) local Code.exe fallback (your previous hardcoded path)
    3) os.startfile
    """
    # 1) code in PATH
    try:
        subprocess.Popen(["code", "-r", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    except Exception:
        pass

    # 2) fallback on Code.exe (kept for compatibility) :contentReference[oaicite:3]{index=3}
    vscode = r"C:\Users\minvi\AppData\Local\Programs\Microsoft VS Code\Code.exe"
    if os.path.exists(vscode):
        subprocess.Popen([vscode, "-r", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return

    # 3) last resort
    os.startfile(path)
