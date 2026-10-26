import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {readFileSync,appendFileSync,mkdirSync,openSync,closeSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const runtime=join(root,'.runtime');
mkdirSync(runtime,{recursive:true});
const shell=process.argv[2];
let startup=null;
const log=(event,details={})=>appendFileSync(join(runtime,'codex-startup.log'),JSON.stringify({at:new Date().toISOString(),event,bridgePid:process.pid,ownerPid:process.ppid,...details})+'\n');
function start(){
  if(process.env.WECHAT_ASSISTANT_CHILD==='1')return Promise.resolve();
  if(startup)return startup;
  startup=new Promise((resolve,reject)=>{
  if(!shell){log('missing_powershell');reject(Error('STARTUP_SHELL_MISSING'));return;}
  const output=openSync(join(runtime,'codex-startup.stdout.log'),'a');
  const errors=openSync(join(runtime,'codex-startup.stderr.log'),'a');
  const child=spawn(shell,['-NoLogo','-NoProfile','-NonInteractive','-File',join(root,'scripts/start.ps1'),'-RespectStop','-Handoff'],{cwd:root,windowsHide:true,stdio:['ignore',output,errors]});
  closeSync(output);closeSync(errors);
  const timer=setTimeout(()=>{child.kill();log('startup_handoff_timeout');reject(Error('STARTUP_HANDOFF_TIMEOUT'));},20000);
  child.on('error',()=>{clearTimeout(timer);log('startup_process_failed');reject(Error('STARTUP_PROCESS_FAILED'));});
  child.on('exit',code=>{clearTimeout(timer);log(code===0?'startup_handoff_completed':'startup_failed');code===0?resolve():reject(Error('STARTUP_HANDOFF_FAILED'));});
  log('codex_requested_start',{starterPid:child.pid});
  });
  return startup;
}
function status(){
  try{const x=JSON.parse(readFileSync(join(runtime,'status.json'),'utf8'));return{state:x.state,codex:x.codex,weixin:x.weixin,busy:!!x.busy,updatedAt:x.updatedAt};}
  catch{return{state:'unavailable'};}
}
const send=(id,result,error)=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',id,...(error?{error}:{result})})+'\n');
createInterface({input:process.stdin}).on('line',async line=>{
  let x;try{x=JSON.parse(line);}catch{send(null,null,{code:-32700,message:'Parse error'});return;}
  if(x.id===undefined)return;
  if(x.method==='initialize'){
    // Report an initialized connection only after the independent worker exists.
    try { await start(); } catch { send(x.id,null,{code:-32603,message:'本机微信助理的启动交接失败，请查看本机启动日志。'});return; }
    send(x.id,{protocolVersion:x.params?.protocolVersion||'2024-11-05',capabilities:{tools:{}},serverInfo:{name:'wechat-local-assistant-startup',version:'1.1.0'}});
  }else if(x.method==='tools/list')send(x.id,{tools:[{name:'assistant_status',description:'查看本机微信助理的连接状态。',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,destructiveHint:false,openWorldHint:false}}]});
  else if(x.method==='tools/call'&&x.params?.name==='assistant_status')send(x.id,{content:[{type:'text',text:JSON.stringify(status())}]});
  else if(x.method==='ping')send(x.id,{});
  else send(x.id,null,{code:-32601,message:'Method not found'});
}).on('close',()=>{log('mcp_connection_closed');process.exit(0);});
