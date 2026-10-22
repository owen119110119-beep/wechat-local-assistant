"""Only the explicitly authorized group; no GUI, network, or source DB writes."""
import argparse
import hashlib
import json
import re
import sys
import sqlite3
import time
from datetime import datetime,timezone,timedelta
import uuid
import zstandard
from storage import load_secret,write_json,local_path
from snapshot import snapshot,readonly
import groups

GROUP=None

def target(v,group=GROUP,delivery=None,choice=None):return groups.resolve(v,group,delivery,choice)

def message_sources(v):
    return groups.message_sources(v)

def content(value,kind):
    if isinstance(value,bytes):
        if value.startswith(b'\x28\xb5\x2f\xfd'):
            try:value=zstandard.ZstdDecompressor().decompress(value,max_output_size=2*1024*1024)
            except zstandard.ZstdError:return '[压缩正文读取失败]'
        try:value=value.decode('utf-8')
        except UnicodeDecodeError:return '[非文字内容，未分析]'
    if not value:return '[非文字内容，未分析]'
    if kind!=1:return '[非文字消息，未分析媒体]'
    return str(value)

def open_state():
    c=sqlite3.connect(local_path('private/delivery.sqlite'),timeout=2)
    c.execute('CREATE TABLE IF NOT EXISTS delivered (id TEXT PRIMARY KEY)')
    c.execute('CREATE TABLE IF NOT EXISTS batches (token TEXT PRIMARY KEY, ids TEXT NOT NULL, created REAL NOT NULL)')
    if 'delivery' not in [r[1] for r in c.execute('PRAGMA table_info(batches)')]:c.execute('ALTER TABLE batches ADD COLUMN delivery TEXT')
    c.commit();return c

def acknowledge(token):
    with open_state() as c:
        row=c.execute('SELECT ids FROM batches WHERE token=?',(token,)).fetchone()
        if not row:raise RuntimeError('CHATDB_BATCH_NOT_FOUND')
        c.executemany('INSERT OR IGNORE INTO delivered VALUES (?)',[(i,) for i in json.loads(row[0])])
        c.execute('DELETE FROM batches WHERE token=?',(token,))
    c.close();return {'status':'acknowledged','count':len(json.loads(row[0]))}

def ack_delivery(delivery):
    if not re.fullmatch('[0-9a-f]{64}',delivery):raise RuntimeError('CHATDB_INVALID_DELIVERY')
    with open_state() as c:
        rows=c.execute('SELECT ids FROM batches WHERE delivery=?',(delivery,)).fetchall()
        ids={i for r in rows for i in json.loads(r[0])}
        c.executemany('INSERT OR IGNORE INTO delivered VALUES (?)',[(i,) for i in ids])
        c.execute('DELETE FROM batches WHERE delivery=?',(delivery,))
    c.close();return {'status':'acknowledged','count':len(ids)}

