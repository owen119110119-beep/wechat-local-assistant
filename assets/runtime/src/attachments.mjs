import {createHash} from 'node:crypto';
import {mkdirSync,writeFileSync,readFileSync,existsSync,readdirSync} from 'node:fs';
import {join,extname} from 'node:path';
import {decryptVoice,mediaUrl} from './voice.mjs';
import {runFile} from './article.mjs';

export function attachmentKey(item){
 const raw=item.aeskey;
 if(raw&&/^[a-f0-9]{32}$/i.test(raw))return Buffer.from(raw,'hex').toString('base64');
 return item.media?.aes_key;
}
export function attachmentExtension(kind,name=''){
 const ext=extname(name).toLowerCase();
 if(kind==='image')return ['.png','.jpg','.jpeg','.webp','.gif','.bmp'].includes(ext)?ext:'.jpg';
 if(kind==='video')return ['.mp4','.mov','.mkv','.webm'].includes(ext)?ext:'.mp4';
 return /^\.[a-z0-9]{1,8}$/.test(ext)?ext:'.bin';
}
export class ContentReader{
 constructor(cfg,runtime){Object.assign(this,{cfg,runtime});}
 result(result,path){
  const {mediaCandidates,images,...safe}=result;
  return {...safe,metadataPath:path,body:result.contentPath&&existsSync(result.contentPath)?readFileSync(result.contentPath,'utf8').slice(0,16000):''};
 }
 fromCache(input){
  const parent=join(this.runtime,'content');if(!existsSync(parent))return null;
  const found=[];
  for(const entry of readdirSync(parent,{withFileTypes:true}).filter(x=>x.isDirectory()&&!x.isSymbolicLink())){
   const path=join(parent,entry.name,'content.json');
   try{const result=JSON.parse(readFileSync(path,'utf8'));
    if(result.url!==input||result.status!=='ready'||!result.contentPath||!existsSync(result.contentPath))continue;
    if(result.imageEvidence?.some(x=>x.status!=='ready'||!existsSync(x.imagePath)))continue;
    found.push({result,path});
   }catch{}
  }
  const cached=found.sort((a,b)=>(b.result.readAt||0)-(a.result.readAt||0))[0];
  return cached?{...this.result(cached.result,cached.path),reused:true}:null;
 }
 async read(input,id,mode='url',{signal,refresh=false}={}){
  if(signal?.aborted)throw Error('CODEX_CANCELLED');
  if(mode==='url'&&!refresh){const cached=this.fromCache(input);if(cached)return cached;}
  const root=join(this.runtime,'content',createHash('sha256').update(id).digest('hex'));
  mkdirSync(root,{recursive:true});
  const path=join(root,'content.json');
  writeFileSync(path,JSON.stringify({status:'processing'}));
  const binary=this.cfg.voicePythonPath&&existsSync(this.cfg.voicePythonPath)?this.cfg.voicePythonPath:this.cfg.pythonPath;
  try{await runFile(binary,['-X','utf8',join(this.cfg.projectRoot,'scripts','content_reader.py'),mode,'--input',input,'--output-dir',root,'--model-dir',join(this.runtime,'models','base')],480000,{HF_HUB_OFFLINE:'1',HF_HUB_DISABLE_TELEMETRY:'1'},signal);}catch{}
  if(signal?.aborted)throw Error('CODEX_CANCELLED');
  if(!existsSync(path))return{status:'failed',reason:'CONTENT_PROCESS_TIMEOUT_OR_FAILED'};
  const result=JSON.parse(readFileSync(path,'utf8'));
  if(result.status==='processing')return{status:'failed',reason:'CONTENT_PROCESS_TIMEOUT_OR_FAILED'};
  return this.result(result,path);
 }
}
export class Attachments{
 constructor(cfg,runtime,transport=fetch,reader=new ContentReader(cfg,runtime)){Object.assign(this,{cfg,runtime,transport,reader});}
 async prepare(items,id,{signal}={}){
  const root=join(this.runtime,'attachments',createHash('sha256').update(id).digest('hex'));mkdirSync(root,{recursive:true});
  const files=[];
  for(let n=0;n<items.length;n++){
   const {kind,item}=items[n];const originalName=String(item.file_name||`${kind}-${n+1}`).replace(/[\u0000-\u001f]/g,'').slice(0,240);
   try{
    const expected=Number(kind==='file'?item.len:kind==='video'?item.video_size:0)||0;
    if(expected>128*1024*1024)throw Error('ATTACHMENT_TOO_LARGE');
    const reference=item.media||{};
    const response=await this.transport(mediaUrl(reference.full_url?{full_url:reference.full_url}:reference),{redirect:'error',signal:signal?AbortSignal.any([signal,AbortSignal.timeout(45000)]):AbortSignal.timeout(45000)});
    if(!response.ok)throw Error('ATTACHMENT_DOWNLOAD_FAILED');
    const chunks=[];let bytes=0;
    for await(const chunk of response.body){bytes+=chunk.length;if(bytes>128*1024*1024+16)throw Error('ATTACHMENT_TOO_LARGE');chunks.push(chunk);}
    const data=decryptVoice(Buffer.concat(chunks),attachmentKey(item));
    if(expected&&data.length!==expected)throw Error('ATTACHMENT_SIZE_MISMATCH');
    const expectedHash=kind==='file'?item.md5:kind==='video'?item.video_md5:null;
    if(expectedHash&&createHash('md5').update(data).digest('hex')!==expectedHash.toLowerCase())throw Error('ATTACHMENT_CHECKSUM_MISMATCH');
    const path=join(root,`${n+1}${attachmentExtension(kind,item.file_name)}`);writeFileSync(path,data);
    const result=await this.reader.read(path,`${id}:attachment:${n}`,'file',{signal});
    files.push({...result,originalName,localPath:path,bytes:data.length});
   }catch(error){if(signal?.aborted)throw Error('CODEX_CANCELLED');files.push({originalName,kind,status:'failed',reason:/^[A-Z_]+$/.test(error.message)?error.message:'ATTACHMENT_READ_FAILED'});}
  }
  // CDN references and AES keys are never copied to model context or this result.
  const result={files};writeFileSync(join(root,'resources.json'),JSON.stringify(result,null,2));return files;
 }
}
export function contentLinks(text){
 const links=[];
 for(const match of String(text).matchAll(/https:\/\/[^\s<>"“”]+/gu)){
  try{const url=new URL(match[0].replace(/[）)。，；！？]+$/u,'').replaceAll('&amp;','&'));
   if(url.hostname==='mp.weixin.qq.com'||url.username||url.password||url.port)continue;
   url.hash='';if(!links.includes(url.href))links.push(url.href);
  }catch{}
 }
 return links;
}
