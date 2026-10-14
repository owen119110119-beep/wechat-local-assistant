import { existsSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';

export function alive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {process.kill(pid,0);return true;} catch(e) {return e.code==='EPERM';}
}
export function acquireLock(token, directory = process.env.HERMES_GATEWAY_LOCK_DIR ||
  join(process.env.XDG_STATE_HOME || join(homedir(),'.local','state'),'hermes','gateway-locks')) {
  mkdirSync(directory,{recursive:true});
  const hash=createHash('sha256').update(token).digest('hex').slice(0,16);
  const file=join(directory,`weixin-bot-token-${hash}.lock`);
  if(existsSync(file)) {
    // A malformed lock is kept: its owner could still be writing it.
    let old;
    try {old=JSON.parse(readFileSync(file,'utf8'));} catch {throw new Error('WEIXIN_LOCK_UNREADABLE');}
    if(alive(old.pid)) throw new Error('WEIXIN_TOKEN_ALREADY_IN_USE');
    unlinkSync(file);
  }
  writeFileSync(file,JSON.stringify({pid:process.pid,kind:'gateway',argv:['weixin-codex','gateway','run'],
    start_time:null,scope:'weixin-bot-token',identity_hash:hash,metadata:{platform:'weixin'},updated_at:new Date().toISOString()}),{flag:'wx'});
  return ()=>{
    try {if(JSON.parse(readFileSync(file,'utf8')).pid===process.pid) unlinkSync(file);} catch {}
  };
}
