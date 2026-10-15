import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { randomBytes, createHash } from 'node:crypto';

export function validateBase(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.port || url.username || url.password ||
      !(url.hostname === 'weixin.qq.com' || url.hostname.endsWith('.weixin.qq.com'))) {
    throw new Error('WEIXIN_UNTRUSTED_HOST');
  }
  return url.origin;
}
export function loadCredentials(home) {
  const env = {};
  for (const line of readFileSync(join(home, '.env'), 'utf8').split(/\r?\n/)) {
    const match = line.match(/^([A-Z_]+)=(.*)$/);
    if (match) env[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/, '$2');
  }
  const account = env.WEIXIN_ACCOUNT_ID;
  if (!account || !/^[\w@.\-]+$/.test(account)) throw new Error('WEIXIN_ACCOUNT_MISSING');
  const saved = JSON.parse(readFileSync(join(home, 'weixin', 'accounts', `${account}.json`), 'utf8'));
  const token = env.WEIXIN_TOKEN || saved.token;
  const allowed = (env.WEIXIN_ALLOWED_USERS || saved.user_id || '').split(',').map(x=>x.trim()).filter(Boolean);
  if (!token || !allowed.length) throw new Error('WEIXIN_TOKEN_OR_ALLOWLIST_MISSING');
  return { account, token, allowed, base: validateBase(env.WEIXIN_BASE_URL || saved.base_url || 'https://ilinkai.weixin.qq.com') };
}
export class Ilink {
  constructor(credentials, transport = fetch) { this.credentials = credentials; this.transport = transport; }
  async post(endpoint, payload, timeout = 40000) {
    const c = this.credentials;
    const response = await this.transport(`${c.base}/ilink/bot/${endpoint}`, {
      method: 'POST', redirect: 'error', signal: AbortSignal.timeout(timeout),
      headers: { 'Content-Type':'application/json', AuthorizationType:'ilink_bot_token',
        Authorization:`Bearer ${c.token}`, 'X-WECHAT-UIN':Buffer.from(String(randomBytes(4).readUInt32BE())).toString('base64'),
        'iLink-App-Id':'bot', 'iLink-App-ClientVersion':String(0x020408) },
      body: JSON.stringify({...payload, base_info:{channel_version:'2.4.8',bot_agent:'WeixinCodex/0.1.0'}})
    });
    if (!response.ok) throw Object.assign(new Error(`WEIXIN_HTTP_${response.status}`), {code:response.status});
    const data = await response.json();
    const code = Number(data.ret || data.errcode || 0);
    if (code) throw Object.assign(new Error(`WEIXIN_API_${code}`), {code});
    return data;
  }
  poll(cursor, timeout) { return this.post('getupdates', {get_updates_buf:cursor}, timeout); }
  check() { return this.post('getconfig', {ilink_user_id:this.credentials.allowed[0]}, 15000); }
  send(row, context) {
    if (!context) throw new Error('WEIXIN_CONTEXT_MISSING');
    return this.post('sendmessage', {msg:{from_user_id:'',to_user_id:row.peer,client_id:row.id,
      message_type:2,message_state:2,context_token:context,item_list:[{type:1,text_item:{text:row.text}}]}}, 15000);
  }
}
export function normalizeMessages(msgs, allowed, acceptSince = 0) {
  const result = [];
  for (const m of msgs ?? []) {
    const peer = m.from_user_id;
    if (!allowed.includes(peer) || m.group_id || m.message_type !== 1 || m.message_state === 1) continue;
    if (m.create_time_ms && m.create_time_ms < acceptSince) continue;
    if (!m.context_token) continue;
    const voices=(m.item_list??[]).filter(i=>i.type===3);
    const media=voices.filter(i=>!i.voice_item?.text).map(i=>i.voice_item||{});
    for(const i of m.item_list??[]){const kind={2:'image',4:'file',5:'video'}[i.type];if(kind&&i[kind+'_item'])media.push({kind,item:i[kind+'_item']});}
    const text = (m.item_list ?? []).map(i=>i.type===1 ? i.text_item?.text : i.type===3 ? i.voice_item?.text : '').filter(Boolean).join('\n').trim()
      || (media.some(x=>!x.kind)?'':media.some(x=>x.kind)?'请读取我发送的附件。':'【未支持的附件】');
    const id = m.message_id ?? m.client_id ?? m.seq;
    const fallback = createHash('sha256').update(JSON.stringify(m)).digest('hex');
    result.push({id:`${peer}:${id ?? fallback}`,peer,context:m.context_token,text,media,voice:voices.length>0});
  }
  return result;
}
export function splitReply(text, limit = 1600) {
  const chars = Array.from(String(text).trim());
  const chunks=[];
  for(let i=0;i<chars.length;i+=limit) chunks.push(chars.slice(i,i+limit).join(''));
  return chunks.length ? chunks : ['此次任务没有产生文字回复。请重新描述你的问题。'];
}
