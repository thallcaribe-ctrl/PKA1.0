"""Aplicativo do helper: painel local, motor, leitor e overlay por sessao Windows."""
import ctypes as c
from ctypes import wintypes as w
import threading,time,json,secrets,datetime,sys,re,copy,webbrowser,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
import helper_settings as settings
from helper_engine import Engine
from helper_native import Reader,Input
from helper_overlay import Overlay
import teste_enter as enter
ROOT=Path(__file__).resolve().parent
TASK_TEMP=ROOT/'runtime'/'tmp';TASK_TEMP.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=str(TASK_TEMP);os.environ['TMP']=str(TASK_TEMP);os.environ['PYTHONDONTWRITEBYTECODE']='1'

from helper_storage import atomic_json as atomic

def session_id():
 k=c.WinDLL('kernel32');k.GetCurrentProcessId.restype=w.DWORD;k.ProcessIdToSessionId.argtypes=[w.DWORD,c.POINTER(w.DWORD)]
 ident=w.DWORD()
 if not k.ProcessIdToSessionId(k.GetCurrentProcessId(),c.byref(ident)):raise RuntimeError('Nao foi possivel identificar a sessao Windows')
 return ident.value

class App:
 def __init__(self,session):
  self.config=settings.load();self.reader=Reader(self.config);self.backend=Input(self.reader,self.config);self.engine=Engine(self.backend,self.config)
  self.lock=threading.RLock();self.frame={};self.error=None;self.session=session;self.runtime=ROOT/'runtime'/f'session-{session}';self.runtime.mkdir(parents=True,exist_ok=True)
  self.overlay=Overlay(self.snapshot);self.pending_start=False;self.pending_input=None;self.calibrating=False;self.calibration={};self.record_identity=None;self.seen=set();self.last_scan_attempt=0;self.last_debug=None
 def snapshot(self):
  with self.lock:return {'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'session':self.session,'config':copy.deepcopy(self.config),'frame':copy.deepcopy(self.frame),'engine':self.engine.snapshot(),'error':self.error,'overlay_error':self.overlay.error,'inputs':list(self.backend.events),'calibrating':self.calibrating,'calibration_marks':list(self.calibration),'pending_start':self.pending_start,'pending_input':self.pending_input}
 def persist_config(self,config):
  if self.engine.running:raise RuntimeError('Pare o helper antes de alterar a configuracao')
  validated=settings.validate(config);saved=settings.save(validated)
  self.engine.configure(saved);self.config=saved;self.reader.config=saved;self.backend.config=saved
  self.pending_start=False
 def action(self,request):
  action=request.get('action')
  if action=='debug_threads':
   import faulthandler
   path=self.runtime/'threads.log'
   with path.open('w',encoding='utf-8')as output:faulthandler.dump_traceback(file=output)
   return {'file':str(path)}
  with self.lock:
   if action=='stop':self.pending_start=False;self.pending_input=None;self.engine.stop('Parado pelo usuario')
   elif action=='start':
    issues=self.engine.requirements()
    if issues:raise RuntimeError('; '.join(issues))
    self.pending_start=True;self.engine.status='Armado: volte ao jogo para iniciar'
   elif action=='focus':return self.backend.activate(bool(request.get('maximize',False)))
   elif action=='debug_references':return {'references':self.reader.reference_locations()}
   elif action=='debug_capture':
    if self.engine.running:raise RuntimeError('Pare o helper antes da captura de diagnostico')
    from helper_debug import capture_isolated as capture
    state=self.reader.window()
    result=capture(state['hwnd'],self.runtime/'debug-latest.png',request.get('mode','print'))
    self.last_debug={**result,'at':time.monotonic(),'hwnd':state['hwnd'],'pid':state['pid']}
    return result
   elif action in ('test_click','test_drag','test_move'):
    if self.engine.running:raise RuntimeError('Pare antes do clique de diagnostico')
    capture=self.last_debug;state=self.reader.window()
    if not capture or time.monotonic()-capture['at']>60 or capture['hwnd']!=state['hwnd']or capture['pid']!=state['pid']:raise RuntimeError('Capture novamente antes do clique de diagnostico')
    if action=='test_drag':self.backend.drag_client(request['x'],request['y'],request['end_x'],request['end_y'],capture['width'],capture['height'])
    else:self.backend.click_client(request['x'],request['y'],capture['width'],capture['height'],('move'if action=='test_move'else request.get('button','left')),request.get('modifiers'))
   elif action=='scan':self.reader.scan()
   elif action=='config':self.persist_config(request['config'])
   elif action=='record_start':
    if not self.frame.get('online')or not self.frame.get('player'):raise RuntimeError('Jogador ainda nao identificado')
    self.engine.begin_recording();self.record_identity=None
   elif action=='record_stop':
    route=self.engine.end_recording();stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S');path=ROOT/'rotas'/f'rota-s{self.session}-{stamp}.json';atomic(path,{'schema':1,'waypoints':route});return {'route':route,'file':str(path)}
   elif action=='use_recording':
    if self.engine.running:raise RuntimeError('Pare antes de carregar a rota')
    config=copy.deepcopy(self.config);config['route']=self.engine.recorded;self.persist_config(config)
   elif action=='import_route':
    route=request['route'];route=route.get('waypoints',route)if isinstance(route,dict)else route
    config=copy.deepcopy(self.config);config['route']=route;self.persist_config(config)
   elif action=='macro':self.engine.start_macro(int(request['index']))
   elif action=='calibrate':
    self.engine.stop('Calibrando grade');self.pending_start=False;self.calibrating=True;self.calibration={}
   elif action=='cancel_calibration':self.calibrating=False
   elif action=='set_own':
    ident=request['id'];obj=next((o for o in self.frame.get('creatures',[])if o['id']==ident and o.get('active')),None)
    if not obj:raise RuntimeError('Criatura nao encontrada na colecao ativa')
    if obj.get('kind')not in ('monster','creature'):raise RuntimeError('Selecione um Pokemon, nao um jogador ou NPC')
    if obj.get('creature_type')not in (None,3):raise RuntimeError('O cliente nao identifica este Pokemon como seu')
    if self.engine.running:raise RuntimeError('Pare antes de identificar seu Pokemon')
    self.reader.own_id=ident;config=copy.deepcopy(self.config);config['own_pokemon']=obj['name'];self.persist_config(config)
   elif action=='validate_creatures':
    if not self.frame.get('capabilities',{}).get('creatures'):raise RuntimeError('Colecao ativa ainda nao confirmada pelo leitor')
    config=copy.deepcopy(self.config);config['validation']['creatures']=True;self.persist_config(config)
   elif action=='validate_health':
    own=next((o for o in self.frame.get('creatures',[])if o['id']==self.reader.own_id),None)
    if not own or own['hp']!=request.get('observed_percent'):raise RuntimeError('Compare a porcentagem mostrada no jogo com o Pokemon selecionado')
    config=copy.deepcopy(self.config);config['validation']['health']=True;self.persist_config(config)
   elif action in ('test_step','reconnect'):
    if self.engine.running:raise RuntimeError('Pare o helper antes de um teste manual')
    direction=request.get('direction','right')
    if action=='test_step'and direction not in ('up','down','left','right'):raise ValueError('Direcao invalida')
    self.pending_input={'action':action,'direction':direction,'deadline':time.monotonic()+30};self.engine.status='Teste armado: volte ao jogo em ate 30 segundos'
   else:raise ValueError('Acao desconhecida')
  return {'ok':True}
 def calibration_tick(self,frame):
  if not self.calibrating or not frame.get('focused'):return
  u=enter.u
  if not(u.GetAsyncKeyState(0x11)&0x8000 and u.GetAsyncKeyState(0x10)&0x8000):return
  for key,label in [(0x74,'center'),(0x75,'east'),(0x76,'south'),(0x77,'top_left'),(0x78,'bottom_right')]:
   if not u.GetAsyncKeyState(key)&0x8000:continue
   if label in self.calibration:continue
   point=w.POINT();u.GetCursorPos(c.byref(point));u.ScreenToClient(frame['hwnd'],c.byref(point));self.calibration[label]=[point.x,point.y];self.engine.log('Calibracao: '+label)
  if len(self.calibration)==5:
   marks=self.calibration;rect=w.RECT();u.GetClientRect(frame['hwnd'],c.byref(rect));cx,cy=marks['center'];tx=marks['east'][0]-cx;ty=marks['south'][1]-cy
   config=copy.deepcopy(self.config);config['grid']={'ready':True,'center_x':cx,'center_y':cy,'tile_x':tx,'tile_y':ty,'client_width':rect.right,'client_height':rect.bottom,'viewport':marks['top_left']+marks['bottom_right']}
   self.persist_config(config);self.calibrating=False;self.engine.log('Grade calibrada')
 def input_tick(self,frame):
  pending=self.pending_input
  if not pending:return
  if time.monotonic()>pending['deadline']:self.pending_input=None;self.engine.status='Teste cancelado: prazo sem foco';return
  if not frame.get('focused'):return
  self.pending_input=None
  if pending['action']=='reconnect':
   if frame.get('online'):raise RuntimeError('Personagem ja esta online')
   import pydirectinput as direct
   direct.keyDown('enter')
   try:time.sleep(self.config['timing']['hold_ms']/1000)
   finally:direct.keyUp('enter')
   self.engine.log('Enter enviado com down/espera/up');return
  if not frame.get('player'):raise RuntimeError('Jogador nao identificado')
  before=frame['player']['position'];self.backend.walk(pending['direction'],self.config['timing']['hold_ms']);time.sleep(1)
  after=self.reader.snapshot().get('player',{}).get('position');self.engine.log(f'Teste {pending["direction"]}: {before} -> {after}')
 def run(self):
  last_write=0
  while True:
   try:
    if enter.u.GetAsyncKeyState(0x7b)&0x8000:
     with self.lock:self.pending_start=False;self.pending_input=None;self.engine.stop('Emergencia F12')
    frame=self.reader.snapshot()
    with self.lock:
     self.frame=frame
     if frame.get('online')and not self.reader.discovery and not self.reader.scanning and time.monotonic()-self.last_scan_attempt>30:
      self.last_scan_attempt=time.monotonic();self.reader.scan()
     if self.engine.recording and(not frame.get('online')or not frame.get('player')):self.engine.end_recording();self.engine.log('Gravacao interrompida: conexao/leitura indisponivel')
     if self.engine.recording and frame.get('player'):
      identity=(frame['pid'],frame['player']['id'])
      if self.record_identity is None:self.record_identity=identity
      if self.record_identity!=identity:self.engine.end_recording();self.engine.log('Gravacao interrompida: jogador mudou')
     self.calibration_tick(frame);self.input_tick(frame)
     if self.pending_start and frame.get('online')and frame.get('focused')and frame.get('player'):
      self.engine.start();self.pending_start=False
     before_count=len(self.engine.recorded);self.engine.tick(frame)
     if len(self.engine.recorded)!=before_count:atomic(self.runtime/'gravacao-em-andamento.json',{'schema':1,'waypoints':self.engine.recorded})
    if time.monotonic()-last_write>.5:atomic(self.runtime/'status.json',self.snapshot());last_write=time.monotonic()
    request_path=self.runtime/'request.json'
    if request_path.exists():
     req=json.loads(request_path.read_text(encoding='utf-8'));ident=req.get('id')
     if isinstance(ident,str)and ident not in self.seen:
      self.seen.add(ident)
      try:answer=self.action(req);result={'id':ident,'ok':True,'result':answer}
      except Exception as error:result={'id':ident,'ok':False,'error':str(error)}
      atomic(self.runtime/'response.json',result)
    self.error=None
   except Exception as error:
    self.error=str(error)
    with self.lock:self.engine.stop('Erro: '+str(error));self.pending_start=False
   time.sleep(.1)

class Server(ThreadingHTTPServer):daemon_threads=True

def main():
 if not c.windll.shell32.IsUserAnAdmin():raise RuntimeError('Abra Iniciar-helper.cmd com Executar como administrador')
 session=session_id();app=App(session);token=secrets.token_urlsafe(32);port=18764+session
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def send_json(self,value,status=200):
   data=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
  def authorized(self):return secrets.compare_digest(self.headers.get('X-Helper-Token',''),token)
  def do_GET(self):
   if urlparse(self.path).path=='/':
    data=(ROOT/'helper_ui.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
   elif urlparse(self.path).path=='/api/debug-image'and self.authorized():
    path=app.runtime/'debug-latest.png'
    if not path.is_file():self.send_json({'error':'Capture a janela primeiro'},404);return
    data=path.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
   elif urlparse(self.path).path=='/api/state'and self.authorized():self.send_json(app.snapshot())
   else:self.send_json({'error':'Nao autorizado ou rota inexistente'},403)
  def do_POST(self):
   origin=self.headers.get('Origin');expected=f'http://127.0.0.1:{port}'
   if not self.authorized()or origin and origin!=expected:self.send_json({'error':'Nao autorizado'},403);return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=1024*1024:raise ValueError('Corpo invalido')
    if urlparse(self.path).path!='/api/action':raise ValueError('Rota inexistente')
    request=json.loads(self.rfile.read(length));result=app.action(request);self.send_json(result)
   except Exception as error:self.send_json({'error':str(error)},400)
 server=Server(('127.0.0.1',port),Handler);url=f'http://127.0.0.1:{port}/?token={token}'
 atomic(ROOT/'helper-session.json',{'session':session,'port':port,'url':url,'runtime':str(app.runtime),'pid':c.windll.kernel32.GetCurrentProcessId()})
 threading.Thread(target=app.run,daemon=True).start();app.overlay.start()
 print('PokeHunt: painel local na porta',port,'sessao Windows',session,flush=True)
 print('F12 para parar as acoes. Fechar esta janela encerra o helper.',flush=True)
 if '--no-browser'not in sys.argv:
  from helper_start import open_panel
  open_panel(url)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:app.engine.stop('Aplicativo encerrado');server.server_close()

if __name__=='__main__':
 try:main()
 except Exception as error:print('Falha:',error,flush=True);sys.exit(1)
