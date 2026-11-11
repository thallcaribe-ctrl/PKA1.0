"""Leitura externa do cliente e entradas com down/delay/up. Sem escrita de memoria."""
import ctypes as c
from ctypes import wintypes as w
import struct,time,re,threading,hashlib,json,collections
from pathlib import Path
import auxiliar_leitura as a
import rtti_probe as r
import teste_enter as e
import pydirectinput as direct
TYPES={'.?AVLocalPlayer@@':'localplayer','.?AVCreature@@':'creature','.?AVMonster@@':'monster','.?AVPlayer@@':'player','.?AVNpc@@':'npc','.?AVPokemon@@':'monster'}

class Reader:
 def __init__(self,config):
  self.config=config;self.discovery=None;self.scan_error=None;self.scanning=False;self.last_scan=0;self.lock=threading.RLock();self.last_objects={};self.retired={};self.last_frame=None;self.expected_hash=None;self.own_id=None;self.own_refresh=None
  from helper_labels import Labels
  self.labels=Labels()
  layout=json.loads((Path(__file__).with_name('client-layout.json')).read_text(encoding='utf-8'))
  self.build_ok=hashlib.sha256(Path(config['game_path']).read_bytes()).hexdigest()==layout['sha256']
 def window(self):
  hwnd=e.find_game(self.config['game_path']);pid=w.DWORD();e.u.GetWindowThreadProcessId(hwnd,c.byref(pid));title=e.title(hwnd)
  return {'hwnd':hwnd,'pid':pid.value,'title':title,'online':' - 'in title,'focused':e.u.GetForegroundWindow()==hwnd}
 def open(self,pid):
  h=a.d.k.OpenProcess(0x410,False,pid)
  if not h:raise c.WinError(c.get_last_error())
  return h
 def read_name(self,h,data):
  length=struct.unpack_from('<Q',data,128)[0];capacity=struct.unpack_from('<Q',data,136)[0]
  if not 0<length<=80 or capacity<length or capacity>4096:return None
  if capacity<=15:raw=data[112:112+length]
  else:
   pointer=struct.unpack_from('<Q',data,112)[0]
   if not 0x10000<=pointer<0x7fffffffffff:return None
   raw=a.read(h,pointer,length)
  try:name=raw.decode('utf-8')
  except UnicodeDecodeError:return None
  if any(ord(ch)<32 for ch in name):return None
  return name
 def object(self,h,address,table):
  data=a.read(h,address,752)
  if len(data)!=752 or struct.unpack_from('<Q',data)[0]!=table['vtable']:return None
  name=self.read_name(h,data)
  if not name:return None
  x,y=struct.unpack_from('<II',data,32);z=data[40];hp=data[176]
  if hp>100:return None
  valid=0<=x<65535 and 0<=y<65535 and z<=15
  return {'id':address,'vtable':table['vtable'],'network_id':struct.unpack_from('<I',data,76)[0],'creature_type':data[374],'presence_hint':data[624],'removed':bool(data[746]),'name':name,'position':{'x':x,'y':y,'z':z}if valid else None,'hp':hp,'kind':TYPES.get(table['type'],'creature'),'shiny':name.casefold().startswith(('shiny ','shiny-','shiny: ')),'active':valid and not data[746],'death_confirmed':hp==0}
 def find_tree(self,h,main,sections,vtables,local_addresses):
  # MSVC x64 std::map<uint32, shared_ptr<Creature>>: node links 0/8/16, nil 25, value pointer 40.
  # A candidate is accepted only if every node type is known and it contains the identified LocalPlayer.
  for sec in sections:
   if sec['name']!='.data':continue
   blob=a.read(h,main['base']+sec['rva'],sec['size']);deadline=time.monotonic()+15;checks=0
   for offset in range(0,len(blob)-16,8):
    head,count=struct.unpack_from('<QQ',blob,offset)
    if not 1<=count<=4096 or not 0x100000000<=head<0x7fff00000000 or main['base']<=head<main['base']+main['size']:continue
    checks+=1
    if checks>30000 or time.monotonic()>deadline:return None
    try:
     header=a.read(h,head,32)
     if len(header)!=32 or header[25]!=1:continue
     root=struct.unpack_from('<Q',header,8)[0]
     nodes=self.traverse_tree(h,head,root,count,vtables)
     if nodes and local_addresses.intersection(nodes):return {'address':main['base']+sec['rva']+offset,'head':head,'count':count,'objects':nodes}
    except (OSError,ValueError):continue
  return None
 def traverse_tree(self,h,head,root,count,vtables):
  if type(count)is not int or not 0<=count<=4096:raise ValueError('Quantidade de nos invalida')
  if root==head:
   if count:raise ValueError('Arvore vazia com quantidade nao zero')
   return []
  todo=[(root,head)];seen=set();objects=[]
  while todo:
   node,parent=todo.pop()
   if node==head:continue
   if node in seen or len(seen)>=count or not 0x10000<=node<0x7fffffffffff:raise ValueError('Arvore invalida')
   data=a.read(h,node,56)
   if len(data)!=56 or data[25]!=0 or struct.unpack_from('<Q',data,8)[0]!=parent:raise ValueError('No invalido')
   left,right=struct.unpack_from('<Q',data,0)[0],struct.unpack_from('<Q',data,16)[0]
   obj=struct.unpack_from('<Q',data,40)[0]
   if not 0x10000<=obj<0x7fffffffffff:raise ValueError('Ponteiro de criatura invalido')
   raw=a.read(h,obj,8)
   if len(raw)!=8:raise ValueError('Ponteiro de criatura ilegivel')
   vtable=struct.unpack('<Q',raw)[0]
   if vtable not in vtables:raise ValueError('Valor nao e CreaturePtr conhecido')
   seen.add(node);objects.append(obj);todo.extend([(left,node),(right,node)])
  if len(seen)!=count:raise ValueError('Quantidade de nos diverge')
  return objects
 def scan_sync(self,state):
  h=None
  try:
   h=self.open(state['pid'])
   main=a.modules(h)[0];sections=a.sections(h,main);blobs=[];descriptors=[]
   for sec in sections:
    if sec['name']not in ('.data','.rdata','_RDATA'):continue
    data=a.read(h,main['base']+sec['rva'],sec['size']);blobs.append((sec['rva'],data))
    for token in TYPES:
     at=data.find(token.encode('ascii')+b'\0')
     if at>=0:descriptors.append((token,main['base']+sec['rva']+at-16))
   tables=r.locate_tables(blobs,main['base'],main['size'],descriptors);del blobs
   vtables={item['vtable']:item for item in tables if item['offset']==0}
   if not vtables:raise RuntimeError('Tabelas Creature/LocalPlayer nao encontradas nesta versao')
   regex=re.compile(b'|'.join(re.escape(struct.pack('<Q',vtable))for vtable in vtables))
   objects={};scanned=0;deadline=time.monotonic()+90;budget=1024*1024*1024
   for address,size,kind in sorted(r.regions(h),key=lambda item:(item[2]!=0x20000,item[1])):
    if kind!=0x20000:continue
    pos=0;tail=b''
    while pos<size and scanned<budget and time.monotonic()<deadline:
     length=min(1024*1024,size-pos,budget-scanned)
     try:data=a.read(h,address+pos,length)
     except OSError:pos+=length;tail=b'';continue
     chunk=tail+data;origin=address+pos-len(tail)
     for match in regex.finditer(chunk):
      obj=origin+match.start()
      if obj%8 or obj in objects:continue
      table=vtables[struct.unpack('<Q',match.group())[0]]
      try:value=self.object(h,obj,table)
      except (OSError,ValueError,struct.error):continue
      if value and value['position']:objects[obj]=table
     tail=chunk[-7:];pos+=length;scanned+=len(data)
    if scanned>=budget or time.monotonic()>=deadline:break
   local={obj for obj,table in objects.items()if table['type']=='.?AVLocalPlayer@@'}
   tree=self.find_tree(h,main,sections,vtables,local)if local else None
   with self.lock:self.discovery={'pid':state['pid'],'main':main,'tables':vtables,'objects':objects,'tree':tree,'scanned_bytes':scanned};self.scan_error=None;self.last_scan=time.monotonic()
  except Exception as error:self.scan_error=str(error)
  finally:
   if h:a.d.k.CloseHandle(h)
   with self.lock:self.scanning=False
 def scan(self):
  state=self.window()
  if not state['online']:raise RuntimeError('Conecte o personagem para localizar os objetos')
  with self.lock:
   if self.scanning:return
   self.scanning=True
  try:threading.Thread(target=self.scan_sync,args=(state,),daemon=True).start()
  except Exception:
   with self.lock:self.scanning=False
   raise
 def reference_locations(self):
  frame=self.last_frame
  if not frame or not frame.get('player')or not self.discovery:raise RuntimeError('Aguarde a descoberta do jogador')
  h=self.open(frame['pid'])
  try:
   main=self.discovery['main'];items=[frame['player']]+frame.get('creatures',[]);result=[]
   for obj in items:
    needle=struct.pack('<Q',obj['id']);refs=[]
    for sec in a.sections(h,main):
     if sec['name']!='.data':continue
     blob=a.read(h,main['base']+sec['rva'],sec['size']);pos=blob.find(needle)
     while pos>=0:
      if pos%8==0:refs.append(main['base']+sec['rva']+pos)
      pos=blob.find(needle,pos+1)
    result.append({'id':obj['id'],'name':obj['name'],'position':obj['position'],'hp':obj['hp'],'references':refs})
   return result
  finally:a.d.k.CloseHandle(h)
 def begin_own_refresh(self):
  frame=self.last_frame
  if not self.own_id or not frame or not frame.get('player'):return
  self.own_refresh={'old':self.own_id,'before':{o['id']for o in frame.get('creatures',[])},'name':self.config['own_pokemon'].casefold(),'pid':frame['pid'],'player':frame['player']['id'],'deadline':time.monotonic()+5,'lost':False}
 def refresh_own(self,state,player,nearby,now):
  pending=self.own_refresh
  if not pending:
   candidates=[o for o in nearby if o.get('active')and o.get('hp',0)>0 and o.get('creature_type')==3 and o['name'].casefold()==self.config['own_pokemon'].casefold()]
   if len(candidates)==1:self.own_id=candidates[0]['id']
   return False
  if pending['pid']!=state['pid']or pending['player']!=player['id']:
   self.own_refresh=None;self.own_id=None;return False
  if now>pending['deadline']:self.own_refresh=None;return False
  active={o['id']:o for o in nearby if o.get('active')and o.get('hp',0)>0 and o.get('creature_type')==3}
  if pending['old']not in active:pending['lost']=True
  p=player['position']
  candidates=[o for ident,o in active.items()if ident not in pending['before']and o['name'].casefold()==pending['name']and o['position']['z']==p['z']and max(abs(o['position']['x']-p['x']),abs(o['position']['y']-p['y']))<=1]
  if pending['lost']and len(candidates)==1:self.own_id=candidates[0]['id'];self.own_refresh=None;return False
  if pending['lost']and pending['old']in active and active[pending['old']]['name'].casefold()==pending['name']:self.own_id=pending['old'];self.own_refresh=None;return False
  return True
 def removed_deaths(self,h,active,tables,now):
  # Re-read only recently observed objects, bounded to two seconds after removal.
  for address,previous in self.last_objects.items():
   if address not in active and previous.get('active')and previous.get('hp',0)>0:
    self.retired.setdefault(address,(previous,now+2))
  deaths=[]
  for address,(previous,deadline)in list(self.retired.items()):
   if now>deadline or address in active:self.retired.pop(address,None);continue
   table=tables.get(previous.get('vtable'))
   if not table:self.retired.pop(address,None);continue
   try:value=self.object(h,address,table)
   except (OSError,ValueError,struct.error):value=None
   if not value or value['name']!=previous['name']or value.get('network_id')!=previous.get('network_id'):
    self.retired.pop(address,None);continue
   if value['hp']==0:
    deaths.append({**value,'position':previous['position'],'active':False,'death_confirmed':True})
    self.retired.pop(address,None)
  return deaths
 def snapshot(self):
  stamp=time.monotonic()
  try:state=self.window()
  except Exception as error:return {'online':False,'fresh':False,'focused':False,'error':str(error),'creatures':[]}
  frame={**state,'fresh':True,'observed_monotonic':stamp,'player':None,'creatures':[],'capabilities':{'position':False,'creatures':False,'health':False},'scan_error':self.scan_error,'scanning':self.scanning}
  if not self.build_ok:frame['scan_error']='Executavel mudou; layout precisa de nova validacao';frame['fresh']=False;return frame
  if not state['online']:
   with self.lock:self.discovery=None
   self.last_objects={};self.retired={};self.own_id=None;self.own_refresh=None;self.last_frame=None;return frame
  with self.lock:discovery=self.discovery
  if not discovery or discovery['pid']!=state['pid']:
   if discovery:
    with self.lock:self.discovery=None
    self.last_objects={};self.retired={};self.own_id=None;self.own_refresh=None;self.last_frame=None
   return frame
  h=self.open(state['pid'])
  try:
   objects=dict(discovery['objects']);tree=discovery['tree'];authoritative=False
   if tree:
    try:
     layout=a.read(h,tree['address'],16);head,count=struct.unpack('<QQ',layout)
     header=a.read(h,head,32);root=struct.unpack_from('<Q',header,8)[0]
     active=self.traverse_tree(h,head,root,count,discovery['tables']);objects={addr:None for addr in active};authoritative=True
    except (OSError,ValueError,struct.error):authoritative=False
   samples=[]
   for address,table in objects.items():
    try:
     if table is None:table=discovery['tables'].get(struct.unpack('<Q',a.read(h,address,8))[0])
     if not table:continue
     value=self.object(h,address,table)
     if not value:continue
     previous=self.last_objects.get(address)
     if value['position']is None and value['hp']==0 and previous and previous['name']==value['name']:value['position']=previous['position'];value['active']=False
     if value['position']is None:continue
     value['active']=value['active']and authoritative;samples.append(value)
    except (OSError,ValueError,struct.error):continue
   if authoritative:samples.extend(self.removed_deaths(h,set(objects),discovery['tables'],stamp))
   else:self.retired={}
   expected=state['title'].partition(' - ')[2]
   players=[obj for obj in samples if obj['kind']=='localplayer'and obj['name']==expected]
   if len(players)==1:
    frame['player']=players[0];frame['capabilities']['position']=True
    nearby=[obj for obj in samples if obj['id']!=players[0]['id']and obj['position']['z']==players[0]['position']['z']and max(abs(obj['position']['x']-players[0]['position']['x']),abs(obj['position']['y']-players[0]['position']['y']))<=16]
    frame['own_refresh_pending']=self.refresh_own(state,players[0],nearby,stamp)
    own=self.config['own_pokemon'].casefold()
    for obj in nearby:obj['own_confirmed']=obj.get('creature_type')==3 and obj['id']==self.own_id and obj['name'].casefold()==own and(obj['active']or obj['hp']==0)
    frame['creatures']=nearby;frame['capabilities']['creatures']=authoritative;frame['capabilities']['health']=bool(self.config['validation']['health'] and self.own_id and any(obj.get('own_confirmed')for obj in nearby))
   self.labels.annotate(frame,self.config)
   self.last_objects={obj['id']:obj for obj in samples if obj.get('position')and obj['hp']>0};self.last_frame=frame;return frame
  finally:a.d.k.CloseHandle(h)

