import {readFileSync,writeFileSync,existsSync,mkdirSync,renameSync,copyFileSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';
import {homedir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {randomUUID} from 'node:crypto';

export function startupConfig(original,{root,node,shell,enabled=true}){
  const start='# BEGIN WECHAT LOCAL ASSISTANT STARTUP',end='# END WECHAT LOCAL ASSISTANT STARTUP';
  const pattern=/# BEGIN WECHAT LOCAL ASSISTANT STARTUP\r?\n[\s\S]*?# END WECHAT LOCAL ASSISTANT STARTUP(?:\r?\n)?/gu;
  const matches=[...original.matchAll(pattern)];
  if(matches.length>1)throw Error('Multiple managed startup entries require review.');
  const script=join(root,'scripts','codex-startup.mjs');
  if(matches.length&&!matches[0][0].includes(JSON.stringify(script)))throw Error('Startup entry belongs to a different installation.');
  const rest=original.replace(pattern,'');
  if(/^\s*\[mcp_servers\.wechat_local_assistant_startup(?:\]|\.)/mu.test(rest))throw Error('An unmanaged startup entry already exists; no changes made.');
  if(!enabled)return rest;
  const block=`${start}\n[mcp_servers.wechat_local_assistant_startup]\ncommand = ${JSON.stringify(node)}\nargs = ${JSON.stringify([script,shell])}\nenv_vars = ["WECHAT_ASSISTANT_CHILD"]\nenabled = true\nstartup_timeout_sec = 30\n${end}\n`;
  return matches.length?original.replace(pattern,()=>block):original+(original.endsWith('\n')?'':'\n')+'\n'+block;
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
  const cfg=JSON.parse(readFileSync(join(root,'config/local.json'),'utf8').replace(/^\uFEFF/,''));
  const arg=name=>{const i=process.argv.indexOf(name);return i<0?null:process.argv[i+1];};
  const configFile=resolve(arg('--config')||join(process.env.CODEX_HOME||join(homedir(),'.codex'),'config.toml'));
  const shell=arg('--shell');const enabled=!process.argv.includes('--disable');
  if(enabled&&(!shell||!existsSync(shell)))throw Error('Provide the installed PowerShell 7 path with --shell.');
  const original=existsSync(configFile)?readFileSync(configFile,'utf8'):'';
  const result=startupConfig(original,{root,node:cfg.nodePath,shell,enabled});
  if(result!==original){
    const backup=join(root,'.runtime','backups','codex-startup');mkdirSync(backup,{recursive:true});
    if(existsSync(configFile))copyFileSync(configFile,join(backup,Date.now()+'-'+randomUUID()+'.toml'));
    mkdirSync(dirname(configFile),{recursive:true});
    if((existsSync(configFile)?readFileSync(configFile,'utf8'):'')!==original)throw Error('Configuration changed concurrently; retry after review.');
    const tmp=configFile+'.wechat-'+randomUUID()+'.tmp';writeFileSync(tmp,result,{flag:'wx',mode:0o600});renameSync(tmp,configFile);
  }
  console.log(JSON.stringify({enabled,changed:result!==original,trigger:'codex-session-start',periodicChecks:false}));
}
