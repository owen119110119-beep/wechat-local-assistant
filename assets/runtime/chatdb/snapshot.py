"""Authenticated, stable, bounded binary copies; SQLite never opens source files."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import struct
import time
from contextlib import contextmanager
import native
from storage import local_path,write_json

MAX_DB=512*1024*1024
MAX_WAL=64*1024*1024

def stamp(path):
    try:
        s=path.stat();return [s.st_size,s.st_mtime_ns]
    except FileNotFoundError:return None

@contextmanager
def readonly(path):
    # immutable prevents SQLite creating/consulting any WAL/SHM, even in our cache.
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True,timeout=2)
    c.execute('PRAGMA query_only=ON');c.row_factory=sqlite3.Row
    deadline=time.monotonic()+20
    c.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
    c.text_factory=lambda b:b.decode('utf-8') if valid_utf8(b) else b
    try:yield c
    finally:c.close()

def valid_utf8(b):
    try:b.decode('utf-8');return True
    except UnicodeDecodeError:return False

def checksum(data,s=(0,0),endian='<'):
    if len(data)%8:raise RuntimeError('CHATDB_WAL_CHECKSUM_ALIGNMENT')
    a,b=s
    for x,y in struct.iter_unpack(endian+'II',data):
        a=(a+x+b)&0xffffffff;b=(b+y+a)&0xffffffff
    return a,b

def committed_frames(wal):
    if not wal:return [],None
    if len(wal)<32:raise RuntimeError('CHATDB_WAL_HEADER_INCOMPLETE')
    magic,version,pagesize=struct.unpack_from('>III',wal)
    if magic not in (0x377f0682,0x377f0683) or pagesize!=4096 or version!=3007000:
        raise RuntimeError('CHATDB_WAL_HEADER_UNSUPPORTED')
    endian='<' if magic==0x377f0682 else '>'
    state=checksum(wal[:24],endian=endian)
    if state!=struct.unpack_from('>II',wal,24):raise RuntimeError('CHATDB_WAL_HEADER_CHECKSUM')
    frames=[];last=0;dbsize=None
    for pos in range(32,len(wal)-4119,4120):
        hdr=wal[pos:pos+24];page=wal[pos+24:pos+4120]
        if hdr[8:16]!=wal[16:24]:break # preallocated stale WAL generation
        pgno,commit=struct.unpack_from('>II',hdr)
        if not 0<pgno<=MAX_DB//4096:raise RuntimeError('CHATDB_WAL_PAGE_OUT_OF_RANGE')
        state=checksum(hdr[:8]+page,state,endian)
        if state!=struct.unpack_from('>II',hdr,16):break # valid committed prefix only
        frames.append((pgno,page))
        if commit:
            if commit>MAX_DB//4096:raise RuntimeError('CHATDB_WAL_SIZE_LIMIT')
            last=len(frames);dbsize=commit
    return frames[:last],dbsize

def decrypt_page(key,page,pgno,mac_key):
    if len(page)!=4096:raise RuntimeError('CHATDB_SHORT_PAGE')
    if not any(page):return page # unused zero-filled space; quick_check checks reachability
    start=16 if pgno==1 else 0
    mac=hmac.new(mac_key,page[start:4032]+struct.pack('<I',pgno),hashlib.sha512).digest()
    if not hmac.compare_digest(mac,page[4032:]):raise RuntimeError('CHATDB_PAGE_AUTHENTICATION_FAILED')
    return native._decrypt_page(key,page,pgno)

def snapshot(account,rel,keyhex):
    deadline=time.monotonic()+30
    if rel!='contact/contact.db' and not re.fullmatch(r'message/message_\d+\.db',rel):
        raise RuntimeError('CHATDB_DATABASE_NOT_ALLOWED')
    root=(Path(account)/'db_storage').resolve();src=root/rel;walpath=Path(str(src)+'-wal')
    if not src.resolve().is_relative_to(root) or src.is_symlink() or walpath.is_symlink():
        raise RuntimeError('CHATDB_SOURCE_LINK_FORBIDDEN')
    name='snapshots/'+rel.replace('/','__');dst=local_path(name);meta=local_path(name+'.json')
    key=bytes.fromhex(keyhex)
    signature={'db':stamp(src),'wal':stamp(walpath)}
    if dst.exists() and meta.exists() and json.loads(meta.read_text())['source']==signature:return dst
    data=wal=None
    for attempt in range(3):
        signature={'db':stamp(src),'wal':stamp(walpath)}
        if not signature['db'] or signature['db'][0]>MAX_DB or (signature['wal'] and signature['wal'][0]>MAX_WAL):
            raise RuntimeError('CHATDB_SNAPSHOT_SIZE_LIMIT')
        with src.open('rb') as f:data=f.read(MAX_DB+1)
        wal=b''
        if signature['wal']:
            with walpath.open('rb') as f:wal=f.read(MAX_WAL+1)
        if signature=={'db':stamp(src),'wal':stamp(walpath)}:break
        data=wal=None;time.sleep(.05)
    if data is None:raise RuntimeError('CHATDB_SOURCE_BUSY_RETRY_LATER')
    if len(data)%4096 or not native._verify_enc_key(key,data[:4096]):raise RuntimeError('CHATDB_SNAPSHOT_KEY_INVALID')
    frames,dbsize=committed_frames(wal)
    mac_key=native._pbkdf2(key,bytes(b^0x3a for b in data[:16]),2)
    tmp=local_path(name+'.'+str(os.getpid())+'.tmp')
    try:
        with tmp.open('w+b') as out:
            for i in range(0,len(data),4096):
                if i%(4096*256)==0 and time.monotonic()>deadline:raise RuntimeError('CHATDB_SNAPSHOT_TIMEOUT')
                out.write(decrypt_page(key,data[i:i+4096],i//4096+1,mac_key))
            for pgno,page in frames:
                if pgno<=dbsize:
                    out.seek((pgno-1)*4096);out.write(decrypt_page(key,page,pgno,mac_key))
            if dbsize:out.truncate(dbsize*4096)
            out.flush();os.fsync(out.fileno())
        with readonly(tmp) as c:
            if [r[0] for r in c.execute('PRAGMA quick_check')]!=['ok']:raise RuntimeError('CHATDB_SNAPSHOT_INTEGRITY_FAILED')
        os.replace(tmp,dst)
        write_json(name+'.json',{'source':signature,'committedFrames':len(frames),'pages':dst.stat().st_size//4096,'capturedAt':time.time()})
        return dst
    finally:
        if tmp.exists():tmp.unlink()
