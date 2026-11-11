"""Registro local independente: conexao, screenshots e OCR. Nunca envia entradas."""
import argparse,ctypes,datetime,json,os,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'runtime'/'diagnostics'
LIMIT=512*1024*1024

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def safe_state(state):
 frame=state.get('frame',{});player=frame.get('player')or{};engine=state.get('engine',{})
 return {'online':frame.get('online'),'focused':frame.get('focused'),'pid':frame.get('pid'),'hwnd':frame.get('hwnd'),'title':frame.get('title'),'player':player.get('name'),'position':player.get('position'),'capabilities':frame.get('capabilities'),'engine_running':engine.get('running'),'engine_status':engine.get('status'),'error':state.get('error')or frame.get('error'),'source_utc':state.get('utc')}

def read_state():
 info=json.loads((ROOT/'helper-session.json').read_text(encoding='utf-8'));url=urlparse(info['url'])
 if url.scheme!='http'or url.hostname!='127.0.0.1'or url.port!=info['port']:raise ValueError('Sessao local invalida')
 token=parse_qs(url.query)['token'][0]
 req=urllib.request.Request(f'http://127.0.0.1:{url.port}/api/state',headers={'X-Helper-Token':token})
 with urllib.request.urlopen(req,timeout=2)as response:return json.load(response)

class Journal:
 def __init__(self,folder,budget=LIMIT):
  from helper_storage import atomic_json
  self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.path=self.folder/'events.jsonl';self.previous=None;self.text=None;self.count=0;self.budget=budget;self.exhausted=False
  atomic_json(self.folder/'manifest.json',{'started_utc':utc(),'timezone':'America/Sao_Paulo','screenshot_interval_s':2,'ocr_interval_s':10,'capture_scope':'somente janela do jogo','limitations':['Nao e video continuo. Mensagens curtas podem escapar.','OCR e transcricao aproximada do texto visivel, nao historico completo do chat.','Chat fechado, texto oculto, erros de captura e interrupcoes geram lacunas.'],'mode':'diagnostico local; nenhuma entrada ou resposta automatica'})
 def emit(self,kind,**fields):
  if self.exhausted:return
  line=json.dumps({'utc':utc(),'kind':kind,**fields},ensure_ascii=False)+'\n'
  if self.path.exists()and self.path.stat().st_size+len(line.encode('utf-8'))>20*1024*1024:self.exhausted=True;return
  with self.path.open('a',encoding='utf-8')as stream:stream.write(line)
  self.count+=1
 def observe(self,state):
  data=safe_state(state);comparable={k:v for k,v in data.items()if k!='source_utc'}
  if comparable!=self.previous:
   self.emit('state_change',before=self.previous,after=data);self.previous=comparable
 def visible_text(self,text,image):
  text='\n'.join(line.rstrip()for line in text.strip().splitlines())
  if text!=self.text:self.emit('visible_text_ocr',text=text,image=image,approximate=True);self.text=text
 def quota(self,total_bytes):return total_bytes<self.budget

def record():
 import msvcrt
 from helper_debug import capture_isolated
 from helper_storage import atomic_json
 from teste_enter import find_game
 from helper_settings import load
 BASE.mkdir(parents=True,exist_ok=True);lock=(BASE/'recorder.lock').open('a+b');lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
 except OSError:return
 stop=BASE/'STOP';stop.unlink(missing_ok=True)
 folder=BASE/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]);journal=Journal(folder)
 total=sum(p.stat().st_size for p in BASE.rglob('*')if p.is_file());next_image=next_ocr=next_status=next_heartbeat=0.;last_tick=time.monotonic();seq=0;images=0;last_error=None;last_connection=None;ocr=Path(r'C:/Program Files/Tesseract-OCR/tesseract.exe');reason='stop_requested'
 journal.emit('recorder_started',pid=os.getpid(),ocr_available=ocr.is_file())
 try:
  while not stop.exists():
   now=time.monotonic()
   if now-last_tick>1.5:journal.emit('sampling_gap',seconds=round(now-last_tick,3))
   last_tick=now;changed=False
   try:
    state=read_state();journal.observe(state);f=state.get('frame',{});connection=(f.get('online'),f.get('pid'),f.get('title'),f.get('error'));changed=connection!=last_connection;last_connection=connection;last_error=None
   except Exception as error:
    error_name=type(error).__name__
    if last_error!=error_name:journal.emit('helper_unavailable',error=error_name)
    last_error=error_name;state={}
   if now>=next_image or changed:
    next_image=now+2;seq+=1;image_name=datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S.%fZ')+f'-{seq:06d}.png';path=folder/image_name
    if not journal.quota(total+64*1024*1024):reason='storage_limit';journal.emit('storage_limit',limit_bytes=LIMIT,retained_bytes=total);break
    try:
     hwnd=find_game(load()['game_path']);started=time.monotonic();result=capture_isolated(hwnd,path,'print',timeout=3);total+=path.stat().st_size;images+=1;journal.emit('screenshot',image=image_name,width=result['width'],height=result['height'],capture_seconds=round(time.monotonic()-started,3),source_utc=state.get('utc'))
     if now>=next_ocr:
      next_ocr=now+10
      if ocr.is_file():
       try:
        result=subprocess.run([str(ocr),str(path),'stdout','-l','eng','--psm','11'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:journal.emit('ocr_gap',error='OCR exit '+str(result.returncode),image=image_name)
        else:journal.visible_text(result.stdout,image_name)
       except (OSError,subprocess.TimeoutExpired)as error:journal.emit('ocr_gap',error=type(error).__name__,image=image_name)
      else:journal.emit('ocr_gap',error='Tesseract nao instalado',image=image_name)
    except Exception as error:journal.emit('capture_gap',error=str(error)[:300])
   if now>=next_heartbeat:journal.emit('heartbeat',images=images,helper_available=not last_error);next_heartbeat=now+5
   if now>=next_status:
    atomic_json(BASE/'status.json',{'utc':utc(),'running':True,'pid':os.getpid(),'folder':str(folder),'images':images,'events':journal.count,'error':last_error,'retained_bytes_approx':total});next_status=now+2
   if journal.exhausted:reason='event_log_limit';break
   time.sleep(.5)
 finally:
  journal.emit('recorder_stopped',reason=reason,images=images);atomic_json(BASE/'status.json',{'utc':utc(),'running':False,'folder':str(folder),'images':images,'reason':reason});lock.close()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--record',action='store_true');parser.add_argument('--start',action='store_true');parser.add_argument('--stop',action='store_true');parser.add_argument('--status',action='store_true');args=parser.parse_args()
 BASE.mkdir(parents=True,exist_ok=True);os.environ['TEMP']=os.environ['TMP']=str(ROOT/'runtime/tmp');os.environ['PYTHONDONTWRITEBYTECODE']='1'
 if args.stop:(BASE/'STOP').write_text(utc());print('Parada solicitada');return
 if args.status:print((BASE/'status.json').read_text(encoding='utf-8')if(BASE/'status.json').exists()else'Nunca iniciado');return
 if args.record:record();return
 if args.start:
  if ctypes.windll.shell32.IsUserAnAdmin():
   subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--record'],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
  else:
   shell=ctypes.WinDLL('shell32');shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int];shell.ShellExecuteW.restype=ctypes.c_void_p
   result=shell.ShellExecuteW(None,'runas',sys.executable,subprocess.list2cmdline(['-B',str(Path(__file__).resolve()),'--record']),str(ROOT),0)
   if not result or result<=32:raise RuntimeError('Registro nao iniciado')
  print('Inicio solicitado. Confira --status.');return
 parser.print_help()
if __name__=='__main__':main()
