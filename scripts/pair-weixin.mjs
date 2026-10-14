// QR pairing follows Tencent/openclaw-weixin src/auth/login-qr.ts; no existing binding is read.
import {mkdirSync,writeFileSync,existsSync,readFileSync} from 'node:fs';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createInterface} from 'node:readline/promises';
import {spawn,execFileSync} from 'node:child_process';

export function trustedBase(value){const u=new URL(value);if(u.protocol!=='https:'||u.port||u.username||u.password||!(u.hostname==='weixin.qq.com'||u.hostname.endsWith('.weixin.qq.com')))throw Error('Untrusted WeChat host');return u.origin;}
const headers={'Content-Type':'application/json','iLink-App-Id':'bot','iLink-App-ClientVersion':String(0x020408)};
async function request(base,path,post,body){const response=await fetch(trustedBase(base)+path,{method:post?'POST':'GET',headers,body:post?JSON.stringify(body):undefined,redirect:'error',signal:AbortSignal.timeout(35000)});if(!response.ok)throw Error('WeChat HTTP '+response.status);return response.json();}
export function saveBinding(home,result){
  const account=result.ilink_bot_id,user=result.ilink_user_id;
  if(!account||!/^[\w@.\-]+$/.test(account)||!user||!/^[\w@.\-]+$/.test(user)||!result.bot_token)throw Error('Incomplete WeChat binding');
  const base=trustedBase(result.baseurl||'https://ilinkai.weixin.qq.com');
  if(existsSync(join(home,'.env')))throw Error('Existing binding preserved; use a fresh target');
  const dir=join(home,'weixin/accounts');mkdirSync(dir,{recursive:true});
  writeFileSync(join(dir,account+'.json'),JSON.stringify({token:result.bot_token,user_id:user,base_url:base}),{flag:'wx',mode:0o600});
  writeFileSync(join(home,'.env'),'WEIXIN_ACCOUNT_ID='+account+'\nWEIXIN_ALLOWED_USERS='+user+'\n',{flag:'wx',mode:0o600});
}
async function main(){
  const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
  const cfg=JSON.parse(readFileSync(join(root,'config/local.json'),'utf8'));
  const home=cfg.credentialsSource;
  if(existsSync(join(home,'.env')))throw Error('This deployment already has a binding; no rebind performed');
  if(cfg.host!=='codex'||cfg.agentMode!==true)throw Error('Only a fresh Codex Agent deployment can pair here');
  let base='https://ilinkai.weixin.qq.com';
  const qr=await request(base,'/ilink/bot/get_bot_qrcode?bot_type=3',true,{local_token_list:[]});
  if(!qr.qrcode||!qr.qrcode_img_content)throw Error('WeChat did not return a QR link');
  const link=new URL(qr.qrcode_img_content);trustedBase(link.href);
  const escaped=link.href.replaceAll('&','&amp;').replaceAll('"','&quot;');
  const page=join(root,'.runtime/weixin-pair.html');mkdirSync(dirname(page),{recursive:true});
  const svg=execFileSync(cfg.pythonPath,['-c',"import sys,qrcode,qrcode.image.svg; qrcode.make(sys.argv[1],image_factory=qrcode.image.svg.SvgPathImage).save(sys.stdout.buffer)",link.href],{windowsHide:true,env:{...process.env,PYTHONPATH:join(root,'.runtime/qr-deps')}});
  const image='data:image/svg+xml;base64,'+svg.toString('base64');
  writeFileSync(page,'<!doctype html><meta charset="utf-8"><title>微信助理绑定</title><h1>用手机微信扫码</h1><p>如果手机提示替换旧助理，请停止，保留原绑定。</p><img alt="绑定二维码" src="'+image+'"><p><a href="'+escaped+'">微信官方绑定链接</a></p>');
  console.log('本机绑定页面：'+page+'；首次扫码在手机完成。');
  if(process.platform==='win32')spawn('rundll32.exe',['url.dll,FileProtocolHandler',pathToFileURL(page).href],{windowsHide:true,stdio:'ignore'}).unref();
  const deadline=Date.now()+300000;let verification;
  while(Date.now()<deadline){
    let result;try{result=await request(base,'/ilink/bot/get_qrcode_status?qrcode='+encodeURIComponent(qr.qrcode)+(verification?'&verify_code='+encodeURIComponent(verification):''),false);}catch(e){if(e.name==='TimeoutError')continue;throw e;}
    if(result.status==='confirmed'){saveBinding(home,result);console.log('微信绑定已保存到本机私有运行目录；尚未启动服务。');return;}
    if(result.status==='scaned_but_redirect'){base=trustedBase('https://'+result.redirect_host);continue;}
    if(result.status==='need_verifycode'){const rl=createInterface({input:process.stdin,output:process.stdout});try{verification=await rl.question('请在本机输入微信显示的二次验证码：');}finally{rl.close();}continue;}
    if(['expired','verify_code_blocked','binded_redirect'].includes(result.status))throw Error('WeChat pairing ended: '+result.status+'; no existing binding modified');
    await new Promise(r=>setTimeout(r,1000));
  }
  throw Error('WeChat QR expired or pairing timed out; no binding saved');
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(e=>{console.error(e.name==='Error'?e.message:'WeChat pairing network failure');process.exitCode=1;});
