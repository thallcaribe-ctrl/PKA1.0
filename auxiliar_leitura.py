"""Inspecao externa somente leitura: PE, modulos e nomes fixos de APIs.
Nao varre heap, nao salva dumps, nao escreve no processo e nao executa codigo nele.
"""
import ctypes as c
from ctypes import wintypes as w
import datetime,json,struct,time,sys
from pathlib import Path
import diagnostico_acesso as d
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'acesso-runtime.json'
STOP=ROOT/'parar-auxiliar.flag'
NAMES=['getPosition','getLocalPlayer','getSpectators','getSpectatorsInRange','getHealthPercent','getAttackingCreature','autoWalk','g_game','g_map','g_modules','g_lua','lua_gettop','lua_pcall','lua_pcallk','lua_getfield','lua_settop']
class MODULEINFO(c.Structure):
 _fields_=[('base',c.c_void_p),('size',w.DWORD),('entry',c.c_void_p)]
d.p.GetModuleInformation.argtypes=[w.HANDLE,w.HMODULE,c.POINTER(MODULEINFO),w.DWORD]
d.p.GetModuleBaseNameW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
d.k.GetCurrentProcessId.restype=w.DWORD

def read(h,address,size):
 if size<0 or size>32*1024*1024:raise ValueError('Limite de leitura excedido')
 buf=c.create_string_buffer(size);got=c.c_size_t()
 ok=d.k.ReadProcessMemory(h,address,buf,size,c.byref(got))
 if not ok and not got.value:raise c.WinError(c.get_last_error())
 return buf.raw[:got.value]

def modules(h):
 array=(w.HMODULE*2048)();needed=w.DWORD()
 if not d.p.EnumProcessModulesEx(h,array,c.sizeof(array),c.byref(needed),3):raise c.WinError(c.get_last_error())
 if needed.value>c.sizeof(array):raise ValueError('Lista de modulos excedeu limite')
 result=[]
 for mod in array[:needed.value//c.sizeof(w.HMODULE)]:
  info=MODULEINFO();name=c.create_unicode_buffer(512)
  if d.p.GetModuleInformation(h,mod,c.byref(info),c.sizeof(info)):
   d.p.GetModuleBaseNameW(h,mod,name,len(name))
   result.append({'name':name.value,'base':info.base,'size':info.size})
 return result

def sections(h,mod):
 base=mod['base'];header=read(h,base,min(4096,mod['size']))
 if header[:2]!=b'MZ':raise ValueError('Assinatura MZ ausente')
 pe=struct.unpack_from('<I',header,60)[0]
 if pe>1024*1024:raise ValueError('Offset PE invalido')
 if pe+24>len(header):header=read(h,base,pe+24)
 if header[pe:pe+4]!=b'PE\0\0':raise ValueError('Assinatura PE ausente')
 count=struct.unpack_from('<H',header,pe+6)[0];opt=struct.unpack_from('<H',header,pe+20)[0]
 if count>96:raise ValueError('Numero de secoes invalido')
 end=pe+24+opt+40*count
 if end>len(header):header=read(h,base,end)
 result=[]
 for i in range(count):
  off=pe+24+opt+i*40
  name=header[off:off+8].rstrip(b'\0').decode('ascii',errors='replace')
  size,rva=struct.unpack_from('<II',header,off+8)
  flags=struct.unpack_from('<I',header,off+36)[0]
  if rva>mod['size'] or size>mod['size']-rva:continue
  result.append({'name':name,'rva':rva,'size':size,'flags':hex(flags),'executable':bool(flags&0x20000000),'writable':bool(flags&0x80000000)})
 return result

def inspect(pid,name):
 h=d.k.OpenProcess(0x410,False,pid)
 if not h:return {'pid':pid,'name':name,'error':c.get_last_error()}
 try:
  mods=modules(h)
  if not mods:raise ValueError('Sem modulos')
  main=mods[0];sects=sections(h,main);found=[];errors=[]
  # Only conventional, non-writable PE string sections. Never scan heap/private data.
  for sec in sects:
   if sec['name'] not in ('.rdata','_RDATA','.rodata') or sec['writable']:continue
   if sec['size']>16*1024*1024:continue
   try:blob=read(h,main['base']+sec['rva'],sec['size'])
   except OSError as e:errors.append({'section':sec['name'],'error':str(e)});continue
   for api in NAMES:
    token=api.encode('ascii')+b'\0';pos=0;hits=[]
    while len(hits)<16:
     pos=blob.find(token,pos)
     if pos<0:break
     if pos==0 or blob[pos-1]==0:hits.append(sec['rva']+pos)
     pos+=len(token)
    if hits:found.append({'api':api,'section':sec['name'],'rvas':hits})
  return {'pid':pid,'name':name,'main_module':main,'modules':mods,'sections':sects,'api_name_candidates':found,'errors':errors,'note':'Nomes encontrados nao comprovam enderecos de funcoes nem layouts de objetos.'}
 finally:d.k.CloseHandle(h)

def game_processes():
 snap=d.k.CreateToolhelp32Snapshot(2,0)
 if snap==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
 try:
  e=d.Entry();e.size=c.sizeof(e);ok=d.k.Process32FirstW(snap,c.byref(e))
  while ok:
   if e.name.lower() in ('pokealliance_dx.exe','pokealliance_gl.exe'):yield e.pid,e.name
   ok=d.k.Process32NextW(snap,c.byref(e))
 finally:d.k.CloseHandle(snap)

def save(value):
 temp=OUT.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');temp.replace(OUT)

def main():
 if '--self-test' in sys.argv:
  result=inspect(d.k.GetCurrentProcessId(),'self-test')
  assert result.get('sections') and result.get('modules'),result
  print('PASS: leitura PE do proprio auxiliar; jogo nao acessado.');return
 admin=bool(c.windll.shell32.IsUserAnAdmin())
 if not admin:raise RuntimeError('Execute Iniciar-auxiliar.cmd como administrador.')
 print('Auxiliar somente leitura ativo por ate 30 minutos. Ctrl+C encerra.',flush=True)
 print('Para parar por arquivo, crie parar-auxiliar.flag nesta pasta.',flush=True)
 deadline=time.monotonic()+1800;cache={}
 while time.monotonic()<deadline and not STOP.exists():
  results=[];active=set()
  for pid,name in game_processes():
   active.add(pid)
   if pid not in cache or 'error' in cache[pid]:
    try:cache[pid]=inspect(pid,name)
    except Exception as error:cache[pid]={'pid':pid,'name':name,'error':str(error)}
   results.append(cache[pid])
  cache={pid:item for pid,item in cache.items() if pid in active}
  save({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'admin':admin,'status':'running','processes':results})
  for _ in range(20):
   if STOP.exists():break
   time.sleep(0.25)
 print('Auxiliar encerrado.',flush=True)
 if OUT.exists():
  result=json.loads(OUT.read_text(encoding='utf-8'));result['status']='stopped';save(result)

if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:print('Interrompido pelo usuario.')
 except Exception as error:print(f'Falha: {error}',flush=True);sys.exit(1)
