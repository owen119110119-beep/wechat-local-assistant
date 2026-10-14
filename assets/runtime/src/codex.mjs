import { spawn, execFile } from 'node:child_process';
import { createInterface } from 'node:readline';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

// Enforce length/count limits after parsing. Native constrained decoding with
// these keywords produced truncated multilingual web-search answers in probes.
export function wireSchema(value) {
  if(Array.isArray(value))return value.map(wireSchema);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([key])=>!['maxLength','minLength','maxItems','minItems'].includes(key)).map(([key,item])=>[key,wireSchema(item)]));
  return value;
}

export function independentEnvironment(environment=process.env){
  const result={...environment};
  for(const key of ['CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY','CODEX_THREAD_ID','CODEX_SESSION_ID'])delete result[key];
  return result;
}
export class Codex {
  constructor(binary, workspace, timeout = 180000, options={}) {
    this.binary=binary; this.workspace=workspace; this.timeout=timeout;
    this.agent=true;this.writableRoots=options.writableRoots||[workspace];
    this.requests=new Map(); this.active=new Map(); this.next=1; this.ready=false;
    this.events={};this.lastError=null;this.mcp={};
  }
  async start() {
    const args=['app-server','--listen','stdio://','-c','web_search="live"','-c','sandbox_mode="workspace-write"','-c','sandbox_workspace_write.network_access=true','-c','sandbox_workspace_write.writable_roots='+JSON.stringify(this.writableRoots),'-c','approval_policy="on-request"','-c','approvals_reviewer="auto_review"','--enable','respect_system_proxy','--disable','multi_agent'];
    this.proc=spawn(this.binary,args,
      {cwd:this.workspace,env:independentEnvironment(),windowsHide:true,stdio:['pipe','pipe','pipe']});
    this.proc.stderr.on('data',()=>{}); // Never persist upstream diagnostic text or credentials.
    this.proc.on('error',()=>this.fail('CODEX_PROCESS_ERROR'));
    this.proc.on('exit',()=>this.fail('CODEX_PROCESS_EXITED'));
    createInterface({input:this.proc.stdout}).on('line',line=>{
      try { this.handle(JSON.parse(line)); } catch { /* non-protocol output */ }
    });
    await this.request('initialize',{clientInfo:{name:'weixin_codex_local',title:'Weixin Codex Local',version:'0.1.0'},capabilities:{experimentalApi:true}});
    this.write({method:'initialized',params:{}});
    const account=await this.request('account/read',{});
    if (!account.account) throw new Error('CODEX_NOT_LOGGED_IN');
    this.ready=true;
  }
  write(value) {
    if (!this.proc?.stdin?.writable) throw new Error('CODEX_DISCONNECTED');
    this.proc.stdin.write(JSON.stringify(value)+'\n');
  }
  request(method,params,timeout=30000) {
    const id=this.next++;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.requests.delete(id);reject(new Error('CODEX_RPC_TIMEOUT'));},timeout);
      this.requests.set(id,{resolve,reject,timer});
      try { this.write({id,method,params}); } catch(e) {clearTimeout(timer);this.requests.delete(id);reject(e);}
    });
  }
  handle(message) {
    if(message.method) this.events[message.method]=(this.events[message.method]||0)+1;
    if(message.method==='error') this.lastError=JSON.stringify(message.params?.error||message.params||{})
      .replace(/Bearer\s+[^"\s]+/gi,'Bearer [REDACTED]').slice(0,1200);
    if(message.method==='mcpServer/startupStatus/updated') {
      const p=message.params;this.mcp[p.name||p.server||'unknown']={status:p.status,error:p.error};
    }
    if (message.id !== undefined && message.method) {
      const method=message.method;
      if(method==='item/permissions/requestApproval') {
        this.write({id:message.id,result:{permissions:{},scope:'turn'}});
      } else if (/requestApproval$/.test(method)) {
        this.write({id:message.id,result:{decision:'decline'}});
      } else if (method==='item/tool/requestUserInput') {
        this.write({id:message.id,result:{answers:{}}});
      } else if (method==='mcpServer/elicitation/request') {
        this.write({id:message.id,result:{action:'decline',content:null}});
      } else {
        this.write({id:message.id,error:{code:-32601,message:'Interactive callback is unavailable in this mobile bridge'}});
      }
      return;
    }
    const pending=this.requests.get(message.id);
    if(pending) {
      this.requests.delete(message.id);clearTimeout(pending.timer);
      if(message.error) pending.reject(Object.assign(new Error(`CODEX_RPC_${message.error.code}`),
        {rpcDetail:String(message.error.message).replace(/Bearer\s+\S+/gi,'Bearer [REDACTED]')}));else pending.resolve(message.result);
      return;
    }
    const p=message.params ?? {};
    const active=this.active.get(p.threadId);
    if(!active) return;
    if(message.method==='turn/started') active.turnId=p.turn.id;
    if(message.method==='item/completed' && p.item?.type==='agentMessage') {
      active.items.push({text:p.item.text,phase:p.item.phase});
      active.onAgentMessage?.(p.item);
    }
    if(message.method==='item/completed' && p.item?.type==='webSearch')active.searches.push(p.item);
    if(message.method==='turn/completed') {
      active.status=p.turn.status;
      active.resolve(p.turn);
    }
  }
  fail(code) {
    this.ready=false;
    for(const r of this.requests.values()) {clearTimeout(r.timer);r.reject(new Error(code));}
    this.requests.clear();
    for(const a of this.active.values()) a.reject(new Error(code));
  }
  async thread(threadId,options={}) {
    const params={cwd:options.cwd||this.workspace,environments:[{environmentId:'local',cwd:options.cwd||this.workspace,runtimeWorkspaceRoots:this.writableRoots}],approvalPolicy:'on-request',approvalsReviewer:'auto_review',sandbox:'workspace-write',developerInstructions:readFileSync(join(this.workspace,'AGENTS.md'),'utf8'),config:{project_doc_max_bytes:0,web_search:'live',sandbox_workspace_write:{writable_roots:this.writableRoots,network_access:true}}};
    const result=await this.request(options.fork?'thread/fork':threadId?'thread/resume':'thread/start',{...params,...(threadId?{threadId,...(options.fork?{ephemeral:true,excludeTurns:true}:{})}:{...(options.projectId?{projectId:options.projectId}:{}),...(options.ephemeral?{ephemeral:true}:{})})});
    return {id:result.thread.id,model:result.model};
  }
  async chat(threadId,text,onProgress,options={}) {
    if(this.active.has(threadId)) throw new Error('CODEX_THREAD_BUSY');
    const active={items:[],searches:[],turnId:null,status:'inProgress',onAgentMessage:options.onAgentMessage};
    const done=new Promise((resolve,reject)=>Object.assign(active,{resolve,reject}));
    done.catch(()=>{});
    this.active.set(threadId,active);
    let timer;
    try {
      const capabilities={environments:[{environmentId:'local',cwd:this.workspace,runtimeWorkspaceRoots:this.writableRoots}],approvalPolicy:'on-request',approvalsReviewer:'auto_review',sandboxPolicy:{type:'workspaceWrite',writableRoots:this.writableRoots,networkAccess:true}};
      const turn=await this.request('turn/start',{threadId,input:[{type:'text',text}],...capabilities,effort:'medium',summary:'concise',
        ...(options.outputSchema?{outputSchema:wireSchema(options.outputSchema)}:{})});
      active.turnId=turn.turn.id;
      if(active.cancelRequested) await this.cancel(threadId);
      onProgress?.(active.turnId);
      const budget=options.requireWebSearch?Math.max(this.timeout,300000):this.timeout;
      const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('CODEX_TURN_TIMEOUT')),budget);});
      const result=await Promise.race([done,timeout]);
      if(result.status==='interrupted') return '已停止本次生成。';
      if(result.status!=='completed') throw Object.assign(new Error('CODEX_TURN_FAILED'),
        {rpcDetail:String(result.error?.message||result.error?.codexErrorInfo||result.status).replace(/Bearer\s+\S+/gi,'Bearer [REDACTED]')});
      options.onSearchEvidence?.(active.searches);
      const final=active.items.filter(i=>i.phase==='final_answer'||i.phase==='finalAnswer');
      const reply=(final.length?final:active.items.slice(-1)).map(i=>i.text).join('\n\n') || '此次任务没有产生文字回复。';
      if(options.requireWebSearch&&!active.searches.some(x=>x.action?.type==='search'||x.query))throw Object.assign(new Error('KNOWLEDGE_SEARCH_NOT_PERFORMED'),{searchEvidence:active.searches,searchReply:reply});
      return reply;
    } catch(e) {
      if(e.message==='CODEX_TURN_TIMEOUT') {
        await this.cancel(threadId).catch(()=>{});
        // Ensure completion before accepting another turn on the same thread.
        await Promise.race([done,new Promise(resolve=>setTimeout(resolve,10000))]).catch(()=>{});
        if(active.status==='inProgress') {this.proc.kill();this.ready=false;}
      }
      throw e;
    } finally {clearTimeout(timer);this.active.delete(threadId);}
  }
  async cancel(threadId) {
    const active=this.active.get(threadId);
    if(!active) return false;
    if(!active.turnId) {active.cancelRequested=true;return true;}
    await this.request('turn/interrupt',{threadId,turnId:active.turnId});return true;
  }
  async compact(threadId) {
    if(this.active.has(threadId))throw new Error('CODEX_THREAD_BUSY');
    const active={items:[],searches:[],turnId:null,status:'inProgress'};
    const done=new Promise((resolve,reject)=>Object.assign(active,{resolve,reject}));done.catch(()=>{});
    this.active.set(threadId,active);let timer;
    try {
      await this.request('thread/compact/start',{threadId});
      const result=await Promise.race([done,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('CODEX_COMPACT_TIMEOUT')),this.timeout);})]);
      if(result.status!=='completed')throw new Error('CODEX_COMPACT_FAILED');
    }catch(e){await this.cancel(threadId).catch(()=>{});if(active.status==='inProgress'){this.proc.kill();this.ready=false;}throw e;}
    finally{clearTimeout(timer);this.active.delete(threadId);}
  }
  async steer(threadId,text){const active=this.active.get(threadId);if(!active?.turnId||active.status!=='inProgress')return false;try{await this.request('turn/steer',{threadId,expectedTurnId:active.turnId,input:[{type:'text',text}]});return true;}catch(e){if(e.message.startsWith('CODEX_RPC_'))return false;throw e;}}
  async stop() {
    for(const thread of this.active.keys()) await this.cancel(thread).catch(()=>{});
    const proc=this.proc;
    if(!proc) return;
    proc.stdin.end();
    // App Server can own a code-mode host. Kill only this known process tree.
    if(process.platform==='win32'&&proc.exitCode===null) {
      await new Promise(resolve=>execFile('taskkill.exe',['/PID',String(proc.pid),'/T','/F'],{windowsHide:true,timeout:10000},()=>resolve()));
    } else {proc.kill();}
    proc.stdin.destroy();proc.stdout.destroy();proc.stderr.destroy();
    this.fail('CODEX_STOPPED');this.proc=null;
  }
}
