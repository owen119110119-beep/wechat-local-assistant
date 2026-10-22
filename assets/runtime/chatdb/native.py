# Read-only primitives; attribution and Apache-2.0 license in THIRD_PARTY_NOTICES.md.
from __future__ import annotations
import ctypes, hashlib, hmac as hmac_mod, struct
from ctypes import wintypes
from typing import Optional, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
_k32 = ctypes.WinDLL('kernel32', use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
PAGE_SZ = 4096
RESERVE_SZ = 80

class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('th32ModuleID', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD), ('GlblcntUsage', wintypes.DWORD), ('ProccntUsage', wintypes.DWORD), ('modBaseAddr', ctypes.c_void_p), ('modBaseSize', wintypes.DWORD), ('hModule', wintypes.HMODULE), ('szModule', ctypes.c_wchar * 256), ('szExePath', ctypes.c_wchar * 260)]

def _pbkdf2(passwd: bytes, salt: bytes, iters: int) -> bytes:
    return hashlib.pbkdf2_hmac('sha512', passwd, salt, iters, dklen=32)

def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()

def _split_key(key: bytes) -> Tuple[bytes, Optional[bytes]]:
    """拆分密钥形态：32 字节 = 标准裸 key（salt 用文件头前 16 字节）；
    48 字节 = SQLCipher 4 "Raw Key with Explicit Salt"（前 32B key + 后 16B salt，
    用于 cipher_plaintext_header_size 明文头模式）。返回 (enc_key, salt_or_None)。"""
    if len(key) == 48:
        return (key[:32], key[32:])
    return (key, None)

def _verify_enc_key(enc_key: bytes, page1: bytes, salt: Optional[bytes]=None) -> bool:
    """验证 enc_key 是否为 page1 的 SQLCipher 4 密钥。

    - enc_key 为 32 字节裸 key：默认用文件头前 16 字节作 salt（标准形式）；
    - enc_key 为 48 字节 key+salt：显式 salt 优先于文件头（明文头模式）；
    - 也允许单独传 salt 参数覆盖（供提取逻辑按 96hex 拆分尝试）。
    """
    if len(page1) < PAGE_SZ:
        return False
    if len(enc_key) == 48 and salt is None:
        enc_key, salt = (enc_key[:32], enc_key[32:])
    if salt is None:
        salt = page1[:16]
    elif len(salt) != 16:
        return False
    mac_salt = bytes((b ^ 58 for b in salt))
    mac_key = _pbkdf2(enc_key, mac_salt, 2)
    hmac_data = page1[16:PAGE_SZ - RESERVE_SZ + 16]
    stored_hmac = page1[PAGE_SZ - 64:PAGE_SZ]
    hm = hmac_mod.new(mac_key, hmac_data, hashlib.sha512)
    hm.update(struct.pack('<I', 1))
    return hm.digest() == stored_hmac

def _find_weixin_module(pid: int) -> Optional[Tuple[int, int, str]]:
    """返回 (模块基址, 模块大小, 路径); weixin.dll 为微信 4.x 主模块"""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MODULEENTRY32W)]
    k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MODULEENTRY32W)]
    snap = k32.CreateToolhelp32Snapshot(8 | 16, pid)
    if not snap or snap == -1 or snap == (1 << 64) - 1:
        return None
    try:
        me = _MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(me)
        ok = k32.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            if me.szModule and me.szModule.lower() == 'weixin.dll':
                return (me.modBaseAddr or 0, me.modBaseSize, me.szExePath)
            me.dwSize = ctypes.sizeof(me)
            ok = k32.Module32NextW(snap, ctypes.byref(me))
    finally:
        k32.CloseHandle(snap)
    return None

def _decrypt_page(enc_key: bytes, page: bytes, pgno: int) -> bytes:
    iv = page[PAGE_SZ - RESERVE_SZ:PAGE_SZ - RESERVE_SZ + 16]
    if pgno == 1:
        if len(enc_key) == 48:
            enc = page[16:PAGE_SZ - RESERVE_SZ]
            return page[:16] + _aes_cbc_decrypt(enc_key[:32], iv, enc) + b'\x00' * RESERVE_SZ
        enc = page[16:PAGE_SZ - RESERVE_SZ]
        return b'SQLite format 3\x00' + _aes_cbc_decrypt(enc_key, iv, enc) + b'\x00' * RESERVE_SZ
    enc = page[:PAGE_SZ - RESERVE_SZ]
    return _aes_cbc_decrypt(enc_key[:32] if len(enc_key) == 48 else enc_key, iv, enc) + b'\x00' * RESERVE_SZ
