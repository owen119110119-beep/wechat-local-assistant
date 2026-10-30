"""Read public links and local attachments into inspectable local evidence.

Never executes source scripts, Office macros, links in documents, or embedded commands.
"""
import argparse
import contextlib
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile
from functools import lru_cache

MAX_BYTES = 128 * 1024 * 1024


def is_xiaohongshu(host):
    return host in ('xiaohongshu.com','xhslink.com','xhslink.cn') or host.endswith('.xiaohongshu.com')


def save(path, value):
    from article_media import save as atomic_save
    atomic_save(path, value)


def validate_public(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('CONTENT_URL_NOT_ALLOWED')
    resolved = socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)
    if not resolved or any(not ipaddress.ip_address(x[4][0]).is_global for x in resolved):
        raise ValueError('CONTENT_PRIVATE_ADDRESS')
    return url


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, validate_public(newurl))


def fetch(url):
    req = Request(validate_public(url), headers={'User-Agent':'Mozilla/5.0', 'Accept-Language':'zh-CN,zh;q=0.9'})
    with build_opener(Redirect()).open(req, timeout=25) as response:
        ctype = response.headers.get('Content-Type', '')
        if int(response.headers.get('Content-Length','0')) > MAX_BYTES:
            raise ValueError('CONTENT_TOO_LARGE')
        data, size, deadline = [], 0, time.monotonic()+90
        while True:
            part = response.read(256*1024)
            if not part:
                break
            size += len(part)
            if size > MAX_BYTES or time.monotonic() > deadline:
                raise ValueError('CONTENT_DOWNLOAD_LIMIT')
            data.append(part)
        return b''.join(data), ctype, response.geturl()


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def ocr_image(path):
    rows, _ = ocr_engine()(str(path))
    return '\n'.join(x[1] for x in rows or [])


def office_guard(path):
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len(entries)>10000 or sum(x.file_size for x in entries)>128*1024*1024:
            raise ValueError('OFFICE_ARCHIVE_TOO_LARGE')


