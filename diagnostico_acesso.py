"""Verifica acesso somente leitura ao PokeAlliance; nao modifica o jogo."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import json,datetime
k=c.WinDLL('kernel32',use_last_error=True)
p=c.WinDLL('psapi',use_last_error=True)
class Entry(c.Structure):
 _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('name',w.WCHAR*260)]
k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,c.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.CloseHandle.argtypes=[w.HANDLE]
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
p.EnumProcessModulesEx.argtypes=[w.HANDLE,c.POINTER(w.HMODULE),w.DWORD,c.POINTER(w.DWORD),w.DWORD]
k.ReadProcessMemory.argtypes=[w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
def probe(pid,name):
 result={'pid':pid,'name':name}
 for label,access in [('query',0x1000),('read',0x410)]:
  c.set_last_error(0);h=k.OpenProcess(access,False,pid)
  result[label]={'ok':bool(h),'winerror':c.get_last_error() if not h else 0}
  if not h:continue
  try:
   if label=='query':
    buf=c.create_unicode_buffer(32768);length=w.DWORD(len(buf))
    if k.QueryFullProcessImageNameW(h,0,buf,c.byref(length)):result['path']=buf.value
   else:
    modules=(w.HMODULE*1024)();needed=w.DWORD()
    if p.EnumProcessModulesEx(h,modules,c.sizeof(modules),c.byref(needed),3) and needed.value:
     result['module_count']=needed.value//c.sizeof(w.HMODULE)
     buf=c.create_string_buffer(64);read=c.c_size_t()
     if k.ReadProcessMemory(h,modules[0],buf,64,c.byref(read)):result['header']={'bytes':read.value,'mz':buf.raw[:2]==b'MZ'}
     else:result['read_error']=c.get_last_error()
    else:result['module_error']=c.get_last_error()
  finally:k.CloseHandle(h)
 return result

def main():
 results=[];snap=k.CreateToolhelp32Snapshot(2,0)
 if snap==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
 try:
  entry=Entry();entry.size=c.sizeof(entry);ok=k.Process32FirstW(snap,c.byref(entry))
  while ok:
   if entry.name.lower() in ('pokealliance_dx.exe','pokealliance_gl.exe'):results.append(probe(entry.pid,entry.name))
   ok=k.Process32NextW(snap,c.byref(entry))
 finally:k.CloseHandle(snap)
 report={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'admin':bool(c.windll.shell32.IsUserAnAdmin()),'processes':results}
 dest=Path(__file__).with_name('diagnostico-acesso.json');dest.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
