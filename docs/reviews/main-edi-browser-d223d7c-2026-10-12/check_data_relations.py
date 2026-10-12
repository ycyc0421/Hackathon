"""One actual multi-item HTTP upload, relational evidence check and completed-task restart."""
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
repo=Path(r'D:\hackson\tmp\followup-main-d223d7c-20261012')
out=root/'data-relations';out.mkdir(exist_ok=True)
runtime=out/'runtime'
checks=[]
def save(name,obj):(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def check(name,passed,actual=None):checks.append({'check':name,'passed':bool(passed),'actual':actual})
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
log=(out/'server.log').open('wb')
command=[sys.executable,'-X','utf8',str(root/'serve_browser_backend.py'),'--repo',str(repo),'--runtime',str(runtime),'--port',str(port)]
process=None
def start(client):
    global process
    process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(200):
        if process.poll() is not None:raise RuntimeError('backend exited')
        try:
            if client.get('/health').status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise TimeoutError('backend startup')
def stop():
    if process is not None and process.poll() is None:process.terminate()
    if process is not None:
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
try:
    with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=30) as client:
        start(client)
        paths=sorted((repo/'backend/samples/04_de_multiitem').glob('*.pdf'));assert len(paths)==3
        r=client.post('/api/v1/checks',data={'destination_country':'DE'},files=[('files',(p.name,p.read_bytes(),'application/pdf')) for p in paths]);r.raise_for_status()
        task_id=r.json()['task_id']
        for _ in range(200):
            task=client.get('/api/v1/checks/'+task_id).json()
            if task['status'] not in {'PENDING','PROCESSING'}:break
            time.sleep(.1)
        save('public.json',task)
        save('input.json',[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths])
        check('real three-file task completed',task['status']=='COMPLETED',task['status'])
        # The unchanged CI/PL originals each print four unique HM-1001..1004 rows.
        check('four item groups printed in the original CI/PL',len(task['items'])==4,len(task['items']))
        with sqlite3.connect(f'file:{(runtime/"tasks.sqlite3").as_posix()}?mode=ro',uri=True) as conn:
            internal=json.loads(conn.execute('SELECT payload_json FROM api_task_payloads WHERE task_id=?',(task_id,)).fetchone()[0]);save('internal.json',internal)
            expected=[f for e in internal['extractions'] for row in e.get('line_items',[]) for f in row['fields']]
            actual=conn.execute('SELECT field_key,normalized_value_json,raw_value,raw_text,page,item_id,line_no FROM extracted_fields WHERE task_id=? AND line_no IS NOT NULL',(task_id,)).fetchall()
            check('all actual line fields saved in relation table',len(actual)==len(expected) and len(expected)>0,{'expected':len(expected),'actual':len(actual)})
            check('grouped fields retain ownership and line numbers',all(row[5] and row[6] for row in actual))
            source_pairs=sorted((f['field_key'],json.dumps(f.get('normalized_value'),sort_keys=True),f.get('raw_value') or '',f.get('raw_text') or '',f.get('page')) for f in expected)
            relation_pairs=sorted((row[0],json.dumps(json.loads(row[1]),sort_keys=True) if row[1] is not None else 'null',row[2] or '',row[3] or '',row[4]) for row in actual)
            check('relation values/page/raw source match full payload',source_pairs==relation_pairs)
            expected_risks=[(r['risk_id'],item) for r in internal['risks'] for item in dict.fromkeys(r.get('related_item_ids',[]) or ([r['item_id']] if r.get('item_id') else []))]
            risk_relations=conn.execute('SELECT risk_id,item_id FROM risk_items WHERE task_id=?',(task_id,)).fetchall()
            decoded_risks=[(json.loads(risk_id)[1],item_id) for risk_id,item_id in risk_relations]
            check('all actual risk-to-item relations retained',all(json.loads(risk_id)[0]==task_id for risk_id,_ in risk_relations)
                  and sorted(expected_risks)==sorted(decoded_risks),{'expected':expected_risks,'actual':decoded_risks})
            check('SQLite foreign key integrity',not conn.execute('PRAGMA foreign_key_check').fetchall())
        stop();start(client)
        after=client.get('/api/v1/checks/'+task_id);after.raise_for_status();save('restart-public.json',after.json())
        check('completed multi-item public result identical after restart',after.json()==task)
finally:
    stop();log.close()
    summary={'commit':'d223d7cfe94acccc60b96656f2f93f866b63e087','checks':len(checks),'failed':sum(not x['passed'] for x in checks),'detail':checks,
             'evidence':'real socket HTTP/current main; relational DB compared to actual full payload; process stop/restart',
             'limits':['one repository multi-item fixture','not PR37 composition or historical migration acceptance','no OCR','no verified legal rules']}
    save('summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
if any(not c['passed'] for c in checks):sys.exit(1)
