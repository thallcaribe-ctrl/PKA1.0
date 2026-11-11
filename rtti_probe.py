"""Resolve RTTI MSVC x64 e procura instancias; somente leitura."""
import ctypes as c
import struct,json,time,datetime,sys
from pathlib import Path
import auxiliar_leitura as a
import diagnostico_acesso as d
import runtime_probe as r
ROOT=Path(__file__).resolve().parent
TYPES=['.?AVLocalPlayer@@','.?AVCreature@@']

def locate_tables(blobs,base,image_size,descriptors):
 tables=[]
 for token,td in descriptors:
  needle=struct.pack('<I',td-base)
  for rva,blob in blobs:
   start=0
   while True:
    at=blob.find(needle,start)
    if at<0:break
    start=at+1;coloff=at-12
    if coloff<0 or coloff+24>len(blob):continue
    signature,offset,cd,typ,cls,selfrva=struct.unpack_from('<IIIIII',blob,coloff)
    colrva=rva+coloff
    if signature!=1 or selfrva!=colrva or typ!=td-base or not 0<cls<image_size or offset>4096:continue
    coladdr=base+colrva
    for vrva,vblob in blobs:
     seek=0;pointer=struct.pack('<Q',coladdr)
     while True:
      ref=vblob.find(pointer,seek)
      if ref<0:break
      seek=ref+1
      if ref+16>len(vblob):continue
      function=struct.unpack_from('<Q',vblob,ref+8)[0]
      if base<=function<base+image_size:
       tables.append({'type':token,'descriptor':td,'col':coladdr,'offset':offset,'vtable':base+vrva+ref+8,'first_function':function})
 return list({item['vtable']:item for item in tables}.values())

def regions(h):
 cursor=0;result=[]
 while cursor<0x7fffffffffff and len(result)<100000:
  info=r.MBI()
  if not d.k.VirtualQueryEx(h,cursor,c.byref(info),c.sizeof(info)):break
  address=info.base or 0
  if not info.size or address+info.size<=cursor:break
  if info.state==0x1000 and not info.protect&0x100 and (info.protect&0xff) in (4,8,0x40,0x80):
   result.append((address,info.size,info.type))
  cursor=address+info.size
 return result

def discover(pid,name,clues):
 h=d.k.OpenProcess(0x410,False,pid)
 if not h:return {'pid':pid,'error':c.get_last_error()}
 try:
  main=a.modules(h)[0];sects=a.sections(h,main);blobs=[]
  for sec in sects:
   if sec['name'] not in ('.rdata','_RDATA','.data'):continue
   try:blobs.append((sec['rva'],a.read(h,main['base']+sec['rva'],sec['size'])))
   except OSError:pass
  descriptors=[]
  for match in clues:
   if match['token'] in TYPES and match['encoding']=='ascii' and match['in_main_image']:
    descriptors.append((match['token'],match['address']-16))
  tables=locate_tables(blobs,main['base'],main['size'],descriptors)
  del blobs
  objects=[];scanned=0;start=time.monotonic();budget=1024*1024*1024
  if tables:
   needles=[(table,struct.pack('<Q',table['vtable'])) for table in tables if table['offset']==0]
   for address,size,kind in sorted(regions(h),key=lambda x:(x[2]!=0x20000,x[1])):
    pos=0;tail=b''
    while pos<size and scanned<budget and time.monotonic()-start<120:
     count=min(1024*1024,size-pos,budget-scanned)
     try:data=a.read(h,address+pos,count)
     except OSError:pos+=count;tail=b'';continue
     blob=tail+data;origin=address+pos-len(tail)
     for table,needle in needles:
      seek=0
      while True:
       at=blob.find(needle,seek)
       if at<0:break
       seek=at+1;obj=origin+at
       if obj%8 or any(x['address']==obj for x in objects):continue
       if sum(x['type']==table['type'] for x in objects)>=64:continue
       objects.append({'type':table['type'],'address':obj,'vtable':table['vtable']})
     tail=blob[-7:];pos+=count;scanned+=len(data)
    if scanned>=budget or time.monotonic()-start>=120:break
  return {'pid':pid,'name':name,'main':main,'type_descriptors':descriptors,'tables':tables,'objects':objects,'scanned_bytes':scanned,'scan_seconds':round(time.monotonic()-start,2)}
 finally:d.k.CloseHandle(h)

