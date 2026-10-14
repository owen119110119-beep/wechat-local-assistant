import { execFile } from 'node:child_process';
import { readFileSync,mkdirSync,existsSync,mkdtempSync } from 'node:fs';
import { join } from 'node:path';
export function articleLinks(text) {
  const links=[];
  for(const match of text.matchAll(/https:\/\/mp\.weixin\.qq\.com[^\s<>"“”]+/g)) {
    const raw=match[0].replace(/[）)。，；！？]+$/u,'').replaceAll('&amp;','&');
    try {const u=new URL(raw);if(u.hostname==='mp.weixin.qq.com'&&!u.username&&!u.password&&!u.port){u.hash='';if(!links.includes(u.href))links.push(u.href);}}catch{}
  }
  return links;
}
export function runFile(binary,args,timeout=120000,env={}) {
  return new Promise((resolve,reject)=>execFile(binary,args,{windowsHide:true,timeout,maxBuffer:1024*1024,env:{...process.env,...env}},(error,stdout)=>{
    if(error) reject(Object.assign(new Error('LOCAL_PROCESS_FAILED'),{exitCode:error.code}));else resolve(stdout.trim());
  }));
}
export class ArticleReader {
  constructor(cfg,runtime){this.cfg=cfg;this.runtime=runtime;}
  async read(url,id) {
    if(articleLinks(url)[0]!==url||!/^A[0-9a-f]{10}$/.test(id))throw new Error('ARTICLE_INVALID_URL');
    const parent=join(this.runtime,'articles',id);mkdirSync(parent,{recursive:true});
    const dir=mkdtempSync(join(parent,'read-'));
    try{await runFile(this.cfg.pythonPath,[this.cfg.articleReaderPath,url,'--output-dir',dir,'--quiet','--timeout','25'],65000);}catch{}
    const metaFile=join(dir,'article.json');
    if(!existsSync(metaFile))throw new Error('ARTICLE_NETWORK_OR_TIMEOUT');
    const meta=JSON.parse(readFileSync(metaFile,'utf8'));
    if(!meta.ok)throw new Error(meta.verification_page?'ARTICLE_VERIFICATION_REQUIRED':'ARTICLE_BODY_UNAVAILABLE');
    const body=readFileSync(join(dir,'article.md'),'utf8');
    if(meta.content_chars<80||!body.trim())throw new Error('ARTICLE_BODY_UNAVAILABLE');
    if(body.length>90000)throw new Error('ARTICLE_TOO_LONG');
    return {url,title:meta.title,author:meta.author,published:meta.publish_time||'',body,chars:meta.content_chars,readAt:new Date().toISOString()};
  }
}
