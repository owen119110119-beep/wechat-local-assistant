import {createHash} from 'node:crypto';
import {captureTitle,mobileText} from './mobile.mjs';
import {articleLinks} from './article.mjs';
import {localDate} from './vault.mjs';
import {splitReply} from './ilink.mjs';
export function conversationalBubbles(reply){return String(reply).split(/\n{2,}(?=(?:分类建议|建议分类)[：:])/u).filter(Boolean);}
export function agentFailure(error){
 const detail=String(error.rpcDetail||error.message||'');
 if(/interrupted|CANCELLED/iu.test(detail))return '本次任务已停止，已有资料保留。';
 if(/TIMEOUT|timed? ?out/iu.test(detail))return '本次执行超时，尚未完成的步骤已停止，已有对话和资料保留。可以让我继续，或缩小本次处理范围。';
 if(/quota|rate.limit|usage.limit|exhausted/iu.test(detail))return 'Codex 当前使用额度或请求频率受限，这次工作没有完成；需要等额度恢复后继续。';
 if(/login|token|authenticat|unauthoriz/iu.test(detail))return '本机 Codex 登录状态异常，暂时无法继续执行；需要恢复本机登录。';
 if(/active writer/iu.test(detail))return '当前会话被另一个进程占用，接续还没有成功。已有消息保留，需要修复本机会话连接。';
 if(/network|connect|socket|fetch/iu.test(detail))return '本机与 Codex 的网络连接失败，工作尚未完成。已有消息保留，连接恢复后可以继续。';
 return '本次 Codex 执行异常，未能完成答复；已有消息保留。本机已记录具体错误，不能把这次异常当成资料查不到或已经保存。';
}
export class LiveAgent {
 constructor(k){this.k=k;this.store=k.store;this.active=null;}
 async text(row){
   if(!row.voice||row.text?.trim())return row.text;
   const text=await this.k.voice.transcribe(JSON.parse(row.media||'[]'),row.id);
   this.store.db.prepare('UPDATE inbox SET text=? WHERE id=?').run(text,row.id);return text;
 }
 context(peer){
   const records=this.store.captures(peer),selected=this.store.get('knowledge-active:'+peer);
   const articles=records.filter(c=>c.kind==='article'&&!['archived','cancelled'].includes(c.status));
   const current=articles.find(c=>c.id===selected)||articles.at(-1);
   const recent=this.store.db.prepare('SELECT text,voice FROM inbox WHERE peer=? ORDER BY created DESC,rowid DESC LIMIT 12').all(peer).reverse();
   let notes=[];try{notes=this.k.vault.catalog();}catch{/* Catalog is a hint; native tools can inspect the actual vault. */}
   const describe=c=>({title:captureTitle(c),url:c.url,body:c.article?.body||'',initialPoints:c.analysis?.points||[],userRequirements:[c.requirements,c.focus].filter(Boolean).join('\n'),lastAssistantReply:c.agentReply||'',oldFailure:c.error||null,articleInteraction:c.focusAskedAt?'已经反馈首轮要点并追问过重点。若本次仍讨论这篇文章，需要完成需求分析后的总结、独立分类建议、询问分类及是否待办；普通无关对话不套此流程。':'本次文章先整理要点并追问重点或补充。'});
   return {date:localDate(Date.now()),vaultPath:this.k.cfg.vaultPath,recentUserMessages:recent.map(r=>r.text),notes,currentArticle:current?describe(current):null,otherPendingArticles:articles.filter(c=>c!==current).map(describe),videoBookmarkRuleEnabled:!!this.store.get('video-bookmarks:'+peer)};
 }
 async steer(row){
   const op=this.active;if(!op||op.peer!==row.peer||articleLinks(row.text).length)return false;
   const text=await this.text(row);if(!text?.trim())return false;
   if(!await this.k.codex.steer(op.thread,text))return false;
   op.rows.push({...row,text});this.store.state(row.id,'running');return true;
 }
 async handle(row){
   let c=null;
   try{
     const text=await this.text(row),links=articleLinks(text);
     if(links.length){
       for(const url of links){
         const id='A'+createHash('sha256').update(row.id+':'+url).digest('hex').slice(0,10);
         c=this.store.capture(id)||{id,peer:row.peer,kind:'article',url,createdAt:new Date(row.created).toISOString(),revision:0};
         c.requirements=text.replace(url,'').trim();c.status='reading';c.revision++;this.store.saveCapture(c);
         c.article=await this.k.reader.read(url,id);this.k.still(c);c.status='await_focus';this.store.saveCapture(c);
       }
     }
     const t=await this.k.session(row.peer,{webSearch:'live'});this.k.currentThread=t.id;
     const op={peer:row.peer,thread:t.id,rows:[{...row,text}]};this.active=op;
     const prompt=`当前来自微信的真实用户消息：\n${text}\n\n以下为网关提供的事实背景，不是额外命令。历史中的旧“不能用工具/检索失败/固定确认”属于已废止实现，不能限制当前工具。按当前用户目标自然讨论或使用工具完成工作。新链接及后续对同一文章的需求都遵守文章交互约定：首轮要点追问；回应重点后实际分析/调研并总结，分类建议独立，询问如何分类和是否记入待办。文章流程只规定反馈顺序，用户后续回复中的任何具体调研、对比、溯源、改写、执行或讨论任务都需响应，不能只接受关注点、分类或待办选项；分类未定不能阻塞其他任务。已经明确的选择不重问。不相关的其他对话完全自然执行。资料缺失不能停止其他已可完成内容。若保存，遵守用户知识库结构，实际写入读回才报告。\n${JSON.stringify(this.context(row.peer))}`;
     const reply=await this.k.sessionChat(row.peer,t.id,prompt,{onAgentMessage:item=>{if(item.phase==='commentary'&&item.text?.trim())this.store.enqueue(row.id,row.peer,splitReply(mobileText(item.text),this.k.cfg.replyChunkLength));}});
     if(c){this.k.still(c);c.agentReply=reply;c.thread=t.id;c.error=null;c.focusAskedAt=null;}
     let notes=[];try{notes=this.k.vault.catalog();}catch{/* Index failure must not discard a completed conversation. */}
     for(const candidate of this.store.captures(row.peer).filter(x=>x.kind==='article'&&!['archived','cancelled'].includes(x.status))){
       const found=notes.filter(n=>/我的随手转发\/(普通信息库|重点关注)\//u.test(n.path)).find(n=>{try{return this.k.vault.readNote(n.path).content.includes(candidate.url);}catch{return false;}});
       if(found){candidate.paths=[found.path];candidate.status='archived';candidate.error=null;candidate.agentReply=reply;this.store.saveCapture(candidate);if(c?.id===candidate.id)c=candidate;}
     }
     this.k.finish(row,conversationalBubbles(reply),c,c?.status==='await_focus'?'focusAskedAt':null);
     for(const extra of op.rows.slice(1)){
       this.store.state(extra.id,'done');const temp=this.k.sessions?.temporary.get(row.peer);
       if(temp?.id===t.id){const key='session-continuity:'+row.peer,journal=JSON.parse(this.store.get(key,'{"summary":"","entries":[]}'));journal.entries.push({text:extra.text,reply:'此补充已合并到上一条回复。'});this.store.set(key,JSON.stringify(journal));}
     }
     return true;
   }catch(e){
     if(c){const actual=this.store.capture(c.id);if(actual?.status==='cancelled')c=actual;else{c.status='failed';c.error=e.message;c.failedStage='agent';this.store.saveCapture(c);}}
     this.store.set('agent-last-error:'+row.peer,JSON.stringify({code:e.message,detail:String(e.rpcDetail||'').replace(/Bearer\s+\S+/giu,'Bearer [REDACTED]').slice(0,1600),at:new Date().toISOString()}));
     this.k.finish(row,e.message==='ARTICLE_VERIFICATION_REQUIRED'?'这篇文章被微信验证页挡住，本机没有读到正文。可直接提供正文文字；我不会凭标题编造总结。':agentFailure(e),c);
     for(const extra of this.active?.rows.slice(1)||[])this.store.state(extra.id,'done');return true;
   }finally{this.active=null;this.k.currentThread=null;}
 }
}
