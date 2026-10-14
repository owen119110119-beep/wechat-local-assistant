import test from 'node:test';
import assert from 'node:assert/strict';
import {Store} from '../src/store.mjs';
import {Sessions} from '../src/sessions.mjs';
import {startupReason} from '../src/gateway.mjs';
function fixture(t){
 const s=new Store(':memory:');s.ingest([{id:'in',peer:'owner',context:'ctx',text:'测试手机问题'}]);s.thread('owner','main');let locked=true,n=0;const calls=[];
 const c={proc:{pid:1},thread:async(id,opts)=>{calls.push({id,opts});if(id?.startsWith('temporary'))throw Object.assign(Error('CODEX_RPC_-32600'),{rpcDetail:'no rollout found for thread id '+id});if(id==='main'&&!opts.fork&&locked)throw Object.assign(Error('CODEX_RPC_-32600'),{rpcDetail:'thread main already has an active writer'});return{id:opts.fork?'temporary'+(++n):id||'new'};},chat:async(id,text)=>{calls.push({chat:id,text});return '已回应';},request:async(method,p)=>{calls.push({method,p});return{};},compact:async()=>{}};
 const cfg={projectRoot:process.cwd(),botProjectId:'project',compactAfterTurns:40};const sessions=new Sessions(s,c,cfg,'.runtime');t.after(()=>s.close());return{s,c,calls,cfg,sessions,unlock:()=>locked=false};
}
test('桌面占用时仅创建内存fork，原绑定保持，文章/普通聊天共用内存接续',async t=>{
 const f=fixture(t),a=await f.sessions.current('owner');assert.equal(a.id,'temporary1');assert.equal(f.s.peer('owner').thread,'main');assert.equal(f.calls.find(x=>x.opts.fork).id,'main');
 await f.sessions.chat('owner',a.id,'需要重点备注商业启发');const same=await f.sessions.current('owner');assert.equal(same.id,a.id);await f.sessions.chat('owner',same.id,'继续第二条');const b=await f.sessions.current('owner',{webSearch:'live'});assert.notEqual(b.id,a.id);assert.equal(f.calls.filter(x=>x.opts?.fork).length,2);assert.match(f.s.get('session-continuity:owner'),/商业启发/);assert(!f.calls.some(x=>x.id?.startsWith('temporary')));
});
test('内存进程重启后从原历史重建并读回持久交流背景；桌面释放后回原线程且不丢记录',async t=>{
 const f=fixture(t),a=await f.sessions.current('owner');await f.sessions.chat('owner',a.id,'研究AI综艺但未授权保存');f.c.proc={pid:2};const restarted=new Sessions(f.s,f.c,f.cfg,'.runtime');const b=await restarted.current('owner');assert.notEqual(a.id,b.id);
 await restarted.chat('owner',b.id,'继续刚才讨论');assert.match(f.calls.findLast(x=>x.chat).text,/此前交流背景[\s\S]*未授权保存[\s\S]*当前请求/);
 f.unlock();restarted.temporary.get('owner').retryAt=0;const main=await restarted.current('owner');assert.equal(main.id,'main');await restarted.chat('owner',main.id,'补回原会话');assert.match(f.calls.findLast(x=>x.chat).text,/继续刚才讨论/);assert.equal(JSON.parse(f.s.get('session-continuity:owner')).entries.length,0);assert.equal(f.s.peer('owner').thread,'main');
});
test('占用期间桌面转录游标不推进，新对话不归档或切换；释放后补录不重跑用户请求',async t=>{
 const f=fixture(t);f.s.complete('in','owner',['网关已发的真实回复']);for(const out of f.s.outgoing())f.s.sent(out.id);await f.sessions.mirror('owner');assert.equal(f.s.get('session-mirror:owner'),'');assert.equal(f.calls.filter(x=>x.chat).length,0);
 assert.match(await f.sessions.rollover('owner'),/暂未切换/);assert.equal(f.s.peer('owner').thread,'main');assert(!f.calls.some(x=>x.method==='thread/archive'));
 f.unlock();f.sessions.temporary.get('owner').retryAt=0;await f.sessions.mirror('owner');assert.equal(f.s.get('session-mirror:owner'),'1');assert.match(f.calls.findLast(x=>x.chat).text,/不重新分析[\s\S]*网关已发的真实回复/);
});
test('非占用错误不私自创建新线程或吞掉；安全诊断区分网络/会话/配置',async t=>{
 const f=fixture(t);f.c.thread=async()=>{throw Object.assign(Error('CODEX_RPC_-32603'),{rpcDetail:'failed to refresh token: network unavailable'});};await assert.rejects(()=>f.sessions.current('owner'),/CODEX_RPC/);assert.equal(f.sessions.temporary.size,0);
 assert.equal(startupReason({rpcDetail:'already has an active writer'}),'SESSION_WRITER_BUSY');assert.equal(startupReason({rpcDetail:'failed to refresh token'}),'CODEX_CONNECTIVITY');assert.equal(startupReason({rpcDetail:'unknown permission profile'}),'CODEX_CONFIGURATION');assert.equal(startupReason({rpcDetail:'private unknown body'}),'UNCLASSIFIED');
});
