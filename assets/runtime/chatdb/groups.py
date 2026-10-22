"""Private dynamic group bindings, backed by genuine owner-turn evidence."""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
import uuid
from difflib import SequenceMatcher
from storage import local_path,write_json
from snapshot import snapshot,readonly

class SelectionRequired(Exception):
    def __init__(self,result):self.result=result

@contextmanager
def registry():
    c=sqlite3.connect(local_path('private/groups.sqlite'),timeout=2);c.row_factory=sqlite3.Row
    c.create_function('chatdb_group_name',1,normalized,deterministic=True)
    try:
        with c:
            c.executescript('''CREATE TABLE IF NOT EXISTS bindings(account TEXT, username TEXT, label TEXT, PRIMARY KEY(account,username));
            CREATE TABLE IF NOT EXISTS initialized(account TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS choices(token TEXT PRIMARY KEY,account TEXT,owner TEXT,label TEXT,username TEXT,created REAL,source TEXT,candidate_count INTEGER);''')
            if 'requires_reply' not in [r[1] for r in c.execute('PRAGMA table_info(choices)')]:
                c.execute('ALTER TABLE choices ADD COLUMN requires_reply INTEGER NOT NULL DEFAULT 0')
            yield c
    finally:c.close()

def account_id(v):return hashlib.sha256(v['account'].encode()).hexdigest()
def contact_path(v):return snapshot(v['account'],'contact/contact.db',v['keys']['contact/contact.db'])
def label(r):return r['remark'] or r['nick_name']
@contextmanager
def contacts(path):
    with readonly(path) as c:
        c.create_function('chatdb_group_name',1,normalized,deterministic=True)
        yield c
def message_sources(v):
    from pathlib import Path
    root=Path(v['account'])/'db_storage'
    found=sorted(p.relative_to(root).as_posix() for p in (root/'message').glob('message_*.db') if re.fullmatch(r'message_\d+\.db',p.name))
    if any(rel not in v['keys'] for rel in found):raise RuntimeError('CHATDB_NEW_SHARD_NEEDS_KEY_AUTHENTICATION')
    return found

def publish(c,account):
    names=[r[0] for r in c.execute('SELECT label FROM bindings WHERE account=? ORDER BY label',(account,))]
    write_json('private/groups-index.json',{'account':account,'groups':names})

def initialize(v,path):
    account=account_id(v)
    with registry() as c:
        c.execute('INSERT OR IGNORE INTO initialized VALUES (?)',(account,))
        publish(c,account)
    return account


def grant(delivery):
    if not delivery or not re.fullmatch('[0-9a-f]{64}',delivery):raise RuntimeError('CHATDB_REAL_USER_REQUEST_REQUIRED')
    p=local_path('private/grants/'+delivery+'.json')
    if not p.exists():raise RuntimeError('CHATDB_REAL_USER_REQUEST_REQUIRED')
    v=json.loads(p.read_text(encoding='utf-8'))
    if v.get('delivery')!=delivery or v.get('source')!='wechat-owner-inbox' or not re.fullmatch('[0-9a-f]{64}',v.get('owner','')) or not 0<=time.time()-v.get('created',0)<3600:
        raise RuntimeError('CHATDB_REAL_USER_REQUEST_REQUIRED')
    return v

def normalized(text):
    if text is None:return ''
    if not isinstance(text,str):raise RuntimeError('CHATDB_GROUP_NAME_ENCODING_UNSUPPORTED')
    return re.sub(r'[\s\u200b\u2060\ufeff]+','',unicodedata.normalize('NFKC',text)).casefold()

# Presentation-only characters are relaxed for search, never for group identity.
# Keep %, _, &, +, digits and emoji meaningful; no SQL wildcard interpretation.
LAYOUT='「」『』【】[]()（）〔〕《》〈〉“”‘’\"\''
GENERIC={'群','群聊','微信群','聊天群','交流群','讨论群','学习群','陪伴群','这个群','信息','消息'}
def search_form(text):
    return normalized(text).translate(str.maketrans('','',LAYOUT))

def one_edit(a,b):
    if abs(len(a)-len(b))>1:return False
    i=j=errors=0
    while i<len(a) and j<len(b):
        if a[i]==b[j]:i+=1;j+=1;continue
        errors+=1
        if errors>1:return False
        if len(a)>=len(b):i+=1
        if len(b)>=len(a):j+=1
    return errors+(i<len(a))+(j<len(b))<=1

