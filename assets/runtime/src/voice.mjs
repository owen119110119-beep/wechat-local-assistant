import { createDecipheriv,createHash } from 'node:crypto';
import { mkdirSync,writeFileSync,unlinkSync,existsSync } from 'node:fs';
import { join } from 'node:path';
import { runFile } from './article.mjs';
const hosts=new Set(['novac2c.cdn.weixin.qq.com','ilinkai.weixin.qq.com']);
export function mediaUrl(media) {
  const url=media.encrypt_query_param?`https://novac2c.cdn.weixin.qq.com/c2c/download?encrypted_query_param=${encodeURIComponent(media.encrypt_query_param)}`:media.full_url;
  const u=new URL(url);
  if(u.protocol!=='https:'||u.username||u.password||u.port||!hosts.has(u.hostname))throw new Error('VOICE_UNTRUSTED_HOST');
  return u.href;
}
export function decryptVoice(data,aes) {
  if(typeof aes!=='string'||!aes)throw new Error('VOICE_KEY_MISSING');
  let key=Buffer.from(aes,'base64');
  if(key.length===32&&/^[0-9a-f]{32}$/i.test(key.toString('ascii')))key=Buffer.from(key.toString('ascii'),'hex');
  if(key.length!==16)throw new Error('VOICE_INVALID_KEY');
  const d=createDecipheriv('aes-128-ecb',key,null);return Buffer.concat([d.update(data),d.final()]);
}
export function wav(pcm,rate=24000) {
  const b=Buffer.alloc(44+pcm.length);b.write('RIFF');b.writeUInt32LE(36+pcm.length,4);b.write('WAVEfmt ',8);
  b.writeUInt32LE(16,16);b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(rate,24);
  b.writeUInt32LE(rate*2,28);b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(pcm.length,40);Buffer.from(pcm).copy(b,44);return b;
}
export class Voice {
  constructor(cfg,runtime,transport=fetch){this.cfg=cfg;this.runtime=runtime;this.transport=transport;}
  async transcribe(items,id) {
    const dir=join(this.runtime,'audio');mkdirSync(dir,{recursive:true});const result=[];
    for(let n=0;n<items.length;n++) {
      const item=items[n],path=join(dir,createHash('sha256').update(id+':'+n).digest('hex')+'.wav');
      try {
        if(item.playtime>180000)throw new Error('VOICE_TOO_LONG');
        const response=await this.transport(mediaUrl(item.media||{}),{redirect:'error',signal:AbortSignal.timeout(30000)});
        if(!response.ok)throw new Error('VOICE_DOWNLOAD_FAILED');
        const chunks=[];let size=0;
        for await(const chunk of response.body){size+=chunk.length;if(size>8*1024*1024)throw new Error('VOICE_TOO_LARGE');chunks.push(chunk);}
        let data=decryptVoice(Buffer.concat(chunks),item.media.aes_key);
        if(data.subarray(0,4).toString()!=='RIFF') {
          const {decode,isSilk,getDuration}=await import('silk-wasm');
          if(isSilk(data)){if(getDuration(data)>180000)throw new Error('VOICE_TOO_LONG');data=wav((await decode(data,24000)).data);}
          else if(item.encode_type===1)data=wav(data,item.sample_rate||24000);
          else if(![7].includes(item.encode_type))throw new Error('VOICE_FORMAT_UNSUPPORTED');
        }
        writeFileSync(path,data);
        const output=await runFile(this.cfg.voicePythonPath,[join(this.cfg.projectRoot,'scripts','transcribe.py'),path,'--model-dir',join(this.runtime,'models','base')],180000,{HF_HUB_OFFLINE:'1',HF_HUB_DISABLE_TELEMETRY:'1',PYTHONUTF8:'1'});
        const transcript=JSON.parse(output);
        if(!transcript.text?.trim())throw new Error('VOICE_EMPTY_TRANSCRIPT');
        if(transcript.duration>180)throw new Error('VOICE_TOO_LONG');
        result.push(transcript.text.trim());
      }finally{if(existsSync(path))unlinkSync(path);}
    }
    return result.join('\n');
  }
}