class Input:
 def __init__(self,reader,config):self.reader=reader;self.config=config;self.held=set();self.events=collections.deque(maxlen=100)
 def activate(self,maximize=False):
  state=self.reader.window()
  if maximize or e.u.IsIconic(state['hwnd']):e.u.ShowWindow(state['hwnd'],3 if maximize else 9)
  e.u.SetForegroundWindow(state['hwnd']);time.sleep(.2)
  if e.u.GetForegroundWindow()!=state['hwnd']:raise RuntimeError('Windows nao concedeu foco ao jogo; nenhuma tecla foi enviada')
  return {'focused':True,'online':state['online']}
 def focus(self):
  state=self.reader.window()
  if not state['online']:raise RuntimeError('Personagem desconectado')
  if not state['focused']:raise RuntimeError('Jogo sem foco; devolva o foco antes de iniciar')
  return state
 def key(self,key,hold_ms):
  from helper_settings import KEYS
  if key not in KEYS or key=='f12':raise ValueError('Tecla invalida ou reservada para emergencia')
  self.focus()
  if key==self.config['keys']['revive']:self.reader.begin_own_refresh()
  direct.keyDown(key);self.held.add(key);self.events.append({'at':time.monotonic(),'event':'down','key':key})
  try:time.sleep(hold_ms/1000)
  finally:direct.keyUp(key);self.held.discard(key);self.events.append({'at':time.monotonic(),'event':'up','key':key})
 def walk(self,direction,hold_ms):
  if direction not in ('up','down','left','right'):raise ValueError('Direcao invalida')
  self.key(direction,hold_ms)
 def tile(self,position,config):
  state=self.focus();g=config['grid'];frame=self.reader.last_frame
  if not g['ready']or not frame or not frame.get('player'):raise RuntimeError('Grade ou jogador nao calibrados')
  age=time.monotonic()-frame.get('observed_monotonic',0)
  if not 0<=age<=1.5 or frame.get('pid')!=state['pid']or frame.get('hwnd')!=state['hwnd']:raise RuntimeError('Estado de tiles desatualizado ou cliente mudou')
  rect=w.RECT();e.u.GetClientRect(state['hwnd'],c.byref(rect))
  if (rect.right,rect.bottom)!=(g['client_width'],g['client_height']):raise RuntimeError('Tamanho da janela mudou; calibre novamente')
  p=frame['player']['position']
  if p['z']!=position['z']:raise RuntimeError('Tile em outro andar')
  x=round(g['center_x']+(position['x']-p['x'])*g['tile_x']);y=round(g['center_y']+(position['y']-p['y'])*g['tile_y'])
  left,top,right,bottom=g['viewport']
  if not(left<=x<right and top<=y<bottom):raise RuntimeError('Tile fora da area calibrada')
  point=w.POINT(x,y)
  if not e.u.ClientToScreen(state['hwnd'],c.byref(point)):raise RuntimeError('Nao foi possivel localizar o tile na tela')
  return point
 def click_tile(self,position,config,button):
  self.click_point(self.tile(position,config),config['timing'],button)
 def click_client(self,x,y,width,height,button='left',modifiers=None):
  state=self.focus();rect=w.RECT()
  if not e.u.GetClientRect(state['hwnd'],c.byref(rect))or (rect.right,rect.bottom)!=(width,height):raise RuntimeError('Janela mudou apos captura')
  if type(x)is not int or type(y)is not int or not(0<=x<width and 0<=y<height)or button not in ('left','right','move'):raise ValueError('Clique fora da area cliente ou botao invalido')
  point=w.POINT(x,y)
  if not e.u.ClientToScreen(state['hwnd'],c.byref(point)):raise RuntimeError('Falha ao localizar ponto')
  if button=='move':self.move_point(point,self.config['timing']);return
  modifiers=modifiers or []
  if not isinstance(modifiers,list)or len(modifiers)>2 or any(k not in ('ctrl','shift')for k in modifiers):raise ValueError('Modificador de clique invalido')
  try:
   for key in modifiers:direct.keyDown(key);self.held.add(key)
   self.click_point(point,self.config['timing'],button)
  finally:
   for key in reversed(modifiers):direct.keyUp(key);self.held.discard(key)
 def drag_client(self,x,y,end_x,end_y,width,height):
  state=self.focus();rect=w.RECT()
  if not e.u.GetClientRect(state['hwnd'],c.byref(rect))or (rect.right,rect.bottom)!=(width,height):raise RuntimeError('Janela mudou apos captura')
  if any(type(v)is not int for v in (x,y,end_x,end_y))or not(0<=x<width and 0<=end_x<width and 0<=y<height and 0<=end_y<height):raise ValueError('Arraste fora da janela')
  start=w.POINT(x,y);end=w.POINT(end_x,end_y)
  if not e.u.ClientToScreen(state['hwnd'],c.byref(start))or not e.u.ClientToScreen(state['hwnd'],c.byref(end)):raise RuntimeError('Origem do arraste indisponivel')
  direct.moveTo(start.x,start.y);time.sleep(.1);self.focus();direct.mouseDown(button='left')
  try:
   time.sleep(.2)
   for i in range(1,21):self.focus();direct.moveTo(round(start.x+(end.x-start.x)*i/20),round(start.y+(end.y-start.y)*i/20));time.sleep(.02)
   time.sleep(.1)
  finally:direct.mouseUp(button='left')
 def move_point(self,point,timing):
  start=direct.position()
  for index in range(1,21):
   self.focus();t=index/20;s=t*t*(3-2*t)
   direct.moveTo(round(start[0]+(point.x-start[0])*s),round(start[1]+(point.y-start[1])*s));time.sleep(timing['move_ms']/20000)
  time.sleep(timing['settle_ms']/1000);self.focus()
 def click_point(self,point,timing,button):
  self.move_point(point,timing);self.press_mouse(timing,button)
 def press_mouse(self,timing,button):
  direct.mouseDown(button=button);self.events.append({'at':time.monotonic(),'event':'mouse_down','key':button})
  try:time.sleep(timing['mouse_hold_ms']/1000)
  finally:direct.mouseUp(button=button);self.events.append({'at':time.monotonic(),'event':'mouse_up','key':button})
 def select(self,position,config,ident=None):
  if ident is None:self.click_tile(position,config,'right');return
  self.move_point(self.tile(position,config),config['timing'])
  self.reader.labels.until=0. # Never reuse a pre-movement label sample for selection.
  frame=self.reader.snapshot();target=next((o for o in frame.get('creatures',[])if o['id']==ident and o.get('active')and o.get('hp',0)>0),None)
  if not target or target.get('creature_type',1)!=1 or target.get('own_confirmed'):raise RuntimeError('Alvo mudou antes do clique; selecao cancelada')
  if target.get('pink_name'):raise RuntimeError('Nome rosa: criatura nao atacavel; clique cancelado')
  if target.get('attackable')is False:raise RuntimeError('Nome fora da area de leitura visual; selecao cancelada')
  point=self.tile(target['position'],config);self.focus();direct.moveTo(point.x,point.y);self.press_mouse(config['timing'],'right')
 def approach(self,position,config):self.click_tile(position,config,'left')
 def capture(self,position,key,config):
  if config['catch']['mode']=='smart_use':
   self.move_point(self.tile(position,config),config['timing']);self.key(key,config['timing']['hold_ms'])
  else:self.key(key,config['timing']['hold_ms']);time.sleep(.12);self.click_tile(position,config,'left')
 def loot(self,position,config):
  if config['loot']=='key':self.key(config['keys']['loot'],config['timing']['hold_ms'])
  elif config['loot']=='corpse':self.click_tile(position,config,config['loot_settings']['button'])
 def release(self):
  for key in list(self.held):
   try:direct.keyUp(key)
   finally:self.held.discard(key)
 def alarm(self):
  import winsound
  winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
