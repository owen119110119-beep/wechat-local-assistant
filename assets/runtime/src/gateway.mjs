import { readFileSync, writeFileSync, mkdirSync, existsSync, appendFileSync, unlinkSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Store } from './store.mjs';
import { Codex } from './codex.mjs';
import { Ilink,loadCredentials,normalizeMessages,splitReply } from './ilink.mjs';
import { acquireLock } from './lock.mjs';
import { ArticleReader } from './article.mjs';
import { Voice } from './voice.mjs';
import { Vault } from './vault.mjs';
import { Knowledge } from './knowledge.mjs';
import { Sessions } from './sessions.mjs';
import { mobileText } from './mobile.mjs';

export const HELP='我是本机 Codex 微信助理。文字或语音自然说需求即可，可以连续讨论、实际联网调研、查看或编辑项目与知识库，不需要固定格式。\n公众号文章按约定：先给要点并追问重点，收到需求后实际整理，再独立建议分类、问如何分类及是否待办。普通/重点只选一类；明确选择就执行，不二次确认。\n我正在处理时也可补充要求；需要时会发进度。保存会实际读回，失败说明具体原因。\n帮助或/help；状态；新对话；停止。电脑需开机联网，后台服务持续运行。';
export function command(text) {
  return ({'/help':'help','帮助':'help','/status':'status','状态':'status','/new':'new','新对话':'new',
    '/cancel':'cancel','停止':'cancel'})[text.trim().replace(/[。.!！]+$/u,'').toLowerCase()] || null;
}
export function startupReason(error){
  const detail=String(error.rpcDetail||error.message||'');
  if(/active writer/i.test(detail))return 'SESSION_WRITER_BUSY';
  if(/refresh.*token|network|connect|timed? ?out|fetch/i.test(detail))return 'CODEX_CONNECTIVITY';
  if(/log.?in|unauthori|authentication/i.test(detail))return 'CODEX_LOGIN_REQUIRED';
  if(/permission|profile|unknown variant|configuration/i.test(detail))return 'CODEX_CONFIGURATION';
  return 'UNCLASSIFIED';
}
export class Gateway {
  constructor(store,ilink,codex,cfg,report=()=>{},knowledge=null) {
    this.store=store;this.ilink=ilink;this.codex=codex;this.cfg=cfg;this.report=report;
    this.busy=false;this.stopping=false;this.lastPoll=null;this.lastReceive=null;this.lastReply=null;this.error=null;
    this.knowledge=knowledge;
    this.acceptSince=Number(store.get('acceptSince',String(Date.now()-300000)));
    store.set('acceptSince',this.acceptSince);
  }
  status() {
    return {codex:this.codex.ready?'ready':'disconnected',weixin:this.error==='WEIXIN_API_-14'?'login_required':this.lastPoll?'connected':'starting',
      busy:this.busy,lastPoll:this.lastPoll,lastReceive:this.lastReceive,lastReply:this.lastReply,error:this.error,...this.store.counts()};
  }
  async ingest(data) {
    const msgs=normalizeMessages(data.msgs,this.ilink.credentials.allowed,this.acceptSince);
    this.store.ingest(msgs,data.get_updates_buf);
    this.lastPoll=new Date().toISOString();this.error=null;
    if(msgs.length) this.lastReceive=this.lastPoll;
    // Control messages bypass generation queue, so cancellation works during a turn.
    for(const row of this.store.pending()) {
      const cmd=command(row.text);
      if(cmd==='help') this.store.complete(row.id,row.peer,[HELP]);
      if(cmd==='status') this.store.complete(row.id,row.peer,[`本机网关运行中。\nCodex：${this.codex.ready?'已连接':'未连接'}\n当前：${this.busy?'正在生成':'空闲'}\n发送“新对话”可开始新的聊天。`]);
      if(cmd==='cancel') {
        this.knowledge?.cancel(row.peer);
        const peer=this.store.peer(row.peer);
        const result=peer?.thread ? await this.codex.cancel(peer.thread) : false;
        const waiting=this.store.db.prepare("SELECT * FROM inbox WHERE peer=? AND state IN ('pending','running')").all(row.peer);
        for(const other of waiting) if(!command(other.text)) this.store.state(other.id,'cancelled');
        this.store.complete(row.id,row.peer,[result?'正在停止本次生成，全部待整理记录已取消。':'当前没有正在生成的回复，等待中的问题和待整理记录已取消。']);
      }
      if(row.text==='【未支持的附件】') this.store.complete(row.id,row.peer,['请发送文字、语音或粘贴公众号链接。文章卡片及图片暂不能作为正文读取。']);
      if(this.busy&&this.cfg.agentMode&&!cmd&&row.text!=='【未支持的附件】')await this.knowledge?.steer(row);
    }
    this.report(this.status());
  }
  async work() {
    if(this.busy||this.stopping||!this.codex.ready) return;
    const row=this.store.pending().find(r=>!['help','status','cancel'].includes(command(r.text)));
    if(!row) return;
    this.busy=true;this.store.state(row.id,'running');this.report(this.status());
    try {
      if(command(row.text)==='new') {
        const reply=this.knowledge?.sessions?await this.knowledge.sessions.rollover(row.peer):'新会话交接功能未连接，原会话已保留。';
        this.store.complete(row.id,row.peer,[reply]);
        return;
      }
      if(this.knowledge&&await this.knowledge.handle(row))return;
      const saved=this.store.peer(row.peer);
      const t=await this.codex.thread(saved.thread);
      this.store.thread(row.peer,t.id);
      const reply=await this.codex.chat(t.id,row.text);
      this.store.complete(row.id,row.peer,splitReply(reply,this.cfg.replyChunkLength));
    } catch(e) {
      const known=/^CODEX_[A-Z_0-9-]+$/.test(e.message)?e.message:'CODEX_UNEXPECTED_ERROR';
      this.error=known;
      this.store.complete(row.id,row.peer,[known==='CODEX_TURN_TIMEOUT'
        ?'本次生成超时，已停止。请缩短问题后重试。'
        :`本次回复未完成（${known}）。请稍后重试；我没有自动重复执行。`]);
    } finally {this.busy=false;this.report(this.status());}
  }
  async deliver() {
    for(const row of this.store.outgoing()) {
      try {
        await this.ilink.send({...row,text:mobileText(row.text)},this.store.peer(row.peer)?.context);
        this.store.sent(row.id);this.lastReply=new Date().toISOString();
      } catch(e) {
        const attempts=row.attempts+1;
        this.error=/^WEIXIN_[A-Z_0-9-]+$/.test(e.message)?e.message:'WEIXIN_SEND_NETWORK_ERROR';
        this.store.retry(row.id,attempts,Math.min(60000,2000*2**attempts),attempts>=5||e.code===-14);
      }
    }
    this.report(this.status());
  }
  async poll() {
    while(!this.stopping) {
      try {
        const data=await this.ilink.poll(this.store.get('cursor'),this.cfg.pollTimeoutMs);
        await this.ingest(data);
      } catch(e) {
        if(this.stopping) break;
        if(e.name==='TimeoutError') {this.lastPoll=new Date().toISOString();}
        else {
          this.error=/^WEIXIN_[A-Z_0-9-]+$/.test(e.message)?e.message:'WEIXIN_POLL_NETWORK_ERROR';
          this.report(this.status());
          await new Promise(resolve=>setTimeout(resolve,e.code===-14?60000:5000));
        }
      }
    }
  }
}

