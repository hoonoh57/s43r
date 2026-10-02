"""DPAPI-encrypted credentials; no plaintext fallback."""
import ctypes,json,os
from pathlib import Path
from ctypes import wintypes
class Blob(ctypes.Structure): _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]
def crypt(data,decode=False):
    if os.name!='nt':raise RuntimeError('Windows DPAPI 저장소가 필요합니다.')
    buf=ctypes.create_string_buffer(data);src=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_byte)));out=Blob();dll=ctypes.WinDLL('crypt32',use_last_error=True)
    if decode:ok=dll.CryptUnprotectData(ctypes.byref(src),None,None,None,None,1,ctypes.byref(out))
    else:ok=dll.CryptProtectData(ctypes.byref(src),'S43R Trader',None,None,None,1,ctypes.byref(out))
    if not ok:raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(out.pbData,out.cbData)
    finally:
        k=ctypes.WinDLL('kernel32');k.LocalFree.argtypes=[ctypes.c_void_p];k.LocalFree(out.pbData)
class Vault:
    def __init__(self,folder):self.folder=Path(folder)
    def path(self,mode):
        if mode not in ('mock','live'):raise ValueError('환경 오류')
        return self.folder/f'{mode}.dpapi'
    def save(self,mode,key,secret):self.path(mode).write_bytes(crypt(json.dumps({'appkey':key,'secretkey':secret}).encode()))
    def load(self,mode):
        p=self.path(mode);return json.loads(crypt(p.read_bytes(),True)) if p.exists() else None
    def exists(self,mode):return self.path(mode).exists()
