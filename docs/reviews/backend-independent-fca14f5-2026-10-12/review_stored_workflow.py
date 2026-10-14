"""Socket HTTP correction regressions using this run's actual original-file results."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx

root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--mode',choices=['ocr','arithmetic'],required=True);a=p.parse_args()
run=root/('ocr-py312-default' if a.mode=='ocr' else 'digital')
out=root/('workflow-'+a.mode);out.mkdir(exist_ok=True)
source=Path(r'D:\hackson\tmp\review37-fca14f5-20261012')
checks=[]
def save(name,value):
    (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def check(name,condition,actual=None):checks.append({'check':name,'passed':bool(condition),'actual':actual})
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
log=(out/'server.log').open('wb')
process=subprocess.Popen([sys.executable,'-X','utf8',str(root/'serve_candidate.py'),'--repo',str(source),
                          '--runtime',str(run/'runtime'),'--port',str(port)],stdout=log,stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    with httpx.Client(base_url=f'http://127.0.0.1:{port}',timeout=30,trust_env=False) as client:
        for _ in range(200):
            if process.poll() is not None:raise RuntimeError('server exited')
            try:
                if client.get('/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.1)
        def correction(label,task,change):
            context=client.get(f"/api/v1/checks/{task['task_id']}/corrections").json()
            request={'request_id':label,'source_hash':context['result_hash'],
                     'reason':'独立接口验证：模拟人工核对后的修正，原件不改写','changes':[change]}
            response=client.post(f"/api/v1/checks/{task['task_id']}/corrections",json=request)
            save(label+'-request-response.json',{'request':request,'status':response.status_code,'response':response.json()})
            response.raise_for_status(); child=response.json()
            save(label+'-public.json',child)
            before=client.get(f"/api/v1/checks/{task['task_id']}").json()
            check(label+' original unchanged',before==task)
            before_fields={(e['file_id'],f.get('line_no'),f['field_key']):f for e in task['extractions'] for f in e['fields']}
            after_fields={(e['file_id'],f.get('line_no'),f['field_key']):f for e in child['extractions'] for f in e['fields']}
            check(label+' raw evidence unchanged',all(all(f.get(k)==after_fields[i].get(k) for k in
                  ['raw_value','raw_text','page','bbox','confidence']) for i,f in before_fields.items()))
            report=client.get(f"/api/v1/checks/{child['task_id']}/report?format=json")
            report.raise_for_status();save(label+'-report.json',report.json())
            return child
        if a.mode=='ocr':
            source_task=json.loads((run/'public/SHIRT-ORIGINAL-PDFS.json').read_text(encoding='utf-8'))
            task=client.get(f"/api/v1/checks/{source_task['task_id']}").json()
            ci=next(d['file_id'] for d in task['documents'] if d['doc_type']=='COMMERCIAL_INVOICE')
            for index,currency in enumerate(['EUR','GBP'],1):
                task=correction(f'ocr-currency-{index}',task,{'file_id':ci,'field_key':'currency','value':currency})
                descriptions=[c for c in task['comparisons'] if c['field_key']=='description' and c.get('item_id')]
                check(f'currency {currency} does not clear pending OCR description',bool(descriptions) and
                      all(c['status']=='NOT_CHECKED' and c.get('note') for c in descriptions),descriptions)
                money=[f for e in task['extractions'] if e['file_id']==ci for f in e['fields']
                       if f['field_key'] in {'amount','total_amount','unit_price'} and f['normalized_value'] is not None]
                check(f'currency {currency} updates all matching money units',bool(money) and all(f['unit']==currency for f in money),money)
            for d in task['documents']:
                response=client.get(f"/api/v1/checks/{task['task_id']}/files/{d['file_id']}")
                original=(source/'backend/samples/shirt-originals'/d['file_name']).read_bytes()
                check(d['file_name']+' multi-revision original download',response.status_code==200 and response.content==original)
            history=client.get(f"/api/v1/checks/{task['task_id']}/corrections").json()
            save('final-context.json',history)
        else:
            for case,kind,code in [('SHP-00015','COMMERCIAL_INVOICE','LINE_AMOUNT_MISMATCH'),
                                   ('SHP-00016','PACKING_LIST','GROSS_BELOW_NET')]:
                original=json.loads((run/'public'/(case+'.json')).read_text(encoding='utf-8'))
                task=client.get(f"/api/v1/checks/{original['task_id']}").json()
                file_id=next(d['file_id'] for d in task['documents'] if d['doc_type']==kind)
                extraction=next(e for e in task['extractions'] if e['file_id']==file_id)
                row={f['field_key']:f for f in extraction['fields'] if f.get('line_no')==1}
                key='amount' if kind=='COMMERCIAL_INVOICE' else 'gross_weight'
                value=(row['quantity']['normalized_value']*row['unit_price']['normalized_value']
                       if key=='amount' else row['net_weight']['normalized_value']+1)
                check(case+' original warning present',any(e['code']==code for e in task['errors']))
                child=correction(case+'-arithmetic',task,{'file_id':file_id,'item_no':1,'field_key':key,'value':str(round(value,2))})
                check(case+' resolved arithmetic warning removed',not any(e['code']==code for e in child['errors']),child['errors'])
finally:
    if process.poll() is None:process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    log.close()
    summary={'source_commit':'fca14f56910333c4bac8c72cfd6428ffe2fb6f2a','mode':a.mode,
             'checks':len(checks),'checks_failed':sum(not c['passed'] for c in checks),'detail':checks,
             'evidence':'real HTTP correction of persisted results from original-file uploads in this run; no new inference in this stage',
             'production_accessed':False}
    save('summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='detail'},ensure_ascii=False))
if any(not c['passed'] for c in checks):sys.exit(1)
