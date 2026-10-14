import { DatabaseSync } from 'node:sqlite';
import { randomUUID } from 'node:crypto';
import { mobileText } from './mobile.mjs';

export class Store {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS peers (id TEXT PRIMARY KEY, thread TEXT, context TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, peer TEXT NOT NULL, text TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', created INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, peer TEXT NOT NULL, text TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next INTEGER NOT NULL DEFAULT 0);
    `);
    for(const [table,column,definition] of [['inbox','media',"TEXT NOT NULL DEFAULT '[]'"],['inbox','voice','INTEGER NOT NULL DEFAULT 0'],['outbox','gate','TEXT'],['outbox','source','TEXT']]) {
      if(!this.db.prepare(`PRAGMA table_info(${table})`).all().some(r=>r.name===column)) this.db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
    }
    this.db.exec('CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY, peer TEXT NOT NULL, data TEXT NOT NULL)');
  }
  get(key, fallback = '') { return this.db.prepare('SELECT value FROM settings WHERE key=?').get(key)?.value ?? fallback; }
  set(key, value) { this.db.prepare('INSERT OR REPLACE INTO settings VALUES (?,?)').run(key, String(value)); }
  peer(id) { return this.db.prepare('SELECT * FROM peers WHERE id=?').get(id); }
  thread(peer, thread) { this.db.prepare('UPDATE peers SET thread=? WHERE id=?').run(thread, peer); }
  ingest(messages, cursor) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      for (const m of messages) {
        this.db.prepare(`INSERT INTO peers(id,context) VALUES (?,?)
          ON CONFLICT(id) DO UPDATE SET context=excluded.context`).run(m.peer, m.context);
        this.db.prepare('INSERT OR IGNORE INTO inbox(id,peer,text,created,media,voice) VALUES (?,?,?,?,?,?)')
          .run(m.id, m.peer, m.text, Date.now(),JSON.stringify(m.media||[]),m.voice?1:0);
      }
      if (cursor) this.set('cursor', cursor);
      this.db.exec('COMMIT');
    } catch (e) { this.db.exec('ROLLBACK'); throw e; }
  }
  pending() { return this.db.prepare("SELECT * FROM inbox WHERE state='pending' ORDER BY created,rowid").all(); }
  state(id, state) {
    this.db.prepare('UPDATE inbox SET state=? WHERE id=?').run(state, id);
    if(['done','cancelled'].includes(state))this.db.prepare("UPDATE inbox SET media='[]' WHERE id=?").run(id);
  }
  capture(id) { const r=this.db.prepare('SELECT data FROM captures WHERE id=?').get(id);return r?JSON.parse(r.data):null; }
  captures(peer) {return this.db.prepare('SELECT data FROM captures WHERE peer=? ORDER BY rowid').all(peer).map(r=>JSON.parse(r.data));}
  saveCapture(c) {this.db.prepare('INSERT INTO captures VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data').run(c.id,c.peer,JSON.stringify(c));}
  noteReservations(exclude) {return this.db.prepare('SELECT data FROM captures WHERE id<>?').all(exclude).flatMap(r=>{const c=JSON.parse(r.data);return [...(c.writePlan?.map(p=>p.path)||[]),...(c.taskPlan?[c.taskPlan.path]:[])];});}
  complete(id, peer, chunks, gate=null, capture=null) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      if(capture) this.saveCapture(capture);
      chunks.forEach((text,index)=>this.db.prepare('INSERT INTO outbox(id,peer,text,gate,source) VALUES (?,?,?,?,?)')
        .run(randomUUID(), peer, mobileText(text),index===chunks.length-1&&gate?JSON.stringify(gate):null,id));
      this.state(id, 'done');
      this.db.exec('COMMIT');
    } catch(e) { this.db.exec('ROLLBACK'); throw e; }
  }
  recover() {
    const rows = this.db.prepare("SELECT * FROM inbox WHERE state='running'").all();
    for (const row of rows) this.complete(row.id, row.peer, ['上次任务因网关重启中断。请重新发送请求；我没有自动重复执行。']);
    return rows.length;
  }
  outgoing() {
    // Generation progress is queued without marking the still-running input complete.
    return this.db.prepare(`SELECT * FROM outbox o WHERE state='pending' AND next<=?
      AND NOT EXISTS (SELECT 1 FROM outbox older WHERE older.peer=o.peer AND older.state='pending' AND older.rowid<o.rowid)
      ORDER BY rowid`).all(Date.now());
  }
  enqueue(source,peer,chunks){for(const text of chunks)this.db.prepare('INSERT INTO outbox(id,peer,text,source) VALUES (?,?,?,?)').run(randomUUID(),peer,mobileText(text),source);}
  sent(id) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const gate=this.db.prepare('SELECT gate FROM outbox WHERE id=?').get(id)?.gate;
      this.db.prepare("UPDATE outbox SET state='sent' WHERE id=?").run(id);
      if(gate) {const g=JSON.parse(gate),c=this.capture(g.id);if(c&&c.revision===g.revision&&c.status===g.status){c[g.field]=Date.now();this.saveCapture(c);this.set('knowledge-active:'+c.peer,c.id);}}
      this.db.exec('COMMIT');
    }catch(e){this.db.exec('ROLLBACK');throw e;}
  }
  retry(id, attempts, delay, terminal = false) {
    this.db.prepare('UPDATE outbox SET attempts=?,next=?,state=? WHERE id=?').run(attempts, Date.now()+delay, terminal ? 'failed' : 'pending', id);
  }
  counts() {
    return { incoming: this.db.prepare("SELECT count(*) n FROM inbox WHERE state IN ('pending','running')").get().n,
      outgoing: this.db.prepare("SELECT count(*) n FROM outbox WHERE state='pending'").get().n,
      failed: this.db.prepare("SELECT count(*) n FROM outbox WHERE state='failed'").get().n };
  }
  close() { this.db.close(); }
}
