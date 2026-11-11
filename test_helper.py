"""Regressoes do motor sem enviar entradas ao jogo."""
import unittest,copy,struct
from unittest.mock import patch
from helper_settings import DEFAULT,validate
from helper_engine import Engine
from helper_native import Reader

class Backend:
 def __init__(self):self.actions=[]
 def release(self):self.actions.append(('release',))
 def key(self,*args):self.actions.append(('key',)+args)
 def walk(self,*args):self.actions.append(('walk',)+args)
 def select(self,*args):self.actions.append(('select',args[0]))
 def capture(self,*args):self.actions.append(('capture',args[0]))
 def alarm(self):self.actions.append(('alarm',))
 def approach(self,position,config):self.actions.append(('approach',position))
 def loot(self,position,config):self.actions.append(('loot',position,config['loot']))

class EngineTests(unittest.TestCase):
 def setUp(self):
  self.now=100.;self.b=Backend();self.c=copy.deepcopy(DEFAULT)
  self.c['own_pokemon']='Charmander';self.c['modules']['targeting']=True;self.c['validation']['creatures']=True
  self.c['grid'].update(ready=True,center_x=500,center_y=300,client_width=1000,client_height=700,viewport=[0,0,900,650])
  self.e=Engine(self.b,self.c,lambda:self.now);self.e.start()
 def obj(self,name='Pidgey',ident=2,hp=80):return {'id':ident,'name':name,'kind':'monster','position':{'x':11,'y':10,'z':7},'hp':hp,'active':True,'shiny':name.startswith('Shiny ')}
 def frame(self,objects=None):
  objects=[self.obj()]if objects is None else list(objects)
  if not any(o.get('own_confirmed')for o in objects):
   own=self.obj('Charmander',ident=100,hp=100);own.update(own_confirmed=True,position={'x':10,'y':10,'z':7});objects.append(own)
  return {'online':True,'fresh':True,'focused':True,'player':{'id':1,'name':'Consulti','position':{'x':10,'y':10,'z':7},'hp':100},'creatures':objects,'capabilities':{'creatures':True,'health':True}}

 def test_combo_waits_one_second_and_revives(self):
  f=self.frame();self.e.tick(f);self.now+=.31;self.e.tick(f)
  self.assertEqual([a[1]for a in self.b.actions if a[0]=='key'],['r'])
  self.now+=.99;self.e.tick(f);self.assertEqual(len([a for a in self.b.actions if a[0]=='key']),1)
  self.now+=.02;self.e.tick(f);self.assertEqual([a[1]for a in self.b.actions if a[0]=='key'],['r','2'])
 def test_pink_name_never_selects_or_casts_even_if_shiny(self):
  obj=self.obj('Shiny Pidgey');obj.update(pink_name=True,attackable=False)
  self.e.tick(self.frame([obj]));self.now+=1;self.e.tick(self.frame([obj]))
  self.assertFalse(any(a[0]in ('key','select')for a in self.b.actions))
 def test_loot_approaches_and_runs_before_capture(self):
  self.e.config['modules'].update(loot=True,catch=True,combo=False);self.e.config['loot']='corpse';self.e.config['keys']['ball']='3'
  alive=self.obj('Shiny Pidgey');alive['position']['x']=13;self.e.tick(self.frame([alive]))
  dead={**alive,'hp':0,'active':False,'death_confirmed':True};self.now+=.1;self.e.tick(self.frame([dead]));self.now+=.6;self.e.tick(self.frame([dead]))
  self.assertTrue(any(a[0]=='approach'for a in self.b.actions));self.assertFalse(any(a[0]in ('loot','capture')for a in self.b.actions))
  f=self.frame([dead]);f['player']['position']['x']=12;self.now+=.5;self.e.tick(f);self.now+=.5;self.e.tick(f)
  self.assertEqual([a[0]for a in self.b.actions if a[0]in ('loot','capture')],['loot','capture'])
 def test_healing_obeys_cooldown_after_low_health_persists(self):
  self.e.config['modules']['healing']=True;self.e.config['validation']['health']=True
  own=self.obj('Charmander',100,10);own['own_confirmed']=True;frame=self.frame([own])
  self.assertTrue(self.e.healing(frame,self.now));self.assertFalse(self.e.healing(frame,self.now+.2))
  self.assertTrue(self.e.healing(frame,self.now+self.e.config['healing']['cooldown_s']))
  self.assertEqual(sum(a[:2]==('key','2')for a in self.b.actions),2)
 def test_completed_route_can_start_again(self):
  self.e.stop();self.e.config['modules']['cavebot']=True;self.e.config['route']=[{'x':10,'y':10,'z':7}];self.e.config['route_loop']=False
  self.e.start();self.e.walking(self.frame([]),self.now);self.e.walking(self.frame([]),self.now+1)
  self.assertFalse(self.e.running);self.e.start();self.assertEqual(self.e.route_index,0)
 def test_other_players_summon_never_becomes_capture_body(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='3'
  pet=self.obj('Shiny Pidgey');pet['creature_type']=4;self.e.deaths(self.frame([pet]));self.now+=.1
  self.e.deaths(self.frame([{**pet,'hp':0,'death_confirmed':True,'active':False}]))
  self.assertFalse(self.e.corpses)
 def test_unsummoned_pokemon_gets_one_attempt_then_stops(self):
  self.e.config['modules']['healing']=True;self.e.config['validation']['health']=True
  frame=self.frame([]);frame['creatures']=[];frame['capabilities']['health']=False
  self.e.tick(frame);self.now+=1;self.e.tick(frame)
  self.assertEqual([a for a in self.b.actions if a[0]=='key'],[('key','1',180)])
  self.now+=5;self.e.tick(frame);self.assertFalse(self.e.running)
 def test_auto_summon_never_retracts_existing_unrecognized_own(self):
  self.e.config['modules']['healing']=True;self.e.config['validation']['health']=True
  frame=self.frame([]);frame['creatures'][0].update(creature_type=3,own_confirmed=False);frame['capabilities']['health']=False
  self.e.tick(frame);self.assertFalse(self.e.running);self.assertFalse(any(a[0]=='key'for a in self.b.actions))
 def test_auto_summon_resumes_when_ownership_returns(self):
  self.e.config['modules']['healing']=True;self.e.config['validation']['health']=True
  frame=self.frame([]);frame['creatures']=[];frame['capabilities']['health']=False;self.e.tick(frame)
  self.now+=.5;self.e.tick(self.frame([]));self.assertTrue(self.e.running);self.assertIsNone(self.e.summon_pending)
 def test_reused_address_with_new_network_id_is_not_death(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='3'
  obj=self.obj('Shiny Pidgey');obj['network_id']=100;self.e.deaths(self.frame([obj]));self.now+=.1
  self.e.deaths(self.frame([{**obj,'network_id':200,'hp':0,'death_confirmed':True,'active':False}]))
  self.assertFalse(self.e.corpses)
 def test_shiny_body_moves_ahead_of_ordinary_loot(self):
  self.e.config['modules'].update(catch=True,loot=True);self.e.config['loot']='corpse';self.e.config['keys']['ball']='3'
  ordinary=self.obj('Pidgey',2);shiny=self.obj('Shiny Pidgey',3)
  self.e.deaths(self.frame([ordinary]));self.now+=.1;self.e.deaths(self.frame([{**ordinary,'hp':0,'death_confirmed':True,'active':False},shiny]))
  self.now+=.1;self.e.deaths(self.frame([{**shiny,'hp':0,'death_confirmed':True,'active':False}]))
  self.assertEqual(self.e.loot_corpses[0]['name'],'Shiny Pidgey');self.assertEqual(self.e.corpses[0]['name'],'Shiny Pidgey')
 def test_disabled_shiny_priority_does_not_interrupt_current_target(self):
  self.e.config['shiny_priority']=False;ordinary=self.obj('Pidgey',2);self.e.tick(self.frame([ordinary]))
  shiny=self.obj('Shiny Pidgey',3);shiny['position']['x']=10;self.now+=.4;self.e.tick(self.frame([ordinary,shiny]))
  self.assertEqual(self.e.target['id'],2)
 def test_no_targets_never_casts_combo(self):
  self.e.tick(self.frame([]));self.now+=10;self.e.tick(self.frame([]));self.assertFalse(any(a[0]=='key'for a in self.b.actions))
 def test_shiny_priority_and_own_exclusion(self):
  targets=self.e.eligible(self.frame([self.obj(),self.obj('Shiny Pidgey',3),self.obj('Shiny Charmander',4)]))
  self.assertEqual([o['id']for o in targets],[3,2])
 def test_lost_focus_cancels_pending_revive(self):
  f=self.frame();self.e.tick(f);self.now+=.4;self.e.tick(f);f['focused']=False;self.now+=2;self.e.tick(f)
  self.assertFalse(self.e.running);self.assertIsNone(self.e.pending_revive);self.assertNotIn(('key','2',180),self.b.actions)
 def test_disappearance_is_not_death(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='5';self.e.tick(self.frame([self.obj('Shiny Pidgey')]))
  self.now+=1;self.e.tick(self.frame([]));self.assertFalse(any(a[0]=='capture'for a in self.b.actions))
 def test_inactive_frame_before_zero_hp_still_confirms_death(self):
  self.e.config['modules'].update(catch=True,combo=False);self.e.config['keys']['ball']='3';alive=self.obj('Shiny Pidgey');self.e.tick(self.frame([alive]))
  ghost={**alive,'active':False};self.now+=.1;self.e.tick(self.frame([ghost]));dead={**ghost,'hp':0,'death_confirmed':True};self.now+=.1;self.e.tick(self.frame([dead]));self.now+=.6;self.e.tick(self.frame([dead]));self.assertEqual(sum(a[0]=='capture'for a in self.b.actions),1)
 def test_capture_approaches_body_before_using_ball(self):
  self.e.config['modules'].update(catch=True,combo=False);self.e.config['keys']['ball']='3'
  alive=self.obj('Shiny Pidgey');alive['position']['x']=13;self.e.tick(self.frame([alive]));dead={**alive,'hp':0,'active':False,'death_confirmed':True}
  self.now+=.1;self.e.tick(self.frame([dead]));self.now+=.6;self.e.tick(self.frame([dead]));self.assertEqual(sum(a[0]=='approach'for a in self.b.actions),1);self.assertFalse(any(a[0]=='capture'for a in self.b.actions))
  f=self.frame([dead]);f['player']['position']['x']=12;self.now+=.5;self.e.tick(f);self.assertEqual(sum(a[0]=='capture'for a in self.b.actions),1)
 def test_confirmed_death_captures_once(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='5';self.e.tick(self.frame([self.obj('Shiny Pidgey')]))
  dead=self.obj('Shiny Pidgey',hp=0);dead.update(active=False,death_confirmed=True)
  self.now+=.3;self.e.tick(self.frame([dead]));self.now+=.6;self.e.tick(self.frame([dead]));self.now+=1;self.e.tick(self.frame([dead]))
  self.assertEqual(sum(a[0]=='capture'for a in self.b.actions),1)
 def test_death_after_one_missing_frame_captures(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='5'
  self.e.tick(self.frame([self.obj('Shiny Pidgey')]))
  self.now+=.1;self.e.tick(self.frame([]))
  dead=self.obj('Shiny Pidgey',hp=0);dead.update(active=False,death_confirmed=True)
  self.now+=.1;self.e.tick(self.frame([dead]));self.now+=.6;self.e.tick(self.frame([dead]))
  self.assertEqual(sum(a[0]=='capture'for a in self.b.actions),1)
 def test_own_shiny_death_never_captures(self):
  self.e.config['modules']['catch']=True;self.e.config['keys']['ball']='5'
  own=self.obj('Shiny Charmander');self.e.tick(self.frame([own]));dead={**own,'hp':0,'death_confirmed':True};self.now+=1;self.e.tick(self.frame([dead]));self.now+=1;self.e.tick(self.frame([dead]));self.assertFalse(any(a[0]=='capture'for a in self.b.actions))
 def test_three_failed_walks_stop_route(self):
  self.e.config['modules']['targeting']=False;self.e.config['modules']['cavebot']=True;self.e.config['route']=[{'x':12,'y':10,'z':7}]
  for _ in range(4):self.e.tick(self.frame([]));self.now+=.7
  self.assertFalse(self.e.running);self.assertIn('bloqueada',self.e.status)
 def test_other_floor_never_walks(self):
  self.e.config['modules']['targeting']=False;self.e.config['modules']['cavebot']=True;self.e.config['route']=[{'x':10,'y':10,'z':6}];self.e.tick(self.frame([]))
  self.assertFalse(self.e.running);self.assertFalse(any(a[0]=='walk'for a in self.b.actions))
 def test_macro_wait_is_cooperative(self):
  self.e.config['modules']['scripts']=True;self.e.config['scripts']=[{'steps':[{'action':'combo'},{'action':'wait','seconds':1},{'action':'revive'}]}];self.e.start_macro(0)
  f=self.frame([]);self.e.tick(f);self.e.tick(f);self.now+=.5;self.e.tick(f);self.assertEqual([a[1]for a in self.b.actions if a[0]=='key'],['r'])
  self.now+=.6;self.e.tick(f);self.assertEqual([a[1]for a in self.b.actions if a[0]=='key'],['r','2'])
 def test_record_only_position_changes(self):
  self.e.begin_recording();self.e.tick(self.frame([]));self.e.tick(self.frame([]));f=self.frame([]);f['player']['position']['x']+=1;self.e.tick(f);self.assertEqual(len(self.e.recorded),2)
 def test_other_players_summons_are_not_targets(self):
  other=self.obj();other['creature_type']=4;self.assertEqual(self.e.eligible(self.frame([other])),[])
 def test_target_outside_viewport_is_excluded(self):
  self.e.config['range']=15;far=self.obj();far['position']['y']=0;self.assertEqual(self.e.eligible(self.frame([far])),[])
 def test_combo_waits_for_pokemon_to_approach(self):
  f=self.frame();own=next(o for o in f['creatures']if o.get('own_confirmed'));own['position']['x']=2
  self.e.tick(f);self.now+=.5;self.e.tick(f);self.assertFalse(any(a[0]=='key'for a in self.b.actions));self.assertIn('aproximar',self.e.status)
 def test_revive_forces_target_reselection(self):
  self.e.tick(self.frame());self.now+=.4;self.e.tick(self.frame());self.now+=1.1;self.e.tick(self.frame());self.assertIsNone(self.e.target)
  self.e.tick(self.frame());self.assertEqual(sum(a[0]=='select'for a in self.b.actions),2)
 def test_three_combos_without_damage_stop(self):
  for _ in range(30):self.e.tick(self.frame());self.now+=.6
  self.assertFalse(self.e.running);self.assertEqual(self.e.counts['combos'],3);self.assertIn('sem perder vida',self.e.status)
 def test_changed_player_identity_stops_before_input(self):
  f=self.frame();self.e.tick(f);before=len(self.b.actions);f['player']['id']=99;self.now+=1;self.e.tick(f)
  self.assertFalse(self.e.running);self.assertEqual(self.b.actions[before:],[('release',)])
 def test_targeting_stops_if_authoritative_map_disappears(self):
  f=self.frame();f['capabilities']['creatures']=False;self.e.tick(f);self.assertFalse(self.e.running);self.assertFalse(any(a[0]=='select'for a in self.b.actions))

class ConfigTests(unittest.TestCase):
 def test_invalid_wait_rejected(self):
  with self.assertRaises(ValueError):validate({'scripts':[{'steps':[{'action':'wait','seconds':-1}]}]})
 def test_arbitrary_script_execution_rejected(self):
  with self.assertRaises(ValueError):validate({'scripts':[{'steps':[{'action':'exec','code':'anything'}]}]})
 def test_invalid_viewport_rejected(self):
  c=copy.deepcopy(DEFAULT);c['grid'].update(ready=True,client_width=1000,client_height=700,viewport=[900,0,50,100])
  with self.assertRaises(ValueError):validate(c)
 def test_invalid_interval_rejected(self):
  with self.assertRaises(ValueError):validate({'healing':{'cooldown_s':-3}})

class TreeTests(unittest.TestCase):
 def fixture(self):
  head=0x100000;root=0x200000;obj=0x300000;vtable=0x400000
  node=bytearray(56);struct.pack_into('<QQQ',node,0,head,head,head);node[25]=0;struct.pack_into('<Q',node,40,obj)
  return head,root,obj,vtable,bytes(node)
 def test_active_creature_tree(self):
  head,root,obj,vtable,node=self.fixture();reader=Reader.__new__(Reader)
  def read(h,address,size):return node if address==root else struct.pack('<Q',vtable)if address==obj else b''
  with patch('helper_native.a.read',side_effect=read):self.assertEqual(reader.traverse_tree(1,head,root,1,{vtable:{}}),[obj])
 def test_freed_or_unrelated_pointer_rejected(self):
  head,root,obj,vtable,node=self.fixture();reader=Reader.__new__(Reader)
  with patch('helper_native.a.read',side_effect=lambda h,addr,size:node if addr==root else struct.pack('<Q',9999)):
   with self.assertRaises(ValueError):reader.traverse_tree(1,head,root,1,{vtable:{}})
 def test_wrong_tree_size_rejected(self):
  head,root,obj,vtable,node=self.fixture();reader=Reader.__new__(Reader)
  with patch('helper_native.a.read',side_effect=lambda h,addr,size:node if addr==root else struct.pack('<Q',vtable)):
   with self.assertRaises(ValueError):reader.traverse_tree(1,head,root,2,{vtable:{}})

class LifecycleTests(unittest.TestCase):
 def test_config_rejected_while_running_before_save(self):
  from helper_app import App
  from unittest.mock import Mock
  app=App.__new__(App);app.engine=Mock(running=True)
  with patch('helper_app.settings.save')as save:
   with self.assertRaises(RuntimeError):app.persist_config(DEFAULT)
   save.assert_not_called()
 def test_route_reconfiguration_resets_progress(self):
  e=Engine(Backend(),DEFAULT);e.route_index=20;e.walk_attempt={'position':{}};e.stuck_count=2
  c=copy.deepcopy(DEFAULT);c['route']=[{'x':10,'y':10,'z':7}];e.configure(c)
  self.assertEqual(e.route_index,0);self.assertIsNone(e.walk_attempt);self.assertEqual(e.stuck_count,0)
 def test_stop_discards_pending_corpses(self):
  e=Engine(Backend(),DEFAULT);e.corpses.append({'marker':1});e.seen={2:{}};e.stop()
  self.assertFalse(e.corpses);self.assertFalse(e.seen)
 def test_scan_open_failure_releases_scanning_flag(self):
  import threading
  r=Reader.__new__(Reader);r.scanning=True;r.lock=threading.RLock();r.open=lambda pid:(_ for _ in ()).throw(OSError('denied'))
  r.scan_sync({'pid':123})
  self.assertFalse(r.scanning);self.assertIn('denied',r.scan_error)
 def test_empty_tree_must_have_zero_count(self):
  r=Reader.__new__(Reader)
  with self.assertRaises(ValueError):r.traverse_tree(1,0x100000,0x100000,1,{})
  self.assertEqual(r.traverse_tree(1,0x100000,0x100000,0,{}),[])
 def test_tree_count_is_bounded(self):
  with self.assertRaises(ValueError):Reader.__new__(Reader).traverse_tree(1,0x100000,0x200000,5000,{})
 def test_f12_reserved_for_emergency(self):
  with self.assertRaises(ValueError):validate({'keys':{'combo':'f12'}})
  with self.assertRaises(ValueError):validate({'scripts':[{'steps':[{'action':'key','key':'f12'}]}]})
 def test_invalid_macro_condition_rejected(self):
  with self.assertRaises(ValueError):validate({'scripts':[{'steps':[{'action':'combo','when':'invalid'}]}]})

class LootTests(unittest.TestCase):
 setUp=EngineTests.setUp
 obj=EngineTests.obj
 frame=EngineTests.frame
 def prepare(self,mode='key'):
  self.e.config['modules'].update(targeting=False,combo=False,loot=True);self.e.config['loot']=mode;self.e.config['keys']['loot']='l'
 def death(self,name='Pidgey'):
  self.e.tick(self.frame([self.obj(name)]));dead=self.obj(name,hp=0);dead.update(active=False,death_confirmed=True)
  self.now+=.1;self.e.tick(self.frame([dead]));self.now+=.5;self.e.tick(self.frame([dead]));self.now+=1;self.e.tick(self.frame([dead]))
 def test_confirmed_death_loots_once(self):
  self.prepare();self.death();self.assertEqual(sum(a[0]=='loot'for a in self.b.actions),1)
 def test_server_autoloot_sends_no_input(self):
  self.prepare('server_auto');self.death();self.assertFalse(any(a[0]=='loot'for a in self.b.actions))
 def test_disappearance_never_loots(self):
  self.prepare();self.e.tick(self.frame());self.now+=1;self.e.tick(self.frame([]));self.assertFalse(any(a[0]=='loot'for a in self.b.actions))
 def test_own_pokemon_is_not_looted(self):
  self.prepare();self.death('Charmander');self.assertFalse(any(a[0]=='loot'for a in self.b.actions))
 def test_stop_discards_loot_queue(self):
  self.prepare();self.e.loot_corpses.append({'marker':1});self.e.stop();self.assertFalse(self.e.loot_corpses)
 def test_active_loot_and_capture_require_validated_health(self):
  for mode in ('loot','catch'):
   config=copy.deepcopy(DEFAULT);config['modules'][mode]=True;config['loot']='key';config['keys'].update(loot='l',ball='b');config['own_pokemon']='Charmander';config['grid']=copy.deepcopy(self.c['grid']);config['validation']['creatures']=True
   e=Engine(self.b,config)
   self.assertTrue(any('vida'in issue for issue in e.requirements()))
 def test_invalid_loot_mode_rejected(self):
  with self.assertRaises(ValueError):validate({'loot':'anything'})
 def test_combo_wait_starts_after_key_release(self):
  self.e.tick(self.frame());self.now+=.4
  def slow_key(*args):self.b.actions.append(('key',)+args);self.now+=.18
  self.b.key=slow_key;self.e.tick(self.frame());self.assertAlmostEqual(self.e.pending_revive,self.now+1)
 def test_potion_never_sent_to_dead_pokemon_when_revive_disabled(self):
  self.e.config['modules'].update(targeting=False,healing=True);self.e.config['healing']['revive_dead']=False;self.e.config['keys']['potion']='p'
  own=self.obj('Charmander',hp=0);own['own_confirmed']=True;self.e.tick(self.frame([own]));self.assertFalse(any(a[0]=='key'for a in self.b.actions))

class CaptureInputTests(unittest.TestCase):
 def test_smart_use_moves_cursor_before_pressing_ball(self):
  from helper_native import Input
  from unittest.mock import Mock
  backend=Input.__new__(Input);backend.tile=Mock(return_value='point');backend.move_point=Mock();backend.key=Mock();backend.click_tile=Mock();events=[]
  backend.move_point.side_effect=lambda *a:events.append('move');backend.key.side_effect=lambda *a:events.append('key')
  config=copy.deepcopy(DEFAULT);config['catch']['mode']='smart_use';backend.capture({},'3',config)
  self.assertEqual(events,['move','key']);backend.click_tile.assert_not_called()
 def test_invalid_capture_mode_is_rejected(self):
  with self.assertRaises(ValueError):validate({'catch':{'mode':'unknown'}})

class CaptureIsolationTests(unittest.TestCase):
 def test_hung_capture_raises_clear_error(self):
  from helper_debug import capture_isolated
  import subprocess
  with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('capture',6)):
   with self.assertRaisesRegex(RuntimeError,'prazo'):capture_isolated(1,'unused.png')

class OwnRefreshTests(unittest.TestCase):
 def setup_reader(self):
  r=Reader.__new__(Reader);r.own_id=10;r.own_refresh={'old':10,'before':{10,20},'name':'charmander','pid':1,'player':5,'deadline':105,'lost':False};return r
 def obj(self,ident,x=10):return {'creature_type':3,'id':ident,'name':'Charmander','active':True,'hp':100,'position':{'x':x,'y':10,'z':7}}
 def player(self):return {'id':5,'position':{'x':10,'y':10,'z':7}}
 def test_stop_keeps_passive_revive_observation(self):
  from helper_native import Input
  r=self.setup_reader();backend=Input(r,copy.deepcopy(DEFAULT));pending=r.own_refresh;backend.release();self.assertIs(r.own_refresh,pending)
 def test_initial_own_identification_uses_own_summon_type(self):
  r=self.setup_reader();r.own_refresh=None;r.config={'own_pokemon':'Charmander'};a=self.obj(30);a['creature_type']=3;b=self.obj(31);b['creature_type']=4
  self.assertFalse(r.refresh_own({'pid':1},self.player(),[a,b],101));self.assertEqual(r.own_id,30)
 def test_revive_rebinds_only_new_nearby_instance(self):
  r=self.setup_reader();self.assertFalse(r.refresh_own({'pid':1},self.player(),[self.obj(20),self.obj(30)],101));self.assertEqual(r.own_id,30)
 def test_new_same_name_other_owner_is_not_adopted_during_revive(self):
  r=self.setup_reader();other=self.obj(30);other['creature_type']=4
  self.assertTrue(r.refresh_own({'pid':1},self.player(),[other],101));self.assertEqual(r.own_id,10)
  own=self.obj(31);self.assertFalse(r.refresh_own({'pid':1},self.player(),[other,own],102));self.assertEqual(r.own_id,31)
 def test_ambiguous_new_instances_wait(self):
  r=self.setup_reader();self.assertTrue(r.refresh_own({'pid':1},self.player(),[self.obj(30),self.obj(31)],101));self.assertEqual(r.own_id,10)
 def test_distant_same_species_is_not_adopted(self):
  r=self.setup_reader();self.assertTrue(r.refresh_own({'pid':1},self.player(),[self.obj(30,15)],101));self.assertEqual(r.own_id,10)
 def test_character_change_cancels_ownership(self):
  r=self.setup_reader();self.assertFalse(r.refresh_own({'pid':2},self.player(),[self.obj(30)],101));self.assertIsNone(r.own_id)
 def test_pending_revive_pauses_healing_without_stopping(self):
  b=Backend();config=copy.deepcopy(DEFAULT);config['modules']['healing']=True;config['validation']['health']=True;e=Engine(b,config);e.start()
  frame={'online':True,'fresh':True,'focused':True,'player':self.player(),'creatures':[],'own_refresh_pending':True,'capabilities':{'health':False}}
  e.tick(frame);self.assertTrue(e.running);self.assertFalse(any(a[0]=='key'for a in b.actions))

class CreaturePresenceTests(unittest.TestCase):
 def object(self,removed):
  r=Reader.__new__(Reader);data=bytearray(752);struct.pack_into('<Q',data,0,0x400000);struct.pack_into('<II',data,32,10,10);data[40]=7;data[112:118]=b'Pidgey';struct.pack_into('<QQ',data,128,6,15);data[176]=100;data[374]=1;data[624]=0;data[746]=removed
  with patch('helper_native.a.read',return_value=bytes(data)):return r.object(1,0x300000,{'vtable':0x400000,'type':'.?AVMonster@@'})
 def test_removed_creature_is_not_active_target(self):self.assertFalse(self.object(1)['active'])
 def test_present_creature_remains_active_even_with_zero_624(self):self.assertTrue(self.object(0)['active'])

class WindowEnumerationTests(unittest.TestCase):
 def test_non_game_titles_are_never_queried(self):
  import teste_enter as e
  def enumerate_windows(callback,param):callback(1,param);callback(2,param);return True
  with patch.object(e.u,'EnumWindows',side_effect=enumerate_windows),patch.object(e.u,'IsWindowVisible',return_value=True),patch.object(e,'path',side_effect=lambda hwnd:'helper.exe'if hwnd==1 else e.GAME),patch.object(e,'title',return_value='PokeAlliance - Consult')as title:
   self.assertEqual(e.find_game(),2)
   title.assert_called_once_with(2)

class TileFreshnessTests(unittest.TestCase):
 def test_stale_or_other_client_frame_never_clicks(self):
  from helper_native import Input
  from unittest.mock import Mock
  import time
  config=copy.deepcopy(DEFAULT);config['grid']['ready']=True
  for frame in ({'observed_monotonic':time.monotonic()-5,'pid':1,'hwnd':2},{'observed_monotonic':time.monotonic(),'pid':3,'hwnd':2}):
   reader=Mock();reader.last_frame={**frame,'player':{'position':{'x':1,'y':1,'z':7}}}
   backend=Input(reader,config);backend.focus=lambda:{'pid':1,'hwnd':2}
   with patch('helper_native.direct.mouseDown')as click:
    with self.assertRaises(RuntimeError):backend.tile({'x':1,'y':1,'z':7},config)
    click.assert_not_called()

class OwnershipTests(unittest.TestCase):
 def test_npc_or_player_cannot_be_owned_pokemon(self):
  from helper_app import App
  from unittest.mock import Mock
  import threading
  for kind in ('npc','player','localplayer'):
   app=App.__new__(App);app.lock=threading.RLock();app.frame={'creatures':[{'id':2,'active':True,'kind':kind}]};app.reader=Mock();app.persist_config=Mock()
   with self.assertRaises(RuntimeError):app.action({'action':'set_own','id':2})
   app.persist_config.assert_not_called()
 def test_window_uses_configured_game_path(self):
  r=Reader.__new__(Reader);r.config={'game_path':'D:/selected/game.exe'}
  with patch('helper_native.e.find_game',side_effect=RuntimeError('checked'))as find:
   with self.assertRaises(RuntimeError):r.window()
   find.assert_called_once_with('D:/selected/game.exe')

class RemovedDeathTests(unittest.TestCase):
 def reader(self):
  r=Reader.__new__(Reader);r.retired={};r.last_objects={0x300000:{'id':0x300000,'vtable':0x400000,'name':'Shiny Pidgey','active':True,'hp':80,'position':{'x':10,'y':10,'z':7}}}
  return r
 def test_disappeared_living_object_is_never_death(self):
  r=self.reader();r.object=lambda *args:{'name':'Shiny Pidgey','hp':80}
  self.assertEqual(r.removed_deaths(1,set(),{0x400000:{'vtable':0x400000}},100),[])
  r.last_objects={};self.assertEqual(r.removed_deaths(1,set(),{0x400000:{'vtable':0x400000}},103),[]);self.assertFalse(r.retired)
 def test_dead_object_preserves_last_known_tile(self):
  r=self.reader();r.object=lambda *args:{'id':0x300000,'name':'Shiny Pidgey','hp':0,'position':None}
  deaths=r.removed_deaths(1,set(),{0x400000:{'vtable':0x400000}},100)
  self.assertEqual(deaths[0]['position'],{'x':10,'y':10,'z':7});self.assertTrue(deaths[0]['death_confirmed']);self.assertFalse(deaths[0]['active'])
 def test_reused_object_name_is_rejected(self):
  r=self.reader();r.object=lambda *args:{'name':'Other','hp':0}
  self.assertEqual(r.removed_deaths(1,set(),{0x400000:{'vtable':0x400000}},100),[]);self.assertFalse(r.retired)

class StorageTests(unittest.TestCase):
 def test_transient_windows_sharing_violation_retries(self):
  from helper_storage import atomic_json
  from pathlib import Path
  import tempfile,json,os
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'runtime'/'tmp')as folder:
   target=Path(folder)/'state.json';target.write_text('{"old":true}')
   replace=os.replace;calls=[]
   def locked_once(source,dest):
    calls.append(1)
    if len(calls)==1:raise PermissionError('sharing violation')
    replace(source,dest)
   with patch('helper_storage.os.replace',side_effect=locked_once),patch('helper_storage.time.sleep'):
    atomic_json(target,{'new':True})
   self.assertEqual(json.loads(target.read_text()),{'new':True});self.assertEqual(len(calls),2)
   self.assertEqual(list(Path(folder).glob('*.tmp')),[])
 def test_permanent_failure_preserves_previous_status(self):
  from helper_storage import atomic_json
  from pathlib import Path
  import tempfile
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent/'runtime'/'tmp')as folder:
   target=Path(folder)/'state.json';target.write_text('previous')
   with patch('helper_storage.os.replace',side_effect=PermissionError('locked')),patch('helper_storage.time.sleep'):
    with self.assertRaises(PermissionError):atomic_json(target,{},attempts=2)
   self.assertEqual(target.read_text(),'previous');self.assertEqual(list(Path(folder).glob('*.tmp')),[])


class LabelIdentityTests(unittest.TestCase):
 def frame(self,network=10,pid=1):
  return {'pid':pid,'hwnd':2,'focused':True,'player':{'id':1},'creatures':[{'id':3,'network_id':network,'name':'Pidgey','active':True}]}
 def test_pink_remains_blocked_when_followup_sample_misses(self):
  from helper_labels import Labels
  labels=Labels();frame=self.frame();config={'grid':{'ready':True}}
  with patch('helper_labels.time.monotonic',return_value=100),patch.object(labels,'sample',side_effect=lambda f,g,n:labels.blocked.update({3:n+3})):
   labels.annotate(frame,config)
  with patch('helper_labels.time.monotonic',return_value=110),patch.object(labels,'sample'):
   labels.annotate(frame,config)
  self.assertTrue(frame['creatures'][0]['pink_name']);self.assertFalse(frame['creatures'][0]['attackable'])
 def test_missing_visual_sample_does_not_allow_wild_target(self):
  from helper_labels import Labels
  labels=Labels();frame=self.frame();frame['creatures'][0]['creature_type']=1
  with patch.object(labels,'sample'):
   labels.annotate(frame,{'grid':{'ready':True}})
  self.assertFalse(frame['creatures'][0]['attackable']);self.assertFalse(frame['creatures'][0]['label_checked'])
 def test_successful_recent_sample_allows_nonpink_wild(self):
  from helper_labels import Labels
  labels=Labels();frame=self.frame();frame['creatures'][0]['creature_type']=1
  def sample(f,g,n):labels.checked[3]=((10,'Pidgey'),n+.7)
  with patch.object(labels,'sample',side_effect=sample):
   labels.annotate(frame,{'grid':{'ready':True}})
  self.assertTrue(frame['creatures'][0]['attackable'])
 def test_confirmed_green_label_releases_previous_pink_identity(self):
  from helper_labels import Labels
  labels=Labels();identity=(10,'Oddish')
  labels.record_sample(3,identity,bytes([255,0,255,0])*25,100)
  self.assertIn(3,labels.blocked)
  labels.record_sample(3,identity,bytes([0,188,0,0])*25,101)
  self.assertNotIn(3,labels.blocked);self.assertGreater(labels.checked[3][1],101)
 def test_unknown_pixels_do_not_confirm_attackability(self):
  from helper_labels import Labels
  labels=Labels();labels.record_sample(3,(10,'Oddish'),bytes([50,100,40,0])*30,100)
  self.assertEqual(labels.checked[3][1],100)
 def test_native_capture_png_decodes_known_label_colors(self):
  from helper_labels import decode_capture_png,pink_pixels,green_pixels
  from helper_debug import png_chunk
  import zlib
  row=b'\x00'+bytes([255,0,255,0,188,0])
  png=b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('>IIBBBBB',2,1,8,2,0,0,0))+png_chunk(b'IDAT',zlib.compress(row))+png_chunk(b'IEND',b'')
  width,height,raw=decode_capture_png(png)
  self.assertEqual((width,height),(2,1));self.assertEqual(raw,row)
  self.assertEqual(pink_pixels(bytes([255,0,255,0,0,188,0,0])),1)
  self.assertEqual(green_pixels(bytes([255,0,255,0,0,188,0,0])),1)
 def test_reused_address_does_not_inherit_pink_name(self):
  from helper_labels import Labels
  labels=Labels();config={'grid':{'ready':True}}
  with patch('helper_labels.time.monotonic',return_value=100),patch.object(labels,'sample',side_effect=lambda f,g,n:labels.blocked.update({3:n+3})):
   labels.annotate(self.frame(),config)
  replacement=self.frame(network=11)
  with patch('helper_labels.time.monotonic',return_value=101),patch.object(labels,'sample'):
   labels.annotate(replacement,config)
  self.assertFalse(replacement['creatures'][0]['pink_name'])
 def test_client_change_clears_old_pink_identity(self):
  from helper_labels import Labels
  labels=Labels();config={'grid':{'ready':True}}
  with patch('helper_labels.time.monotonic',return_value=100),patch.object(labels,'sample',side_effect=lambda f,g,n:labels.blocked.update({3:n+3})):
   labels.annotate(self.frame(),config)
  replacement=self.frame(pid=5)
  with patch('helper_labels.time.monotonic',return_value=101),patch.object(labels,'sample'):
   labels.annotate(replacement,config)
  self.assertFalse(replacement['creatures'][0]['pink_name'])

class RealFrameReplayTests(unittest.TestCase):
 def test_real_death_trace_obeys_shiny_filter_and_never_duplicates(self):
  import json
  from pathlib import Path
  trace=json.loads((Path(__file__).parent/'fixtures/pidgey-real-death.json').read_text(encoding='utf-8'))['frames']
  self.assertTrue(any(o['hp']==0 for frame in trace for o in frame['creatures']))
  for shiny,expected in ((False,0),(True,1)):
   backend=Backend();config=copy.deepcopy(DEFAULT);config['own_pokemon']='Charmander';config['modules']['catch']=True;config['keys']['ball']='3';config['validation'].update(creatures=True,health=True)
   config['grid'].update(ready=True,center_x=960,center_y=508.5,tile_x=1920/21,tile_y=1920/21,client_width=1920,client_height=1017,viewport=[0,40,1725,957])
   clock=[100.];engine=Engine(backend,config,lambda:clock[0])
   for raw in trace:
    frame=copy.deepcopy(raw);clock[0]=100+frame['at']
    if shiny:
     for obj in frame['creatures']:obj['name']='Shiny '+obj['name'];obj['shiny']=True
    engine.deaths(frame);engine.catching(frame,clock[0])
   for _ in range(4):clock[0]+=.6;engine.deaths(frame);engine.catching(frame,clock[0])
   self.assertEqual(sum(a[0]=='capture'for a in backend.actions),expected)

if __name__=='__main__':unittest.main(verbosity=2)