def read_messages(group,mode,limit=200,offset=0,delivery=None,choice=None,since=None,until=None):
    if mode not in ('history','new') or not 1<=limit<=500 or not 0<=offset<=50000:raise RuntimeError('CHATDB_INVALID_QUERY')
    if delivery is not None and not re.fullmatch('[0-9a-f]{64}',delivery):raise RuntimeError('CHATDB_INVALID_DELIVERY')
    def timestamp(s):
        if not s:return None
        try:
            d=datetime.fromisoformat(s)
            if d.tzinfo is None:d=d.replace(tzinfo=timezone(timedelta(hours=8)))
            return int(d.timestamp())
        except ValueError:raise RuntimeError('CHATDB_INVALID_TIME_RANGE')
    lower,upper=timestamp(since),timestamp(until)
    if lower is not None and upper is not None and lower>=upper:raise RuntimeError('CHATDB_INVALID_TIME_RANGE')
    where=[];params=[]
    if lower is not None:where.append('create_time>=?');params.append(lower)
    if upper is not None:where.append('create_time<?');params.append(upper)
    condition=' WHERE '+' AND '.join(where) if where else ''
    v=load_secret('database-keys');user,contacts=target(v,group,delivery,choice)
    group=groups.display_name(v,user,group)
    table='Msg_'+hashlib.md5(user.encode()).hexdigest();items=[];total=0
    matched=0
    with open_state() as state:
        delivered={r[0] for r in state.execute('SELECT id FROM delivered')}
    state.close()
    for rel in message_sources(v):
        p=snapshot(v['account'],rel,v['keys'][rel])
        with readonly(p) as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
            total+=c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
            matched+=c.execute('SELECT COUNT(*) FROM '+table+condition,params).fetchone()[0]
            if matched>50000:raise RuntimeError('CHATDB_HISTORY_REQUIRES_TIME_RANGE')
            for r in c.execute('SELECT local_id,server_id,local_type,sort_seq,real_sender_id,create_time,message_content,compress_content FROM '+table+condition+' ORDER BY sort_seq,local_id',params):
                raw_id=f'{user}:server:{r["server_id"]}' if r['server_id'] else f'{user}:{rel}:{r["local_id"]}'
                identity=hashlib.sha256(raw_id.encode()).hexdigest()
                if mode=='new' and identity in delivered:continue
                sender=c.execute('SELECT user_name FROM Name2Id WHERE rowid=?',(r['real_sender_id'],)).fetchone()
                items.append({'_id':identity,'_order':(r['sort_seq'],rel,r['local_id']),'_sender':sender[0] if sender else '',
                    'time':datetime.fromtimestamp(r['create_time'],timezone(timedelta(hours=8))).isoformat(),
                    'type':int(r['local_type'])&0xffffffff,
                    'content':content(r['message_content'] or r['compress_content'],int(r['local_type'])&0xffffffff)})
    # Stable IDs handle equal timestamps/sequences and overlapping shards.
    unique={}
    for m in sorted(items,key=lambda m:m['_order']):unique.setdefault(m['_id'],m)
    rows=list(unique.values())
    if mode=='history':rows.reverse()
    selected=rows[offset:offset+limit]
    with readonly(contacts) as c:
        for m in selected:
            name=c.execute('SELECT nick_name,remark FROM contact WHERE username=?',(m['_sender'],)).fetchone()
            m['sender']=(name['remark'] or name['nick_name']) if name else '发送者未解析'
    ids=[m['_id'] for m in selected];token=uuid.uuid4().hex if ids else None
    if token:
        with open_state() as state:state.execute('INSERT INTO batches (token,ids,created,delivery) VALUES (?,?,?,?)',(token,json.dumps(ids),time.time(),delivery))
        state.close()
        if delivery:
            name='private/receipts/'+delivery+'.json';p=local_path(name)
            old=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
            names=set(old.get('groups',[]) or ([old['group']] if old.get('group') else []));names.add(group)
            write_json(name,{'delivery':delivery,'groups':sorted(names)})
    public=[{k:v for k,v in m.items() if not k.startswith('_')} for m in selected]
    return {'group':group,'mode':mode,'source':'local_database_readonly','capturedAt':datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'totalStoredMessages':total,'rangeStoredMessages':matched,'returned':len(public),'more':offset+limit<len(rows),'nextOffset':offset+len(public),
        'messages':public,'internalBatch':token,'acknowledged':False,'mediaAnalyzed':False}

def inspect(group=GROUP,delivery=None,choice=None):
    v=load_secret('database-keys')
    user,path=target(v,group,delivery,choice)
    table='Msg_'+hashlib.md5(user.encode()).hexdigest()
    databases=[]
    for rel,key in v['keys'].items():
        if not re.fullmatch(r'message/message_\d+\.db',rel):continue
        p=snapshot(v['account'],rel,key)
        with readonly(p) as c:
            found=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if found:
                databases.append({'database':rel,'columns':[r[1] for r in c.execute('PRAGMA table_info('+table+')')],
                    'nameColumns':[r[1] for r in c.execute('PRAGMA table_info(Name2Id)')],
                    'groupMessages':c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]})
    return {'group':group,'exactGroupMatches':1,'snapshots':'quick_check_ok','databases':databases}

