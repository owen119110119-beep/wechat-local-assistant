"""Project-only state and current-user DPAPI protection; no UI or network."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / '.runtime' / 'chatdb'

def local_path(name: str) -> Path:
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('CHATDB_UNSAFE_CACHE_PATH')
    p=ROOT / relative
    for part in [ROOT, *p.parents, p]:
        if part.exists() and (part.is_symlink() or getattr(part,'is_junction',lambda:False)()):
            raise ValueError('CHATDB_CACHE_LINK_FORBIDDEN')
    if not p.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('CHATDB_UNSAFE_CACHE_PATH')
    p.parent.mkdir(parents=True,exist_ok=True)
    return p

def write_json(name: str, value) -> None:
    p=local_path(name);tmp=local_path(name+'.tmp')
    text=json.dumps(value,ensure_ascii=False,indent=2)
    tmp.write_text(text,encoding='utf-8');os.replace(tmp,p)
    if p.read_text(encoding='utf-8')!=text:raise RuntimeError('CHATDB_READBACK_FAILED')

class Blob(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_ubyte))]

def _dpapi(data: bytes, protect: bool) -> bytes:
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    output=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    kernel.LocalFree.restype=ctypes.c_void_p
    if protect:
        fn=crypt.CryptProtectData
        fn.argtypes=[ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fn(ctypes.byref(source),'WeChat Local Assistant ChatDB',None,None,None,1,ctypes.byref(output))
    else:
        fn=crypt.CryptUnprotectData
        fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok=fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output))
    if not ok:raise RuntimeError('CHATDB_DPAPI_FAILED')
    try:return ctypes.string_at(output.pbData,output.cbData)
    finally:kernel.LocalFree(output.pbData)

def save_secret(name: str, value) -> None:
    p=local_path('private/'+name+'.dpapi')
    p.write_bytes(_dpapi(json.dumps(value).encode('utf-8'),True))
    if load_secret(name)!=value:raise RuntimeError('CHATDB_SECRET_READBACK_FAILED')

def load_secret(name: str):
    p=local_path('private/'+name+'.dpapi')
    return json.loads(_dpapi(p.read_bytes(),False))
