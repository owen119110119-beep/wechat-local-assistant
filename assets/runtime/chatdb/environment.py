from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time

def data_root():
    candidates = []
    appdata = Path(os.environ.get('APPDATA', '')) / 'Tencent' / 'xwechat'
    for folder in [appdata / 'config', appdata]:
        if not folder.is_dir():
            continue
        for f in folder.glob('*.ini'):
            if f.is_symlink() or f.stat().st_size > 8192:
                continue
            raw = f.read_bytes()
            for encoding in ['utf-8-sig', 'gbk']:
                try:
                    s = raw.decode(encoding).strip()
                except UnicodeDecodeError:
                    continue
                if len(s) > 2 and s[1] == ':' and (s[2] in '/\\'):
                    candidates.append(Path(s))
    home = Path(os.environ.get('USERPROFILE', ''))
    candidates += [home / 'Documents', home]
    hits = []
    for base in candidates:
        for root in [base, base / 'xwechat_files']:
            if not root.is_dir() or root.is_symlink():
                continue
            accounts = [p for p in root.iterdir() if p.is_dir() and (p / 'db_storage').is_dir()]
            if accounts and root.resolve() not in hits:
                hits.append(root.resolve())
    if len(hits) != 1:
        raise RuntimeError('CHATDB_DATA_ROOT_NOT_UNIQUE')
    return hits[0]
