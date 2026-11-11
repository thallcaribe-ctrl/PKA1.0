"""Teste unico: Enter com down/espera/up no PokeAlliance original."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import time,json,datetime,sys
import pydirectinput as direct
import controle_basico as control
u=control.u
k=c.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)]
k.CloseHandle.argtypes=[w.HANDLE]
u.IsWindowVisible.argtypes=[w.HWND]
u.SetForegroundWindow.argtypes=[w.HWND]
u.ShowWindow.argtypes=[w.HWND,c.c_int]
ROOT=Path(__file__).resolve().parent
GAME=r'D:\PokeAlliance\PokeAlliance_dx.exe'

def title(hwnd):
 text=c.create_unicode_buffer(512);u.GetWindowTextW(hwnd,text,len(text));return text.value

def path(hwnd):
 pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,c.byref(pid));h=k.OpenProcess(0x1000,False,pid)
 if not h:return ''
 try:
  text=c.create_unicode_buffer(32768);length=w.DWORD(len(text))
  return text.value if k.QueryFullProcessImageNameW(h,0,text,c.byref(length)) else ''
 finally:k.CloseHandle(h)

def find_game(game_path=GAME):
 found=[];callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
 @callback
 def visit(hwnd,param):
  if u.IsWindowVisible(hwnd) and path(hwnd).lower()==game_path.lower() and title(hwnd).startswith('PokeAlliance'):found.append(hwnd)
  return True
 u.EnumWindows.argtypes=[callback,w.LPARAM];u.EnumWindows(visit,0)
 if len(found)!=1:raise RuntimeError(f'Esperava uma janela original; encontrei {len(found)}.')
 return found[0]

def press_enter(hwnd):
 if u.GetForegroundWindow()!=hwnd:raise RuntimeError('Cancelado: jogo nao esta em foco.')
 direct.keyDown('enter')
 started=time.perf_counter()
 try:time.sleep(0.180)
 finally:direct.keyUp('enter')
 return round((time.perf_counter()-started)*1000,2)

def main():
 if not c.windll.shell32.IsUserAnAdmin():raise RuntimeError('Abra Testar-Enter.cmd com Executar como administrador.')
 hwnd=find_game();before=title(hwnd)
 if ' - ' in before:raise RuntimeError('Janela ja indica personagem conectado; Enter nao foi enviado.')
 print('Teste unico: pressionar Enter, segurar 180 ms e soltar.',flush=True)
 print('Focando a janela do jogo em 3 segundos. Nao mude de janela durante o teste.',flush=True)
 time.sleep(3)
 u.ShowWindow(hwnd,9);u.SetForegroundWindow(hwnd);time.sleep(0.5)
 if path(hwnd).lower()!=GAME.lower():raise RuntimeError('Processo alvo mudou.')
 if ' - ' in title(hwnd):raise RuntimeError('Personagem ja conectado; teste cancelado.')
 held=press_enter(hwnd)
 time.sleep(3)
 after=title(hwnd)
 result={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'admin':True,'events':['keyDown(enter)','wait(180ms)','keyUp(enter)'],'actual_hold_ms':held,'title_before':before,'title_after':after,'reconnected_by_title':' - ' in after,'note':'Envio da sequencia nao garante que o cliente aceitou o comando.'}
 (ROOT/'resultado-enter.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
 try:main()
 except Exception as error:
  result={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'error':str(error),'reconnected_by_title':False}
  (ROOT/'resultado-enter.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('Falha:',error,flush=True);sys.exit(1)
