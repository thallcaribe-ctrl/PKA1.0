"""Filtro visual de nomes rosa no cliente focado; nao altera memoria."""
import ctypes as c,struct,time
from ctypes import wintypes as w

def pink_pixels(raw):
 return sum(raw[i]>180 and raw[i+1]<80 and raw[i+2]>180 for i in range(0,len(raw)-3,4))

def green_pixels(raw):
 return sum(raw[i]<8 and 175<=raw[i+1]<=205 and raw[i+2]<8 for i in range(0,len(raw)-3,4))

class Labels:
 def __init__(self):self.until=0.;self.blocked={};self.identities={};self.checked={};self.client=None
 def annotate(self,frame,config):
  now=time.monotonic();g=config['grid'];player=frame.get('player')
  client=(frame.get('pid'),frame.get('hwnd'))
  if client!=self.client:self.blocked.clear();self.identities.clear();self.checked.clear();self.until=0.;self.client=client
  active={o['id']:o for o in frame.get('creatures',[])if o.get('active')}
  for ident in list(self.blocked):
   obj=active.get(ident)
   identity=(obj.get('network_id'),obj.get('name'))if obj else None
   if obj and self.identities.get(ident)==identity:self.blocked[ident]=now+3
   elif not obj and self.blocked[ident]>now:continue
   else:self.blocked.pop(ident,None);self.identities.pop(ident,None)
  if not player or not frame.get('focused')or not g['ready']:return
  if now>=self.until:
   self.until=now+.35
   self.sample(frame,g,now)
  self.blocked={ident:deadline for ident,deadline in self.blocked.items()if deadline>now}
  for obj in frame['creatures']:
   if obj['id']in self.blocked:self.identities[obj['id']]=(obj.get('network_id'),obj.get('name'))
   obj['pink_name']=obj['id']in self.blocked
   identity=(obj.get('network_id'),obj.get('name'))
   checked=self.checked.get(obj['id'])
   obj['label_checked']=bool(checked and checked[0]==identity and checked[1]>now)
   obj['attackable']=not obj['pink_name']and(obj.get('creature_type')!=1 or obj['label_checked'])
  self.checked={ident:value for ident,value in self.checked.items()if value[1]>now}
 def record_sample(self,ident,identity,raw,now):
  pink=pink_pixels(raw)>=6;green=green_pixels(raw)>=20
  if pink:
   self.blocked[ident]=now+3;self.identities[ident]=identity
  elif green:
   self.blocked.pop(ident,None);self.identities.pop(ident,None)
  self.checked[ident]=(identity,now+.7)if pink or green else (identity,now)
 def sample(self,frame,g,now):
  from pathlib import Path
  from helper_debug import capture_isolated
  if not frame.get('focused'):return
  p=frame['player']['position'];regions=[];left,top,right,bottom=g['viewport']
  for obj in frame['creatures']:
   if not obj.get('active')or obj.get('creature_type')!=1:continue
   pos=obj['position'];x=g['center_x']+(pos['x']-p['x'])*g['tile_x'];y=g['center_y']+(pos['y']-p['y'])*g['tile_y']
   if pos['z']!=p['z']or not(left<=x-g['tile_x']and x+g['tile_x']<=right and top<=y-g['tile_y']*1.5 and y-g['tile_y']*.25<=bottom):continue
   regions.append((obj,round(x-g['tile_x']),round(y-g['tile_y']*1.5),round(x+g['tile_x']),round(y-g['tile_y']*.25)))
  if not regions:return
  path=Path(__file__).resolve().parent/'runtime'/'labels-latest.png'
  try:
   result=capture_isolated(frame['hwnd'],path,'print',timeout=2)
   if (result['width'],result['height'])!=(g['client_width'],g['client_height']):return
   width,height,raw=decode_capture_png(path.read_bytes());stride=width*3+1;stamp=time.monotonic()
   for obj,x1,y1,x2,y2 in regions:
    rgb=b''.join(raw[y*stride+1+x1*3:y*stride+1+x2*3]for y in range(y1,y2))
    rgba=bytearray(len(rgb)//3*4);rgba[0::4]=rgb[0::3];rgba[1::4]=rgb[1::3];rgba[2::4]=rgb[2::3]
    self.record_sample(obj['id'],(obj.get('network_id'),obj.get('name')),rgba,stamp)
   self.until=stamp+.35
  except (OSError,RuntimeError,ValueError,struct.error):return


def decode_capture_png(data):
 import zlib
 if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Captura PNG invalida')
 offset=8;parts=[];width=height=0
 while offset<len(data):
  size=struct.unpack_from('>I',data,offset)[0];kind=data[offset+4:offset+8];chunk=data[offset+8:offset+8+size];offset+=size+12
  if kind==b'IHDR':
   width,height,depth,color,_,_,interlace=struct.unpack('>IIBBBBB',chunk)
   if depth!=8 or color!=2 or interlace:raise ValueError('Formato PNG inesperado')
  elif kind==b'IDAT':parts.append(chunk)
 raw=zlib.decompress(b''.join(parts));stride=width*3+1
 if not width or not height or len(raw)!=stride*height or any(raw[y*stride]!=0 for y in range(height)):raise ValueError('Linhas PNG inesperadas')
 return width,height,raw
