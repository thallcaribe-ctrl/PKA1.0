"""Configuracao validada do helper."""
import json,copy,math
from pathlib import Path
ROOT=Path(__file__).resolve().parent
DEFAULT={
 'game_path':r'D:\PokeAlliance\PokeAlliance_dx.exe',
 'own_pokemon':'','targets':['Pidgey'],'shiny_priority':True,'range':8,'combo_range':4,
 'modules':{'targeting':False,'cavebot':False,'combo':True,'healing':False,'catch':False,'loot':False,'alarms':True,'scripts':False},
 'keys':{'summon':'1','combo':'r','revive':'2','potion':'','ball':'','loot':''},
 'timing':{'hold_ms':180,'mouse_hold_ms':150,'move_ms':220,'settle_ms':120,'combo_revive_s':1.0,'cycle_gap_s':0.4,'walk_gap_s':0.65},
 'healing':{'auto_summon':True,'revive_below':30,'potion_below':70,'cooldown_s':3,'revive_dead':True},
 'catch':{'use_distance':1,'approach_timeout_s':12,'body_timeout_s':30,'mode':'crosshair','only_shiny':True,'names':[],'delay_s':0.5,'cooldown_s':1},
 'route':[],'route_loop':True,'route_index':0,'waypoint_tolerance':0,
 'grid':{'ready':False,'center_x':0,'center_y':0,'tile_x':64,'tile_y':64,'client_width':0,'client_height':0,'viewport':[0,0,0,0]},
 'overlay':True,'loot':'server_auto','loot_settings':{'delay_s':.2,'cooldown_s':.5,'button':'right'},'scripts':[],
 'alarms':{'player_below':30,'players':False,'stuck_s':30},
 'validation':{'position':True,'creatures':False,'health':False},
}
KEYS=set('abcdefghijklmnopqrstuvwxyz0123456789')|{f'f{i}' for i in range(1,13)}|{'space','enter','tab','esc','up','down','left','right'}

def merge(base,patch):
 result=copy.deepcopy(base)
 for key,value in patch.items():
  if key not in base:raise ValueError(f'Campo desconhecido: {key}')
  if isinstance(base[key],dict):
   if not isinstance(value,dict):raise ValueError(f'{key}: esperado objeto')
   result[key]=merge(base[key],value)
  else:result[key]=copy.deepcopy(value)
 return result

