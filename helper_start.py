"""Iniciador unico: reabre painel existente ou solicita elevacao Windows."""
import os,sys,json,ctypes as c,subprocess,webbrowser,urllib.request
from pathlib import Path
from urllib.parse import urlparse,parse_qs
ROOT=Path(__file__).resolve().parent
TMP=ROOT/'runtime'/'tmp';TMP.mkdir(parents=True,exist_ok=True)
os.environ['TEMP']=str(TMP);os.environ['TMP']=str(TMP);os.environ['PYTHONDONTWRITEBYTECODE']='1'

def existing(session):
 try:
  info=json.loads((ROOT/'helper-session.json').read_text(encoding='utf-8'));url=urlparse(info['url'])
  if info['session']!=session or url.scheme!='http'or url.hostname!='127.0.0.1'or url.port!=18764+session:return None
  token=parse_qs(url.query)['token'][0]
  req=urllib.request.Request(f'http://127.0.0.1:{url.port}/api/state',headers={'X-Helper-Token':token})
  with urllib.request.urlopen(req,timeout=2)as response:state=json.load(response)
  return info['url']if state['session']==session else None
 except (OSError,ValueError,KeyError,IndexError):return None

def open_panel(url):
 candidates=[Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Google/Chrome/Application/chrome.exe']
 chrome=next((p for p in candidates if p.is_file()),None)
 if chrome is None:raise RuntimeError('Chrome nao encontrado para abrir o painel local')
 profile=ROOT/'runtime'/'panel-browser';profile.mkdir(parents=True,exist_ok=True)
 return subprocess.Popen([str(chrome),'--user-data-dir='+str(profile),'--no-first-run','--disable-background-networking','--app='+url],env=os.environ.copy()).pid

def main():
 from helper_app import session_id
 url=existing(session_id())
 if url:open_panel(url);print('Painel existente reaberto');return
 if c.windll.shell32.IsUserAnAdmin():
  with (ROOT/'runtime'/'helper-stdout.log').open('w')as out,(ROOT/'runtime'/'helper-stderr.log').open('w')as err:
   subprocess.Popen([sys.executable,'-B',str(ROOT/'helper_app.py')],cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
 else:
  shell=c.WinDLL('shell32',use_last_error=True);shell.ShellExecuteW.argtypes=[c.c_void_p,c.c_wchar_p,c.c_wchar_p,c.c_wchar_p,c.c_wchar_p,c.c_int];shell.ShellExecuteW.restype=c.c_void_p
  result=shell.ShellExecuteW(None,'runas',sys.executable,subprocess.list2cmdline(['-B',str(ROOT/'helper_app.py')]),str(ROOT),0)
  if not result or result<=32:raise RuntimeError('Windows nao autorizou iniciar o helper elevado')

if __name__=='__main__':
 try:main()
 except Exception as error:print('Falha:',error);sys.exit(1)
