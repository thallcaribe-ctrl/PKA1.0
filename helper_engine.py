"""Motor cooperativo: rotas, targeting, combo/revive, captura e macros."""
import copy,time,math,collections
from helper_settings import validate

def distance(a,b):return max(abs(a['x']-b['x']),abs(a['y']-b['y']))if a['z']==b['z']else math.inf

def base_name(name):
 name=name.casefold().strip()
 for prefix in ('shiny ','shiny-','shiny: '):
  if name.startswith(prefix):return name[len(prefix):]
 return name

class Engine:
 def __init__(self,backend,config,clock=time.monotonic):
  self.backend=backend;self.config=validate(config);self.clock=clock
  self.running=False;self.status='Parado';self.events=collections.deque(maxlen=200)
  self.target=None;self.combat_progress=None;self.pending_revive=None;self.next_combo=0.;self.next_walk=0.;self.next_heal=0.;self.next_catch=0.
  self.route_index=min(self.config['route_index'],max(0,len(self.config['route'])-1));self.waypoint_wait=None;self.walk_attempt=None;self.stuck_count=0
  self.seen={};self.corpses=collections.deque(maxlen=100);self.loot_corpses=collections.deque(maxlen=100);self.next_loot=0.;self.caught=set();self.macro=None;self.last_frame=None;self.recording=False;self.recorded=[]
  self.summon_pending=None;self.summon_attempted=False;self.run_identity=None;self.last_alert=0.;self.last_position=None;self.last_motion=clock();self.counts={'combos':0,'revives':0,'capture_attempts':0,'loot_attempts':0,'steps':0,'laps':0}
 def log(self,message):self.events.append({'at':round(self.clock(),2),'message':str(message)})
 def configure(self,config):
  if self.running:raise RuntimeError('Pare o helper antes de alterar a configuracao')
  self.config=validate(config)
  self.route_index=min(self.config['route_index'],max(0,len(self.config['route'])-1))
  self.walk_attempt=None;self.waypoint_wait=None;self.stuck_count=0
 def requirements(self):
  c=self.config;m=c['modules'];issues=[]
  if m['cavebot']and not c['route']:issues.append('Carregue uma rota')
  if m['targeting']or m['catch']or (m['loot']and c['loot']!='server_auto'):
   if not c['own_pokemon'].strip():issues.append('Informe o nome do seu Pokemon para exclui-lo dos alvos')
   if (m['targeting']or m['catch']or c['loot']=='corpse')and not c['grid']['ready']:issues.append('Calibre a grade de tiles')
   if not c['validation']['creatures']:issues.append('Valide a leitura das criaturas antes de ativar targeting/captura')
  if (m['healing']or m['catch']or (m['loot']and c['loot']!='server_auto'))and not c['validation']['health']:issues.append('Valide a leitura de vida antes de ativar cura, captura ou loot ativo')
  if m['catch']and not c['keys']['ball']:issues.append('Defina a tecla da pokebola')
  if m['loot']and c['loot']=='key'and not c['keys']['loot']:issues.append('Defina a tecla do loot')
  if m['targeting']and not c['targets']and not c['shiny_priority']:issues.append('Defina os alvos')
  return issues
 def start(self):
  issues=self.requirements()
  if issues:raise RuntimeError('; '.join(issues))
  if self.route_index>=len(self.config['route']):self.route_index=min(self.config['route_index'],max(0,len(self.config['route'])-1))
  self.summon_pending=None;self.summon_attempted=False
  self.run_identity=None;self.running=True;self.status='Aguardando estado do jogo';self.log('Helper iniciado')
 def stop(self,reason='Parado'):
  self.summon_pending=None;self.run_identity=None;self.running=False;self.pending_revive=None;self.target=None;self.combat_progress=None;self.macro=None;self.status=reason
  self.seen={};self.corpses.clear();self.loot_corpses.clear();self.caught.clear();self.walk_attempt=None;self.waypoint_wait=None;self.stuck_count=0
  self.backend.release();self.log(reason)
 def begin_recording(self):self.recorded=[];self.recording=True;self.log('Gravacao iniciada')
 def end_recording(self):self.recording=False;self.log(f'Gravacao encerrada: {len(self.recorded)} waypoints');return copy.deepcopy(self.recorded)
 def start_macro(self,index):
  scripts=self.config['scripts']
  if not self.running:raise RuntimeError('Inicie o helper primeiro')
  if not self.config['modules']['scripts']:raise RuntimeError('Habilite o modulo de macros')
  self.pending_revive=None;self.target=None
  if not 0<=index<len(scripts):raise ValueError('Macro inexistente')
  self.macro={'script':copy.deepcopy(scripts[index]),'index':0,'wake':self.clock()};self.log('Macro iniciada')
 def tile_visible(self,position,frame):
  g=self.config['grid']
  if not g['ready']or not frame.get('player'):return False
  p=frame['player']['position']
  if p['z']!=position['z']:return False
  x=g['center_x']+(position['x']-p['x'])*g['tile_x'];y=g['center_y']+(position['y']-p['y'])*g['tile_y'];left,top,right,bottom=g['viewport']
  return left<=x<right and top<=y<bottom
 def eligible(self,frame):
  c=self.config;own=base_name(c['own_pokemon']);names={base_name(n)for n in c['targets']};p=frame['player']['position'];result=[]
  for obj in frame.get('creatures',[]):
   if obj.get('kind')in ('player','npc','localplayer'):continue
   if obj.get('creature_type',1)!=1 or obj.get('attackable')is False or obj.get('pink_name'):continue
   if not obj.get('active',False)or obj.get('hp',0)<=0:continue
   if base_name(obj['name'])==own:continue
   if distance(p,obj['position'])>c['range']:continue
   if not self.tile_visible(obj['position'],frame):continue
   shiny=obj.get('shiny',False)
   if base_name(obj['name'])not in names and not(shiny and c['shiny_priority']):continue
   result.append(obj)
  return sorted(result,key=lambda o:(not(o.get('shiny')and c['shiny_priority']),distance(p,o['position']),o['hp'],o['id']))
 def deaths(self,frame):
  now=self.clock();current={o['id']:o for o in frame.get('creatures',[])}
  for ident,obj in current.items():
   previous=self.seen.get(ident)
   if previous and (previous.get('creature_type',1)!=1 or base_name(previous['name'])==base_name(self.config['own_pokemon'])or previous.get('own_confirmed')or previous.get('kind')in ('player','npc','localplayer')):continue
   if previous and previous.get('network_id')==obj.get('network_id')and previous['name']==obj['name'] and previous['hp']>0 and obj['hp']==0 and obj.get('death_confirmed'):
    marker=(ident,obj.get('generation',0),previous['seen'])
    if marker not in self.caught:
     corpse={**previous,'death_time':now,'marker':marker};self.caught.add(marker)
     if self.config['modules']['catch']:(self.corpses.appendleft if corpse.get('shiny')else self.corpses.append)(corpse)
     if self.config['modules']['loot']and self.config['loot']!='server_auto':(self.loot_corpses.appendleft if corpse.get('shiny')else self.loot_corpses.append)(corpse)
  retained={ident:obj for ident,obj in self.seen.items()if (ident not in current or not current[ident].get('active'))and now-obj['seen']<=2}
  retained.update({ident:{**obj,'seen':now}for ident,obj in current.items()if obj.get('hp',0)>0 and obj.get('active')})
  self.seen=retained
  self.caught=set(list(self.caught)[-1000:])
 def cast(self,which):
  key=self.config['keys'][which]
  if not key:raise RuntimeError(f'Tecla {which} nao configurada')
  self.backend.key(key,self.config['timing']['hold_ms'])
  if which=='revive':self.target=None
 def macro_tick(self,frame,now):
  if not self.macro:return False
  macro=self.macro;steps=macro['script']['steps']
  if now<macro['wake']:return True
  if macro['index']>=len(steps):self.macro=None;self.log('Macro concluida');return False
  step=steps[macro['index']];macro['index']+=1
  condition=step.get('when','always')
  if condition not in ('always','targets','no_targets'):raise RuntimeError('Condicao de macro desconhecida')
  active=bool(self.eligible(frame))
  if condition=='targets'and not active or condition=='no_targets'and active:return True
  action=step['action']
  if action=='wait':macro['wake']=now+step['seconds']
  elif action=='key':self.backend.key(step['key'],self.config['timing']['hold_ms'])
  elif action=='walk':self.backend.walk(step['direction'],self.config['timing']['hold_ms'])
  elif action=='log':self.log(step.get('text','Macro'))
  elif action=='pause':self.stop('Pausado pela macro')
  elif action=='combo':self.cast('combo');self.counts['combos']+=1
  elif action=='revive':self.cast('revive');self.counts['revives']+=1
  return True
 def healing(self,frame,now):
  c=self.config
  if not c['modules']['healing']or now<self.next_heal:return False
  pokemon=next((o for o in frame.get('creatures',[])if base_name(o['name'])==base_name(c['own_pokemon'])and o.get('own_confirmed')),None)
  if pokemon is None:self.status='Cura aguardando identificacao do seu Pokemon';return False
  hp=pokemon.get('hp')
  if not isinstance(hp,(int,float))or not 0<=hp<=100:return False
  if hp<=c['healing']['revive_below']and(hp>0 or c['healing']['revive_dead']):
   self.cast('revive');self.counts['revives']+=1;self.next_heal=now+c['healing']['cooldown_s'];self.pending_revive=None;return True
  if hp<=0:return False
  if hp<=c['healing']['potion_below']and not self.eligible(frame)and c['keys']['potion']:
   self.cast('potion');self.next_heal=now+c['healing']['cooldown_s'];return True
  return False
 def catching(self,frame,now):
  if not self.config['modules']['catch']:return False
  c=self.config;names={base_name(n)for n in c['catch']['names']}
  while self.corpses:
   corpse=self.corpses[0]
   if now-corpse['death_time']>c['catch']['body_timeout_s'] or c['catch']['only_shiny']and not corpse.get('shiny')or names and base_name(corpse['name'])not in names:
    self.corpses.popleft();continue
   p=frame['player']['position'];dist=distance(p,corpse['position'])
   if not corpse.get('approach_started')and(dist>c['range']or not self.tile_visible(corpse['position'],frame)):self.corpses.popleft();continue
   if now<corpse['death_time']+c['catch']['delay_s']or now<self.next_catch:return True
   if dist>c['catch']['use_distance']:
    if not corpse.get('approach_started'):
     self.backend.approach(corpse['position'],c);corpse.update(approach_started=now,last_progress=now,walk_position=dict(p));self.status='Aproximando do corpo para captura';return True
    if p!=corpse['walk_position']:corpse.update(last_progress=now,walk_position=dict(p))
    if now-corpse['approach_started']>c['catch']['approach_timeout_s']or now-corpse['last_progress']>3:
     self.corpses.popleft();self.log('Captura ignorada: corpo sem caminho confirmado');continue
    self.status='Aproximando do corpo para captura';return True
   if not self.tile_visible(corpse['position'],frame):self.corpses.popleft();continue
   self.backend.capture(corpse['position'],c['keys']['ball'],c);self.corpses.popleft();self.counts['capture_attempts']+=1;self.next_catch=now+c['catch']['cooldown_s'];self.status='Tentativa de captura: '+corpse['name'];self.log(self.status);return True
  return False
 def looting(self,frame,now):
  c=self.config
  if not c['modules']['loot']or c['loot']=='server_auto':return False
  while self.loot_corpses:
   corpse=self.loot_corpses[0]
   if now-corpse['death_time']>10 or distance(frame['player']['position'],corpse['position'])>c['range']:self.loot_corpses.popleft();continue
   if now<corpse['death_time']+c['loot_settings']['delay_s']or now<self.next_loot:return True
   if c['loot']=='corpse'and distance(frame['player']['position'],corpse['position'])>1:
    if not corpse.get('approach_started'):
     self.backend.approach(corpse['position'],c);corpse['approach_started']=now
    self.status='Aproximando do corpo para loot';return True
   if not self.tile_visible(corpse['position'],frame):self.loot_corpses.popleft();continue
   self.backend.loot(corpse['position'],c);self.loot_corpses.popleft();self.next_loot=now+c['loot_settings']['cooldown_s'];self.counts['loot_attempts']+=1;self.status='Tentativa de loot: '+corpse['name'];self.log(self.status);return True
  return False
 def walking(self,frame,now):
  c=self.config
  if not c['modules']['cavebot']or now<self.next_walk:return
  route=c['route']
  if not route:self.stop('Rota vazia');return
  if self.route_index>=len(route):
   self.counts['laps']+=1
   if not c['route_loop']:self.stop('Rota concluida');return
   self.route_index=0
  point=route[self.route_index];p=frame['player']['position'];action=point.get('action','walk')
  if self.walk_attempt:
   if p==self.walk_attempt['position']:self.stuck_count+=1
   else:self.stuck_count=0
   self.walk_attempt=None
   if self.stuck_count>=3:self.stop('Rota bloqueada: tres passos sem deslocamento');return
  if distance(p,point)<=c['waypoint_tolerance']:
   if action=='end':self.stop('Fim da volta');return
   if action=='stairs':
    self.backend.walk(point['direction'],c['timing']['hold_ms']);self.route_index+=1;self.next_walk=now+1;return
   if action in ('wait','finish_lure'):
    if self.waypoint_wait is None:self.waypoint_wait=now+point.get('wait_s',1)
    if now<self.waypoint_wait:self.status='Pausa no waypoint';return
    self.waypoint_wait=None
   self.route_index+=1;return
  if p['z']!=point['z']:self.stop('Andar diferente: falta waypoint de escada');return
  dx=point['x']-p['x'];dy=point['y']-p['y']
  direction=('right'if dx>0 else'left')if abs(dx)>=abs(dy)else('down'if dy>0 else'up')
  self.backend.walk(direction,c['timing']['hold_ms']);self.counts['steps']+=1
  self.walk_attempt={'position':dict(p),'direction':direction};self.next_walk=now+c['timing']['walk_gap_s'];self.status=f'Caminhando: WP {self.route_index+1}/{len(route)}'
 def tick(self,frame):
  now=self.clock();self.last_frame=frame
  if frame.get('online')and frame.get('player')and frame.get('fresh',False):
   p=frame['player']['position']
   if p!=self.last_position:self.last_position=dict(p);self.last_motion=now
   if self.recording and(not self.recorded or any(self.recorded[-1][k]!=p[k]for k in ('x','y','z'))):self.recorded.append({**p,'action':'walk'})
  if not self.running:return
  try:
   if not frame.get('online')or not frame.get('fresh')or not frame.get('player'):self.stop('Sem estado atual do personagem');return
   if not frame.get('focused'):self.stop('Pausado: o jogo perdeu o foco');return
   identity=(frame.get('pid'),frame['player']['id'])
   if self.run_identity is not None and identity!=self.run_identity:self.stop('Cliente ou personagem mudou; inicie novamente');return
   self.run_identity=identity
   caps=frame.get('capabilities',{})
   if (self.config['modules']['targeting'] or self.config['modules']['catch'] or (self.config['modules']['loot']and self.config['loot']!='server_auto'))and not caps.get('creatures'):self.stop('Colecao ativa de criaturas indisponivel');return
   if self.config['modules']['healing']and not caps.get('health')and not frame.get('own_refresh_pending'):
    if not self.config['healing']['auto_summon']or not self.config['validation']['health']or not caps.get('creatures'):self.stop('Vida/propriedade do Pokemon nao validada');return
    if any(o.get('active')and o.get('creature_type')==3 for o in frame.get('creatures',[])):self.stop('Pokemon invocado difere da identificacao configurada');return
    if not self.summon_attempted:
     self.cast('summon');self.summon_attempted=True;self.summon_pending=self.clock()+5;self.status='Invocando Pokemon: aguardando identificacao';return
    if self.summon_pending and now<self.summon_pending:self.status='Invocando Pokemon: aguardando identificacao';return
    self.stop('Pokemon nao retornou apos uma tentativa de invocacao');return
   if caps.get('health'):self.summon_pending=None
   self.deaths(frame)
   if frame.get('own_refresh_pending'):self.status='Aguardando retorno do Pokemon apos Smart Revive';return
   if self.config['modules']['alarms']:
    shiny=any(o.get('shiny')and o.get('active')for o in frame.get('creatures',[]))
    low=frame['player'].get('hp',100)<=self.config['alarms']['player_below']
    strangers=self.config['alarms']['players']and any(o.get('kind')=='player'and o.get('active')for o in frame.get('creatures',[]))
    stuck=self.config['modules']['cavebot']and now-self.last_motion>self.config['alarms']['stuck_s']
    if (shiny or low or strangers or stuck)and now-self.last_alert>10:
     self.backend.alarm();self.last_alert=now;self.log('Alarme: '+('shiny'if shiny else'vida baixa'if low else'outro jogador'if strangers else'personagem parado'))
   if self.healing(frame,now):return
   if self.macro_tick(frame,now):return
   if self.pending_revive is not None:
    if now>=self.pending_revive:
     self.cast('revive');self.counts['revives']+=1;self.pending_revive=None;self.next_combo=now+self.config['timing']['cycle_gap_s']
    return
   if self.looting(frame,now):return
   if self.catching(frame,now):return
   targets=self.eligible(frame)if self.config['modules']['targeting']else[]
   if targets:
    chosen=next((o for o in targets if self.target and o['id']==self.target['id']),targets[0])
    if self.config['shiny_priority']and targets[0].get('shiny')and not chosen.get('shiny'):chosen=targets[0]
    if not self.combat_progress or self.combat_progress['id']!=chosen['id']:self.combat_progress={'id':chosen['id'],'hp':chosen['hp'],'cycles':0,'approach':now}
    elif chosen['hp']<self.combat_progress['hp']:self.combat_progress.update(hp=chosen['hp'],cycles=0)
    if not self.target or self.target['id']!=chosen['id']:
     self.backend.select(chosen['position'],self.config,chosen['id']);self.target=chosen;self.next_combo=now+.3;self.log('Alvo: '+chosen['name']);return
    self.target=chosen;self.status='Combate: '+chosen['name']
    if self.config['modules']['combo']and now>=self.next_combo:
     own=next((o for o in frame.get('creatures',[])if o.get('own_confirmed')and o.get('hp',0)>0),None)
     if own is None:self.status='Combo aguardando Pokemon proprio identificado';return
     if distance(own['position'],chosen['position'])>self.config['combo_range']:
      if now-self.combat_progress['approach']>10:self.stop('Pokemon nao alcancou o alvo; confira obstaculos e caminho');return
      self.status='Aguardando Pokemon aproximar-se do alvo';return
     if self.combat_progress['cycles']>=3:self.stop('Alvo sem perder vida apos tres combos; confira alcance e selecao');return
     self.combat_progress['cycles']+=1
     self.cast('combo');self.counts['combos']+=1;self.pending_revive=self.clock()+self.config['timing']['combo_revive_s']
    return
   self.target=None;self.combat_progress=None;self.status='Sem alvo elegivel';self.walking(frame,now)
  except Exception as error:self.stop('Interrompido: '+str(error))
 def snapshot(self):return {'running':self.running,'status':self.status,'target':self.target,'route_index':self.route_index,'recording':self.recording,'recorded_waypoints':len(self.recorded),'counts':dict(self.counts),'events':list(self.events),'requirements':self.requirements()}
