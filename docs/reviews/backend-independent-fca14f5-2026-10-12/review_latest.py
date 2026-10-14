"""Independent socket HTTP verification. Expected values are read only after prediction.

The candidate source and all original PDFs/images/EDI bytes remain unchanged.
This is a synthetic-template regression and a small original-scan check, not formal accuracy.
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import httpx

PIN = 'fca14f56910333c4bac8c72cfd6428ffe2fb6f2a'
DOC_KEYS = {'shipper', 'consignee', 'currency', 'country', 'invoice_no', 'total_amount',
            'packages', 'net_weight', 'gross_weight', 'volume'}
ROW_KEYS = {'item_code', 'description', 'hs_code', 'quantity', 'unit_price', 'amount',
            'packages', 'net_weight', 'gross_weight', 'volume'}

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def same(actual, expected, key):
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-6)
    if expected is None:
        return actual is None
    if key == 'hs_code':
        return str(actual).replace('.', '') == str(expected).replace('.', '')
    if key in {'shipper', 'consignee'}:
        clean = lambda x: re.sub(r'[^\w]', '', str(x)).casefold()
        return clean(actual) == clean(expected)
    return re.sub(r'\s+', ' ', str(actual)).strip().upper() == re.sub(r'\s+', ' ', str(expected)).strip().upper()

def field_maps(task, name):
    doc = next(d for d in task['documents'] if d['file_name'] == name)
    ext = next((e for e in task['extractions'] if e['file_id'] == doc['file_id']), {'fields': []})
    header, rows = {}, defaultdict(dict)
    for f in ext['fields']:
        if f.get('line_no') is not None:
            rows[f['line_no']][f['field_key']] = f
        elif f.get('item_id') is None:
            header[f['field_key']] = f
    return doc, header, rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--edi', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', choices=['digital', 'ocr'], default='digital')
    p.add_argument('--disable-mkldnn', action='store_true')
    p.add_argument('--ocr-cache', type=Path)
    a = p.parse_args()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=a.repo, text=True).strip()
    assert commit == PIN, commit
    a.out.mkdir(parents=True, exist_ok=True)
    checks, cases, fields, manifests, evaluations = [], [], [], [], []
    def check(case, label, passed, actual=None, expected=None, category='integration'):
        entry = {'case': case, 'check': label, 'passed': bool(passed), 'actual': actual,
                 'expected': expected, 'category': category}
        checks.append(entry)
        return bool(passed)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    log = (a.out / 'server.log').open('ab')
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('serve_candidate.py')), '--repo', str(a.repo),
               '--runtime', str(a.out / 'runtime'), '--port', str(port)]
    if a.mode == 'ocr': command.append('--ocr')
    if a.disable_mkldnn: command.append('--disable-mkldnn')
    if a.ocr_cache: command.extend(['--ocr-cache', str(a.ocr_cache)])
    process = None
    client = httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=90, trust_env=False)
    def start():
        nonlocal process
        process = subprocess.Popen(command, cwd=a.repo, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(300):
            if process.poll() is not None: raise RuntimeError('server exited; see server.log')
            try:
                if client.get('/health').status_code == 200: return
            except httpx.HTTPError: pass
            time.sleep(.1)
        raise TimeoutError('server readiness')
    def stop():
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
    def run(case, paths, data=None, source_hashes=None):
        data = data or {'destination_country': 'US'}
        started = time.monotonic()
        uploads, originals = [], []
        for path in paths:
            payload = path.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
            entry = {'case': case, 'file_name': path.name, 'path': str(path), 'size_bytes': len(payload), 'sha256': digest}
            manifests.append(entry); originals.append(entry)
            if source_hashes and str(path) in source_hashes:
                check(case, path.name + ' original hash', digest == source_hashes[str(path)], digest,
                      source_hashes[str(path)], 'source_integrity')
            media = 'application/pdf' if path.suffix.lower() == '.pdf' else ('image/png' if path.suffix.lower() == '.png' else 'application/octet-stream')
            uploads.append(('files', (path.name, payload, media)))
        response = client.post('/api/v1/checks', data=data, files=uploads)
        save(a.out / 'requests' / (case + '.json'), {'method': 'POST', 'path': '/api/v1/checks', 'data': data,
                                                  'files': originals, 'status': response.status_code, 'post_response': response.json()})
        response.raise_for_status()
        task_id = response.json()['task_id']; deadline = time.monotonic() + (900 if a.mode == 'ocr' else 90)
        polls = []
        while True:
            value = client.get('/api/v1/checks/' + task_id); value.raise_for_status(); task = value.json()
            polls.append({'status': task['status'], 'documents': [{'file_name': d['file_name'], 'process_status': d['process_status']} for d in task['documents']]})
            if task['status'] not in {'PENDING', 'PROCESSING'}: break
            if time.monotonic() > deadline: raise TimeoutError(case)
            time.sleep(.3 if a.mode == 'digital' else 1)
        save(a.out / 'public' / (case + '.json'), task)
        save(a.out / 'polls' / (case + '.json'), polls)
        report = client.get(f'/api/v1/checks/{task_id}/report?format=json')
        check(case, 'JSON report available', report.status_code == 200, report.status_code)
        if report.status_code == 200: save(a.out / 'reports' / (case + '.json'), report.json())
        for path in paths:
            doc = next(d for d in task['documents'] if d['file_name'] == path.name)
            download = client.get(f"/api/v1/checks/{task_id}/files/{doc['file_id']}")
            check(case, path.name + ' download byte identity', download.status_code == 200 and download.content == path.read_bytes(),
                  {'status': download.status_code, 'sha256': hashlib.sha256(download.content).hexdigest()}, category='source_integrity')
        entry = {'case': case, 'task_id': task_id, 'status': task['status'], 'summary': task['summary'],
                 'item_count': len(task['items']), 'documents': [{'name': d['file_name'], 'status': d['process_status']} for d in task['documents']],
                 'errors': task['errors'], 'seconds': round(time.monotonic()-started, 3)}
        cases.append(entry)
        save(a.out / 'cases.json', cases)
        if a.mode == 'ocr' or len(cases) % 10 == 0 or not case.startswith('SHP-'):
            print(json.dumps({'case': case, 'status': task['status'], 'items': len(task['items']), 'seconds': entry['seconds'],
                              'error_codes': [e['code'] for e in task['errors']]}, ensure_ascii=False), flush=True)
        return task

    dataset_manifest = list(csv.DictReader((a.dataset/'dataset_manifest.csv').open(encoding='utf-8-sig')))
    input_hashes = json.loads((a.dataset/'input_sha256.json').read_text(encoding='utf-8'))
    def members(group, kind):
        result = [r for r in dataset_manifest if r['shipment_group_id'] == group and
                  (r['sample_kind'] == 'synthetic' if kind == 'digital' else r['document_id'].endswith('_' + kind))]
        return sorted(result, key=lambda r: Path(r['local_path']).name)
    def evaluate(case, task, records):
        case_fields = []
        expected_by_sku = defaultdict(lambda: defaultdict(list))
        arithmetic_needed = set()
        for record in records:
            expected = json.loads((a.dataset / record['extraction_path']).read_text(encoding='utf-8'))
            name = Path(record['local_path']).name
            doc, header, rows = field_maps(task, name)
            check(case, name + ' extracted', doc['process_status'] == 'EXTRACTED', doc['process_status'], category='parse')
            expected_rows = defaultdict(dict)
            for f in expected['fields']:
                if f.get('line_no') is not None: expected_rows[f['line_no']][f['field_key']] = f
            check(case, name + ' row count', len(rows) == len(expected_rows), len(rows), len(expected_rows), 'rows')
            for f in expected['fields']:
                is_row = f.get('line_no') is not None
                key = f['field_key']
                if key not in (ROW_KEYS if is_row else DOC_KEYS): continue
                if f['normalized_value'] is None and not (is_row and key == 'hs_code' and f['status'] == 'MISSING_IN_DOC'): continue
                got = (rows.get(f['line_no'], {}) if is_row else header).get(key)
                ok = got is not None and same(got['normalized_value'], f['normalized_value'], key)
                if f['normalized_value'] is None: ok = ok and got['status'] == f['status']
                entry = {'case': case, 'file': name, 'line_no': f.get('line_no'), 'key': key,
                         'expected': f['normalized_value'], 'actual': got.get('normalized_value') if got else None,
                         'actual_status': got.get('status') if got else 'NO_FIELD', 'passed': ok}
                fields.append(entry); case_fields.append(entry)
                if got and got['normalized_value'] is not None:
                    check(case, f'{name} {f.get("line_no")} {key} original evidence', got.get('page') == 1 and bool(got.get('raw_text')),
                          {'page': got.get('page'), 'raw_text': got.get('raw_text')}, category='evidence')
            for line, row in expected_rows.items():
                sku = row.get('item_code', {}).get('normalized_value')
                for key in ['quantity', 'hs_code', 'amount']:
                    v = row.get(key, {}).get('normalized_value')
                    if sku and v is not None: expected_by_sku[sku][key].append(v)
                qty, price, amount = [row.get(k, {}).get('normalized_value') for k in ['quantity','unit_price','amount']]
                if all(isinstance(x,(int,float)) for x in [qty,price,amount]) and abs(qty*price-amount) > .010001:
                    arithmetic_needed.add('LINE_AMOUNT_MISMATCH')
                net, gross = [row.get(k, {}).get('normalized_value') for k in ['net_weight','gross_weight']]
                if isinstance(net,(int,float)) and isinstance(gross,(int,float)) and gross < net:
                    arithmetic_needed.add('GROSS_BELOW_NET')
        actual_identity = {}
        for e in task['extractions']:
            for f in e['fields']:
                if f['field_key'] == 'item_code' and f.get('item_id'): actual_identity[f['normalized_value']] = f['item_id']
        for sku, by_key in expected_by_sku.items():
            for key, values in by_key.items():
                distinct = {str(v).replace('.', '') if key == 'hs_code' else str(v) for v in values}
                if len(distinct) <= 1: continue
                found = [c for c in task['comparisons'] if c['field_key'] == key and c.get('item_id') == actual_identity.get(sku)]
                check(case, f'{sku} true {key} conflict', bool(found) and found[0]['status'] == 'CONFLICT',
                      found[0] if found else None, values, 'conflict')
        for warning in sorted(arithmetic_needed):
            check(case, warning + ' internal warning', any(e['code'] == warning for e in task['errors']),
                  [e['code'] for e in task['errors']], category='internal_warning')
        observed = [{'key': c['field_key'], 'status': c['status'], 'item_id': c.get('item_id')} for c in task['comparisons'] if c['status'] == 'CONFLICT']
        evaluation = {'case':case, 'category':records[0]['category'], 'field_count':len(case_fields),
                      'field_failures':[f for f in case_fields if not f['passed']], 'conflicts':observed,
                      'address_field_present':any('address' in f['field_key'] for e in task['extractions'] for f in e['fields'])}
        if records[0]['category'] in {'clean','benign_format_variation'}:
            check(case, 'clean numeric comparisons have no false conflict', not observed, observed, category='conflict')
        evaluations.append(evaluation)
        save(a.out / 'evaluations' / (case+'.json'), evaluation)
    try:
        start()
        capability = client.get('/api/v1/capabilities'); capability.raise_for_status()
        save(a.out/'capabilities.json', capability.json())
        if a.mode == 'digital':
            for number in range(1,101):
                case = f'SHP-{number:05d}'; records = members(case,'digital'); assert len(records)==3
                # Only declared request metadata is used here; extraction gold is not loaded before inference.
                request = json.loads((a.dataset/'docs/fixtures/result'/(case+'.json')).read_text(encoding='utf-8'))['input']
                data = {k:request[k] for k in ['destination_country','destination_country_name'] if request.get(k)}
                paths = [a.dataset/r['local_path'] for r in records]
                hashes = {str(a.dataset/r['local_path']): input_hashes[r['local_path']] for r in records}
                task = run(case,paths,data,hashes); evaluate(case,task,records)
            edi_files = sorted(a.edi.glob('*/*.edi')); assert len(edi_files)==23
            for i, path in enumerate(edi_files,1):
                case = f'EDI-{i:02d}-{path.parent.name}-{path.stem}'
                task = run(case,[path])
                check(case,'EDI unsupported is FAILED',task['status']=='FAILED' and task['documents'][0]['process_status']=='UNSUPPORTED', task['status'], category='capability_boundary')
                check(case,'unsupported has explicit error', any(e['code']=='UNSUPPORTED_FILE_TYPE' for e in task['errors']),task['errors'],category='capability_boundary')
            pdfs = [a.dataset/r['local_path'] for r in members('SHP-00002','digital')]
            mixed = run('MIXED-PDF-EDI', pdfs+[edi_files[0]])
            check('MIXED-PDF-EDI','PARTIAL with successful PDFs and unsupported EDI',mixed['status']=='PARTIAL' and
                  sum(d['process_status']=='EXTRACTED' for d in mixed['documents'])==3, mixed['documents'])
            original = run('JSON-MISSING-QUANTITY', sorted((a.repo/'backend/samples/review38').glob('*.json')))
            for doc in original['documents']:
                if doc['doc_type']!='PACKING_LIST': continue
                _,_,rows = field_maps(original,doc['file_name'])
                b2 = next((r for r in rows.values() if r.get('item_code',{}).get('normalized_value')=='SKU-B2'),{})
                quantity=b2.get('quantity',{})
                check('JSON-MISSING-QUANTITY','PL B2 quantity is explicitly missing',quantity.get('status')=='MISSING_IN_DOC',quantity)
                found=[c for c in original['comparisons'] if c['field_key']=='quantity' and c.get('item_id')==quantity.get('item_id')]
                check('JSON-MISSING-QUANTITY','B2 comparison MISSING_IN_SOME',bool(found) and found[0]['status']=='MISSING_IN_SOME',found)
            source_id=original['task_id']; before=client.get(f'/api/v1/checks/{source_id}').json()
            metadata=client.get(f'/api/v1/checks/{source_id}/corrections'); metadata.raise_for_status()
            target_file=next(d['file_id'] for d in original['documents'] if d['doc_type']=='COMMERCIAL_INVOICE')
            payload={'request_id':'b-independent-currency-1','source_hash':metadata.json()['result_hash'],'reason':'隔离接口验证：人工核对币种的派生任务语义',
                     'changes':[{'file_id':target_file,'field_key':'currency','value':'EUR'}]}
            response=client.post(f'/api/v1/checks/{source_id}/corrections',json=payload)
            save(a.out/'workflow'/'correction.json', {'request':payload,'status':response.status_code,'response':response.json()})
            check('WORKFLOW','correction creates child',response.status_code==200,response.status_code)
            response.raise_for_status(); child_id=response.json()['task_id']
            child=client.get(f'/api/v1/checks/{child_id}').json(); save(a.out/'public'/'WORKFLOW-CHILD.json',child)
            check('WORKFLOW','source task unchanged',client.get(f'/api/v1/checks/{source_id}').json()==before)
            retry=client.post(f'/api/v1/checks/{source_id}/corrections',json=payload)
            check('WORKFLOW','retry is idempotent',retry.status_code==200 and retry.json()['task_id']==child_id)
            stale=client.post(f'/api/v1/checks/{source_id}/corrections',json={**payload,'request_id':'b-independent-stale','source_hash':'0'*64})
            check('WORKFLOW','stale source hash rejected',stale.status_code==409,stale.status_code)
            for doc in child['documents']:
                name=doc['file_name']; path=a.repo/'backend/samples/review38'/name
                value=client.get(f"/api/v1/checks/{child_id}/files/{doc['file_id']}")
                check('WORKFLOW',name+' child downloads original bytes',value.status_code==200 and value.content==path.read_bytes())
            html=client.get(f'/api/v1/checks/{child_id}/report?format=html')
            check('WORKFLOW','HTML report download',html.status_code==200 and 'attachment' in html.headers.get('content-disposition',''))
            if html.status_code==200: (a.out/'workflow'/'child-report.html').write_bytes(html.content)
            saved={source_id:before,child_id:child,mixed['task_id']:mixed}
            stop(); start()
            for task_id, expected in saved.items():
                reread=client.get(f'/api/v1/checks/{task_id}')
                check('RESTART',task_id+' full result retained',reread.status_code==200 and reread.json()==expected,reread.status_code)
                if reread.status_code==200: save(a.out/'restart'/(task_id+'.json'),reread.json())
            download=client.get(f'/api/v1/checks/{child_id}/files/{target_file}')
            source_file=next(d['file_name'] for d in child['documents'] if d['file_id']==target_file)
            check('RESTART','derived task source download retained',download.status_code==200 and download.content==(a.repo/'backend/samples/review38'/source_file).read_bytes())
        else:
            case='SCAN-PNG-SHP-00001'; records=members('SHP-00001','scan_png'); assert len(records)==3
            paths=[a.dataset/r['local_path'] for r in records]
            hashes={str(a.dataset/r['local_path']):input_hashes[r['local_path']] for r in records}
            task=run(case,paths,source_hashes=hashes); evaluate(case,task,records)
            case='SHIRT-ORIGINAL-PDFS'; paths=sorted((a.repo/'backend/samples/shirt-originals').glob('*.pdf')); assert len(paths)==3
            golden=json.loads((a.repo/'backend/samples/shirt-originals/golden-fields.json').read_text(encoding='utf-8'))
            hashes={str(a.repo/'backend/samples/shirt-originals'/d['file_name']):d['sha256'] for d in golden['documents']}
            task=run(case,paths,source_hashes=hashes)
            for source in golden['documents']:
                name=source['file_name']; doc,header,rows=field_maps(task,name)
                extraction = next((e for e in task['extractions'] if e['file_id'] == doc['file_id']), {})
                check(case,name+' parsed by actual OCR',doc['process_status']=='EXTRACTED' and extraction.get('parse_method')=='OCR',doc,category='parse')
                check(case,name+' one item row',len(rows)==1,len(rows),1,'rows')
                row=next(iter(rows.values()),{})
                for key,expected in source['fields'].items():
                    mapped={'seller':'shipper','buyer':'consignee','sku':'item_code'}.get(key,key)
                    if mapped=='description': continue
                    if mapped not in DOC_KEYS|ROW_KEYS|{'document_no'}: continue
                    got=row.get(mapped) if mapped in ROW_KEYS and mapped not in {'total_amount','document_no'} else header.get(mapped)
                    if mapped in {'shipper','consignee'}: got=header.get(mapped)
                    if not got: got=header.get(mapped)
                    ok=got is not None and same(got.get('normalized_value'),expected['value'],mapped)
                    fields.append({'case':case,'file':name,'line_no':got.get('line_no') if got else None,'key':mapped,'expected':expected['value'],
                                   'actual':got.get('normalized_value') if got else None,'actual_status':got.get('status') if got else 'NO_FIELD','passed':ok})
                    if got and got['normalized_value'] is not None:
                        check(case,name+' '+mapped+' page/raw source',got.get('page')==1 and bool(got.get('raw_text')),got,category='evidence')
                if doc['doc_type']=='PACKING_LIST':
                    for scope,mapping in [('header',header),('row',row)]:
                        f=mapping.get('total_amount' if scope=='header' else 'amount',{})
                        check(case,'PL '+scope+' amount is NOT_IN_DOC',f.get('normalized_value') is None and f.get('status')=='NOT_IN_DOC',f)
            descriptions=[c for c in task['comparisons'] if c['field_key']=='description' and c.get('item_id')]
            check(case,'uncertain descriptions stay NOT_CHECKED',bool(descriptions) and all(c['status']=='NOT_CHECKED' and c.get('note') for c in descriptions),descriptions)
            check(case,'document numbers not compared as equal',not any(c['field_key']=='document_no' for c in task['comparisons']))
    except BaseException as exc:
        save(a.out/'execution-error.json', {'type':type(exc).__name__, 'message':str(exc),
             'server_exit_code_before_cleanup':process.poll() if process is not None else None,
             'completed_cases':len(cases), 'status':'INCOMPLETE'})
        raise
    finally:
        stop(); client.close(); log.close()
        save(a.out/'input-manifest.json',manifests)
        save(a.out/'checks.json',checks)
        save(a.out/'field-checks.json',fields)
        failures=[c for c in checks if not c['passed']]
        field_failures=[c for c in fields if not c['passed']]
        summary={'source_commit':commit,'mode':a.mode,'evidence':'real loopback TCP HTTP with isolated SQLite and upload paths',
                 'execution_status':'INCOMPLETE' if (a.out/'execution-error.json').exists() else 'FINISHED',
                 'python':sys.version,'checked_at':datetime.now(timezone.utc).isoformat(),'external_llm_enabled':False,
                 'fresh_ocr_invoked':a.mode=='ocr','ocr_observation':'save raw model outputs without changing predictions' if a.mode=='ocr' else None,
                 'diagnostic_runtime_override':'enable_mkldnn=False' if a.disable_mkldnn else None,
                 'http_tasks':len(cases),'uploaded_files':len(manifests),'task_statuses':dict(Counter(c['status'] for c in cases)),
                 'field_checks':len(fields),'field_checks_failed':len(field_failures),'field_failures_by_key':dict(Counter(c['key'] for c in field_failures)),
                 'checks':len(checks),'checks_failed':len(failures),'checks_by_category':dict(Counter(c['category'] for c in checks)),
                 'failures_by_category':dict(Counter(c['category'] for c in failures)),
                 'address_gap_cases':[e['case'] for e in evaluations if e['category']=='buyer_address_mismatch' and not e['address_field_present']],
                 'production_accessed':False,'candidate_source_modified':False,'limits':['synthetic single-template text benchmark',
                 'no browser acceptance','no production deployment/restart acceptance','no verified country-law or certificate-bodies acceptance']}
        packages={}
        for name in ['fastapi','pydantic','httpx','uvicorn','pypdf','pymupdf','paddleocr','paddlepaddle','paddlex']:
            try: packages[name]=importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError: pass
        summary['packages']=packages
        save(a.out/'summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    return 1 if failures or field_failures else 0

if __name__=='__main__': sys.exit(main())