def local_file(path, output, model_dir=None):
    path, output = Path(path).resolve(), Path(output).resolve()
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('CONTENT_FILE_INVALID_OR_LARGE')
    output.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    with path.open('rb') as stream:
        header = stream.read(16)
    result = {'kind':'file','title':path.name,'sourcePath':str(path),'status':'ready', 'sections':[]}
    if header.startswith(b'%PDF'):
        from pypdf import PdfReader
        reader = PdfReader(path)
        if reader.is_encrypted and reader.decrypt('') == 0:
            raise ValueError('PDF_PASSWORD_REQUIRED')
        result['kind'] = 'pdf'
        count = len(reader.pages)
        result['totalPages'] = count
        result['status'] = 'partial' if count>300 else 'ready'
        renderer = None
        for index, page in enumerate(reader.pages[:300]):
            text = page.extract_text() or ''
            source = 'text'
            if len(text.strip()) < 40:
                import pypdfium2 as pdfium
                if renderer is None:
                    renderer = pdfium.PdfDocument(str(path))
                image_path = output / f'page-{index+1:04d}.png'
                raster = renderer[index].render(scale=1.5).to_pil()
                raster.save(image_path)
                text = ocr_image(image_path)
                source = 'ocr'
            result['sections'].append({'page':index+1,'text':text,'method':source})
        if renderer:
            renderer.close()
    elif suffix == '.docx':
        office_guard(path)
        from docx import Document
        document = Document(path)
        rows = [p.text for p in document.paragraphs if p.text.strip()]
        rows += [' | '.join(c.text for c in row.cells) for table in document.tables for row in table.rows]
        result['sections'] = [{'text':'\n\n'.join(rows)}]
    elif suffix == '.pptx':
        office_guard(path)
        from pptx import Presentation
        result['sections'] = [{'page':i+1,'text':'\n'.join(s.text for s in slide.shapes if s.has_text_frame)} for i,slide in enumerate(Presentation(path).slides)]
    elif suffix == '.xlsx':
        office_guard(path)
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        for sheet in book:
            rows = []
            for i,row in enumerate(sheet.iter_rows(values_only=True)):
                if i>=10000:
                    result['status']='partial';break
                rows.append(' | '.join('' if v is None else str(v) for v in row[:100]))
            result['sections'].append({'sheet':sheet.title,'text':'\n'.join(rows)})
        book.close()
    elif header.startswith((b'\xff\xd8\xff',b'\x89PNG',b'GIF8',b'RIFF',b'BM')) and suffix in ('.png','.jpg','.jpeg','.webp','.gif','.bmp'):
        from PIL import Image
        with Image.open(path) as image:
            if image.width*image.height > 40_000_000:
                raise ValueError('IMAGE_TOO_LARGE')
        result['kind']='image'
        result['sections']=[{'text':ocr_image(path),'method':'ocr'}]
        result['imagePath']=str(path)
    elif suffix in ('.mp4','.mkv','.mov','.webm','.avi'):
        from article_media import evidence
        prepared = evidence({'kind':'local'},output/'video',model_dir,str(path))
        result.update(kind='video',status=prepared['status'],evidencePath=str(output/'video/evidence.json'))
        result['sections']=[{'text':'\n'.join(f'[{s["start"]:.2f}] {s["text"]}' for s in prepared['segments'])}]
    elif suffix in ('.mp3','.m4a','.wav','.ogg','.flac','.aac'):
        if not model_dir or not (Path(model_dir)/'model.bin').exists():
            raise ValueError('LOCAL_TRANSCRIPTION_MODEL_MISSING')
        from faster_whisper import WhisperModel
        model = WhisperModel(str(model_dir),device='cpu',compute_type='int8',local_files_only=True)
        segments,_ = model.transcribe(str(path),beam_size=5,vad_filter=True)
        result['kind']='audio'
        result['sections']=[{'start':s.start,'end':s.end,'text':s.text.strip()} for s in segments]
    elif suffix in ('.txt','.md','.csv','.json','.html','.htm'):
        data=path.read_bytes()
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:text=data.decode('gb18030',errors='replace')
        if suffix in ('.html','.htm'):
            result.update(html_content(text,''))
        else:
            result['sections']=[{'text':text}]
    else:
        raise ValueError('CONTENT_FORMAT_UNSUPPORTED')
    return finish(result,output)


def xhs_content(html,url=None):
    import chompjs
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*',html)
    if not match:
        return None
    state = chompjs.parse_js_object(html[match.end():])
    notes = state.get('note',{}).get('noteDetailMap',{})
    match_id=re.search(r'/(?:explore|discovery/item)/([A-Za-z0-9]+)',urlsplit(url).path) if url else None
    expected=match_id.group(1) if match_id else None
    for key,item in notes.items():
        note=item.get('note') or {}
        if expected and key!=expected and note.get('noteId')!=expected and note.get('id')!=expected:
            continue
        if not expected and len(notes)!=1:
            continue
        if not note.get('desc') and not note.get('title'):
            continue
        images=[x.get('urlDefault') or x.get('urlPre') for x in note.get('imageList',[])]
        streams=note.get('video',{}).get('media',{}).get('stream',{})
        return {'kind':'xiaohongshu','title':note.get('title') or note.get('desc','')[:40],
                'author':note.get('user',{}).get('nickname',''),'sections':[{'text':note.get('desc','')}],
                'images':[x for x in images if x], 'mediaCandidates':[v.get('masterUrl') for group in streams.values() if isinstance(group,list) for v in group if v.get('masterUrl')], 'status':'ready'}
    return None


