#!/usr/bin/env python3
"""Install project-only QR renderer and integrity-checked SILK; no npm/global install."""
from pathlib import Path
import os
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
qr = root / '.runtime/qr-deps'
tmp = root / '.runtime/tmp';tmp.mkdir(parents=True,exist_ok=True)
environment={**os.environ,'TEMP':str(tmp),'TMP':str(tmp),'TMPDIR':str(tmp),'PYTHONUTF8':'1'}
subprocess.run([sys.executable,'-m','pip','install','--target',str(qr),'--upgrade','--no-deps','--no-cache-dir','--retries','1','--timeout','20','qrcode==8.2'],check=True,env=environment)
subprocess.run([sys.executable,str(root / 'scripts/install-silk.py')],cwd=root,check=True)
print('Project QR/SILK dependencies installed. No global environment changed.')
