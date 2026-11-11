"""Publicacao JSON atomica com tolerancia a leitores Windows."""
import json,os,time,uuid
from pathlib import Path

def atomic_json(path,value,attempts=8):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
  for attempt in range(attempts):
   try:os.replace(temp,path);return
   except PermissionError:
    if attempt+1==attempts:raise
    time.sleep(.02*(attempt+1))
 finally:
  try:temp.unlink(missing_ok=True)
  except OSError:pass
