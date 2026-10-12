"""Start isolated current-main backend/frontend and run the independent browser check."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx

root=Path(__file__).resolve().parent
repo=Path(r'D:\hackson\tmp\followup-main-d223d7c-20261012')
pin='d223d7cfe94acccc60b96656f2f93f866b63e087'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==pin
def port():
    with socket.socket() as p:p.bind(('127.0.0.1',0));return p.getsockname()[1]
back,web=port(),port()
root.mkdir(exist_ok=True)
logs=[(root/'backend.log').open('wb'),(root/'frontend.log').open('wb')]
processes=[]
try:
    processes.append(subprocess.Popen([sys.executable,'-X','utf8',str(root/'serve_browser_backend.py'),
        '--repo',str(repo),'--runtime',str(root/'runtime'),'--port',str(back)],stdout=logs[0],stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    env={**os.environ,'VITE_PROXY_API':f'http://127.0.0.1:{back}','VITE_API_BASE':''}
    processes.append(subprocess.Popen(['node',str(repo/'web/node_modules/vite/bin/vite.js'),'--host','127.0.0.1',
        '--port',str(web),'--strictPort'],cwd=repo/'web',env=env,stdout=logs[1],stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    with httpx.Client(trust_env=False,timeout=3) as client:
        for _ in range(200):
            if any(p.poll() is not None for p in processes):raise RuntimeError('service exited; inspect logs')
            try:
                if client.get(f'http://127.0.0.1:{back}/health').status_code==200 and client.get(f'http://127.0.0.1:{web}/').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
    result=subprocess.run(['node',str(root/'browser_review.cjs'),f'http://127.0.0.1:{web}',str(repo),str(root/'browser')],timeout=180)
    (root/'run.json').write_text(json.dumps({'commit':pin,'backend_port':back,'web_port':web,'browser_exit_code':result.returncode,
        'external_ocr_llm_enabled':False,'production_accessed':False},indent=2)+'\n',encoding='utf-8')
finally:
    for process in reversed(processes):
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    for log in logs:log.close()
sys.exit(result.returncode)
