"""Enable optional local named-group reading in a deployed Windows Codex assistant."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

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

def module_from(root,name):
    spec=importlib.util.spec_from_file_location('wechat_setup_'+name,root/'chatdb'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def cache_account(root):
    cache=root/'.runtime/chatdb/private/database-keys.dpapi'
    if not cache.is_file():return None
    # Only the account location leaves this function, never any decrypted material.
    return module_from(root,'storage').load_secret('database-keys').get('account')

def discovery(root,cfg,args,shell):
    env=module_from(root,'environment');saved=cfg.get('chatHistory',{})
    remembered=saved.get('accountPath');cache_error=None
    if not remembered:
        try:remembered=cache_account(root)
        except (OSError,RuntimeError,ValueError):cache_error='CHATDB_CACHE_UNAVAILABLE'
    explicit=getattr(args,'account',None);hint=getattr(args,'data_dir',None)
    found=env.discover_accounts([value for value in [explicit,hint] if value],saved=remembered)
    accounts=found['accounts'];account=None;reason=None
    if explicit:
        try:
            location=env.local_directory(explicit)
            if location.name=='db_storage':location=location.parent
            account=next((a for a in accounts if Path(a['accountPath'])==location),None)
        except (ValueError,OSError):pass
        if account is None:reason='account_path_invalid'
    elif hint:
        options=[]
        try:
            location=env.local_directory(hint)
            options=[a for a in accounts if Path(a['accountPath']).is_relative_to(location)]
        except (ValueError,OSError):pass
        if len(options)==1:account=options[0]
        else:reason='multiple_accounts' if options else 'data_not_found'
    elif remembered:
        account=next((a for a in accounts if Path(a['accountPath'])==Path(remembered).resolve()),None)
        if account is None:reason='remembered_path_missing'
    elif len(accounts)==1:account=accounts[0]
    else:reason='multiple_accounts' if accounts else 'data_not_found'
    rows=process_candidates(shell)
    verified=[p for p in rows if p.get('signature')=='Valid' and re.search('tencent|腾讯',p.get('publisher',''),re.I)]
    selected=None
    if args.pid:selected=next((p for p in verified if p['pid']==args.pid),None)
    elif saved.get('installPath'):
        matches=[p for p in verified if Path(p['path']).resolve()==Path(saved['installPath']).resolve()]
        if len(matches)==1:selected=matches[0]
        elif not matches and verified:reason=reason or 'remembered_install_missing'
    elif len(verified)==1:selected=verified[0]
    if selected is None:reason=reason or ('multiple_processes' if len(verified)>1 else 'wechat_not_running' if not rows else 'official_process_unverified')
    guidance={
        'data_not_found':'请在电脑微信设置的文件管理/存储位置查看聊天数据目录，把位置发给助理；无需移动文件或重新安装微信。',
        'multiple_accounts':'找到多个微信数据账号。结合存放位置和用户说明自然询问要整理哪个账号，不根据顺序猜选。',
        'remembered_path_missing':'之前记住的聊天数据目录已不可用。先说明这一变化，询问是否移动过目录，并引导从微信设置提供当前位置；不自动切换其他账号。',
        'account_path_invalid':'提供的位置未找到微信4聊天数据库。请核对设置里的数据存储位置，而不是程序安装目录。',
        'multiple_processes':'发现多个已运行的官方微信，请按安装位置或用户用途自然核对本次使用哪个；内部PID不用发给用户。',
        'wechat_not_running':'请先打开并登录电脑微信，再继续原来的整理任务；不用重新描述群和整理要求。',
        'official_process_unverified':'当前未找到可验证的微信4官方进程。请核对是否正在使用官方Windows微信4版本；不更改或降级微信。',
        'remembered_install_missing':'之前选择的微信程序当前未运行。询问用户是打开原来的微信还是改用当前这个，不自动切换。',
    }
    return {'status':'selection_required' if reason else 'ready_to_enable','reason':reason,'guidance':guidance.get(reason),
            'accounts':accounts,'issues':found['issues'],'processes':verified,'selectedAccount':account,'selectedProcess':selected,
            'enabled':bool(saved.get('enabled')),'cacheIssue':cache_error,'readsMessages':False}

def safe_failure(error):
    if isinstance(error,subprocess.CalledProcessError):
        try:
            value=json.loads(error.stdout or '{}');code=value.get('error') or value.get('reason')
            if isinstance(code,str) and re.fullmatch(r'CHATDB_[A-Z_]+',code):return code
        except (ValueError,TypeError):pass
    if isinstance(error,ValueError):return str(error)
    return 'CHAT_HISTORY_SETUP_'+type(error).__name__.upper()

def continued_request(root,args):
    origin=getattr(args,'continue_delivery',None)
    if not origin:return None
    current=getattr(args,'delivery',None)
    if origin==current or not all(re.fullmatch('[a-f0-9]{64}',v or '') for v in [origin,current]):raise ValueError('CHATDB_CONTINUATION_INVALID')
    def grant(key):
        path=root/'.runtime/chatdb/private/grants'/f'{key}.json'
        if path.is_symlink():raise ValueError('CHATDB_CONTINUATION_INVALID')
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('source')!='wechat-owner-inbox' or value.get('delivery')!=key or not 0<=time.time()-value.get('created',0)<3600:raise ValueError('CHATDB_CONTINUATION_EXPIRED')
        return path,value
    _,previous=grant(origin);path,current=grant(current)
    if not re.fullmatch('[a-f0-9]{64}',current.get('owner','')) or current['owner']!=previous.get('owner'):raise ValueError('CHATDB_CONTINUATION_OWNER_MISMATCH')
    if any(re.search('取消|先不|不要继续|不整理了|停止',text) for text in current.get('texts',[])):raise ValueError('CHATDB_CONTINUATION_CANCELLED')
    value={**current,'texts':list(dict.fromkeys([*previous.get('texts',[]),*current.get('texts',[])])),'sources':list(dict.fromkeys([*previous.get('sources',[]),*current.get('sources',[])]))}
    return path,value

def configure(args):
    root,cfg=load_root(args.root)
    config_path=root/'config/local.json';previous_config=config_path.read_bytes()
    if json.loads(previous_config.decode('utf-8-sig'))!=cfg:raise ValueError('CHATDB_CONFIG_CHANGED_DURING_SETUP')
    if args.disable:
        cfg['chatHistory']={**cfg.get('chatHistory',{}),'enabled':False};write_config(root,cfg)
        return {'enabled':False,'restartRequired':False,'chatDataDeleted':False}
    if os.name!='nt':raise ValueError('Local chat database reading requires Windows')
    choices=[Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/powershell/pwsh.exe',Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PowerShell/7/pwsh.exe']
    shell=args.pwsh or shutil.which('pwsh') or next((str(p) for p in choices if p.is_file()),None)
    if not shell:raise ValueError('PowerShell 7 required; supply --pwsh')
    plan=discovery(root,cfg,args,shell)
    if args.check or plan['status']=='selection_required':return plan
    continuation=continued_request(root,args)
    binary=ensure_dependencies(root,cfg['pythonPath']);protect_cache(root,shell)
    cache=root/'.runtime/chatdb/private/database-keys.dpapi'
    account=plan['selectedAccount']['accountPath'];selected=plan['selectedProcess']
    previous_cache=cache.read_bytes() if cache.exists() else None
    index=root/'.runtime/chatdb/private/groups-index.json';previous_index=index.read_bytes() if index.exists() else None
    config_started=False;grant_before=continuation[0].read_bytes() if continuation else None
    try:
        reused=cache.exists() and not args.refresh and cache_account(root)==account
        if not reused:
            command=[binary,'-X','utf8',str(root/'chatdb/scan.py'),'--pid',str(selected['pid']),'--install-root',str(Path(selected['path']).parent),'--account',account]
            report=json.loads(run(command,cwd=root,timeout=90).stdout)
            if report.get('status')!='config_cipher_keys_verified':raise ValueError('CHATDB_AUTHENTICATION_INCOMPLETE')
            if cache_account(root)!=account:raise ValueError('CHATDB_ACCOUNT_READBACK_FAILED')
        existing=json.loads(run([binary,'-X','utf8',str(root/'chatdb/reader.py'),'--list-groups'],cwd=root).stdout)
        if existing.get('status')!='registered_groups':raise ValueError('CHATDB_CACHE_UNAVAILABLE')
        cfg['chatHistory']={**cfg.get('chatHistory',{}),'enabled':True,'accountPath':account,'installPath':str(Path(selected['path']).resolve())}
        if config_path.read_bytes()!=previous_config:raise ValueError('CHATDB_CONFIG_CHANGED_DURING_SETUP')
        config_started=True;write_config(root,cfg)
        if continuation:
            path,value=continuation;temporary=path.with_suffix('.selection-tmp')
            try:
                temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');os.replace(temporary,path)
                if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('CHATDB_CONTINUATION_READBACK_FAILED')
            finally:temporary.unlink(missing_ok=True)
    except Exception:
        # A failed new selection never replaces the last working account or config.
        if previous_cache is None:cache.unlink(missing_ok=True)
        else:cache.write_bytes(previous_cache)
        if config_started:config_path.write_bytes(previous_config)
        if continuation and grant_before is not None:continuation[0].write_bytes(grant_before)
        if previous_index is None:index.unlink(missing_ok=True)
        else:index.write_bytes(previous_index)
        raise
    return {'status':'enabled','enabled':True,'restartRequired':False,'selectionRemembered':True,'cacheReused':reused,'groupsSelectedByUser':True,'source':'computer-synced','wechatModified':False,'networkModified':False}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--pwsh');p.add_argument('--pid',type=int);p.add_argument('--account');p.add_argument('--data-dir');p.add_argument('--delivery');p.add_argument('--continue-delivery');p.add_argument('--refresh',action='store_true')
    mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--enable',action='store_true');mode.add_argument('--disable',action='store_true')
    try:print(json.dumps(configure(p.parse_args()),ensure_ascii=False))
    except Exception as e:
        code=safe_failure(e)
        print(json.dumps({'status':'failed','reason':code},ensure_ascii=False));raise SystemExit(1)