def html_content(html,url):
    from lxml import html as lxml_html
    import trafilatura
    host=(urlsplit(url).hostname or '').lower()
    if is_xiaohongshu(host):
        parsed=xhs_content(html,url)
        if parsed:return parsed
        raise ValueError('XIAOHONGSHU_LOGIN_OR_VERIFICATION_REQUIRED')
    tree=lxml_html.fromstring(html)
    title=' '.join(tree.xpath('//title/text()')) or '网页内容'
    text=trafilatura.extract(html,include_links=True,include_tables=True,output_format='txt') or ''
    if len(text.strip())<80:
        raise ValueError('CONTENT_BODY_UNAVAILABLE')
    if re.search(r'captcha|access denied|人机验证|请完成验证|访问过于频繁', title, re.I):
        raise ValueError('CONTENT_VERIFICATION_REQUIRED')
    return {'kind':'web','title':title,'sections':[{'text':text}], 'status':'ready',
            'images':[urljoin(url,img.get('src') or img.get('data-src')) for img in tree.xpath('//article//img') if img.get('src') or img.get('data-src')]}


def platform_media(url,output,model_dir):
    from yt_dlp import YoutubeDL
    import shutil
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    options={'outtmpl':str(output/'source.%(ext)s'),'noplaylist':True,'max_filesize':MAX_BYTES,
             'socket_timeout':20,'retries':0,'quiet':True,'no_warnings':True,'cachedir':False,
             'format':'best[ext=mp4]/best','writesubtitles':True,'writeautomaticsub':True,
             'subtitleslangs':['zh.*','en.*'],'subtitlesformat':'vtt'}
    from local_tools import ffmpeg_path
    ffmpeg=ffmpeg_path()
    if ffmpeg:options['ffmpeg_location']=ffmpeg
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        with YoutubeDL(options) as dl:
            info=dl.extract_info(url,download=True)
            path=Path(dl.prepare_filename(info))
    if not path.is_file():raise ValueError('PLATFORM_MEDIA_DOWNLOAD_FAILED')
    result=local_file(path,output,model_dir)
    result.update(title=info.get('title') or result['title'],url=url,author=info.get('uploader') or '')
    return finish(result,output)


def public_link(url,output,model_dir=None):
    validate_public(url)
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    host=urlsplit(url).hostname.lower()
    if host in ('weixin.qq.com','www.weixin.qq.com') and urlsplit(url).path.startswith('/sph/'):
        from browser_provider import channels
        profile=channels(url)
        data,ctype,_=fetch(profile['videoUrl'])
        if ctype.startswith('image/') or 'text/' in ctype:raise ValueError('MEDIA_RESPONSE_IS_NOT_VIDEO')
        if profile.get('decodeKey'):
            from isaac64 import decrypt_prefix
            data=decrypt_prefix(data,int(profile['decodeKey']))
        path=output/'source.mp4';path.write_bytes(data)
        result=local_file(path,output,model_dir)
        result.update(title=profile.get('title') or result['title'],author=profile.get('author'),url=url)
        return finish(result,output)
    video_hosts=('bilibili.com','b23.tv','youtube.com','youtu.be','douyin.com','xiaoyuzhoufm.com')
    if any(host==x or host.endswith('.'+x) for x in video_hosts):
        return platform_media(url,output,model_dir)
    try:data,ctype,final_url=fetch(url)
    except Exception as error:
        if getattr(error,'code',None) in (403,429):
            from browser_provider import read_web,read_xiaohongshu
            if is_xiaohongshu(host):
                return read_xiaohongshu(url,output)
            return read_web(url,output)
        raise
    if data.startswith(b'%PDF'):
        path=output/'source.pdf';path.write_bytes(data)
        result=local_file(path,output,model_dir);result.update(url=url,finalUrl=final_url)
    else:
        html=data.decode('utf-8',errors='replace');(output/'source.html').write_text(html,encoding='utf-8')
        try:result=html_content(html,final_url)
        except ValueError as error:
            if str(error)=='XIAOHONGSHU_LOGIN_OR_VERIFICATION_REQUIRED':
                from browser_provider import read_xiaohongshu
                return read_xiaohongshu(url,output)
            raise
        result.update(url=url,finalUrl=final_url)
    return finish(result,output)


