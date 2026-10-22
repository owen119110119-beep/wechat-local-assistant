import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {readFileSync,appendFileSync,mkdirSync,openSync,closeSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const runtime=join(root,'.runtime');
mkdirSync(runtime,{recursive:true});
const shell=process.argv[2];
let started=false;
const log=event=>appendFileSync(join(runtime,'codex-startup.log'),JSON.stringify({at:new Date().toISOString(),event})+'\n');
function start(){
  if(started||process.env.WECHAT_ASSISTANT_CHILD==='1')return;
  started=true;
  if(!shell){log('missing_powershell');return;}
  const output=openSync(join(runtime,'codex-startup.stdout.log'),'a');
  const errors=openSync(join(runtime,'codex-startup.stderr.log'),'a');
  const child=spawn(shell,['-NoLogo','-NoProfile','-NonInteractive','-File',join(root,'scripts/start.ps1'),'-RespectStop'],{cwd:root,windowsHide:true,stdio:['ignore',output,errors]});
  closeSync(output);closeSync(errors);
  child.on('error',()=>log('startup_process_failed'));
  child.on('exit',code=>log(code===0?'startup_ok':'startup_failed'));
  log('codex_requested_start');
}
function status(){
  try{const x=JSON.parse(readFileSync(join(runtime,'status.json'),'utf8'));return{state:x.state,codex:x.codex,weixin:x.weixin,busy:!!x.busy,updatedAt:x.updatedAt};}
  catch{return{state:'unavailable'};}
}
const send=(id,result,error)=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',id,...(error?{error}:{result})})+'\n');
createInterface({input:process.stdin}).on('line',line=>{
  let x;try{x=JSON.parse(line);}catch{send(null,null,{code:-32700,message:'Parse error'});return;}
  if(x.id===undefined)return;
  if(x.method==='initialize'){
    send(x.id,{protocolVersion:x.params?.protocolVersion||'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'wechat-local-assistant-startup',version:'1.1.0'}});
    start();
  }else if(x.method==='tools/list')send(x.id,{tools:[{name:'assistant_status',description:'查看本机微信助理的连接状态。',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:false}}]});
  else if(x.method==='tools/call'&&x.params?.name==='assistant_status')send(x.id,{content:[{type:'text',text:JSON.stringify(status())}]});
  else if(x.method==='ping')send(x.id,{});
  else send(x.id,null,{code:-32601,message:'Method not found'});
}).on('close',()=>process.exit(0));
