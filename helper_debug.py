"""Captura de diagnostico da area cliente, sem dependencias externas."""
import ctypes as c,struct,zlib,json,time
from ctypes import wintypes as w
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def png_chunk(kind,data):
 return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)

def capture(hwnd,path,mode='print'):
 if mode not in ('print','screen'):raise ValueError('Modo de captura invalido')
 u=c.WinDLL('user32',use_last_error=True);g=c.WinDLL('gdi32',use_last_error=True)
 u.GetClientRect.argtypes=[w.HWND,c.POINTER(w.RECT)];u.GetDC.argtypes=[w.HWND];u.GetDC.restype=w.HDC
 u.ClientToScreen.argtypes=[w.HWND,c.POINTER(w.POINT)];u.ReleaseDC.argtypes=[w.HWND,w.HDC];u.PrintWindow.argtypes=[w.HWND,w.HDC,w.UINT]
 u.IsIconic.argtypes=[w.HWND];u.IsWindow.argtypes=[w.HWND]
 g.CreateCompatibleDC.argtypes=[w.HDC];g.CreateCompatibleDC.restype=w.HDC
 g.CreateCompatibleBitmap.argtypes=[w.HDC,c.c_int,c.c_int];g.CreateCompatibleBitmap.restype=w.HBITMAP
 g.SelectObject.argtypes=[w.HDC,w.HANDLE];g.SelectObject.restype=w.HANDLE
 g.BitBlt.argtypes=[w.HDC,c.c_int,c.c_int,c.c_int,c.c_int,w.HDC,c.c_int,c.c_int,w.DWORD]
 g.DeleteObject.argtypes=[w.HANDLE];g.DeleteDC.argtypes=[w.HDC]
 g.GetDIBits.argtypes=[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT]
 if not u.IsWindow(hwnd)or u.IsIconic(hwnd):raise RuntimeError('Janela invalida ou minimizada')
 rect=w.RECT()
 if not u.GetClientRect(hwnd,c.byref(rect)):raise c.WinError(c.get_last_error())
 width,height=rect.right,rect.bottom
 if not 1<=width<=8192 or not 1<=height<=8192:raise RuntimeError('Dimensoes invalidas')
 origin=w.POINT(0,0)
 if mode=='screen'and not u.ClientToScreen(hwnd,c.byref(origin)):raise RuntimeError('Origem da janela indisponivel')
 source=u.GetDC(None if mode=='screen'else hwnd);memory=g.CreateCompatibleDC(source);bitmap=g.CreateCompatibleBitmap(source,width,height)
 if not source or not memory or not bitmap:raise RuntimeError('Nao foi possivel criar bitmap de diagnostico')
 previous=g.SelectObject(memory,bitmap)
 try:
  ok=u.PrintWindow(hwnd,memory,3)if mode=='print'else g.BitBlt(memory,0,0,width,height,source,origin.x,origin.y,0x40cc0020)
  if not ok:raise RuntimeError('Captura nativa falhou')
  header=struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0)
  info=c.create_string_buffer(header+bytes(1024));pixels=c.create_string_buffer(width*height*4)
  g.SelectObject(memory,previous)
  if g.GetDIBits(memory,bitmap,0,height,pixels,info,0)!=height:raise RuntimeError('Leitura de bitmap falhou')
  raw=pixels.raw;rgb=bytearray(width*height*3);rgb[0::3]=raw[2::4];rgb[1::3]=raw[1::4];rgb[2::3]=raw[0::4]
  lines=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3]for y in range(height))
  png=b'\x89PNG\r\n\x1a\n'+png_chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+png_chunk(b'IDAT',zlib.compress(lines,3))+png_chunk(b'IEND',b'')
  path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(png)
  return {'file':str(path),'width':width,'height':height,'mode':mode,'sample_colors':len(set(tuple(rgb[i:i+3])for i in range(0,len(rgb),max(3,(len(rgb)//3000)//3*3))))}
 finally:
  g.SelectObject(memory,previous);g.DeleteObject(bitmap);g.DeleteDC(memory);u.ReleaseDC(None if mode=='screen'else hwnd,source)

def capture_isolated(hwnd,path,mode='print',timeout=6):
 import subprocess,sys
 try:
  result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--window',str(hwnd),'--out',str(path),'--mode',mode],capture_output=True,text=True,timeout=timeout,cwd=ROOT)
 except subprocess.TimeoutExpired:raise RuntimeError('Captura excedeu o prazo; processo de diagnostico encerrado')
 if result.returncode:raise RuntimeError(result.stderr.strip()or'Captura falhou')
 return json.loads(result.stdout)

if __name__=='__main__':
 import sys
 if '--window'in sys.argv:
  import argparse
  from teste_enter import find_game
  from helper_settings import load
  parser=argparse.ArgumentParser();parser.add_argument('--window',type=int);parser.add_argument('--out');parser.add_argument('--mode',choices=['print','screen']);args=parser.parse_args()
  if find_game(load()['game_path'])!=args.window:raise RuntimeError('Janela mudou antes da captura')
  print(json.dumps(capture(args.window,args.out,args.mode)));sys.exit(0)

 from teste_enter import find_game
 from helper_storage import atomic_json
 import sys
 results=[]
 try:
  hwnd=find_game()
  for mode in ('print','screen'):
   try:results.append(capture(hwnd,ROOT/'runtime'/'session-2'/('debug-'+mode+'.png'),mode))
   except Exception as error:results.append({'mode':mode,'error':str(error)})
 except Exception as error:results.append({'error':str(error)})
 atomic_json(ROOT/'runtime'/'session-2'/'debug-capture.json',results)