"""Busca limitada somente leitura por identificadores conhecidos no processo PKA.
Somente nomes da lista fixa e enderecos sao salvos; nenhum dump e produzido.
"""
import ctypes as c
from ctypes import wintypes as w
import json,time,datetime,re,struct
from pathlib import Path
import auxiliar_leitura as a
import diagnostico_acesso as d
ROOT=Path(__file__).resolve().parent
class MBI(c.Structure):
 _fields_=[('base',c.c_void_p),('allocation',c.c_void_p),('allocation_protect',w.DWORD),('partition',w.WORD),('size',c.c_size_t),('state',w.DWORD),('protect',w.DWORD),('type',w.DWORD)]
d.k.VirtualQueryEx.argtypes=[w.HANDLE,c.c_void_p,c.POINTER(MBI),c.c_size_t]
d.k.VirtualQueryEx.restype=c.c_size_t
TOKENS=a.NAMES+['.?AVGame@@','.?AVCreature@@','.?AVLocalPlayer@@','.?AVMap@@','Pidgey','Consulti']

def inspect_runtime(pid,name):
 h=d.k.OpenProcess(0x410,False,pid)
 if not h:return {'pid':pid,'error':c.get_last_error()}
 try:
  mods=a.modules(h);main=mods[0];sections=a.sections(h,main)
  stats=[]
  for sec in sections:
   try:
    data=a.read(h,main['base']+sec['rva'],min(65536,sec['size']))
    stats.append({'section':sec['name'],'sample_bytes':len(data),'nonzero_bytes':sum(x!=0 for x in data),'distinct_bytes':len(set(data))})
   except OSError as error:stats.append({'section':sec['name'],'error':str(error)})
  regions=[];cursor=0;limit=0x7fffffffffff
  while cursor<limit and len(regions)<100000:
   info=MBI()
   if not d.k.VirtualQueryEx(h,cursor,c.byref(info),c.sizeof(info)):break
   base=info.base or 0;size=info.size
   if size==0 or base+size<=cursor:break
   if info.state==0x1000 and not info.protect&0x100 and (info.protect&0xff) in (2,4,8,0x20,0x40,0x80):
    regions.append({'base':base,'size':size,'type':hex(info.type),'protect':hex(info.protect),'in_main_image':main['base']<=base<main['base']+main['size']})
   cursor=base+size
  # Prioritize main image, then small private executable/readwrite regions.
  candidates=sorted(regions,key=lambda r:(not r['in_main_image'], int(r['type'],16)!=0x20000, r['size']))
  matches=[];scanned=0;errors=0;max_bytes=384*1024*1024
  patterns=[(token,encoding,token.encode(encoding)) for token in TOKENS for encoding in ('ascii','utf-16le')]
  started=time.monotonic()
  for region in candidates:
   if not region['in_main_image'] and int(region['type'],16)!=0x20000:continue
   if scanned>=max_bytes or time.monotonic()-started>90:break
   pos=0;tail=b''
   while pos<region['size'] and scanned<max_bytes:
    if time.monotonic()-started>90:break
    count=min(1024*1024,region['size']-pos,max_bytes-scanned)
    try:data=a.read(h,region['base']+pos,count)
    except OSError:errors+=1;pos+=count;tail=b'';continue
    blob=tail+data;origin=region['base']+pos-len(tail)
    for token,encoding,needle in patterns:
     seek=0
     while True:
      at=blob.find(needle,seek)
      if at<0:break
      addr=origin+at
      if sum(m['token']==token and m['encoding']==encoding for m in matches)<32 and not any(m['address']==addr and m['token']==token for m in matches):
       matches.append({'token':token,'encoding':encoding,'address':addr,'in_main_image':main['base']<=addr<main['base']+main['size'],'rva':addr-main['base'] if main['base']<=addr<main['base']+main['size'] else None,'region_type':region['type']})
      seek=at+len(needle)
    tail=blob[-128:];pos+=count;scanned+=len(data)
  return {'pid':pid,'name':name,'main':main,'section_samples':stats,'readable_regions':len(regions),'scanned_bytes':scanned,'read_errors':errors,'scan_seconds':round(time.monotonic()-started,2),'matches':matches,'note':'Ocorrencias sao pistas; nao sao offsets validados de objetos.'}
 finally:d.k.CloseHandle(h)

def main():
 if not c.windll.shell32.IsUserAnAdmin():raise RuntimeError('Abra Iniciar-auxiliar.cmd como administrador.')
 print('Diagnostico v2 somente leitura. Aguarde a busca inicial (ate 90 s por cliente).',flush=True)
 cache={};deadline=time.monotonic()+1800;stop=ROOT/'parar-auxiliar.flag';out=ROOT/'runtime-v2.json'
 while time.monotonic()<deadline and not stop.exists():
  results=[]
  for pid,name in a.game_processes():
   if pid not in cache:
    print('Inspecionando',name,pid,flush=True)
    try:cache[pid]=inspect_runtime(pid,name)
    except Exception as error:cache[pid]={'pid':pid,'error':str(error)}
   results.append(cache[pid])
   temp=out.with_suffix('.tmp');temp.write_text(json.dumps({'version':2,'status':'running','admin':True,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processes':results},indent=2),encoding='utf-8');temp.replace(out)
  time.sleep(2)
 print('Auxiliar encerrado.',flush=True)

if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:pass
 except Exception as error:print('Falha:',error,flush=True);raise SystemExit(1)
