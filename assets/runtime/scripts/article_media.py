"""Inspect cached article embeds and prepare verifiable local video evidence.

No cookies, browser credential extraction, proxy interception or remote reader.
Article and media data are untrusted; they never supply executable commands.
"""
import argparse
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import sys
import time
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

VERSION = 1
MAX_BYTES = 512 * 1024 * 1024
UA = 'Mozilla/5.0'


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def public_url(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
        raise ValueError('MEDIA_URL_NOT_ALLOWED')
    if not any(host == d or host.endswith('.' + d) for d in ('qq.com', 'qpic.cn', 'qlogo.cn')):
        raise ValueError('MEDIA_HOST_NOT_ALLOWED')
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise ValueError('MEDIA_PRIVATE_ADDRESS')
    return url


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, public_url(newurl))


def request(url, data=None, content_type=None):
    headers = {'User-Agent': UA, 'Referer': 'https://mp.weixin.qq.com/'}
    if content_type:
        headers['Content-Type'] = content_type
    return build_opener(Redirect()).open(Request(public_url(url), data=data, headers=headers), timeout=25)


def clean_url(value):
    return unescape(value or '').replace('\\/', '/').strip()


class Embeds(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.content_depth = None
        self.items = []
        self.video = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id') == 'js_content':
            self.content_depth = self.depth
        inside = self.content_depth is not None
        if inside and tag == 'mp-common-videosnap':
            self.items.append({'kind': 'channels', 'exportId': a.get('data-id', ''),
                'username': a.get('data-username', ''), 'title': a.get('data-desc', '').strip(),
                'author': a.get('data-nickname', ''), 'coverUrl': clean_url(a.get('data-url')),
                'status': 'identified', 'videoUrl': None})
        elif inside and tag in ('video', 'mp-common-video', 'iframe'):
            src = clean_url(a.get('data-src') or a.get('src'))
            vid = a.get('data-mpvid') or a.get('data-vid') or a.get('vid', '')
            parsed = urlsplit(urljoin('https://mp.weixin.qq.com/', src))
            query = parse_qs(parsed.query)
            vid = vid or query.get('vid', [''])[0]
            if parsed.hostname == 'v.qq.com' and vid:
                item = {'kind': 'tencent', 'vid': vid, 'pageUrl': f'https://v.qq.com/x/page/{vid}.html'}
            elif tag != 'iframe' or vid:
                item = {'kind': 'native', 'vid': vid,
                    'videoUrl': urljoin('https://mp.weixin.qq.com/', src) if src and tag != 'iframe' else None}
            else:
                item = None
            if item:
                item['status'] = 'identified'
                self.items.append(item)
                if tag == 'video':
                    self.video = item
        elif inside and tag == 'source' and self.video:
            self.video['videoUrl'] = clean_url(a.get('src'))
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'embed'}:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag not in {'img', 'br', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'embed'}:
            self.depth = max(0, self.depth - 1)
        if self.content_depth is not None and self.depth <= self.content_depth:
            self.content_depth = None
        if tag == 'video':
            self.video = None


