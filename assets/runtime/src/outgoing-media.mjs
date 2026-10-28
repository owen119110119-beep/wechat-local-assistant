import {createHash,createCipheriv,randomBytes} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync,lstatSync,realpathSync,existsSync} from 'node:fs';
import {resolve,relative,dirname,join,basename,sep} from 'node:path';

export const MAX_DELIVERY_BYTES=128*1024*1024;
export function confinedFile(root,path){
 const base=resolve(root),target=resolve(path),rel=relative(base,target);
 if(!rel||rel==='..'||rel.startsWith('..'+sep)||resolve(base,rel)!==target)throw Error('MEDIA_PATH_ESCAPE');
 for(let p=target;;p=dirname(p)){
  if(existsSync(p)&&lstatSync(p).isSymbolicLink())throw Error('MEDIA_LINK_FORBIDDEN');
  if(p===base)break;if(dirname(p)===p)throw Error('MEDIA_PATH_ESCAPE');
 }
 if(existsSync(target)&&relative(realpathSync(base),realpathSync(target)).startsWith('..'))throw Error('MEDIA_PATH_ESCAPE');
 return target;
}
export function snapshotMedia(root,path,name){
 const target=confinedFile(root,path),stat=lstatSync(target);
 if(!stat.isFile()||stat.size<1||stat.size>MAX_DELIVERY_BYTES)throw Error('MEDIA_SIZE_INVALID');
 const data=readFileSync(target),sha256=createHash('sha256').update(data).digest('hex');
 const fileName=basename(name||target).replace(/[\u0000-\u001f<>:"/\\|?*]/g,'_').slice(0,160);
 const kind=/\.(png|jpe?g|webp|gif)$/iu.test(fileName)?'image':'file';
 if(kind==='image'&&!isImage(data))throw Error('MEDIA_IMAGE_INVALID');
 if(/\.pdf$/iu.test(fileName)&&data.subarray(0,5).toString()!=='%PDF-')throw Error('MEDIA_PDF_INVALID');
 const folder=join(root,'delivery-snapshots');mkdirSync(folder,{recursive:true});
 const saved=confinedFile(root,join(folder,sha256));
 if(!existsSync(saved))writeFileSync(saved,data,{flag:'wx'});
 return {path:saved,name:fileName,bytes:data.length,sha256,kind};
}
export function isImage(data){return data.subarray(0,3).equals(Buffer.from([255,216,255]))||data.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))||/^GIF8/u.test(data.subarray(0,4).toString())||(data.subarray(0,4).toString()==='RIFF'&&data.subarray(8,12).toString()==='WEBP');}
export function checkedMedia(media){
 const data=readFileSync(media.path);
 if(data.length!==media.bytes||data.length>MAX_DELIVERY_BYTES||createHash('sha256').update(data).digest('hex')!==media.sha256)throw Error('MEDIA_CONTENT_CHANGED');
 return data;
}
export function uploadUrl(response,filekey){
 const value=response.upload_full_url?.trim()||(response.upload_param?`https://novac2c.cdn.weixin.qq.com/c2c/upload?encrypted_query_param=${encodeURIComponent(response.upload_param)}&filekey=${encodeURIComponent(filekey)}`:'');
 if(!value)throw Error('WEIXIN_UPLOAD_URL_MISSING');
 const u=new URL(value);
 if(u.protocol!=='https:'||u.username||u.password||u.port||!['novac2c.cdn.weixin.qq.com'].includes(u.hostname))throw Error('WEIXIN_UPLOAD_UNTRUSTED_HOST');
 return u.href;
}
export async function uploadMedia(ilink,media,peer){
 const data=checkedMedia(media),key=randomBytes(16),filekey=randomBytes(16).toString('hex');
 const cipher=createCipheriv('aes-128-ecb',key,null),encrypted=Buffer.concat([cipher.update(data),cipher.final()]);
 const response=await ilink.post('getuploadurl',{filekey,media_type:media.kind==='image'?1:3,to_user_id:peer,rawsize:data.length,rawfilemd5:createHash('md5').update(data).digest('hex'),filesize:encrypted.length,no_need_thumb:true,aeskey:key.toString('hex')},20000);
 const uploaded=await ilink.transport(uploadUrl(response,filekey),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:encrypted,redirect:'error',signal:AbortSignal.timeout(90000)});
 if(uploaded.status!==200)throw Error('WEIXIN_UPLOAD_HTTP_'+uploaded.status);
 const param=uploaded.headers.get('x-encrypted-param');if(!param)throw Error('WEIXIN_UPLOAD_RECEIPT_MISSING');
 // The official client encodes ASCII hex, rather than raw key bytes, in outgoing references.
 const reference={encrypt_query_param:param,aes_key:Buffer.from(key.toString('hex')).toString('base64'),encrypt_type:1};
 return media.kind==='image'?{type:2,image_item:{media:reference,mid_size:encrypted.length}}:{type:4,file_item:{media:reference,file_name:media.name,len:String(data.length)}};
}
