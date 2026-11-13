"""PDF copy of an HTML report through a headless Chromium browser (Edge or Chrome).

Persian shaping and right-to-left layout need a real browser engine; when
none is found the HTML report is still produced and the gap is reported.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_browser() -> str | None:
    for path in CANDIDATES:
        if os.path.isfile(path):
            return path
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def html_to_pdf(html_path: Path, timeout: int = 90) -> tuple[Path | None, str | None]:
    """(pdf path, None) on success, (None, reason) otherwise."""
    browser = find_browser()
    if not browser:
        return None, "مرورگر Chromium (Edge/Chrome) برای ساخت PDF یافت نشد"
    pdf = html_path.with_suffix(".pdf")
    if pdf.exists():
        return None, "فایل PDF هم‌نام از قبل وجود دارد؛ بازنویسی نشد"
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--no-first-run",
           f"--print-to-pdf={pdf}", html_path.resolve().as_uri()]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"ساخت PDF ناموفق: {type(exc).__name__}"
    if pdf.exists() and pdf.stat().st_size > 1000:
        return pdf, None
    return None, "مرورگر فایل PDF تولید نکرد"
