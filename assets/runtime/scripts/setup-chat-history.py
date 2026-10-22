"""Enable optional local named-group reading in a deployed Windows Codex assistant."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

def run(args,**kwargs):
    return subprocess.run(args,check=True,encoding='utf-8',capture_output=True,creationflags=0x08000000 if os.name=='nt' else 0,**kwargs)

def load_root(value):
    raw=Path(value).expanduser()
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [raw,*raw.parents]):raise ValueError('Linked deployment refused')
    root=raw.resolve()
    if root==Path(root.anchor):raise ValueError('Drive root refused')
    cfg=json.loads((root/'config/local.json').read_text(encoding='utf-8-sig'))
    manifest=json.loads((root/'.runtime/deployment.json').read_text(encoding='utf-8'))
    if cfg.get('host')!='codex' or manifest.get('host')!='codex' or cfg.get('agentMode') is not True:raise ValueError('This backend requires a deployed Codex assistant')
    return root,cfg

def process_candidates(shell):
    script="""$ErrorActionPreference='Stop'; @(Get-CimInstance Win32_Process -Filter \"Name='Weixin.exe'\" | Where-Object { $_.ExecutablePath } | ForEach-Object { $s=Get-AuthenticodeSignature -LiteralPath $_.ExecutablePath; [pscustomobject]@{pid=$_.ProcessId;path=$_.ExecutablePath;signature=[string]$s.Status;publisher=[string]$s.SignerCertificate.Subject} }) | ConvertTo-Json -Compress"""
    text=run([shell,'-NoLogo','-NoProfile','-Command',script]).stdout.strip()
    rows=json.loads(text) if text else []
    return rows if isinstance(rows,list) else [rows]

def protect_cache(root,shell):
    sid=run([shell,'-NoLogo','-NoProfile','-Command','[Security.Principal.WindowsIdentity]::GetCurrent().User.Value']).stdout.strip()
    if not re.fullmatch(r'S-\d+(?:-\d+)+',sid):raise ValueError('Current user unavailable')
    for name in ['private','snapshots']:
        target=root/'.runtime/chatdb'/name
        if any(p.exists() and (p.is_symlink() or getattr(p,'is_junction',lambda:False)()) for p in [target,*target.parents]):raise ValueError('Linked cache refused')
        target.mkdir(parents=True,exist_ok=True)
        run(['icacls.exe',str(target),'/inheritance:r','/grant:r','*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F','/T','/Q'])

def ensure_dependencies(root,python):
    binary=root/'chatdb/.venv/Scripts/python.exe'
    temp=root/'.runtime/setup-tmp';temp.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'TEMP':str(temp),'TMP':str(temp),'TMPDIR':str(temp),'PYTHONUTF8':'1'}
    if not binary.exists():run([python,'-m','venv',str(root/'chatdb/.venv')],env=env)
    result=subprocess.run([str(binary),'-c','import cryptography,zstandard'],capture_output=True,creationflags=0x08000000)
    if result.returncode:run([str(binary),'-m','pip','install','--disable-pip-version-check','--no-cache-dir','-r',str(root/'chatdb/requirements.txt')],env=env)
    return str(binary)

def write_config(root,cfg):
    path=root/'config/local.json';temporary=path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temporary,path)
    if json.loads(path.read_text(encoding='utf-8'))!=cfg:raise ValueError('Config readback failed')

def configure(args):
    root,cfg=load_root(args.root)
    if args.disable:
        cfg['chatHistory']={**cfg.get('chatHistory',{}),'enabled':False};write_config(root,cfg)
        return {'enabled':False,'restartRequired':True,'chatDataDeleted':False}
    if os.name!='nt':raise ValueError('Local chat database reading requires Windows')
    choices=[Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PowerShell/7/pwsh.exe']
    shell=args.pwsh or shutil.which('pwsh') or next((str(p) for p in choices if p.is_file()),None)
    if not shell:raise ValueError('PowerShell 7 required; supply --pwsh')
    binary=root/'chatdb/.venv/Scripts/python.exe'
    if args.check:
        return {'enabled':bool(cfg.get('chatHistory',{}).get('enabled')),'dependenciesInstalled':binary.is_file(),'privateCachePresent':(root/'.runtime/chatdb/private/database-keys.dpapi').is_file(),'processes':process_candidates(shell),'readsMessages':False}
    binary=ensure_dependencies(root,cfg['pythonPath']);protect_cache(root,shell)
    cache=root/'.runtime/chatdb/private/database-keys.dpapi'
    if cache.exists() and not args.refresh:
        existing=json.loads(run([binary,'-X','utf8',str(root/'chatdb/reader.py'),'--list-groups'],cwd=root).stdout)
        if existing.get('status')!='registered_groups':raise ValueError('Existing cache unavailable; inspect before refreshing')
    else:
        rows=[p for p in process_candidates(shell) if p['signature']=='Valid' and re.search('tencent|腾讯',p['publisher'],re.I)]
        if args.pid:rows=[p for p in rows if p['pid']==args.pid]
        if len(rows)!=1:raise ValueError('Select one running officially signed WeChat process using --pid; check installation if none is verified')
        selected=rows[0];install=str(Path(selected['path']).parent)
        command=[binary,'-X','utf8',str(root/'chatdb/scan.py'),'--pid',str(selected['pid']),'--install-root',install]
        if args.account:command+=['--account',str(Path(args.account).expanduser().resolve())]
        report=json.loads(run(command,cwd=root,timeout=90).stdout)
        if report.get('status')!='config_cipher_keys_verified':raise ValueError('Local database authentication incomplete')
    cfg['chatHistory']={**cfg.get('chatHistory',{}),'enabled':True};write_config(root,cfg)
    return {'enabled':True,'restartRequired':True,'groupsSelectedByUser':True,'source':'computer-synced','wechatModified':False,'networkModified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--pwsh');p.add_argument('--pid',type=int);p.add_argument('--account');p.add_argument('--refresh',action='store_true')
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--enable',action='store_true');mode.add_argument('--disable',action='store_true')
    try:print(json.dumps(configure(p.parse_args()),ensure_ascii=False))
    except Exception as e:
        code=str(e) if isinstance(e,ValueError) else 'CHAT_HISTORY_SETUP_'+type(e).__name__.upper()
        print(json.dumps({'status':'failed','reason':code},ensure_ascii=False));raise SystemExit(1)
