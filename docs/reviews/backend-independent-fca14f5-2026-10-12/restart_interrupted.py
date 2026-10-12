"""Restart the actual interrupted OCR attempt and inspect public states and retained bytes."""
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import httpx

root=Path(__file__).resolve().parent
source=Path(r'D:\hackson\tmp\review37-fca14f5-20261012')
attempt=root/'ocr-diagnostic'
out=root/'interrupted-restart'
out.mkdir(exist_ok=True)
def save(name,value):
    (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
request=json.loads((attempt/'requests/SCAN-PNG-SHP-00001.json').read_text(encoding='utf-8'))
task_id=request['post_response']['task_id']
with sqlite3.connect(f'file:{(attempt/"runtime/tasks.sqlite3").as_posix()}?mode=ro',uri=True) as conn:
    before=json.loads(conn.execute('SELECT payload_json FROM api_task_payloads WHERE task_id=?',(task_id,)).fetchone()[0])
save('before-internal.json',before)
assert before['status']=='PROCESSING',before['status']
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
with (out/'server.log').open('wb') as log:
    process=subprocess.Popen([sys.executable,'-X','utf8',str(root/'serve_candidate.py'),'--repo',str(source),
                              '--runtime',str(attempt/'runtime'),'--port',str(port)],stdout=log,stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=30,trust_env=False) as client:
            for _ in range(200):
                if process.poll() is not None: raise RuntimeError('restart server exited')
                try:
                    if client.get('/health').status_code==200: break
                except httpx.HTTPError: pass
                time.sleep(.1)
            response=client.get(f'/api/v1/checks/{task_id}');response.raise_for_status();after=response.json()
            save('after-public.json',after)
            report=client.get(f'/api/v1/checks/{task_id}/report?format=json')
            report.raise_for_status();save('report.json',report.json())
            downloads=[]
            for index,file in enumerate(request['files'],1):
                r=client.get(f'/api/v1/checks/{task_id}/files/f{index}')
                downloads.append({'file_id':f'f{index}','file_name':file['file_name'],'http_status':r.status_code,
                                  'expected_sha256':file['sha256'],'actual_sha256':hashlib.sha256(r.content).hexdigest() if r.status_code==200 else None,
                                  'byte_identity':r.status_code==200 and hashlib.sha256(r.content).hexdigest()==file['sha256']})
            summary={'source_commit':'fca14f56910333c4bac8c72cfd6428ffe2fb6f2a','evidence':'real interrupted upload and real socket HTTP after restart',
                     'before_status':before['status'],'after_status':after['status'],
                     'interruption_explicit':any(e['code']=='TASK_INTERRUPTED' for e in after['errors']),
                     'published_documents_after_restart':after['documents'],'uploaded_files':len(request['files']),
                     'files_in_upload_directory':[p.name for p in (attempt/'runtime/uploads'/task_id).iterdir()],
                     'source_downloads':downloads,'report_http_status':report.status_code,
                     'limits':'No automatic resume; the crash attempt itself never produced terminal OCR results. Unstarted uploads remain outside documents.'}
            save('summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
    finally:
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
