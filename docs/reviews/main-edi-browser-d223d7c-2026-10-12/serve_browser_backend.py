"""Observe actual ASGI request bytes without modifying requests or responses."""
import argparse
import json
import os
from pathlib import Path
import sys

p=argparse.ArgumentParser();p.add_argument('--repo',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
os.environ['TASK_DB_PATH']=str(a.runtime/'tasks.sqlite3');os.environ['PADDLE_OCR_ENABLED']='0'
for key in ['LLM_API_KEY','LLM_BASE_URL','LLM_MODEL']:os.environ[key]=''
sys.path.insert(0,str(a.repo/'backend'))
from app import config
config.DATA_DIR=a.runtime;config.UPLOAD_DIR=a.runtime/'uploads';config.TASK_DIR=a.runtime/'legacy'
from app.main import app
class Audit:
    def __init__(self,app):self.app=app;self.count=0
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method')!='POST' or scope['path']!='/api/v1/checks':
            return await self.app(scope,receive,send)
        self.count+=1;number=self.count;chunks=[]
        async def observed_receive():
            message=await receive()
            if message['type']=='http.request':chunks.append(message.get('body',b''))
            return message
        try:return await self.app(scope,observed_receive,send)
        finally:
            root=a.runtime.parent/'audit-requests';root.mkdir(exist_ok=True)
            (root/f'{number}.multipart').write_bytes(b''.join(chunks))
            (root/f'{number}.json').write_text(json.dumps({'method':'POST','path':scope['path'],
                'headers':{k.decode('latin1'):v.decode('latin1') for k,v in scope['headers']},'body_file':f'{number}.multipart'},indent=2)+'\n',encoding='utf-8')
import uvicorn
uvicorn.run(Audit(app),host='127.0.0.1',port=a.port,log_level='warning')
