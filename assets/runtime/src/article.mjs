import { execFile } from 'node:child_process';
import { readFileSync,mkdirSync,existsSync,mkdtempSync,readdirSync,lstatSync,statSync } from 'node:fs';
import { join,dirname } from 'node:path';
import { createHash } from 'node:crypto';
export function articleLinks(text) {
  const links=[];
  for(const match of text.matchAll(/https:\/\/mp\.weixin\.qq\.com[^\s<>"“”]+/g)) {
    const raw=match[0].replace(/[）)。，；！？]+$/u,'').replaceAll('&amp;','&');
    try {const u=new URL(raw);if(u.hostname==='mp.weixin.qq.com'&&!u.username&&!u.password&&!u.port){u.hash='';if(!links.includes(u.href))links.push(u.href);}}catch{}
  }
  return links;
}
export function runFile(binary,args,timeout=120000,env={},signal) {
  return new Promise((resolve,reject)=>execFile(binary,args,{windowsHide:true,timeout,signal,maxBuffer:1024*1024,env:{...process.env,...env}},(error,stdout)=>{
    if(error) reject(Object.assign(new Error('LOCAL_PROCESS_FAILED'),{exitCode:error.code}));else resolve(stdout.trim());
  }));
}
export class ArticleReader {
  constructor(cfg,runtime){this.cfg=cfg;this.runtime=runtime;}
  async fromCache(url,id){
    if(!/^A[0-9a-f]{10}$/.test(id))return null;
    const parent=join(this.runtime,'articles',id);if(!existsSync(parent)||lstatSync(parent).isSymbolicLink())return null;
    for(const entry of readdirSync(parent,{withFileTypes:true}).filter(x=>x.isDirectory()&&!x.isSymbolicLink()).sort((a,b)=>statSync(join(parent,b.name)).mtimeMs-statSync(join(parent,a.name)).mtimeMs)){
      const dir=join(parent,entry.name),path=join(dir,'article.json');
      if(!existsSync(path)||lstatSync(path).isSymbolicLink())continue;
      try{const meta=JSON.parse(readFileSync(path,'utf8'));if(meta.ok&&meta.url===url)return await this.result(url,id,dir,meta);}catch{/* Corrupt cache is not a usable article. */}
    }
    return null;
  }
  async result(url,id,dir,meta){
    const contentPath=join(dir,'article.md'),rawPath=join(dir,'raw.html');
    if(lstatSync(contentPath).isSymbolicLink())throw Error('ARTICLE_CACHE_LINK_FORBIDDEN');
    const body=readFileSync(contentPath,'utf8');
    if(meta.content_chars<80||!body.trim())throw new Error('ARTICLE_BODY_UNAVAILABLE');
    if(body.length>90000)throw new Error('ARTICLE_TOO_LONG');
    const result={url,title:meta.title,author:meta.author,published:meta.publish_time||'',body,chars:meta.content_chars,readAt:new Date().toISOString(),cache:{directory:dir,contentPath,rawPath,metadataPath:join(dir,'article.json')}};
    const script=join(dirname(this.runtime),'scripts','article_media.py');
    if(existsSync(script)&&existsSync(rawPath)&&!lstatSync(rawPath).isSymbolicLink()){
      const mediaDir=join(this.runtime,'article-media',id),manifestPath=join(mediaDir,'media.json');
      try{
        const digest=createHash('sha256').update(readFileSync(rawPath)).digest('hex');
        let previous=null;try{previous=JSON.parse(readFileSync(manifestPath,'utf8'));}catch{}
        if(previous?.sourceSha256!==digest)await runFile(this.cfg.pythonPath,['-X','utf8',script,'inspect','--html',rawPath,'--article-url',url,'--output-dir',mediaDir],30000);
        const manifest=JSON.parse(readFileSync(manifestPath,'utf8'));
        if(manifest.articleUrl!==url)throw Error('ARTICLE_MEDIA_CACHE_MISMATCH');
        const binary=this.cfg.voicePythonPath&&existsSync(this.cfg.voicePythonPath)?this.cfg.voicePythonPath:this.cfg.pythonPath;
        result.media={manifestPath,status:manifest.status,videos:manifest.videos.map(({index,kind,title,author,duration,status,reason,evidencePath})=>({index,kind,title,author,duration,status,reason,evidencePath})),analyze:{binary,args:['-X','utf8',script,'analyze','--manifest',manifestPath,'--model-dir',join(this.runtime,'models','base')]}};
      }catch{result.media={status:'inspection_failed',explanation:'正文已读取，内嵌媒体识别失败；可检查保留的原始HTML。'};}
    }
    return result;
  }
  async read(url,id) {
    if(articleLinks(url)[0]!==url||!/^A[0-9a-f]{10}$/.test(id))throw new Error('ARTICLE_INVALID_URL');
    const cached=await this.fromCache(url,id);if(cached)return cached;
    const parent=join(this.runtime,'articles',id);mkdirSync(parent,{recursive:true});
    const dir=mkdtempSync(join(parent,'read-'));
    try{await runFile(this.cfg.pythonPath,[this.cfg.articleReaderPath,url,'--output-dir',dir,'--quiet','--timeout','25'],65000);}catch{}
    const metaFile=join(dir,'article.json');
    if(!existsSync(metaFile))throw new Error('ARTICLE_NETWORK_OR_TIMEOUT');
    const meta=JSON.parse(readFileSync(metaFile,'utf8'));
    if(!meta.ok)throw new Error(meta.verification_page?'ARTICLE_VERIFICATION_REQUIRED':'ARTICLE_BODY_UNAVAILABLE');
    return this.result(url,id,dir,meta);
  }
}
