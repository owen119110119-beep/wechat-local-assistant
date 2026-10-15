import {existsSync,lstatSync,readdirSync,statSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {homedir} from 'node:os';

export const WINDOWS_COMPONENTS=['codex-code-mode-host.exe','codex-command-runner.exe','codex-windows-sandbox-setup.exe'];
export function missingRuntimeFiles(binary,{platform=process.platform}={}){
  const files=[binary,...(platform==='win32'?WINDOWS_COMPONENTS.map(name=>join(dirname(binary),name)):[])];
  return files.filter(file=>!existsSync(file)||!statSync(file).isFile());
}
export function resolveRuntime(binary,{platform=process.platform,installRoot=join(homedir(),'AppData','Local','OpenAI','Codex','bin')}={}){
  if(!missingRuntimeFiles(binary,{platform}).length)return binary;
  if(platform!=='win32'||!existsSync(installRoot))throw new Error('CODEX_RUNTIME_INCOMPLETE');
  const choices=readdirSync(installRoot,{withFileTypes:true}).filter(e=>e.isDirectory()&&!e.isSymbolicLink()).map(e=>join(installRoot,e.name,'codex.exe'))
    .filter(file=>!lstatSync(dirname(file)).isSymbolicLink()&&!missingRuntimeFiles(file,{platform}).length)
    .sort((a,b)=>statSync(b).mtimeMs-statSync(a).mtimeMs||a.localeCompare(b));
  if(!choices.length)throw new Error('CODEX_RUNTIME_INCOMPLETE');
  return choices[0];
}
export function verifyRuntime(binary){
  const result=spawnSync(binary,['--version'],{encoding:'utf8',windowsHide:true,timeout:10000});
  if(result.status!==0||!/^codex-cli /u.test(result.stdout?.trim()||''))throw new Error('CODEX_RUNTIME_INVALID');
  return binary;
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  try{const selected=resolveRuntime(process.argv[2]);verifyRuntime(selected);process.stdout.write(JSON.stringify({codexPath:selected}));}
  catch(error){process.stderr.write(error.message+'\n');process.exitCode=1;}
}