def validate(config):
 c=merge(DEFAULT,config)
 for key in ('own_pokemon','game_path'):
  if not isinstance(c[key],str) or len(c[key])>512:raise ValueError(f'{key} invalido')
 for key,value in c['modules'].items():
  if type(value)is not bool:raise ValueError(f'Modulo {key}: esperado booleano')
 for group in ('validation',):
  if any(type(v)is not bool for v in c[group].values()):raise ValueError('Validacao invalida')
 for key,value in c['keys'].items():
  if not isinstance(value,str) or (value and (value.lower()not in KEYS or value.lower()=='f12')):raise ValueError(f'Tecla {key} invalida')
  c['keys'][key]=value.lower()
 for key,value in c['timing'].items():
  maximum=2000 if key.endswith('_ms') else 60
  minimum=30 if key.endswith('_ms') else .05
  if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError(f'Tempo {key} fora do intervalo')
 for key in ('targets',):
  if not isinstance(c[key],list) or len(c[key])>1000 or any(not isinstance(n,str) or len(n)>80 for n in c[key]):raise ValueError('Lista de alvos invalida')
 for key in ('names',):
  if not isinstance(c['catch'][key],list) or any(not isinstance(n,str) for n in c['catch'][key]):raise ValueError('Lista de captura invalida')
 for key in ('revive_below','potion_below'):
  value=c['healing'][key]
  if not isinstance(value,(int,float)) or not 0<=value<=100:raise ValueError('Porcentagem de cura invalida')
 if type(c['range'])is not int or not 1<=c['range']<=15:raise ValueError('Alcance invalido')
 if type(c['combo_range'])is not int or not 1<=c['combo_range']<=8:raise ValueError('Alcance do combo invalido')
 if not isinstance(c['route'],list) or len(c['route'])>10000:raise ValueError('Rota invalida')
 for point in c['route']:
  if not isinstance(point,dict) or any(type(point.get(k))is not int for k in ('x','y','z')):raise ValueError('Waypoint precisa de x/y/z inteiros')
  if not(0<=point['x']<65535 and 0<=point['y']<65535 and 0<=point['z']<=15):raise ValueError('Waypoint fora do mapa')
  if point.get('action','walk')not in ('walk','wait','finish_lure','stairs','end'):raise ValueError('Acao de waypoint invalida')
  if point.get('action')=='stairs' and point.get('direction')not in ('up','down','left','right'):raise ValueError('Escada precisa de direcao')
  if 'wait_s'in point and (not isinstance(point['wait_s'],(int,float)) or not 0<=point['wait_s']<=3600):raise ValueError('Pausa invalida')
 g=c['grid']
 for key in ('center_x','center_y','tile_x','tile_y','client_width','client_height'):
  if not isinstance(g[key],(int,float)) or not math.isfinite(g[key]):raise ValueError('Grade invalida')
 if g['ready'] and (not 4<=g['tile_x']<=512 or not 4<=g['tile_y']<=512 or g['client_width']<=0 or g['client_height']<=0):raise ValueError('Grade nao calibrada')
 if not isinstance(c['scripts'],list) or len(c['scripts'])>100:raise ValueError('Scripts invalidos')
 for script in c['scripts']:
  if not isinstance(script,dict) or not isinstance(script.get('steps'),list) or len(script['steps'])>1000:raise ValueError('Macro precisa de steps')
  for step in script['steps']:
   if not isinstance(step,dict):raise ValueError('Passo de macro precisa ser objeto')
   if step.get('when','always')not in ('always','targets','no_targets'):raise ValueError('Condicao de macro invalida')
   if step.get('action')not in ('wait','key','walk','log','pause','combo','revive'):raise ValueError('Acao de macro nao permitida')
   if step.get('action')=='key' and (step.get('key')not in KEYS or step.get('key')=='f12'):raise ValueError('Tecla de macro invalida')
   if step.get('action')=='walk' and step.get('direction')not in ('up','down','left','right'):raise ValueError('Direcao de macro invalida')
   if step.get('action')=='wait' and (not isinstance(step.get('seconds'),(int,float)) or not .05<=step['seconds']<=3600):raise ValueError('Espera de macro invalida')
 for flag in ('route_loop','overlay','shiny_priority'):
  if type(c[flag])is not bool:raise ValueError('Esperado booleano: '+flag)
 for parent,key in [('catch','only_shiny'),('healing','revive_dead'),('healing','auto_summon'),('grid','ready'),('alarms','players')]:
  if type(c[parent][key])is not bool:raise ValueError('Esperado booleano: '+key)
 if type(c['catch']['use_distance'])is not int or not 0<=c['catch']['use_distance']<=3:raise ValueError('Distancia de uso da ball invalida')
 if c['catch']['mode']not in ('crosshair','smart_use'):raise ValueError('Modo de captura invalido')
 if c['loot']not in ('server_auto','key','corpse'):raise ValueError('Modo de loot invalido')
 if c['loot_settings']['button']not in ('left','right'):raise ValueError('Botao de loot invalido')
 for parent,key in [('catch','approach_timeout_s'),('catch','body_timeout_s'),('loot_settings','delay_s'),('loot_settings','cooldown_s'),('healing','cooldown_s'),('catch','delay_s'),('catch','cooldown_s'),('alarms','stuck_s')]:
  value=c[parent][key]
  if type(value)not in (int,float)or not math.isfinite(value)or not .05<=value<=3600:raise ValueError('Intervalo invalido: '+key)
 if type(c['route_index'])is not int or c['route_index']<0:raise ValueError('Indice de rota invalido')
 if type(c['waypoint_tolerance'])is not int or not 0<=c['waypoint_tolerance']<=3:raise ValueError('Tolerancia invalida')
 if not 0<=c['alarms']['player_below']<=100:raise ValueError('Limite de alarme invalido')
 if g['ready']:
  area=g['viewport']
  if not isinstance(area,list)or len(area)!=4 or any(type(v)not in(int,float)or not math.isfinite(v)for v in area):raise ValueError('Area jogavel invalida')
  if not(0<=area[0]<area[2]<=g['client_width']and 0<=area[1]<area[3]<=g['client_height']):raise ValueError('Area jogavel fora da janela')
  if not(area[0]<=g['center_x']<area[2]and area[1]<=g['center_y']<area[3]):raise ValueError('Centro fora da area jogavel')
 return c

def load():
 path=ROOT/'helper-config.json'
 return validate(json.loads(path.read_text(encoding='utf-8')))if path.exists()else copy.deepcopy(DEFAULT)

def save(config):
 from helper_storage import atomic_json
 c=validate(config);atomic_json(ROOT/'helper-config.json',c);return c
