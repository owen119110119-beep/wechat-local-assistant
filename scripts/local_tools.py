"""Resolve deployment-owned helpers without borrowing another Skill's files."""
import json
import os
from pathlib import Path
import shutil


def ffmpeg_path():
    owned = Path(__file__).resolve().parents[1]/'.runtime/bin'/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    if owned.is_file():return str(owned)
    existing = shutil.which('ffmpeg')
    if existing:return existing
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def browser_options(root):
    choice = Path(root)/'.runtime/browser-choice.json'
    if choice.is_file() and json.loads(choice.read_text(encoding='utf-8')).get('engine') == 'chromium':return {}
    candidates = [Path(os.environ[key])/'Google/Chrome/Application/chrome.exe'
                  for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA') if os.environ.get(key)]
    return {'channel': 'chrome'} if any(p.is_file() for p in candidates) else {}