def sample(discovery):
 h=d.k.OpenProcess(0x410,False,discovery['pid'])
 if not h:return []
 result=[]
 try:
  for obj in discovery.get('objects',[]):
   try:
    data=a.read(h,obj['address'],512)
    if len(data)<512 or struct.unpack_from('<Q',data)[0]!=obj['vtable']:continue
    # Numeric candidates only; no strings or full object dump.
    positions=[]
    for off in range(8,256,2):
     x,y,z=struct.unpack_from('<HHB',data,off)
     if 50<=x<=65000 and 50<=y<=65000 and z<=15:
      positions.append({'offset':off,'x':x,'y':y,'z':z})
    positions32=[]
    for off in range(8,384,4):
     x,y,z=struct.unpack_from('<III',data,off)
     if 1<=x<=65535 and 1<=y<=65535 and z<=15:
      positions32.append({'offset':off,'x':x,'y':y,'z':z})
    # Only numeric fields in the known Creature/LocalPlayer object; no arbitrary memory requests.
    scalars=[{'offset':off,'u32':struct.unpack_from('<I',data,off)[0]} for off in range(8,384,4)]
    public_name_offsets=[]
    for token in (b'Consulti',b'Pidgey',b'Charmander'):
     at=data.find(token+b'\0')
     if at>=0:public_name_offsets.append({'name':token.decode('ascii'),'offset':at})
    result.append({'type':obj['type'],'address':obj['address'],'positions16_unvalidated':positions,'positions32_unvalidated':positions32,'numeric_fields':scalars,'known_public_name_offsets':public_name_offsets})
   except OSError:continue
 finally:d.k.CloseHandle(h)
 return result

def selftest():
 base=0x140000000;blob=bytearray(4096);td=base+0x800;col=0x100;vref=0x200
 struct.pack_into('<IIIIII',blob,col,1,0,0,0x800,0x900,col)
 struct.pack_into('<QQ',blob,vref,base+col,base+0x300)
 tables=locate_tables([(0,bytes(blob))],base,len(blob),[('test',td)])
 assert len(tables)==1 and tables[0]['vtable']==base+vref+8
 struct.pack_into('<I',blob,col+20,123)
 assert not locate_tables([(0,bytes(blob))],base,len(blob),[('test',td)])
 print('PASS: RTTI x64 valido reconhecido; falso COL rejeitado.')

def main():
 if '--self-test' in sys.argv:selftest();return
 if not c.windll.shell32.IsUserAnAdmin():raise RuntimeError('Execute como administrador')
 out=ROOT/'runtime-layout.json'
 prior=ROOT/'runtime-rtti.json'
 results=json.loads(prior.read_text(encoding='utf-8')).get('processes',[]) if prior.exists() else []
 results=[proc for proc in results if 'objects' in proc]
 clues=json.loads((ROOT/'runtime-v2.json').read_text(encoding='utf-8'))
 for proc in ([] if results else clues['processes']):
  print('Resolvendo tipos:',proc['name'],flush=True)
  try:results.append(discover(proc['pid'],proc['name'],proc.get('matches',[])))
  except Exception as error:results.append({'pid':proc['pid'],'error':str(error)})
  out.write_text(json.dumps({'version':4,'status':'discovering','processes':results},indent=2),encoding='utf-8')
 deadline=time.monotonic()+1800
 while time.monotonic()<deadline and not (ROOT/'parar-auxiliar.flag').exists():
  live=[{'pid':proc['pid'],'object_samples':sample(proc)} for proc in results if 'objects'in proc]
  temp=out.with_suffix('.tmp');temp.write_text(json.dumps({'version':4,'status':'monitoring','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'processes':results,'live':live},indent=2),encoding='utf-8');temp.replace(out)
  time.sleep(1)

if __name__=='__main__':
 try:main()
 except KeyboardInterrupt:pass
 except Exception as error:print('Falha:',error,flush=True);raise SystemExit(1)
