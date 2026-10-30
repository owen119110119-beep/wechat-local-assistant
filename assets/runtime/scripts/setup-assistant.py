"""Check or repair one deployment without binding accounts or starting services."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import sys

HOST_GUIDANCE = {
    'shell': '在宿主启用本机命令执行，并允许助理在专用部署目录运行安装脚本；不要关闭平台审批。',
    'file_read': '在宿主允许读取专用部署目录和所选知识库。',
    'file_write': '在宿主允许写入所选知识库；用临时文件写入读回后删除，保留已有笔记。',
    'image_read': '选用支持图片的模型，并在实际微信助理会话核对图片附件可传给模型。',
    'image_edit': '在实际助理会话启用宿主提供的图像编辑工具并检查登录/额度；没有该工具时可先使用图片识别与PDF整理。',
    'web_search': '在实际助理会话启用联网搜索工具；网页正文读取不能代替公开检索和溯源。',
    'attachment_receive': '启用微信入口的文件/图片接收，在手机发送一张无隐私测试图并核对助理确实读到。',
    'attachment_send': '启用微信入口的文件/图片发送，回传无隐私测试文件并请用户核对手机收到。',
}
FEATURES = {
    '公众号整理与入库': (['article'], ['shell', 'file_read', 'file_write']),
    '网页与小红书': (['web_extract', 'browser', 'ocr'], ['shell', 'file_read']),
    'PDF和Office读取': (['pdf', 'office', 'ocr'], ['shell', 'file_read', 'attachment_receive']),
    '课件图片与PDF回传': (['pdf', 'ocr'], ['image_read', 'file_read', 'file_write', 'shell', 'attachment_receive', 'attachment_send']),
    '图片编辑与回传': ([], ['image_read', 'image_edit', 'attachment_receive', 'attachment_send']),
    '联网调研与溯源': ([], ['web_search']),
    '视频画面与下载处理': (['media', 'ocr'], ['shell', 'file_read']),
    '本机语音转写': (['speech'], ['shell', 'attachment_receive']),
}


def run(argv, root, environment, timeout=600):
    return subprocess.run([str(x) for x in argv], cwd=root, env=environment, capture_output=True,
                          encoding='utf-8', errors='replace', check=True, timeout=timeout,
                          creationflags=0x08000000 if os.name == 'nt' else 0)


def host_checks(path):
    # Only the installing host can attest its actual tools. A CLI process cannot
    # infer those from installed executables or from this machine's other Skills.
    supplied = json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else {}
    result = {}
    for name, guidance in HOST_GUIDANCE.items():
        row = supplied.get(name, {})
        status = row.get('status', 'not_checked')
        evidence = row.get('evidence', '')
        if status not in {'available', 'unavailable', 'not_checked'} or (status != 'not_checked' and not str(evidence).strip()):
            raise ValueError('宿主工具核对必须包含真实状态与证据：'+name)
        result[name] = {'status': status, 'evidence': str(evidence)[:400], 'guidance': guidance}
    return result


def feature_status(checks, host, host_name):
    index = {x['name']: x['status'] for x in checks};features = []
    for title, (local, tools) in FEATURES.items():
        if host_name == 'codex':local = local + ['node_runtime', 'powershell_runtime', 'codex_runtime', 'wechat_transport']
        if title == '本机语音转写' and index.get('speech') == 'not_requested':
            features.append({'name': title, 'status': 'not_requested', 'guidance': '微信已转写的语音直接使用；确需本机转写时用--with-media补齐依赖和模型。'})
            continue
        missing = [x for x in local if index.get(x) not in {'verified', 'installed'}]
        absent = [x for x in tools if host[x]['status'] != 'available']
        status = 'needs_dependencies' if missing else 'needs_host_check' if absent else 'verified' if all(index.get(x) == 'verified' for x in local) else 'installed_not_verified'
        features.append({'name': title, 'status': status, 'dependencies': missing, 'hostTools': absent})
    features.append({'name': '指定微信群整理', 'status': 'not_enabled' if host_name == 'codex' and os.name == 'nt' else 'unsupported_host',
                     'guidance': '仅Windows Codex：用户要求后运行scripts/setup-chat-history.py --check发现位置，再按需启用；此检查不扫描聊天或取钥。' if host_name == 'codex' else '此群数据库后端需要Windows Codex；WorkBuddy可继续使用其他素材功能。'})
    return features


def setup(root, check_only=False, with_media=False, host_path=None, runner=run):
    root = Path(root).expanduser().resolve()
    if root == Path(root.anchor) or any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in [root, *root.parents]):
        raise ValueError('请使用无链接的专用部署目录。')
    for name in ['.runtime', '.runtime/tmp', '.runtime/bin', '.runtime/browsers', '.runtime/models', '.venv', '.venv/Scripts', '.venv/bin', 'config', 'scripts', 'node_modules']:
        path = root/name
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():raise ValueError('安装目标含链接，保留原目录并先核对位置。')
    manifest = json.loads((root/'.runtime/deployment.json').read_text(encoding='utf-8'))
    host_name = manifest['host']
    if host_name not in {'codex', 'workbuddy'}:raise ValueError('未知宿主。')
    config = root/('config/local.json' if host_name == 'codex' else 'config/profile.json')
    cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    if cfg.get('host') != host_name:raise ValueError('宿主配置不一致，保留现有文件并先核对部署目录。')
    host = host_checks(host_path)
    binary = root/('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    tmp = root/'.runtime/tmp'
    environment = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PLAYWRIGHT_BROWSERS_PATH': str(root/'.runtime/browsers'),
                   'HF_HOME': str(root/'.runtime/huggingface'), 'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_XET': '1',
                   'TEMP': str(tmp), 'TMP': str(tmp), 'TMPDIR': str(tmp)}
    stages = [];checks = [];failure = None
    qr_args = [cfg.get('pythonPath', sys.executable), '-B', '-c', "import sys;from pathlib import Path;p=Path(sys.argv[1]).resolve();sys.path.insert(0,str(p));import qrcode;assert Path(qrcode.__file__).resolve().is_relative_to(p);q=qrcode.QRCode();q.add_data('dependency-check');q.make();assert len(q.get_matrix())>0", root/'.runtime/qr-deps']
    silk_args = [cfg.get('nodePath', 'node'), '--input-type=module', '-e', "const x=await import('./node_modules/silk-wasm/lib/index.mjs');const encoded=await x.encode(Buffer.alloc(4800),24000);const decoded=await x.decode(encoded.data,24000);if(!decoded.data.length)throw Error('SILK_INVALID');"]

    def stage(name, argv, timeout=600):
        try:
            if not check_only:
                (root/'.runtime/installation-check.json').write_text(json.dumps({'status': 'checking', 'stage': name, 'fullyReady': False}), encoding='utf-8')
            output = runner(argv, root, environment, timeout)
            stages.append({'name': name, 'status': 'complete'})
            return output
        except KeyboardInterrupt:
            if not check_only:
                (root/'.runtime/installation-check.json').write_text(json.dumps({'status': 'cancelled', 'fullyReady': False, 'guidance': '安装已取消；保留已有环境，可运行相同命令继续。'}, ensure_ascii=False), encoding='utf-8')
            raise
        except (OSError, subprocess.SubprocessError) as error:
            detail = str(getattr(error, 'stderr', '') or '')
            unavailable = re.search(r'No matching distribution found for ([A-Za-z0-9_.=<>!-]+)', detail)
            if unavailable:reason='PackageUnavailable:'+unavailable.group(1)
            elif re.search(r'CERTIFICATE_VERIFY_FAILED|certificate verify failed', detail, re.I):reason='CertificateValidationFailed'
            elif re.search(r'Permission denied|Access is denied', detail, re.I):reason='PermissionDenied'
            elif re.search(r'No space left|disk.*full|WinError 112', detail, re.I):reason='DiskFull'
            elif re.search(r'Timed?\s*out|ConnectionError|ProxyError|Failed to establish', detail, re.I):reason='DownloadConnectionFailed'
            else:reason=type(error).__name__
            stages.append({'name': name, 'status': 'failed', 'reason': reason})
            # Do not echo pip/browser output: it can contain authenticated index URLs.
            return None

    usable_python = True
    if binary.is_file():
        usable_python = stage('python_environment', [binary, '-B', '-c', 'import sys;assert sys.version_info >= (3,12)'], 20) is not None
        if not usable_python:failure='python_environment'
    if not check_only and usable_python:
        tmp.mkdir(parents=True, exist_ok=True)
        (root/'.runtime/installation-check.json').write_text(json.dumps({'status': 'checking', 'fullyReady': False}), encoding='utf-8')
        if not binary.is_file():
            base = cfg.get('pythonPath', sys.executable)
            if stage('create_environment', [base, '-m', 'venv', str(root/'.venv')]) is None:failure='create_environment'
        if binary.is_file() and failure is None:
            preliminary = stage('inspect_dependencies', [binary, '-B', root/'scripts/dependency_probe.py', '--root', root] + (['--with-media'] if with_media else []))
            existing = json.loads(preliminary.stdout)['checks'] if preliminary else []
            need = any(x['status'] == 'missing_or_broken' for x in existing if x['name'] != 'speech') or not existing
            broken = any(x['name'] == 'package_versions' and x['status'] == 'installed' for x in existing) and need
            if need and stage('install_content_dependencies', [binary, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '--retries', '1', '--timeout', '20'] + (['--force-reinstall'] if broken else []) + ['-r', root/'scripts/requirements-content.txt']) is None:
                failure='install_content_dependencies'
            if stage('package_consistency', [binary, '-m', 'pip', 'check'], 30) is None:failure=failure or 'package_consistency'
            # yt-dlp expects the canonical executable name, not the wheel's suffix.
            ffmpeg_script = "import hashlib,imageio_ffmpeg,shutil,sys;from pathlib import Path;p=Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);s=Path(imageio_ffmpeg.get_ffmpeg_exe());shutil.copy2(s,p) if not p.exists() or hashlib.sha256(p.read_bytes()).digest()!=hashlib.sha256(s.read_bytes()).digest() else None"
            if stage('prepare_project_ffmpeg', [binary, '-c', ffmpeg_script, root/'.runtime/bin'/('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')]) is None:failure=failure or 'prepare_project_ffmpeg'
            if with_media:
                speech = next((x for x in existing if x['name'] == 'speech'), {})
                if speech.get('status') != 'installed':
                    if stage('install_speech_dependencies', [binary, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '--retries', '1', '--timeout', '20', '-r', root/'scripts/requirements-voice.lock.txt']) is None:failure=failure or 'install_speech_dependencies'
            if host_name == 'codex':
                # QR modules live in the project and SILK is integrity checked.
                usable_qr = stage('inspect_qr', qr_args, 20)
                usable_silk = stage('inspect_silk', silk_args, 20)
                if not (usable_qr and usable_silk):
                    if stage('install_wechat_dependencies', [cfg['pythonPath'], root/'scripts/install-dependencies.py']) is None:failure=failure or 'install_wechat_dependencies'
            # A failed Chrome launch gets one project-local Chromium repair attempt.
            smoke = stage('functional_checks', [binary, '-B', root/'scripts/dependency_probe.py', '--root', root, '--smoke'] + (['--with-media'] if with_media else []), 180)
            checks = json.loads(smoke.stdout)['checks'] if smoke else []
            if any(x['name'] == 'browser' and x['status'] == 'missing_or_broken' for x in checks):
                if stage('install_browser', [binary, '-m', 'playwright', 'install', 'chromium']) is None:failure=failure or 'install_browser'
                else:(root/'.runtime/browser-choice.json').write_text(json.dumps({'engine': 'chromium'}), encoding='utf-8')
            if with_media and not (root/'.runtime/models/base/model.bin').is_file():
                if stage('download_speech_model', [binary, root/'scripts/transcribe.py', '--model-dir', root/'.runtime/models/base', '--download'], 1200) is None:failure=failure or 'download_speech_model'
            elif with_media and any(x['name'] == 'speech' and x['status'] == 'missing_or_broken' for x in checks):
                repair = "from huggingface_hub import snapshot_download;import sys;snapshot_download('Systran/faster-whisper-base',local_dir=sys.argv[1],force_download=True)"
                if stage('repair_speech_model', [binary, '-c', repair, root/'.runtime/models/base'], 1200) is None:failure=failure or 'repair_speech_model'
            final = stage('final_checks', [binary, '-B', root/'scripts/dependency_probe.py', '--root', root, '--smoke'] + (['--with-media'] if with_media else []), 180)
            checks = json.loads(final.stdout)['checks'] if final else checks
    elif check_only and binary.is_file() and usable_python:
        inspected = stage('read_only_checks', [binary, '-B', root/'scripts/dependency_probe.py', '--root', root] + (['--with-media'] if with_media else []), 120)
        checks = json.loads(inspected.stdout)['checks'] if inspected else []
    if not checks:
        checks = [{'name': name, 'status': 'missing_or_broken'} for name in ['article', 'web_extract', 'office', 'pdf', 'ocr', 'browser', 'media', 'speech']]
    if host_name == 'codex':
        try:
            # Import and execute the decoder in Node; existence alone proves nothing.
            qr = stage('qr_check', qr_args, 20)
            silk = stage('silk_check', silk_args, 20)
            checks.append({'name': 'wechat_transport', 'status': ('installed' if check_only else 'verified') if qr and silk else 'missing_or_broken'})
        except KeyError:checks.append({'name': 'wechat_transport', 'status': 'missing_or_broken'})
        for name, args in [
            ('node', [cfg.get('nodePath', 'node'), '--input-type=module', '-e', "if(Number(process.versions.node.split('.')[0])<22)throw Error();const{DatabaseSync}=await import('node:sqlite');new DatabaseSync(':memory:').close();"]),
            ('powershell', [cfg.get('shellPath', 'pwsh'), '-NoProfile', '-Command', 'if ($PSVersionTable.PSVersion.Major -lt 7) { exit 1 }']),
            ('codex', [cfg.get('nodePath', 'node'), '--input-type=module', '-e', "import{resolveRuntime,verifyRuntime}from './src/runtime.mjs';verifyRuntime(resolveRuntime(process.argv[1]));console.log('codex-cli verified');", cfg.get('codexPath', 'codex')]),
        ]:
            result = stage(name+'_runtime', args, 20)
            okay = result is not None and (name != 'codex' or result.stdout.strip().startswith('codex-cli '))
            checks.append({'name': name+'_runtime', 'status': 'installed' if okay and check_only else 'verified' if okay else 'missing_or_broken'})
    requested = [x for x in checks if x['status'] != 'not_requested']
    ready = bool(requested) and all(x['status'] in {'verified', 'installed'} for x in requested) and failure is None
    features = feature_status(checks, host, host_name)
    guidance = []
    if failure or not ready:
        guidance.append('依赖未齐，保留已安装部分。检查下载网络、磁盘和执行权限，再运行同一安装入口重试；不要重复部署或扫码。不会修改代理、证书或微信。')
        guidance.append('软件源无兼容包时使用官方Python 3.12建立新部署环境；不要删除或替换现有环境。PDF字体缺失请安装系统中文字体；浏览器受策略限制请在获准环境运行。')
    if not usable_python:guidance.append('现有项目Python低于3.12或不可运行；已保留旧环境且未安装新依赖。请用官方Python3.12建立新的专用环境，再安全迁移原配置与笔记。')
    fixes = {'pdf': 'PDF依赖或中文字体不可用；补齐系统中文字体后重试安装检查。',
             'browser': '浏览器未能启动；项目Chromium安装和本机执行权限需要核对，不改系统浏览器或网络。',
             'ocr': '本机OCR无法运行；核对当前Python的ONNX运行环境和平台支持，建议官方Python3.12。',
             'media': '视频工具未通过编解码检查；修复项目视频依赖后再用，不借用其他Skill目录。',
             'speech': '本机转写依赖或模型未齐；检查下载网络后用--with-media继续，已转写语音仍可直接使用。',
             'wechat_transport': '微信收发依赖未通过检查；用同一安装入口补齐二维码/SILK，再进行手机往返。',
             'node_runtime': 'Node运行时不完整或不支持本机SQLite；安装官方Node >=22.13并核对配置路径。',
             'powershell_runtime': 'PowerShell7不可用；安装官方版本并核对实际路径。',
             'codex_runtime': 'Codex本机执行组件不完整；修复官方安装，不能仅凭Codex窗口已打开判断可用。'}
    for item in checks:
        if item['status'] == 'missing_or_broken' and item['name'] in fixes:guidance.append(fixes[item['name']])
    failure_fixes = {'CertificateValidationFailed': '下载证书校验失败：核对系统时间和软件源证书，不关闭TLS验证或安装未知证书。',
                     'PermissionDenied': '当前安装路径或执行权限不足：使用获准的专用目录，不修改其他程序权限。',
                     'DiskFull': '安装磁盘空间不足：换有足够空间的专用目录，保留现有部署。',
                     'DownloadConnectionFailed': '软件下载连接未完成：使用当前可用网络重试，不更改用户代理或VPN。'}
    for row in stages:
        reason = row.get('reason', '')
        if reason in failure_fixes:guidance.append(failure_fixes[reason])
        if reason.startswith('PackageUnavailable:'):guidance.append('软件源未提供兼容依赖'+reason.split(':', 1)[1]+'，请核对Python版本、平台及所用软件源；不能报告该功能已安装。')
    for name, row in host.items():
        if row['status'] != 'available':guidance.append(row['guidance'])
    report = {'host': host_name, 'checkedAt': datetime.now(timezone.utc).isoformat(), 'checkOnly': check_only,
              'dependenciesReady': ready, 'functionalChecksPassed': ready and not check_only,
              'hostChecksComplete': all(x['status'] != 'not_checked' for x in host.values()),
              'fullyReady': ready and not check_only and all(x['status'] == 'available' for x in host.values()),
              'checks': checks, 'features': features, 'hostTools': host, 'stages': stages, 'guidance': list(dict.fromkeys(guidance)),
              'accountsBound': False, 'serviceStarted': False}
    if not check_only:
        destination = root/'.runtime/installation-check.json'
        temp = destination.with_suffix('.tmp');temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8');os.replace(temp, destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--check', action='store_true');parser.add_argument('--with-media', action='store_true')
    parser.add_argument('--host-checks')
    args = parser.parse_args()
    try:
        report = setup(args.root, args.check, args.with_media, args.host_checks)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report['fullyReady'] else 2
    except KeyboardInterrupt:
        if not args.check:
            receipt = Path(args.root)/'.runtime/installation-check.json'
            receipt.write_text(json.dumps({'status': 'cancelled', 'fullyReady': False, 'guidance': '安装已取消，保留已有文件和依赖；运行相同命令可继续，无需重新部署或扫码。'}, ensure_ascii=False), encoding='utf-8')
        print(json.dumps({'status': 'cancelled', 'fullyReady': False}, ensure_ascii=False));return 130
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'incomplete', 'reason': type(error).__name__, 'guidance': '核对专用部署目录和配置，先完成文件部署再运行安装检查；不要删除已有配置。'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':raise SystemExit(main())
