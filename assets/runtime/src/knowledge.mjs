import {LiveAgent} from './live-agent.mjs';
import {splitReply} from './ilink.mjs';
export class Knowledge {
 constructor(store,codex,reader,voice,vault,cfg){Object.assign(this,{store,codex,reader,voice,vault,cfg});if(!cfg.agentMode)throw Error('AGENT_MODE_REQUIRED');this.currentThread=null;this.liveAgent=new LiveAgent(this);}
 finish(row,text,c=null,field=null){const gate=c?{id:c.id,revision:c.revision,status:c.status,field:field||'interactionSentAt'}:null;this.store.complete(row.id,row.peer,(Array.isArray(text)?text:[text]).filter(Boolean).flatMap(x=>splitReply(x,this.cfg.replyChunkLength)),gate,c);}
 recover(){for(const {peer} of this.store.db.prepare('SELECT DISTINCT peer FROM captures').all())for(const c of this.store.captures(peer))if(['reading','analyzing','drafting','writing','researching'].includes(c.status)){c.failedStage=c.status;c.status='failed';c.error='INTERRUPTED';this.store.saveCapture(c);}}
 cancel(peer){for(const c of this.store.captures(peer).filter(x=>!['archived','cancelled'].includes(x.status))){c.status='cancelled';c.revision++;this.store.saveCapture(c);}if(this.currentThread)void this.codex.cancel(this.currentThread).catch(()=>{});}
 still(c){if(this.store.capture(c.id)?.status==='cancelled')throw Error('CODEX_CANCELLED');}
 async handle(row){return this.liveAgent.handle(row);}
 async steer(row){return this.liveAgent.steer(row);}
 async session(peer,options={}){if(this.sessions)return this.sessions.current(peer,options);const t=await this.codex.thread(this.store.peer(peer)?.thread||null,options);this.store.thread(peer,t.id);return t;}
 async sessionChat(peer,thread,text,options={}){if(this.sessions)return this.sessions.chat(peer,thread,text,options);return this.codex.chat(thread,text,undefined,options);}
}
