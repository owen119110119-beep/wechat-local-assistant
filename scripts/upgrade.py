"""Upgrade a stopped managed installation while preserving local data and configuration."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from deploy import SKILL,POLICY_START,POLICY_END,managed_policy,payload_files

def safe(root,name):
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid managed path')
    path=root/relative
    if any(p.exists() and (p.is_symlink() or getattr(p,'is_junction',lambda:False)()) for p in [path,*path.parents]):raise ValueError('Linked managed path refused')
    if not path.resolve().is_relative_to(root):raise ValueError('Managed path outside target')
    return path

def active(root):
    if os.name!='nt':return False
    env={**os.environ,'WECHAT_UPGRADE_ROOT':str(root)}
    script=r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=New-Object Text.UTF8Encoding; $p=Join-Path $env:WECHAT_UPGRADE_ROOT 'src\gateway.mjs'; $rx='(?:^|\s|")'+[regex]::Escape($p)+'(?:"|\s|$)'; @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.Replace('/','\') -match $rx }).Count"""
    result=subprocess.run([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'),'-NoLogo','-NoProfile','-Command',script],env=env,check=True,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=0x08000000)
    return int(result.stdout.strip())>0

def atomic_write(path,payload):
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.upgrade-tmp')
    try:
        with temporary.open('xb') as f:f.write(payload)
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)

def upgrade(target,check_only=False):
    raw=Path(target).expanduser()
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [raw,*raw.parents]):raise ValueError('Linked target refused')
    root=raw.resolve()
    if root==Path(root.anchor):raise ValueError('Drive root refused')
    manifest_path=safe(root,'.runtime/deployment.json');old=json.loads(manifest_path.read_text(encoding='utf-8'))
    old['files']={name.replace('\\','/'):digest for name,digest in old.get('files',{}).items()}
    host=old.get('host')
    if host not in {'codex','workbuddy'}:raise ValueError('Managed deployment required')
    cfgpath=safe(root,'config/'+('local.json' if host=='codex' else 'profile.json'))
    cfg=json.loads(cfgpath.read_text(encoding='utf-8-sig'));vault=Path(cfg['vaultPath'])
    if not vault.is_dir():raise ValueError('Existing vault missing; configuration preserved')
    if active(root):raise ValueError('Assistant is running; finish pending work and stop it before upgrading')
    source=payload_files(host);writes={};conflicts=[]
    for name,p in source.items():
        destination=safe(root,name);payload=p.read_bytes()
        if destination.exists() and destination.read_bytes()!=payload:
            expected=old.get('files',{}).get(name)
            if expected is None or hashlib.sha256(destination.read_bytes()).hexdigest()!=expected:conflicts.append(name)
        writes[name]=payload
    for name in ['AGENTS.md','workspace/AGENTS.md']:
        path=safe(root,name);text=path.read_text(encoding='utf-8') if path.exists() else ''
        policy=managed_policy(vault)
        if POLICY_START in text or POLICY_END in text:
            if text.count(POLICY_START)!=1 or text.count(POLICY_END)!=1:raise ValueError('Managed policy markers need review')
            start=text.index(POLICY_START);end=text.index(POLICY_END,start)+len(POLICY_END)
            policy=text[:start]+policy.rstrip()+text[end:]
        elif text and hashlib.sha256(path.read_bytes()).hexdigest()!=old.get('files',{}).get(name):conflicts.append(name)
        writes[name]=policy.encode('utf-8')
    if conflicts:raise ValueError('Custom files preserved; merge these before upgrading: '+', '.join(conflicts))
    version=json.loads((SKILL/'assets/runtime/package.json').read_text(encoding='utf-8'))['version']
    if host=='codex' and 'chatHistory' not in cfg:
        cfg['chatHistory']={'enabled':False};writes[cfgpath.relative_to(root).as_posix()]=(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    changed={name:payload for name,payload in writes.items() if not (path:=safe(root,name)).exists() or path.read_bytes()!=payload}
    if check_only:return {'valid':True,'host':host,'version':version,'changedFiles':list(changed),'writes':False}
    backup=safe(root,'.runtime/upgrades/'+version+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'));backup.mkdir(parents=True)
    previous={name:safe(root,name).read_bytes() if safe(root,name).exists() else None for name in changed}
    previous['.runtime/deployment.json']=manifest_path.read_bytes()
    for name,payload in previous.items():
        if payload is not None:
            path=backup/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    applied=[]
    try:
        for name,payload in changed.items():
            path=safe(root,name);path.parent.mkdir(parents=True,exist_ok=True)
            current=path.read_bytes() if path.exists() else None
            if current!=previous[name]:raise ValueError('File changed during upgrade: '+name)
            atomic_write(path,payload);applied.append(name)
            if path.read_bytes()!=payload:raise ValueError('Upgrade readback failed')
        owned=set(source)|{'AGENTS.md','workspace/AGENTS.md',cfgpath.relative_to(root).as_posix()}
        hashes={name:hashlib.sha256(safe(root,name).read_bytes()).hexdigest() for name in owned if safe(root,name).is_file()}
        new={**old,'version':version,'host':host,'files':hashes,'started':False}
        if manifest_path.read_bytes()!=previous['.runtime/deployment.json']:raise ValueError('Manifest changed during upgrade')
        atomic_write(manifest_path,json.dumps(new,ensure_ascii=False,indent=2).encode('utf-8'));applied.append('.runtime/deployment.json')
        if json.loads(manifest_path.read_text(encoding='utf-8'))!=new:raise ValueError('Manifest readback failed')
    except Exception:
        for name in reversed(applied):
            payload=previous[name]
            path=safe(root,name)
            if payload is None:path.unlink(missing_ok=True)
            else:path.write_bytes(payload)
        raise
    return {'upgraded':True,'version':version,'host':host,'changedFiles':len(changed),'backup':str(backup),'started':False,'credentialsPreserved':True,'vaultUnchanged':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--target',required=True);parser.add_argument('--check-only',action='store_true')
    try:
        args=parser.parse_args();print(json.dumps(upgrade(args.target,args.check_only),ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'status':'failed','reason':str(e) if isinstance(e,ValueError) else type(e).__name__},ensure_ascii=False));raise SystemExit(1)
