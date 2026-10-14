import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,mkdtempSync,rmSync,readFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
import {Store} from '../src/store.mjs';
import {Sessions,historyContains} from '../src/sessions.mjs';
import {Gateway,HELP} from '../src/gateway.mjs';
import {mobileText} from '../src/mobile.mjs';
function fixture(t){mkdirSync('.runtime',{recursive:true});const root=mkdtempSync(join(process.cwd(),'.runtime','session-test-')),s=new Store(':memory:');s.ingest([{id:'incoming',peer:'owner',context:'private',text:'测试'}]);s.thread('owner','previous');let fail=false,n=0;const calls=[];
 const model={thread:async(id,opts)=>{calls.push({id,opts});return{id:id||'next'+(++n)};},compact:async id=>{calls.push({compact:id});if(fail)throw Error('CODEX_COMPACT_FAILED');},chat:async(id,text)=>{calls.push({chat:id,text});if(fail)throw Error('CODEX_TURN_FAILED');return text.startsWith('仅整理')?'用户讨论创作方法，待核实来源。':'已接续';},request:async(method,params)=>{calls.push({method,params});if(method==='thread/read')return{thread:{turns:[{text:calls.filter(x=>x.chat===params.threadId).at(-1)?.text}]}};return{};}};
 const session=new Sessions(s,model,{projectRoot:process.cwd(),botProjectId:'project',compactAfterTurns:2,compactAfterChars:100000},root);
 t.after(()=>{s.close();rmSync(root,{recursive:true,force:true});});return{s,session,model,calls,root,fail:v=>fail=v};}
test('全部移动出口脱敏含历史编号，正文提示和帮助均不要求编号',()=>{
 const s=new Store(':memory:');s.ingest([{id:'in',peer:'owner',context:'ctx',text:'x'}]);s.complete('in','owner',['重试 A0123456789；取消 I1234567890；旧路径/任务-A1234567890.md']);assert.doesNotMatch(s.outgoing()[0].text,/[AI][0-9a-f]{10}|编号/);assert.doesNotMatch(HELP,/编号/);assert.doesNotMatch(mobileText('00000000-0000-0000-0000-000000000000'),/[0-9a-f]{8}-/);s.close();
});
test('后台文章和搜索共享当前会话；重启后继续同一线程，压缩不换线程',async t=>{
 const f=fixture(t);await f.session.current('owner');await f.session.current('owner',{webSearch:'live'});assert(f.calls.every(x=>x.id==='previous'));
 await f.session.chat('owner','previous','第一条');await f.session.chat('owner','previous','第二条');await f.session.current('owner');assert.equal(f.calls.filter(x=>x.compact).length,1);assert.equal(f.s.peer('owner').thread,'previous');assert.equal(JSON.parse(f.s.get('session-load:previous')).turns,0);
 const restarted=new Sessions(f.s,f.model,f.session.cfg,f.root);await restarted.current('owner');assert.equal(f.calls.at(-1).id,'previous');
});
test('新对话先交接持久化读回，未完成记录跨会话保留，旧会话仅归档',async t=>{
 const f=fixture(t);f.s.saveCapture({id:'A1234567890',peer:'owner',kind:'article',status:'await_focus',article:{title:'教育文章'},requirements:'用于教学',revision:1});
 await f.session.rollover('owner');assert.equal(f.s.peer('owner').thread,'next1');const data=JSON.parse(readFileSync(f.s.get('session-handoff:owner'),'utf8'));assert.equal(data.pending[0].title,'教育文章');assert.equal(f.s.capture('A1234567890').status,'await_focus');assert(f.calls.some(x=>x.method==='thread/archive'&&x.params.threadId==='previous'));assert(!f.calls.some(x=>x.method==='thread/delete'));
});
test('交接生成、承接读回或压缩失败都不切换原会话',async t=>{
 const f=fixture(t);f.fail(true);await assert.rejects(()=>f.session.rollover('owner'));assert.equal(f.s.peer('owner').thread,'previous');f.fail(false);
 const request=f.model.request;f.model.request=async(method,p)=>method==='thread/read'?{thread:{turns:[]}}:request(method,p);await assert.rejects(()=>f.session.rollover('owner'),/READBACK/);assert.equal(f.s.peer('owner').thread,'previous');assert(!f.calls.some(x=>x.method==='thread/archive'&&x.params.threadId==='previous'));
 f.s.set('session-load:previous',JSON.stringify({turns:3,chars:0}));f.fail(true);await assert.rejects(()=>f.session.current('owner'),/COMPACT/);assert.equal(f.s.peer('owner').thread,'previous');
});
test('真实手机确认/状态记录集中写入当前会话且不会重复记录，无额外线程',async t=>{
 const f=fixture(t);f.s.complete('incoming','owner',['分类已准备好']);const out=f.s.outgoing()[0];f.s.sent(out.id);await f.session.mirror('owner');const chat=f.calls.find(x=>x.chat);assert.equal(chat.chat,'previous');assert.match(chat.text,/手机消息：测试[\s\S]*分类已准备好/);const count=f.calls.filter(x=>x.chat).length;await f.session.mirror('owner');assert.equal(f.calls.filter(x=>x.chat).length,count);assert(!f.calls.some(x=>x.id===null));
});
test('旧队列出件也经过移动端编号拦截，实际失败仍保留重试',async()=>{
 const s=new Store(':memory:');s.ingest([{id:'in',peer:'owner',context:'ctx',text:'x'}]);s.complete('in','owner',['x']);s.db.prepare('UPDATE outbox SET text=?').run('重试 A0123456789');let text;const g=new Gateway(s,{send:async row=>{text=row.text;}},{ready:true},{replyChunkLength:100});await g.deliver();assert.equal(text,'重试 ');s.close();
});
test('交接读回对比原始文本，包含换行和JSON引号时仍能核验；停止不得变成交接授权',async t=>{
 const text='交接\n{"未完成":"创作验证"}';assert(historyContains({turns:[{content:[{text}]}]},text));assert(!historyContains({turns:[]},text));
 const f=fixture(t);f.model.chat=async()=> '已停止本次生成。';await assert.rejects(()=>f.session.rollover('owner'),/INTERRUPTED/);assert.equal(f.s.peer('owner').thread,'previous');assert(!f.calls.some(x=>x.method==='thread/archive'));
});
