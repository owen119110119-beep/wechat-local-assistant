#!/usr/bin/env python3
"""Non-destructive deployment; no login, token reads, service start or global changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SKILL = Path(__file__).resolve().parents[1]
WINDOWS_CODEX_COMPONENTS = ['codex-code-mode-host.exe', 'codex-command-runner.exe', 'codex-windows-sandbox-setup.exe']
POLICY_START='<!-- wechat-local-assistant:policy:start -->'
POLICY_END='<!-- wechat-local-assistant:policy:end -->'

def managed_policy(vault):
    policy=(SKILL/'references/interaction.md').read_text(encoding='utf-8')
    policy+='\n\n当前知识库绝对路径：'+str(vault)+'\n'
    policy+='\n素材读取使用部署目录scripts/content_reader.py，按用户目标读取其正文及本机证据；群读取仅在已配置的Codex入口提供chatHistory时使用给定程序，不自行编造授权。\n'
    return POLICY_START+'\n'+policy+'\n'+POLICY_END+'\n'

def payload_files(host):
    runtime=SKILL/'assets/runtime'
    if host=='codex':
        result={p.relative_to(runtime).as_posix():p for p in runtime.rglob('*') if p.is_file()}
        for name in ['pair-weixin.mjs','read_wechat_article.py','install-dependencies.mjs','install-dependencies.py']:
            result['scripts/'+name]=SKILL/'scripts'/name
        return result
    shared=['article_media.py','content_reader.py','browser_provider.py','isaac64.py','THIRD_PARTY_NOTICES.md','requirements-content.txt','requirements-media.txt','requirements-voice.lock.txt','setup-content.py','transcribe.py']
    return {**{'scripts/'+name:runtime/'scripts'/name for name in shared},'scripts/read_wechat_article.py':SKILL/'scripts/read_wechat_article.py'}

def codex_runtime_complete(path):
    return path.is_file() and (os.name != 'nt' or all((path.parent / name).is_file() for name in WINDOWS_CODEX_COMPONENTS))

def find_binary(kind, explicit=None):
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise ValueError(f'{kind} executable missing')
        if kind == 'codex' and not codex_runtime_complete(p):
            raise ValueError('Codex execution components missing; select a complete official installation')
        return str(p)
    local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local'))
    cache = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    codex_roots={local / 'OpenAI/Codex/bin',Path.home() / 'AppData/Local/OpenAI/Codex/bin'}
    fixed = {'node': [cache / 'node/bin/node.exe'], 'python': [cache / 'python/python.exe'],
             'codex': sorted({p for base in codex_roots for p in base.glob('*/codex.exe')}, key=lambda p:p.stat().st_mtime, reverse=True)}
    for p in fixed.get(kind, []):
        if p.is_file() and (kind != 'codex' or codex_runtime_complete(p)):
            return str(p.resolve())
    found = shutil.which(kind)
    if found:
        if kind == 'codex' and not codex_runtime_complete(Path(found)):
            raise ValueError('Codex execution components missing; repair the official installation')
        return str(Path(found).resolve())
    if kind == 'python':
        return sys.executable
    raise ValueError(f'{kind} missing; install official runtime or supply --{kind}')

def initialize_vault(vault):
    for path in ['.obsidian', '我的随手转发/普通信息库', '我的随手转发/重点关注', '待办事项']:
        target = vault / path
        target.mkdir(parents=True, exist_ok=True)

def deploy(args):
    target, vault = Path(args.target).expanduser().resolve(), Path(args.vault).expanduser().resolve()
    if target == vault or target in vault.parents or vault in target.parents:
        raise ValueError('Use separate deployment and vault directories')
    if target == Path(target.anchor) or vault == Path(vault.anchor):
        raise ValueError('Drive roots cannot be deployment/vault targets')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('Non-empty deployment target refused; existing files preserved')
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in [target,vault,*target.parents,*vault.parents]):
        raise ValueError('Linked/junction targets refused')
    cfg = {'host':args.host, 'vaultPath':str(vault)}
    if args.host == 'codex':
        cfg.update(nodePath=find_binary('node', args.node), pythonPath=find_binary('python', args.python), codexPath=find_binary('codex', args.codex))
        version = subprocess.run([cfg['nodePath'],'-p',"process.versions.node"], capture_output=True, text=True, encoding='utf-8', check=True).stdout.strip()
        parts = [int(n) for n in version.split('.')[:2]]
        if parts < [22,13]:
            raise ValueError('Node >=22.13 required for node:sqlite')
        subprocess.run([cfg['nodePath'],'--input-type=module','-e',"import {DatabaseSync} from 'node:sqlite'; const d=new DatabaseSync(':memory:');d.close()"],capture_output=True,check=True)
        check = subprocess.run([cfg['codexPath'],'--version'],capture_output=True,text=True,encoding='utf-8',check=True).stdout.strip()
        if not check.startswith('codex-cli '):
            raise ValueError('Unexpected Codex executable')
        cfg.update(agentMode=True, agentTimeoutMs=600000, turnTimeoutMs=180000, pollTimeoutMs=40000,
                   replyChunkLength=1600, compactAfterTurns=40, compactAfterChars=50000,
                   credentialsSource=str(target / '.runtime/credentials'),
                   articleReaderPath=str(target / 'scripts/read_wechat_article.py'),
                   voicePythonPath=str(target / '.venv/Scripts/python.exe'),
                   botProjectId=args.project_id or None,chatHistory={'enabled':False},
                   writableRoots=[str(target), str(vault)], sessionCwd=str(target / 'workspace'))
    if args.check_only:
        return {'valid':True,'host':args.host,'writes':False}
    target.mkdir(parents=True,exist_ok=True)
    initialize_vault(vault)
    for name,source in payload_files(args.host).items():
        destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    (target / 'config').mkdir(exist_ok=True)
    (target / 'workspace').mkdir(exist_ok=True)
    (target / '.runtime').mkdir(exist_ok=True)
    policy = managed_policy(vault)
    (target / 'AGENTS.md').write_text(policy,encoding='utf-8')
    (target / 'workspace/AGENTS.md').write_text(policy,encoding='utf-8')
    name = 'local.json' if args.host == 'codex' else 'profile.json'
    (target / 'config' / name).write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest = {str(p.relative_to(target)):hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob('*') if p.is_file()}
    version=json.loads((SKILL/'assets/runtime/package.json').read_text(encoding='utf-8'))['version']
    (target / '.runtime/deployment.json').write_text(json.dumps({'version':version,'host':args.host,'files':manifest,'started':False,'paired':False},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'deployed':True,'host':args.host,'target':str(target),'vault':str(vault),'started':False,'paired':False}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',choices=['codex','workbuddy'],required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--vault',required=True)
    for name in ['node','python','codex','project-id']:
        parser.add_argument('--'+name)
    parser.add_argument('--check-only',action='store_true')
    try:
        print(json.dumps(deploy(parser.parse_args()),ensure_ascii=False))
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print(f'Deployment failed: {error}',file=sys.stderr)
        sys.exit(1)
