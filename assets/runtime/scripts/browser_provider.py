"""Optional read-only providers using their own locally authenticated profiles.

Uses dedicated profiles, never imports cookies or opens an existing browser profile.
Credentials remain inside the browser profile; stdout contains only status and paths.
"""
import argparse
import json
from pathlib import Path
import re
import time
import os
from urllib.parse import urlsplit, parse_qs

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.runtime/browsers'))
ORIGINS={'yuanbao':'https://yuanbao.tencent.com/','xiaohongshu':'https://www.xiaohongshu.com/explore','web':'about:blank'}


def profile(provider):
    if provider not in ORIGINS:raise ValueError('PROVIDER_UNKNOWN')
    return ROOT/'.runtime/providers'/provider


def open_context(playwright,provider,visible=False):
    directory=profile(provider)/'profile';directory.mkdir(parents=True,exist_ok=True)
    candidates=[Path(os.environ.get(key,''))/'Google/Chrome/Application/chrome.exe' for key in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA') if os.environ.get(key)]
    options={'channel':'chrome'} if any(path.is_file() for path in candidates) else {}
    return playwright.chromium.launch_persistent_context(str(directory),**options,headless=not visible,
             viewport={'width':1280,'height':900},accept_downloads=False,chromium_sandbox=True)


def yuanbao_authenticated(status,text):
    return status==200 and bool(text.strip()) and '未登录' not in text and '请登录后输入内容' not in text


def authenticate(provider,timeout=600,test_url=None):
    from playwright.sync_api import sync_playwright
    from article_media import save
    state=profile(provider)/'status.json'
    save(state,{'status':'waiting_for_login','provider':provider})
    with sync_playwright() as p:
        context=open_context(p,provider,True)
        page=context.pages[0] if context.pages else context.new_page()
        page.goto(ORIGINS[provider],wait_until='domcontentloaded',timeout=60000)
        save(state,{'status':'login_window_open','provider':provider})
        end=time.monotonic()+timeout
        try:
            while time.monotonic()<end:
                text=page.locator('body').inner_text(timeout=5000)
                if provider=='yuanbao':
                    # The editor exists during anonymous loading as well. Only a server
                    # response can establish that this dedicated profile is authenticated.
                    status=page.evaluate('''async (url)=>{try{const r=await fetch('/api/weixin/get_parse_result',{
                      method:'POST',credentials:'include',headers:{'content-type':'application/json'},
                      body:JSON.stringify({type:'video_channel_url',url,scene:1})});return r.status}catch{return 0}}''',
                      test_url or 'https://weixin.qq.com/sph/sessioncheck')
                    logged=yuanbao_authenticated(status,text)
                else:
                    logged='登录以探索更多精彩内容' not in text and page.get_by_text('我',exact=True).count()>0
                if logged:
                    save(state,{'status':'authenticated','provider':provider,'at':time.time()})
                    print(json.dumps({'provider':provider,'status':'authenticated'},ensure_ascii=False));return
                page.wait_for_timeout(5000)
        finally:context.close()
    save(state,{'status':'login_not_completed','provider':provider})


def channels(share_url):
    from playwright.sync_api import sync_playwright
    from content_reader import validate_public
    parsed=urlsplit(share_url)
    if parsed.hostname not in ('weixin.qq.com','www.weixin.qq.com') or not re.fullmatch(r'/sph/[A-Za-z0-9]+/?',parsed.path):
        raise ValueError('CHANNELS_SHARE_URL_REQUIRED')
    with sync_playwright() as p:
        context=open_context(p,'yuanbao')
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(ORIGINS['yuanbao'],wait_until='domcontentloaded',timeout=45000)
            response=page.evaluate('''async(url)=>{const r=await fetch('/api/weixin/get_parse_result',{
                method:'POST',credentials:'include',headers:{'content-type':'application/json'},
                body:JSON.stringify({type:'video_channel_url',url,scene:1})});return {status:r.status,body:await r.json()}}''',share_url)
            if response['status'] in (401,403):raise ValueError('YUANBAO_LOGIN_REQUIRED')
            if response['status']!=200:raise ValueError('YUANBAO_PARSE_UNAVAILABLE')
            parsed=response['body'].get('data') or {}
        finally:context.close()
    playable=parsed.get('playable_url','');query=parse_qs(urlsplit(playable).query)
    token=query.get('token',[''])[0];export=query.get('eid',[''])[0]
    if not token or not export:raise ValueError('CHANNELS_PARSE_NO_PLAYBACK')
    # Tencent returns the playback credential for this exact public share.
    from urllib.request import Request,urlopen
    req=Request('https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info',
        data=json.dumps({'baseReq':{'generalToken':token},'exportId':export}).encode(),
        headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0','Referer':playable,'Origin':'https://channels.weixin.qq.com'})
    with urlopen(req,timeout=25) as response:payload=json.load(response)
    feed=payload.get('data',{}).get('feedInfo') or {}
    url=(feed.get('h264VideoInfo') or {}).get('videoUrl') or feed.get('videoUrl') or feed.get('originVideoUrl')
    if not url:raise ValueError('CHANNELS_PARSE_NO_PLAYBACK')
    validate_public(url)
    return {'videoUrl':url,'decodeKey':feed.get('decodeKey'), 'title':feed.get('description') or parsed.get('desc'),
            'author':payload.get('data',{}).get('authorInfo',{}).get('nickname') or parsed.get('author'),
            'shareUrl':share_url,'exportId':export}


def read_xiaohongshu(url,output):
    from playwright.sync_api import sync_playwright
    from content_reader import html_content,finish,validate_public,is_xiaohongshu
    validate_public(url)
    host=urlsplit(url).hostname
    if not is_xiaohongshu(host):
        raise ValueError('XIAOHONGSHU_URL_INVALID')
    with sync_playwright() as p:
        context=open_context(p,'xiaohongshu')
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(url,wait_until='domcontentloaded',timeout=45000)
            try:page.wait_for_selector('#detail-title, .note-content',timeout=20000)
            except Exception:pass  # The initial state below decides whether target content exists.
            result=html_content(page.content(),page.url)
            result.update(url=url,finalUrl=page.url)
        finally:context.close()
    return finish(result,output)


def read_web(url,output):
    from playwright.sync_api import sync_playwright
    from content_reader import html_content,finish,validate_public
    validate_public(url)
    with sync_playwright() as p:
        context=open_context(p,'web')
        def public_only(route):
            try:
                if route.request.url.startswith(('data:','blob:')):route.continue_();return
                validate_public(route.request.url);route.continue_()
            except Exception:route.abort()
        context.route('**/*',public_only)
        try:
            page=context.pages[0] if context.pages else context.new_page()
            page.goto(url,wait_until='domcontentloaded',timeout=45000)
            text=page.locator('body').inner_text(timeout=10000)
            if re.search(r'请完成验证|人机验证|captcha',text[:1500],re.I):raise ValueError('CONTENT_VERIFICATION_REQUIRED')
            result=html_content(page.content(),page.url);result.update(url=url,finalUrl=page.url)
        finally:context.close()
    return finish(result,output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['auth','channels','xiaohongshu']);parser.add_argument('--provider',choices=['yuanbao','xiaohongshu'])
    parser.add_argument('--url');parser.add_argument('--output');parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    try:
        if args.command=='auth':authenticate(args.provider,args.timeout,args.url);return
        if args.command=='channels':
            result=channels(args.url)
            from article_media import save
            save(Path(args.output),result)
            print(json.dumps({'status':'resolved','metadataPath':args.output,'title':result.get('title')},ensure_ascii=False))
        else:
            result=read_xiaohongshu(args.url,args.output)
            print(json.dumps({k:result.get(k) for k in ['status','title','chars','contentPath']},ensure_ascii=False))
    except Exception as error:
        reason=str(error)
        if not re.fullmatch(r'[A-Z_]{5,90}',reason):reason=type(error).__name__
        print(json.dumps({'status':'failed','reason':reason},ensure_ascii=False))


if __name__=='__main__':main()