def match_name(query,name):
    q,n=normalized(query),normalized(name)
    if not n:return None
    if q==n:return (100,'exact',False)
    if q in n:return (98,'fragment',False)
    q,n=search_form(query),search_form(name)
    if not q:return None
    if q==n or q in n:return (96,'layout',False)
    # A real punctuation mark used by the owner stays literal, including SQL
    # metacharacters; typo/gap matching cannot erase it as a supposed mistake.
    if any(ch in q and ch not in n for ch in '%_&+'):
        return None
    tokens=[search_form(t) for t in re.split(r'[\s、，,;；/|&+的「」『』【】\[\]()（）“”‘’\"\']+',unicodedata.normalize('NFKC',query))]
    tokens=list(dict.fromkeys(t for t in tokens if len(t)>=2 and t not in GENERIC))
    if len(tokens)>=2 and sum(map(len,tokens))>=4 and all(t in n for t in tokens):
        return (90,'keywords',True)
    if any(not ch.isalnum() for ch in q):return None
    if len(q)>=4:
        blocks=[b for b in SequenceMatcher(None,q,n,autojunk=False).get_matching_blocks() if b.size>=2]
        if len(blocks)>=2 and sum(b.size for b in blocks)==len(q) and blocks[-1].b+blocks[-1].size-blocks[0].b<=max(len(q)*3,len(q)+10):
            return (88,'separated_keywords',True)
    # One wrong/missing/extra character only in a substantial name; a short
    # person's name is not enough to expand access. Require an exact anchor.
    if len(q)>=6:
        for size in (len(q),len(q)-1,len(q)+1):
            for start in range(max(0,len(n)-size+1)):
                part=n[start:start+size]
                if one_edit(q,part) and max(b.size for b in SequenceMatcher(None,q,part,autojunk=False).get_matching_blocks())>=3:
                    return (84,'possible_typo',True)
    return None
def mentioned(text,name,removal=False):
    # Name evidence is checked separately from the agent's natural-language decision.
    # Examples, reported instructions, code blocks and explicit prohibitions cannot add groups.
    text=re.sub(r'```[\s\S]*?```','',text)
    # Protect punctuation and words inside the actual group name before examining
    # surrounding prose, so names such as "别摸鱼！AI群" remain legitimate names.
    target=search_form(name)
    if not target:return False
    protected=search_form(text).replace(target,'__target_group__')
    for clause in re.split('[\n。！？!?；;]',protected):
        if '__target_group__' not in clause:continue
        if re.search('例如|比如|举例|原文|群里说|有人说|引用|转述',clause):continue
        if not removal and re.search(r'(不要|不用|不必|别|禁止|无需|不需要|不是要|不想|暂不).{0,10}(读|整理|添加|接入|开通)|(读|整理|添加|接入|开通).{0,8}(不要|不用|不必|禁止)',clause):continue
        return True
    return False

def named_grant(delivery,name,removal=False):
    g=grant(delivery)
    if not name or len(name)>120 or not any(mentioned(t,name,removal) for t in g.get('texts',[])):
        raise RuntimeError('CHATDB_TARGET_NOT_IN_REAL_USER_REQUEST')
    return g

def registered(v):
    path=contact_path(v);account=initialize(v,path)
    with registry() as c:return {'status':'registered_groups','groups':[r[0] for r in c.execute('SELECT label FROM bindings WHERE account=? ORDER BY label',(account,))]}

def candidates(v,name,delivery):
    g=named_grant(delivery,name);path=contact_path(v);account=initialize(v,path)
    if len(search_form(name))<2 or search_form(name) in GENERIC:
        return {'status':'need_more_specific_name','message':'这个片段太短或过于宽泛，请补充群名中有区分度的词。'}
    matches={}
    def score(nick,remark):
        best=max((m for m in (match_name(name,nick or ''),match_name(name,remark or '')) if m),default=None)
        if best:matches[(nick,remark)]=best
        return best[0] if best else 0
    with contacts(path) as c:
        c.create_function('chatdb_match_score',2,score)
        rows=c.execute("SELECT username,nick_name,remark,chatdb_match_score(nick_name,remark) AS match_score FROM contact WHERE username LIKE '%@chatroom' AND chatdb_match_score(nick_name,remark)>0 ORDER BY match_score DESC,nick_name,remark LIMIT 11").fetchall()
    # Do not introduce speculative alternatives when literal/layout matches
    # already locate the requested fragment. Keep all such matches, not top-1.
    literal=[r for r in rows if r['match_score']>=96]
    if literal:rows=literal
    if len(rows)>10:return {'status':'need_more_specific_name','message':'匹配群较多，请补充更完整群名。'}
    if not rows:return {'status':'group_not_found','message':'本机群名中没有找到可靠匹配。已核对空格、括号及有限错字；请补充有区分度的群名片段，不能仅据此判断群未同步。'}
    return choices(v,rows,name,delivery,g,{r['username']:matches[(r['nick_name'],r['remark'])] for r in rows})

