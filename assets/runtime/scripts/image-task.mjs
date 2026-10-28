// Internal agent tool. User meaning is interpreted by the conversational agent, not command regexes.
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import {join,resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {randomUUID} from 'node:crypto';
import {Store} from '../src/store.mjs';
import {ImageBatches} from '../src/image-batches.mjs';
import {snapshotMedia,confinedFile} from '../src/outgoing-media.mjs';
import {runFile} from '../src/article.mjs';

export async function imageTask(turn,request,{render=runFile,root=resolve(dirname(dirname(fileURLToPath(import.meta.url))))}={}){
 const runtime=join(root,'.runtime');
 // Grants live only in this installation; they never contain credentials or media keys.
 const grant=JSON.parse(readFileSync(confinedFile(join(runtime,'image-turns'),turn),'utf8'));
 if(resolve(grant.projectRoot)!==root||resolve(grant.database)!==join(runtime,'state.sqlite'))throw Error('IMAGE_TURN_INVALID');
 confinedFile(join(runtime,'image-output'),join(grant.outputRoot,'marker'));
 const store=new Store(grant.database),manager=new ImageBatches(store,{},runtime);
 const valid=()=>{
  const row=store.db.prepare('SELECT * FROM inbox WHERE id=? AND peer=?').get(grant.source,grant.peer),c=store.capture(grant.batch);
  if(!row||row.state!=='running'||!c||c.peer!==grant.peer||c.kind!=='image_batch'||c.status==='cancelled')throw Error('IMAGE_TURN_EXPIRED');
  return c;
 };
 try{
  let c=valid();
  const save=()=>{valid();c.revision++;c.updatedAt=new Date().toISOString();store.saveCapture(c);return manager.describe(c);};
  const pages=()=>c.files.filter(f=>!f.removed&&!f.duplicateOf);
  if(request.action==='inspect')return manager.describe(c);
  if(request.action==='new_batch'){
   const old=pages(),indices=request.fromPages;
   if(!request.reason?.trim()||!Array.isArray(indices)||!indices.length||new Set(indices).size!==indices.length||indices.some(n=>!Number.isInteger(n)||n<1||n>old.length))throw Error('IMAGE_PAGE_SELECTION_INVALID');
   const selected=indices.map(n=>old[n-1]);
   c.files=c.files.map(f=>selected.includes(f)?{...f,removed:true}:f);save();
   c={id:'B'+randomUUID(),peer:grant.peer,kind:'image_batch',status:'collecting',createdAt:new Date().toISOString(),revision:0,files:selected,outputs:[],requirements:[]};store.saveCapture(c);store.set('image-batch-active:'+grant.peer,c.id);store.set('resource-active:'+grant.peer,c.id);
   grant.batch=c.id;grant.outputRoot=join(runtime,'image-output',createHash('sha256').update(c.id).digest('hex'));mkdirSync(grant.outputRoot,{recursive:true});writeFileSync(turn,JSON.stringify(grant));
   return {...manager.describe(c),outputRoot:grant.outputRoot};
  }
  if(request.action==='update'){
   if(request.keepPages){
    const old=pages(),indices=request.keepPages;
    if(!Array.isArray(indices)||!indices.length||new Set(indices).size!==indices.length||indices.some(n=>!Number.isInteger(n)||n<1||n>old.length))throw Error('IMAGE_PAGE_SELECTION_INVALID');
    const selected=indices.map(n=>old[n-1]),removed=c.files.filter(f=>!selected.includes(f)).map(f=>({...f,removed:true}));c.files=[...selected,...removed];
   }
   if(typeof request.requirements==='string'&&request.requirements.trim()&&!c.requirements.includes(request.requirements.trim()))c.requirements.push(request.requirements.trim());
   return save();
  }
  if(request.action==='seal'){if(typeof request.reason!=='string'||!request.reason.trim())throw Error('IMAGE_COMPLETION_REASON_REQUIRED');c.completionReason=request.reason;c.status='ready';return save();}
  if(request.action==='reopen'){c.status='collecting';return save();}
  if(request.action==='cancel'){c.status='cancelled';return save();}
  if(!['ready','generated','delivered'].includes(c.status)&&!(request.action==='deliver'&&request.independent===true))throw Error('IMAGE_UPLOADS_NOT_FINISHED');
  if(request.action==='pdf'){
   const report=request.report;
   if(!report?.title||!Array.isArray(report.sections)||!report.sections.length)throw Error('IMAGE_REPORT_EMPTY');
   const revision=c.revision,p=pages();
   for(const section of report.sections){if(!Array.isArray(section.sourcePages)||!section.sourcePages.length||section.sourcePages.some(n=>!Number.isInteger(n)||n<1||n>p.length))throw Error('IMAGE_REPORT_SOURCE_INVALID');}
   const hash=createHash('sha256').update(JSON.stringify({report,files:p.map(f=>f.sha256)})).digest('hex');
   const output=join(grant.outputRoot,hash);mkdirSync(output,{recursive:true});
   const spec=join(output,'report.json'),receipt=join(output,'receipt.json');
   writeFileSync(spec,JSON.stringify({...report,images:p.map((f,i)=>({page:i+1,path:f.imagePath||f.localPath||null,status:f.status,reason:f.reason||null}))}));
   let cached=null;try{const previous=JSON.parse(readFileSync(receipt,'utf8'));const path=confinedFile(output,previous.path);if(previous.status==='ready'&&createHash('sha256').update(readFileSync(path)).digest('hex')===previous.sha256)cached=previous;}catch{/* Incomplete artifacts are regenerated, not delivered. */}
   if(!cached)await render(grant.python,['-X','utf8',join(root,'scripts/image_report.py'),'--spec',spec,'--output-dir',output],120000,{},null);
   c=valid();if(c.revision!==revision)throw Error('IMAGE_BATCH_CHANGED');
   if(!existsSync(receipt))throw Error('IMAGE_PDF_NOT_CREATED');
   const result=JSON.parse(readFileSync(receipt,'utf8'));if(result.status!=='ready')throw Error('IMAGE_PDF_NOT_CREATED');
   c.title=report.title;c.outputs ||= [];if(!c.outputs.some(x=>x.path===result.path))c.outputs.push({...result,source:grant.source});save();return result;
  }
  if(request.action==='deliver'){
   const media={...snapshotMedia(grant.outputRoot,request.path,request.name),batch:grant.batch};
   c=valid();const result=store.enqueueMedia(grant.source,grant.peer,media);
   c.outputs ||= [];let output=c.outputs.find(x=>x.path===request.path);
   if(!output){output={path:request.path};c.outputs.push(output);}Object.assign(output,{deliveryId:result.id,name:media.name,sha256:media.sha256});
   if(c.status!=='collecting')c.status='generated';save();return {queued:result.state==='pending',previouslySent:result.state==='sent',name:media.name,deliveryId:result.id};
  }
  throw Error('IMAGE_ACTION_UNKNOWN');
 }finally{store.close();}
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{const arg=name=>process.argv[process.argv.indexOf(name)+1];if(!process.argv.includes('--turn')||!process.argv.includes('--request'))throw Error('IMAGE_ARGUMENT_REQUIRED');
  const result=await imageTask(arg('--turn'),JSON.parse(readFileSync(arg('--request'),'utf8')));console.log(JSON.stringify(result));
 }catch(error){console.error(/^[A-Z_]+$/u.test(error.message)?error.message:'IMAGE_TASK_FAILED');process.exitCode=1;}
}
