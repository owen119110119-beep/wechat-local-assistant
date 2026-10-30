"""One entry for deployment and dependency repair; never logs in or starts a bot."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from deploy import deploy, find_binary


def runtime(kind, explicit=None):
    try:
        binary = find_binary(kind, explicit)
        if kind == 'node':
            version = subprocess.run([binary, '-p', 'process.versions.node'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
            if tuple(map(int, version.split('.')[:2])) < (22, 13):raise ValueError('Node >=22.13 required')
        if kind == 'pwsh':
            version = subprocess.run([binary, '-NoProfile', '-Command', '$PSVersionTable.PSVersion.Major'], capture_output=True, text=True, check=True, timeout=15).stdout.strip()
            if int(version) < 7:raise ValueError('PowerShell 7 required')
        return binary
    except (ValueError, OSError, subprocess.SubprocessError):
        if explicit or kind not in {'node', 'pwsh'} or os.name != 'nt':raise
        winget = shutil.which('winget.exe')
        if not winget:raise ValueError('缺少'+kind+'且未找到winget；请从nodejs.org或learn.microsoft.com/powershell安装官方运行时后重试。')
        package = {'node': 'OpenJS.NodeJS.LTS', 'pwsh': 'Microsoft.PowerShell'}[kind]
        result = subprocess.run([winget, 'install', '--id', package, '--exact', '--source', 'winget',
                                 '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity'], capture_output=True, timeout=600)
        if result.returncode:raise ValueError('官方运行时安装未完成：'+kind+'。核对安装权限和网络后重试，保留已有环境。')
        standard = Path(os.environ.get('ProgramFiles','C:/Program Files'))/('nodejs/node.exe' if kind == 'node' else 'PowerShell/7/pwsh.exe')
        return runtime(kind, str(standard) if standard.is_file() else find_binary(kind))


def obsidian_check(shell, check_only=False):
    script = str(Path(__file__).with_name('install-obsidian.ps1'))
    def detect():
        response = subprocess.run([shell, '-NoProfile', '-File', script, '-DetectOnly', '-Json'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25)
        return json.loads(response.stdout) if response.returncode == 0 else {'status': 'unknown'}
    try:
        detected = detect()
        if detected['status'] == 'installed':return {'name': 'obsidian', 'status': 'installed'}
        if detected['status'] != 'not_found' or check_only:return {'name': 'obsidian', 'status': 'needs_user_action', 'reason': detected['status']}
        winget = shutil.which('winget.exe')
        if not winget:return {'name': 'obsidian', 'status': 'needs_user_action', 'reason': 'installer_missing'}
        result = subprocess.run([winget, 'install', '--id', 'Obsidian.Obsidian', '--exact', '--source', 'winget', '--scope', 'user',
                                 '--accept-source-agreements', '--accept-package-agreements', '--disable-interactivity'], capture_output=True, timeout=180)
        verified = detect()
        return {'name': 'obsidian', 'status': 'installed' if verified['status'] == 'installed' else 'needs_user_action', 'reason': 'checked_after_install'}
    except subprocess.TimeoutExpired:return {'name': 'obsidian', 'status': 'needs_user_action', 'reason': 'timeout_check_before_retry'}
    except (OSError, ValueError, KeyError):return {'name': 'obsidian', 'status': 'needs_user_action', 'reason': 'detection_incomplete'}


def install(args):
    if sys.version_info < (3, 10):raise ValueError('需要Python >=3.10；建议使用官方Python 3.12。')
    raw = Path(args.target).expanduser()
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in [raw, *raw.parents]):raise ValueError('请使用无链接的专用部署目录。')
    target = raw.resolve()
    if target == Path(target.anchor):raise ValueError('不能使用磁盘根目录部署。')
    manifest = target/'.runtime/deployment.json'
    if manifest.exists():
        existing = json.loads(manifest.read_text(encoding='utf-8'))
        name = 'local.json' if args.host == 'codex' else 'profile.json'
        cfg = json.loads((target/'config'/name).read_text(encoding='utf-8-sig'))
        if existing['host'] != args.host or Path(cfg['vaultPath']).resolve() != Path(args.vault).expanduser().resolve():
            raise ValueError('已有部署的宿主或知识库不同；请使用原配置，不自动覆盖。')
        if not (target/'scripts/setup-assistant.py').is_file():
            raise ValueError('旧部署尚无安装检查入口；先按升级说明用upgrade.py安全升级，再重试。')
        # A second invocation repairs deps only, never overwrites managed/custom code.
    else:
        if args.host == 'codex':
            args.node = find_binary('node', args.node) if args.check_only else runtime('node', args.node)
            args.pwsh = find_binary('pwsh', args.pwsh) if args.check_only else runtime('pwsh', args.pwsh)
        deployed = deploy(args)
        if args.check_only:return {**deployed,'fullyReady':False,'checks':[],'guidance':['只核对部署条件，尚未执行部署和安装。']}
    name = 'local.json' if args.host == 'codex' else 'profile.json'
    cfg = json.loads((target/'config'/name).read_text(encoding='utf-8-sig'))
    obsidian = {'name': 'obsidian', 'status': 'needs_user_action'}
    if os.name == 'nt':
        shell = (cfg.get('shellPath') or find_binary('pwsh',args.pwsh)) if args.host == 'codex' else str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
        obsidian = obsidian_check(shell,args.check_only)
    spec = importlib.util.spec_from_file_location('assistant_setup', target/'scripts/setup-assistant.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result = module.setup(target, args.check_only, args.with_media, args.host_checks)
    result['checks'].append(obsidian)
    if obsidian['status'] == 'needs_user_action':
        result['fullyReady'] = False
        result['guidance'].append('Obsidian尚未核实；安装超时时先检查安装器或已安装结果，勿重复启动。可从https://obsidian.md/download安装后打开所选知识库。已有Markdown笔记和其他通过检查的功能可继续使用。')
    if not args.check_only:(target/'.runtime/installation-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=['codex', 'workbuddy'], required=True)
    parser.add_argument('--target', required=True);parser.add_argument('--vault', required=True)
    for name in ['node', 'python', 'codex', 'pwsh', 'project-id', 'host-checks']:parser.add_argument('--'+name)
    parser.add_argument('--with-media', action='store_true');parser.add_argument('--check',dest='check_only',action='store_true')
    try:
        result = install(parser.parse_args());print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['fullyReady'] else 2)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'incomplete', 'guidance': str(error) if isinstance(error, ValueError) else '安装检查未完成，请核对执行权限、运行时及网络，再用同一命令继续。'}, ensure_ascii=False))
        raise SystemExit(1)
    except KeyboardInterrupt:
        print(json.dumps({'status': 'cancelled', 'fullyReady': False, 'guidance': '已取消，保留已有部署和依赖；用相同命令继续，不重复部署或扫码。'}, ensure_ascii=False))
        raise SystemExit(130)
