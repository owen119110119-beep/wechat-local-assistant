import {existsSync,lstatSync,readdirSync,readFileSync,realpathSync} from 'node:fs';
import {resolve,join,relative,dirname,sep} from 'node:path';
import {createHash} from 'node:crypto';
export function localDate(at){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(at));}
export class Vault {
 constructor(root){this.root=resolve(root);this.safe(this.root);if(!existsSync(join(this.root,'.obsidian')))throw Error('VAULT_NOT_CONFIGURED');}
 safe(target){const p=resolve(target),rel=relative(this.root,p);if(rel==='..'||rel.startsWith('..'+sep))throw Error('VAULT_PATH_ESCAPE');let part=p;while(true){if(existsSync(part)&&lstatSync(part).isSymbolicLink())throw Error('VAULT_LINK_FORBIDDEN');const parent=dirname(part);if(parent===part)break;part=parent;}if(existsSync(p)&&relative(this.root,realpathSync(p)).startsWith('..'))throw Error('VAULT_PATH_ESCAPE');return p;}
 catalog(){const notes=[];const scan=(p)=>{this.safe(p);if(!existsSync(p))return;for(const entry of readdirSync(p,{withFileTypes:true})){if(entry.isSymbolicLink())throw Error('VAULT_LINK_FORBIDDEN');const file=join(p,entry.name);if(entry.isDirectory())scan(file);else if(entry.name.endsWith('.md')){const content=readFileSync(file,'utf8');notes.push({path:relative(this.root,file).split(sep).join('/'),title:content.match(/^#\s+(.+)$/mu)?.[1]||entry.name,excerpt:content.slice(0,160)});}}};scan(join(this.root,'我的随手转发'));scan(join(this.root,'我的突发奇想','待办事项'));return notes;}
 readNote(path){const p=this.safe(resolve(this.root,path));if(!p.endsWith('.md')||!existsSync(p))throw Error('VAULT_NOTE_MISSING');const content=readFileSync(p,'utf8');return{path:relative(this.root,p).split(sep).join('/'),content,hash:createHash('sha256').update(content).digest('hex')};}
}