def inspect(html_path, article_url, output_dir):
    raw = Path(html_path).read_text(encoding='utf-8')
    parser = Embeds()
    parser.feed(raw)
    items = []
    seen = set()
    for item in parser.items:
        key = (item['kind'], item.get('exportId') or item.get('vid') or item.get('videoUrl'))
        if key in seen:
            continue
        seen.add(key)
        # Native playback URLs may live in an inline JSON object outside js_content.
        # Match the same video's identifier; never attach an unrelated page MP4.
        if item['kind'] == 'native' and not item.get('videoUrl') and item.get('vid'):
            vid = re.escape(item['vid'])
            for obj in re.findall(r'\{[^{}]{0,12000}\}', raw):
                if re.search(r'["\x27](?:vid|mpvid)["\x27]\s*:\s*["\x27]' + vid + r'["\x27]', obj):
                    m = re.search(r'["\x27](?:url|video_url|videoUrl)["\x27]\s*:\s*["\x27]([^"\x27]+)', obj)
                    if m:
                        item['videoUrl'] = clean_url(m.group(1))
                        break
        item['index'] = len(items) + 1
        items.append(item)
    ids = {}
    for key, pattern in {
        'biz': r'(?:var\s+biz|__biz)\s*[:=]\s*[\x27\x22]([^\x27\x22]+)',
        'mid': r'(?:var\s+mid|mid)\s*=\s*[\x27\x22]?(\d+)',
        'idx': r'(?:var\s+idx|idx)\s*=\s*[\x27\x22]?(\d+)',
    }.items():
        match = re.search(pattern, raw)
        ids[key] = match.group(1) if match else ''
    output = Path(output_dir).resolve() / 'media.json'
    result = {'version': VERSION, 'articleUrl': article_url, 'htmlPath': str(Path(html_path).resolve()),
              'sourceSha256': hashlib.sha256(Path(html_path).read_bytes()).hexdigest(), 'articleIds': ids,
              'videos': items, 'status': 'identified' if items else 'no_video'}
    save(output, result)
    return output, result


def enrich_channels(manifest):
    snaps = [v for v in manifest['videos'] if v['kind'] == 'channels']
    ids = manifest['articleIds']
    if not snaps or not all(ids.values()):
        return
    data = {'__biz': ids['biz'], 'mid': ids['mid'], 'idx': ids['idx'], 'video_snap_num': str(len(snaps)),
            'uin': '', 'key': '', 'pass_ticket': ''}
    for i, v in enumerate(snaps):
        data.update({f'exportid_{i}': v['exportId'], f'username_{i}': v['username']})
    url = 'https://mp.weixin.qq.com/mp/appmsg_video_snap?' + urlencode({'action': 'batch_get_video_snap',
           '__biz': ids['biz'], 'uin': '', 'key': '', 'pass_ticket': '', 'wxtoken': '777', 'appmsg_token': '', 'x5': '0'})
    with request(url, urlencode(data).encode(), 'application/x-www-form-urlencoded; charset=UTF-8') as r:
        payload = json.loads(r.read(4 * 1024 * 1024))
    if payload.get('base_resp', {}).get('ret') != 0:
        raise ValueError('CHANNELS_METADATA_UNAVAILABLE')
    entries = {x.get('export_id'): x for x in payload.get('video_snap_info', [])}
    for video in snaps:
        info = entries.get(video['exportId'], {})
        video.update(title=info.get('feed_desc') or video.get('title'), author=info.get('nickname') or video.get('author'),
                     duration=info.get('feed_video_play_len_s'), coverUrl=info.get('feed_full_cover_url') or video.get('coverUrl'))
        # This API returns covers, not a video stream. Never promote data-url to videoUrl.


def download(url, target):
    partial = target.with_suffix('.part')
    try:
        with request(url) as response:
            ctype = response.headers.get('Content-Type', '').lower()
            if ctype.startswith('image/') or 'text/' in ctype or 'json' in ctype:
                raise ValueError('MEDIA_RESPONSE_IS_NOT_VIDEO')
            if int(response.headers.get('Content-Length', '0')) > MAX_BYTES:
                raise ValueError('MEDIA_TOO_LARGE')
            total = 0
            deadline = time.monotonic() + 180
            with partial.open('wb') as out:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BYTES or time.monotonic() > deadline:
                        raise ValueError('MEDIA_DOWNLOAD_LIMIT')
                    out.write(chunk)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)