def main():
    p=argparse.ArgumentParser();p.add_argument('--inspect',action='store_true');p.add_argument('--group',default=GROUP)
    p.add_argument('--mode',choices=['history','new']);p.add_argument('--limit',type=int,default=200);p.add_argument('--offset',type=int,default=0);p.add_argument('--ack')
    p.add_argument('--delivery');p.add_argument('--ack-delivery')
    p.add_argument('--choice');p.add_argument('--find-group');p.add_argument('--list-groups',action='store_true');p.add_argument('--register',action='store_true');p.add_argument('--remove-group',action='store_true')
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--since');p.add_argument('--until')
    a=p.parse_args()
    import msvcrt
    lock=local_path('private/reader.lock')
    with lock.open('a+b') as f:
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('CHATDB_READER_BUSY')
        try:
            if a.inspect:result=inspect(a.group,a.delivery,a.choice)
            elif a.ack_delivery:result=ack_delivery(a.ack_delivery)
            elif a.ack:result=acknowledge(a.ack)
            elif a.find_group:result=groups.candidates(load_secret('database-keys'),a.find_group,a.delivery)
            elif a.list_groups:result=groups.registered(load_secret('database-keys'))
            elif a.prepare:result=groups.prepare(load_secret('database-keys'),a.group,a.delivery,a.choice)
            elif a.register:
                groups.resolve(load_secret('database-keys'),a.group,a.delivery,a.choice)
                result={'status':'group_registered','group':a.group}
            elif a.remove_group:result=groups.remove(load_secret('database-keys'),a.group,a.delivery)
            elif a.mode:result=read_messages(a.group,a.mode,a.limit,a.offset,a.delivery,a.choice,a.since,a.until)
            else:raise RuntimeError('CHATDB_QUERY_REQUIRED')
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except groups.SelectionRequired as exc:print(json.dumps(exc.result,ensure_ascii=False))
    except Exception as exc:
        code=str(exc) if str(exc).startswith('CHATDB_') else 'CHATDB_READ_'+type(exc).__name__.upper()
        import traceback
        trace=[{'function':f.name,'line':f.lineno} for f in traceback.extract_tb(exc.__traceback__)]
        reasons={'CHATDB_REAL_USER_REQUEST_REQUIRED':'新增群需要本轮微信真实用户的指定要求。','CHATDB_TARGET_NOT_IN_REAL_USER_REQUEST':'目标名称没有出现在真实用户请求中，或只是例子、引用或禁止操作；请核对目标。','CHATDB_GROUP_SELECTION_NEEDS_USER_REPLY':'存在多个候选或错字/关键词推测，需要先自然核对目标；不是确认配置，不要求编号或固定口令。','CHATDB_GROUP_CHOICE_EXPIRED':'之前的群候选已失效，请按用户给的名称重新核对。','CHATDB_HISTORY_REQUIRES_TIME_RANGE':'该范围消息超过读取容量，请加上起止日期分段整理。','CHATDB_NEW_SHARD_NEEDS_KEY_AUTHENTICATION':'微信新增了消息数据库分片，目前尚未认证，不能冒充已读完整记录。'}
        reasons['CHATDB_GROUP_SELECTION_CANCELLED']='当前真实用户回应取消整理或否定该目标，不应绑定或读取此候选；继续按用户最新要求交流。'
        report={'status':'failed','error':code,'reason':reasons.get(code,'本机读取未完成，请结合错误阶段说明具体情况，不能把失败当作没有消息。'),'winerror':getattr(exc,'winerror',None),'errno':getattr(exc,'errno',None),'trace':trace}
        write_json('reader-error.json',report)
        print(json.dumps(report));sys.exit(1)