def choices(v,rows,name,delivery,g,match_info=None):
    account=account_id(v);items=[]
    sources=[snapshot(v['account'],rel,v['keys'][rel]) for rel in message_sources(v)]
    with registry() as state:
        for r in rows:
            token=uuid.uuid4().hex;last=None;count=0
            table='Msg_'+hashlib.md5(r['username'].encode()).hexdigest()
            for source in sources:
                with readonly(source) as c:
                    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                        info=c.execute('SELECT COUNT(*),MAX(create_time) FROM '+table).fetchone();count+=info[0]
                        if info[1] is not None:last=max(last or 0,info[1])
            info=(match_info or {}).get(r['username'],(100,'exact',False))
            needs_reply=len(rows)>1 or info[2]
            state.execute('INSERT INTO choices (token,account,owner,label,username,created,source,candidate_count,requires_reply) VALUES (?,?,?,?,?,?,?,?,?)',(token,account,g['owner'],label(r),r['username'],time.time(),delivery,len(rows),int(needs_reply)))
            matched_names=[n for n in (r['nick_name'],r['remark']) if n and match_name(name,n)]
            items.append({'name':label(r),'matchedNames':list(dict.fromkeys(matched_names)),'localMessages':count,'lastLocalMessage':datetime.fromtimestamp(last,timezone(timedelta(hours=8))).isoformat() if last else None,'matchKind':info[1],'needsTargetClarification':needs_reply,'internalChoice':token})
    return {'status':'group_candidates','query':name,'candidates':items,'instruction':'按匹配理由核对真实群名。仅唯一且needsTargetClarification=false可同轮用name/internalChoice继续；错字或分散关键词即使唯一也先自然核对目标，多个候选需用户区分。可合并询问尚缺的重点/时间，不要求配置确认或固定口令，内部标识不发给手机。'}

def resolve(v,name,delivery=None,choice=None):
    if not name:raise RuntimeError("CHATDB_GROUP_REQUIRED")
    path=contact_path(v);account=initialize(v,path)
    binding_label=name
    with registry() as state:
        if choice:
            g=grant(delivery)
            selected=state.execute('SELECT * FROM choices WHERE token=? AND account=? AND owner=?',(choice,account,g['owner'])).fetchone()
            if not selected or time.time()-selected['created']>86400 or normalized(selected['label'])!=normalized(name):raise RuntimeError('CHATDB_GROUP_CHOICE_EXPIRED')
            if (selected['candidate_count']>1 or selected['requires_reply']) and selected['source']==delivery:raise RuntimeError('CHATDB_GROUP_SELECTION_NEEDS_USER_REPLY')
            if selected['requires_reply'] or selected['candidate_count']>1:
                if g['created']<selected['created']:raise RuntimeError('CHATDB_GROUP_SELECTION_NEEDS_USER_REPLY')
                # Rejection guard only, never a required confirmation vocabulary.
                latest=normalized(g.get('texts',[''])[-1]).replace(normalized(selected['label']),'__target_group__')
                if re.search(r'^(?:就)?取消[吧了。！!]*$|取消(?:整理|读取|这个群|本次)|(?:先别|先不要|暂不|不需要|不用|不要|别)(?:再)?(?:整理|读取|分析)|停止(?:整理|读取|本次)|不是(?:这个|该)群|^不对',latest):
                    raise RuntimeError('CHATDB_GROUP_SELECTION_CANCELLED')
            username=selected['username']
            binding_label=selected['label']
        else:
            bound=state.execute('SELECT username,label FROM bindings WHERE account=? AND chatdb_group_name(label)=?',(account,normalized(name))).fetchall()
            if len(bound)==1:username=bound[0]['username'];binding_label=bound[0]['label']
            else:
                g=named_grant(delivery,name)
                with contacts(path) as c:
                    rows=c.execute('SELECT username,nick_name,remark FROM contact WHERE username LIKE ? AND (chatdb_group_name(nick_name)=? OR chatdb_group_name(remark)=?)',('%@chatroom',normalized(name),normalized(name))).fetchall()
                if len(rows)!=1:
                    # Release the registry transaction before recording pending choices.
                    username=None
                else:username=rows[0]['username'];binding_label=label(rows[0])
        if username:
            with readonly(path) as c:
                if not c.execute('SELECT 1 FROM contact WHERE username=?',(username,)).fetchone():raise RuntimeError('CHATDB_BOUND_GROUP_NOT_LOCAL')
            state.execute('INSERT INTO bindings VALUES (?,?,?) ON CONFLICT(account,username) DO UPDATE SET label=excluded.label',(account,username,binding_label))
            publish(state,account)
    if username is None:
        result=choices(v,rows,name,delivery,g) if rows else candidates(v,name,delivery)
        raise SelectionRequired(result)
    with registry() as state:
        saved=state.execute('SELECT label FROM bindings WHERE account=? AND username=?',(account,username)).fetchone()
        if not saved or saved[0]!=binding_label:raise RuntimeError('CHATDB_BINDING_READBACK_FAILED')
    return username,path