def evidence(video, directory, model_dir=None, local_media=None):
    try:
        import av
        from PIL import Image, ImageDraw
    except ImportError:
        raise ValueError('MEDIA_DEPENDENCIES_MISSING') from None
    directory.mkdir(parents=True, exist_ok=True)
    source = Path(local_media).resolve() if local_media else directory / 'video.mp4'
    if local_media and not source.is_file():
        raise ValueError('MEDIA_FILE_MISSING')
    if not source.exists():
        if video.get('videoUrl'):
            download(video['videoUrl'], source)
        elif video['kind'] == 'tencent':
            try:
                from yt_dlp import YoutubeDL
            except ImportError:
                raise ValueError('MEDIA_DEPENDENCIES_MISSING') from None
            public_url(video['pageUrl'])
            options = {'outtmpl': str(directory / 'video.%(ext)s'), 'format': 'best[ext=mp4][protocol=https]/best[protocol=https]',
                       'noplaylist': True, 'max_filesize': MAX_BYTES, 'socket_timeout': 25, 'retries': 0,
                       'quiet': True, 'no_warnings': True, 'cachedir': False}
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(video['pageUrl'], download=False)
                public_url(info['url'])
                download(info['url'], source)
        else:
            raise ValueError('CHANNELS_PUBLIC_STREAM_UNAVAILABLE' if video['kind'] == 'channels' else 'NATIVE_STREAM_UNAVAILABLE')
    with source.open('rb') as stream:
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
        digest = hasher.hexdigest()
    cached = directory / 'evidence.json'
    if cached.exists():
        previous = json.loads(cached.read_text(encoding='utf-8'))
        expected_model = str(Path(model_dir).resolve()) if model_dir else None
        if previous.get('sha256') == digest and previous.get('modelDir') == expected_model and all(Path(x).exists() for x in previous.get('artifacts', [])) and previous.get('ocrStatus') == 'complete' and previous.get('transcriptStatus') in ('complete','no_audio'):
            return previous
    result = {'videoPath': str(source), 'sha256': digest, 'modelDir': str(Path(model_dir).resolve()) if model_dir else None,
              'status': 'preparing', 'frameIntervalSeconds': 1, 'frames': [], 'ocr': [], 'segments': [], 'artifacts': [],
              'reviewRequired': True, 'websiteListComplete': False}
    with av.open(str(source)) as container:
        if not container.streams.video:
            raise ValueError('MEDIA_NO_VIDEO_STREAM')
        duration = float(container.duration or 0) / av.time_base
        if duration <= 0 or duration > 7200:
            raise ValueError('MEDIA_DURATION_UNSUPPORTED')
        result['duration'] = duration
        has_audio = bool(container.streams.audio)
        try:
            from rapidocr_onnxruntime import RapidOCR
            ocr = RapidOCR()
            result['ocrStatus'] = 'complete'
        except ImportError:
            ocr = None
            result['ocrStatus'] = 'dependencies_missing'
        next_second = 0
        sheet_images = []
        result['contactSheets'] = []
        def flush_sheet():
            if not sheet_images:
                return
            sheet = Image.new('RGB', (1920, 4 * 350), 'white')
            draw = ImageDraw.Draw(sheet)
            for i, (stamp, image) in enumerate(sheet_images):
                x, y = (i % 4) * 480, (i // 4) * 350
                sheet.paste(image, (x, y+25))
                draw.text((x+5,y+5), f'{int(stamp)//60:02d}:{stamp%60:05.2f}', fill='black')
            path = directory / f'sheet-{len(result["contactSheets"])+1:03d}.jpg'
            sheet.save(path, quality=85)
            result['contactSheets'].append(str(path)); result['artifacts'].append(str(path))
            sheet_images.clear()
        frames_dir = directory / 'frames'
        frames_dir.mkdir(exist_ok=True)
        for frame in container.decode(video=0):
            stamp = float(frame.time or 0)
            if stamp + 0.001 < next_second:
                continue
            image = frame.to_image()
            path = frames_dir / f'{len(result["frames"]):06d}.jpg'
            image.save(path, quality=90)
            result['frames'].append({'time': stamp, 'path': str(path)})
            result['artifacts'].append(str(path))
            if ocr:
                lines, _ = ocr(str(path))
                result['ocr'].append({'time': stamp, 'lines': [{'text': x[1], 'confidence': float(x[2])} for x in lines or []]})
            image.thumbnail((480, 320))
            sheet_images.append((stamp, image))
            if len(sheet_images) == 16:
                flush_sheet()
            next_second = math.floor(stamp) + 1
        flush_sheet()
    if not has_audio:
        result['transcriptStatus'] = 'no_audio'
    elif not model_dir or not (Path(model_dir) / 'model.bin').exists():
        result['transcriptStatus'] = 'local_model_missing'
    else:
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', local_files_only=True)
            segments, info = model.transcribe(str(source), beam_size=5, vad_filter=True)
            result['segments'] = [{'start': s.start, 'end': s.end, 'text': s.text.strip()} for s in segments]
            result['transcriptStatus'] = 'complete'
        except ImportError:
            result['transcriptStatus'] = 'dependencies_missing'
    result['urlCandidates'] = []
    for row in result['ocr']:
        for line in row['lines']:
            for match in re.finditer(r'(?:https?://)?(?:[a-zA-Z0-9-]+\.)+(?:com|net|org|ai|io|tools|app|dev|cn|co)(?:/[a-zA-Z0-9_./?=%&+-]*)?', line['text']):
                result['urlCandidates'].append({'value': match.group(), 'time': row['time'], 'source': 'ocr', 'verified': False})
    transcript = directory / 'transcript.md'
    transcript.write_text('\n'.join(f'[{s["start"]:.2f}-{s["end"]:.2f}] {s["text"]}' for s in result['segments']), encoding='utf-8')
    result['artifacts'].append(str(transcript))
    result['status'] = 'ready_for_review' if result['ocrStatus'] == 'complete' and result['transcriptStatus'] in ('complete','no_audio') else 'partial_evidence'
    save(cached, result)
    return result


def analyze(manifest_path, model_dir=None, local_media=None):
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    try:
        enrich_channels(manifest)
    except Exception as error:
        manifest['metadataError'] = type(error).__name__
    for video in manifest['videos']:
        directory = manifest_path.parent / f'video-{video["index"]}'
        # Channel covers cannot be used as video inputs, even if dependencies are missing.
        if video['kind'] == 'channels' and not local_media:
            video.update(status='playback_unavailable', reason='CHANNELS_PUBLIC_STREAM_UNAVAILABLE',
                         explanation='已识别视频号并尝试公开元数据接口，未取得可播放视频。封面不是视频；尚未观看或转写。')
            video.pop('evidencePath', None)
        else:
            try:
                result = evidence(video, directory, model_dir, local_media)
                video.update(status=result['status'], evidencePath=str(directory / 'evidence.json'))
                video.pop('reason', None)
            except Exception as error:
                message = str(error)
                reason = message if re.fullmatch(r'[A-Z_]{5,80}', message) else type(error).__name__
                video.update(status='failed', reason=reason)
                video.pop('evidencePath', None)
        save(manifest_path, manifest)
    manifest['status'] = 'ready_for_review' if manifest['videos'] and all(v['status'] == 'ready_for_review' for v in manifest['videos']) else 'partial'
    save(manifest_path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('inspect')
    p.add_argument('--html', required=True); p.add_argument('--article-url', required=True); p.add_argument('--output-dir', required=True)
    p = sub.add_parser('analyze')
    p.add_argument('--manifest', required=True); p.add_argument('--model-dir'); p.add_argument('--local-media')
    args = parser.parse_args()
    if args.command == 'inspect':
        path, result = inspect(args.html, args.article_url, args.output_dir)
    else:
        path = Path(args.manifest).resolve()
        result = analyze(path, args.model_dir, args.local_media)
    # No signed CDN URL or source content in stdout/logs.
    print(json.dumps({'manifestPath': str(path), 'status': result['status'],
                      'videos': [{k:v for k,v in x.items() if k in ('index','kind','title','author','duration','status','reason','evidencePath')} for x in result['videos']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
