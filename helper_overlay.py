"""Overlay separado, transparente a cliques, para debug de tiles e rota."""
import threading,ctypes as c
from ctypes import wintypes as w

class Overlay:
 def __init__(self,get_state):self.get_state=get_state;self.error=None;self.thread=None
 def start(self):
  self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def run(self):
  try:
   import tkinter as tk
   u=c.WinDLL('user32',use_last_error=True)
   u.ClientToScreen.argtypes=[w.HWND,c.POINTER(w.POINT)]
   u.GetClientRect.argtypes=[w.HWND,c.POINTER(w.RECT)]
   u.GetParent.argtypes=[w.HWND];u.GetParent.restype=w.HWND
   getlong=u.GetWindowLongPtrW if c.sizeof(c.c_void_p)==8 else u.GetWindowLongW
   setlong=u.SetWindowLongPtrW if c.sizeof(c.c_void_p)==8 else u.SetWindowLongW
   getlong.argtypes=[w.HWND,c.c_int];getlong.restype=c.c_ssize_t
   setlong.argtypes=[w.HWND,c.c_int,c.c_ssize_t];setlong.restype=c.c_ssize_t
   root=tk.Tk();root.title('PokeHunt Debug');root.overrideredirect(True);root.configure(bg='#010203')
   root.attributes('-topmost',True);root.attributes('-transparentcolor','#010203');root.attributes('-disabled',True);root.configure(takefocus=False);root.withdraw()
   canvas=tk.Canvas(root,bg='#010203',highlightthickness=0);canvas.pack(fill='both',expand=True)
   root.update_idletasks();hwnd=u.GetParent(root.winfo_id())or root.winfo_id();setlong(hwnd,-20,getlong(hwnd,-20)|0x80000|0x20|0x08000000|0x80)
   def draw():
    try:
     data=self.get_state();frame=data.get('frame',{});config=data['config'];g=config['grid']
     if not config['overlay']or not frame.get('focused')or not frame.get('player')or not g['ready']:
      root.withdraw();root.after(150,draw);return
     point=w.POINT(0,0);u.ClientToScreen(frame['hwnd'],c.byref(point));rect=w.RECT();u.GetClientRect(frame['hwnd'],c.byref(rect))
     if (rect.right,rect.bottom)!=(g['client_width'],g['client_height']):root.withdraw();root.after(150,draw);return
     root.geometry(f'{rect.right}x{rect.bottom}+{point.x}+{point.y}');root.deiconify();canvas.delete('all')
     player=frame['player']['position'];left,top,right,bottom=g['viewport']
     def tile(position,color,label):
      if position['z']!=player['z']:return
      x=g['center_x']+(position['x']-player['x'])*g['tile_x'];y=g['center_y']+(position['y']-player['y'])*g['tile_y']
      if not(left<=x<right and top<=y<bottom):return
      sx,sy=g['tile_x']/2,g['tile_y']/2
      x1,y1,x2,y2=max(left,x-sx),max(top,y-sy),min(right,x+sx),min(bottom,y+sy)
      canvas.create_rectangle(x1,y1,x2,y2,outline=color,width=2)
      canvas.create_text(x1+4,y1+4,text=label,fill=color,anchor='nw',font=('Segoe UI',10,'bold'))
     for index,waypoint in enumerate(config['route']):tile(waypoint,'#20d99a',str(index+1))
     for obj in frame.get('creatures',[]):
      if obj.get('active'):tile(obj['position'],'#f6d44a'if obj.get('shiny')else'#ef8c54',obj['name'])
     tile(player,'#28c8ef','VOCE')
     if data.get('engine',{}).get('target'):tile(data['engine']['target']['position'],'#ff4a73','ALVO')
     canvas.create_text(left+8,top+8,text=data.get('engine',{}).get('status',''),fill='#fff',anchor='nw',font=('Segoe UI',12,'bold'))
    except Exception as error:self.error=str(error)
    root.after(150,draw)
   root.after(100,draw);root.mainloop()
  except Exception as error:self.error=str(error)