def display_name(v,username,fallback):
    with registry() as c:
        row=c.execute('SELECT label FROM bindings WHERE account=? AND username=?',(account_id(v),username)).fetchone()
    return row[0] if row else fallback

def remove(v,name,delivery):
    named_grant(delivery,name,removal=True);account=initialize(v,contact_path(v))
    with registry() as c:
        matches=c.execute('SELECT username FROM bindings WHERE account=? AND chatdb_group_name(label)=?',(account,normalized(name))).fetchall()
        if len(matches)>1:raise RuntimeError('CHATDB_REGISTERED_GROUP_NAME_AMBIGUOUS')
        n=c.execute('DELETE FROM bindings WHERE account=? AND chatdb_group_name(label)=?',(account,normalized(name))).rowcount
        publish(c,account)
    with registry() as c:
        if c.execute('SELECT 1 FROM bindings WHERE account=? AND chatdb_group_name(label)=?',(account,normalized(name))).fetchone():raise RuntimeError('CHATDB_BINDING_READBACK_FAILED')
    return {'status':'group_removed' if n else 'group_not_registered','group':name,'wechatDataDeleted':False}

def prepare(v,name,delivery=None,choice=None,now=None):
    username,path=resolve(v,name,delivery,choice)
    name=display_name(v,username,name)
    now=now or datetime.now(timezone(timedelta(hours=8)))
    midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    start3=midnight-timedelta(days=2);start7=midnight-timedelta(days=6)
    until=midnight+timedelta(days=1)
    table='Msg_'+hashlib.md5(username.encode()).hexdigest();count3=count7=0
    for rel in message_sources(v):
        key=v['keys'][rel]
        with readonly(snapshot(v['account'],rel,key)) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                n=c.execute('SELECT SUM(CASE WHEN create_time>=? THEN 1 ELSE 0 END),COUNT(*) FROM '+table+' WHERE create_time>=? AND create_time<?',(int(start3.timestamp()),int(start7.timestamp()),int(until.timestamp()))).fetchone()
                count3+=n[0] or 0;count7+=n[1]
    days=3 if count3>=200 or count7>=600 else 7
    return {'status':'group_ready','group':name,'configuredAutomatically':True,'sourceScope':'电脑微信本机已同步记录，不能直接调取手机独有记录',
        'messagesLast3CalendarDays':count3,'messagesLast7CalendarDays':count7,
        'suggestedDays':days,'suggestedSince':(start3 if days==3 else start7).date().isoformat(),'suggestedUntilExclusive':until.date().isoformat(),
        'instruction':'不需要确认配置。仅自然追问尚缺的重点或时间，时间缺失时结合这里的消息量给建议；无特定方向就自行筛重点归类。用户已说明目标/方向/时间或接受建议后直接read，不再要求确认整理。此结果不含正文，不等于已整理完成。'}
