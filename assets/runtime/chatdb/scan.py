"""Bounded read-only Config.Cipher lookup adapted from upstream db.py.

No generic byte/key dump, other-process scan, UI, memory writes, or network.
Only page-authenticated database keys are retained in current-user DPAPI.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import re
import struct
import time
import native
from environment import data_root
from storage import save_secret,write_json

NEEDLE=b'com.Tencent.WCDB.Config.Cipher'
MASK=bytes.fromhex('d2c7442458020000004889442450488b450048844c2448488944254048584c24')
HEX=re.compile(rb"[xX]'([0-9a-fA-F]{64,192})'")
DIAGNOSTICS={}

class MBI(ctypes.Structure):
    _fields_=[('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),('AllocationProtect',wintypes.DWORD),('alignment',wintypes.DWORD),('RegionSize',ctypes.c_size_t),('State',wintypes.DWORD),('Protect',wintypes.DWORD),('Type',wintypes.DWORD),('alignment2',wintypes.DWORD)]

def scan_keys(pid,headers,seconds=35,max_bytes=1536*1024*1024):
    k=native._k32
    k.VirtualQueryEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
    k.VirtualQueryEx.restype=ctypes.c_size_t
    h=k.OpenProcess(0x410,False,pid)
    if not h:raise RuntimeError('CHATDB_PROCESS_READ_DENIED')
    deadline=time.monotonic()+seconds;total=0;regions=0
    def read(addr,n):
        nonlocal total
        if time.monotonic()>deadline or total+n>max_bytes:raise RuntimeError('CHATDB_SCAN_BUDGET_EXCEEDED')
        if n<=0 or n>1024*1024:raise RuntimeError('CHATDB_READ_SIZE_LIMIT')
        total+=n;buf=ctypes.create_string_buffer(n);done=ctypes.c_size_t()
        if k.ReadProcessMemory(h,ctypes.c_void_p(addr),buf,n,ctypes.byref(done)) and done.value:return buf.raw[:done.value]
        return b''
    def find(patterns):
        nonlocal regions
        hits={p:[] for p in patterns};addr=0
        phase='config_names' if patterns==[NEEDLE] else 'config_references'
        DIAGNOSTICS.update(phase=phase,patternCount=len(patterns))
        while True:
            info=MBI()
            if not k.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(info),ctypes.sizeof(info)):break
            base=info.BaseAddress or 0;size=info.RegionSize
            if size<=0 or base+size<=addr:break
            if info.State==0x1000 and not info.Protect&0x100 and info.Protect&0xff in (2,4,8,32,64,128) and info.Type in (0x20000,0x1000000):
                regions+=1;tail=b''
                for offset in range(0,size,1024*1024):
                    block=read(base+offset,min(1024*1024,size-offset));joined=tail+block;origin=base+offset-len(tail)
                    for pattern in patterns:
                        start=0
                        while True:
                            i=joined.find(pattern,start)
                            if i<0:break
                            hit=origin+i
                            if hit not in hits[pattern]:hits[pattern].append(hit)
                            # Two distinct names can have many per-database configuration
                            # references. Keep names tightly bounded and references separately.
                            limit=128 if phase=='config_names' else 4096
                            if len(hits[pattern])>limit:
                                DIAGNOSTICS.update(largestMatchCount=len(hits[pattern]),scanMiB=round(total/1048576,1),regionPasses=regions)
                                raise RuntimeError('CHATDB_TOO_MANY_CONFIG_MATCHES')
                            start=i+1
                    tail=joined[-63:]
                    time.sleep(0.001)
            addr=base+size
        return hits
    try:
        needles=find([NEEDLE])[NEEDLE]
        DIAGNOSTICS.update(configNames=len(needles),namePassMiB=round(total/1048576,1))
        if not needles:raise RuntimeError('CHATDB_CONFIG_CIPHER_NOT_FOUND')
        pairs=[struct.pack('<QQ',a,len(NEEDLE)) for a in needles]
        refs=find(pairs);keys={};seen=set();objects=0
        DIAGNOSTICS.update(phase='authenticate',references=sum(map(len,refs.values())),scanMiB=round(total/1048576,1))
        for pair in pairs:
            for q in refs[pair]:
                node=read(q-16,80)
                if len(node)<64 or struct.unpack_from('<Q',node,16)[0] not in needles:continue
                ptr=struct.unpack_from('<Q',node,40)[0]
                if not 0x10000<=ptr<0x800000000000:continue
                obj=read(ptr+0x88,40)
                if len(obj)<24:continue
                data_ptr,length=struct.unpack_from('<QQ',obj,8)
                if not 0<length<=1024 or not 0x10000<=data_ptr<0x800000000000:continue
                blob=read(data_ptr,length)
                if len(blob)!=length:continue
                objects+=1;decoded=bytes(b^MASK[i%len(MASK)] for i,b in enumerate(blob))
                for match in HEX.finditer(decoded):
                    run=match.group(1).decode();starts=[0]
                    if len(run)>96:starts+=list(range(0,len(run)-63,32))+[len(run)-64]
                    for pos in dict.fromkeys(starts):
                        if pos+64>len(run):continue
                        candidate=bytes.fromhex(run[pos:pos+64])
                        if candidate in seen:continue
                        seen.add(candidate)
                        if len(set(candidate))<15:continue
                        for rel,page in headers.items():
                            if rel not in keys and native._verify_enc_key(candidate,page):keys[rel]=candidate.hex()
        return keys,{'scanMiB':round(total/1048576,1),'regionPasses':regions,'configNames':len(needles),'configObjects':objects,'authenticatedDatabases':len(keys)}
    finally:k.CloseHandle(h)

def main():
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('--install-root',required=True);p.add_argument('--account');a=p.parse_args();start=time.monotonic()
    module=native._find_weixin_module(a.pid)
    if not module or not Path(module[2]).resolve().is_relative_to(Path(a.install_root).resolve()):raise RuntimeError('CHATDB_PROCESS_PATH_MISMATCH')
    root=data_root() if not a.account else Path(a.account).resolve().parent;accounts=[Path(a.account).resolve()] if a.account else [d for d in root.iterdir() if d.is_dir() and (d/'db_storage').is_dir()]
    if len(accounts)!=1:raise RuntimeError('CHATDB_ACCOUNT_SELECTION_REQUIRED')
    account=accounts[0];headers={}
    if not (account/'db_storage/contact/contact.db').is_file():raise RuntimeError('CHATDB_ACCOUNT_INVALID')
    if any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in [account,*account.parents]):raise RuntimeError('CHATDB_ACCOUNT_LINK_FORBIDDEN')
    for db in (account/'db_storage').rglob('*.db'):
        rel=db.relative_to(account/'db_storage').as_posix()
        if rel=='contact/contact.db' or re.fullmatch(r'message/message_\d+\.db',rel):
            with db.open('rb') as f:headers[rel]=f.read(4096)
    keys,stats=scan_keys(a.pid,headers)
    if 'contact/contact.db' not in keys:raise RuntimeError('CHATDB_CONTACT_KEY_NOT_AUTHENTICATED')
    if set(headers)-set(keys):raise RuntimeError('CHATDB_MESSAGE_KEYS_NOT_AUTHENTICATED')
    save_secret('database-keys',{'account':str(account.resolve()),'keys':keys})
    report={'status':'config_cipher_keys_verified','secretProtected':'current-user DPAPI','seconds':round(time.monotonic()-start,3),'originalFilesWritten':False,'networkUsed':False,'guiUsed':False,**stats}
    write_json('bootstrap-status.json',report);print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        code=str(exc) if str(exc).startswith('CHATDB_') else 'CHATDB_SCAN_'+type(exc).__name__.upper()
        write_json('scan-error.json',{'error':code,'at':time.time(),**DIAGNOSTICS})
        print(json.dumps({'status':'failed','error':code,**DIAGNOSTICS}));raise SystemExit(1)