async function main() {
  const root=dirname(dirname(fileURLToPath(import.meta.url)));
  const cfg=JSON.parse(readFileSync(join(root,'config/local.json'),'utf8').replace(/^\uFEFF/,''));
  cfg.projectRoot=root;if(cfg.agentMode!==true)throw Error('AGENT_MODE_REQUIRED');
  const runtime=join(root,'.runtime');mkdirSync(runtime,{recursive:true});
  const credentials=loadCredentials(cfg.credentialsSource);
  if(process.argv.includes('--check')) {
    await new Ilink(credentials).check();
    console.log('微信凭据有效；允许私聊账号数：'+credentials.allowed.length);return;
  }
  const unlock=acquireLock(credentials.token);
  const store=new Store(join(runtime,'state.sqlite'));
  // A different binding must not inherit the old user's sessions or cursor.
  const account=store.get('account');
  if(account&&account!==credentials.account) {store.close();unlock();throw new Error('WEIXIN_ACCOUNT_CHANGED');}
  store.set('account',credentials.account);
  const codex=new Codex(cfg.codexPath,join(root,'workspace'),cfg.agentMode?(cfg.agentTimeoutMs||600000):cfg.turnTimeoutMs,{agent:cfg.agentMode,writableRoots:cfg.writableRoots||[root,cfg.vaultPath]});
  const ilink=new Ilink(credentials);
  const statusFile=join(runtime,'status.json'),stopFile=join(runtime,'stop.request');
  const log=(event)=>appendFileSync(join(runtime,'gateway.log'),JSON.stringify({at:new Date().toISOString(),event})+'\n');
  let lastState='';
  const report=(status)=>{
    writeFileSync(statusFile,JSON.stringify({pid:process.pid,startedAt,updatedAt:new Date().toISOString(),state:'running',...status},null,2));
    const key=[status.codex,status.weixin,status.error].join('|');
    if(key!==lastState) {log(key);lastState=key;}
  };
  const startedAt=new Date().toISOString();
  let timer,gateway,ticking=false,startupStage='weixin_check';
  const stage=value=>{startupStage=value;writeFileSync(statusFile,JSON.stringify({pid:process.pid,state:'starting',stage:value,updatedAt:new Date().toISOString()}));};
  const shutdown=async()=>{
    if(gateway?.stopping) return;
    if(gateway) gateway.stopping=true;
    clearInterval(timer);
    await codex.stop();
    store.close();unlock();
    writeFileSync(statusFile,JSON.stringify({pid:process.pid,state:'stopped',updatedAt:new Date().toISOString()}));
    log('stopped');process.exit(0);
  };
  process.on('SIGINT',shutdown);process.on('SIGTERM',shutdown);
  try {
    if(existsSync(stopFile)) unlinkSync(stopFile);
    stage('weixin_check');await ilink.check();stage('codex_initialize');await codex.start();stage('sessions_restore');
    const knowledge=new Knowledge(store,codex,new ArticleReader(cfg,runtime),new Voice(cfg,runtime),new Vault(cfg.vaultPath,join(runtime,'backups','task-updates')),cfg);
    knowledge.sessions=new Sessions(store,codex,cfg,runtime);
    for(const {id,thread} of store.db.prepare('SELECT id,thread FROM peers').all())if(thread){try{await knowledge.sessions.current(id);}catch(e){log('session_restore_deferred:'+startupReason(e));}}
    knowledge.recover();store.recover();
    gateway=new Gateway(store,ilink,codex,cfg,report,knowledge);report(gateway.status());
    log('ready');
    timer=setInterval(async()=>{
      if(ticking||gateway.stopping) return;
      if(existsSync(stopFile)) {await shutdown();return;}
      ticking=true;
      try {
        await gateway.deliver();
        if(codex.ready&&!gateway.busy&&!store.counts().incoming&&!store.counts().outgoing){
          gateway.busy=true;report(gateway.status());
          try{for(const {id} of store.db.prepare('SELECT id FROM peers').all())await knowledge.sessions.mirror(id);}
          finally{gateway.busy=false;report(gateway.status());}
        }
        if(!codex.ready&&!gateway.busy) {
          await codex.stop();await codex.start();log('codex_reconnected');
        }
        void gateway.work().catch(()=>log('worker_error'));
      } catch {log('tick_error');} finally {ticking=false;}
    },1000);
    await gateway.poll();
  } catch(e) {
    clearInterval(timer);await codex.stop();store.close();unlock();
    const code=/^[A-Z_0-9-]+$/.test(e.message)?e.message:'STARTUP_FAILED';
    const reason=startupReason(e);
    writeFileSync(statusFile,JSON.stringify({pid:process.pid,state:'failed',error:code,stage:startupStage,reason,updatedAt:new Date().toISOString()}));
    log(startupStage+':'+code+':'+reason);throw new Error(code);
  }
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]) main().catch(e=>{console.error(e.message);process.exitCode=1;});