def prepare_xhs_media(result,output,model_dir=None):
    """Read the target note's own images/video; preserve per-item coverage failures."""
    from PIL import Image
    output=Path(output).resolve()
    result['imageEvidence']=[]
    images=result.get('images',[])
    for index,url in enumerate(images[:30]):
        entry={'index':index+1,'status':'failed'}
        try:
            # XHS embeds http CDN links; request the same resource over TLS only.
            if url.startswith('http://'):url='https://'+url[7:]
            data,ctype,_=fetch(url)
            if not ctype.startswith('image/'):raise ValueError('CONTENT_IMAGE_RESPONSE_INVALID')
            path=output/f'image-{index+1:03d}.png'
            with Image.open(io.BytesIO(data)) as image:
                if image.width*image.height>40_000_000:raise ValueError('IMAGE_TOO_LARGE')
                image.convert('RGB').save(path)
            text=ocr_image(path)
            entry.update(status='ready',imagePath=str(path),text=text)
            result['sections'].append({'page':index+1,'text':text,'method':'image_ocr'})
        except Exception as error:
            entry['reason']=safe_reason(error)
        result['imageEvidence'].append(entry)
    if len(images)>30 or any(x['status']!='ready' for x in result['imageEvidence']):
        result['status']='partial'
    candidates=result.get('mediaCandidates',[])
    if candidates:
        try:
            data,ctype,_=fetch(candidates[0].replace('http://','https://',1))
            if ctype.startswith(('image/','text/')):raise ValueError('MEDIA_RESPONSE_IS_NOT_VIDEO')
            path=output/'source.mp4';path.write_bytes(data)
            video=local_file(path,output/'video',model_dir)
            result['videoEvidence']={k:video.get(k) for k in ['status','evidencePath','contentPath']}
            result['sections']+=video.get('sections',[])
            if video['status']!='ready_for_review':result['status']='partial'
        except Exception as error:
            result['videoEvidence']={'status':'failed','reason':safe_reason(error)}
            result['status']='partial'
    result['mediaPrepared']=True
    return result


def safe_reason(error):
    code=str(error)
    if re.fullmatch(r'[A-Z_]{5,90}',code):return code
    network=re.search(r'net::(ERR_[A-Z_]+)',code)
    if network:return 'CONTENT_BROWSER_'+network.group(1)
    if "Executable doesn't exist" in code:return 'CONTENT_BROWSER_NOT_INSTALLED'
    if 'Singleton' in code or 'user data directory is already in use' in code:return 'CONTENT_BROWSER_PROFILE_BUSY'
    if type(error).__name__=='TimeoutError':return 'CONTENT_BROWSER_TIMEOUT'
    return 'CONTENT_HTTP_'+str(error.code) if hasattr(error,'code') else type(error).__name__


def finish(result,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    body='\n\n'.join((f'第{s["page"]}页\n' if s.get('page') else f'{s["sheet"]}\n' if s.get('sheet') else '')+s.get('text','') for s in result.get('sections',[]))
    path=output/'content.md';path.write_text(body,encoding='utf-8')
    result.update(contentPath=str(path),chars=len(body),readAt=time.time())
    save(output/'content.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['url','file']);parser.add_argument('--input',required=True)
    parser.add_argument('--output-dir',required=True);parser.add_argument('--model-dir')
    args=parser.parse_args();output=Path(args.output_dir).resolve()
    try:
        result=(public_link if args.mode=='url' else local_file)(args.input,output,args.model_dir)
        if result.get('kind')=='xiaohongshu':
            result=finish(prepare_xhs_media(result,output,args.model_dir),output)
    except Exception as error:
        code=safe_reason(error)
        detail=re.sub(r'https?://\S+','[URL]',str(error))
        save(output/'diagnostic.json',{'type':type(error).__name__,'reason':code,'message':'\n'.join(detail.splitlines()[:4])[:1200]})
        result={'status':'failed','reason':code,'kind':args.mode,'input':args.input if args.mode=='file' else None}
        save(output/'content.json',result)
    print(json.dumps({k:v for k,v in result.items() if k in ('status','reason','kind','title','chars','contentPath','evidencePath')},ensure_ascii=False))


if __name__=='__main__':main()
