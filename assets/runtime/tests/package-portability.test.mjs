import test from 'node:test';
import assert from 'node:assert/strict';
import {independentEnvironment} from '../src/codex.mjs';
import {Vault} from '../src/vault.mjs';
import {mkdtempSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
test('Independent server strips only invoking chat routing metadata and preserves proxy/auth/runtime environment',()=>{const original={CODEX_THREAD_ID:'fixture',CODEX_SESSION_ID:'fixture',CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY:'fixture',HTTP_PROXY:'fixture-proxy',PATH:'fixture-path',CODEX_ACCESS_TOKEN:'fixture-not-real'};const result=independentEnvironment(original);assert.equal(result.CODEX_THREAD_ID,undefined);assert.equal(result.CODEX_SESSION_ID,undefined);assert.equal(result.CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY,undefined);assert.equal(result.HTTP_PROXY,original.HTTP_PROXY);assert.equal(result.PATH,original.PATH);assert.equal(result.CODEX_ACCESS_TOKEN,original.CODEX_ACCESS_TOKEN);assert.equal(original.CODEX_THREAD_ID,'fixture');});
test('Agent vault catalog and actual note readback preserve content; paths outside vault are rejected',()=>{const root=mkdtempSync(join(tmpdir(),'skill-vault-'));try{mkdirSync(join(root,'.obsidian'));const folder=join(root,'我的随手转发','重点关注','用途');mkdirSync(folder,{recursive:true});writeFileSync(join(folder,'文章-20261014.md'),'# 文章\n正文与手写内容');const v=new Vault(root);const list=v.catalog();assert.equal(list.length,1);assert.equal(v.readNote(list[0].path).content,'# 文章\n正文与手写内容');assert.throws(()=>v.readNote('../escape.md'),/VAULT_PATH_ESCAPE/);}finally{rmSync(root,{recursive:true,force:true});}});
