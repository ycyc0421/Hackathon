"""Real VL / HTTP acceptance on original shirt PDFs. No model mocks."""
import argparse
import json
import os
import resource
import sys
import time
import re
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import main
from app.pipeline import runner
from app.sqlite_store import TaskStore
from fastapi.testclient import TestClient


def run(out, base_url=None):
    out.mkdir(parents=True, exist_ok=True)
    store = TaskStore(out / 'tasks.db', out / 'legacy')
    samples = Path(__file__).resolve().parents[1] / 'samples/shirt-originals'
    names = ['exportdoc-proforma-invoice-sample.pdf', 'exportdoc-commercial-invoice-sample.pdf',
             'exportdoc-packing-list-sample.pdf']
    started = time.monotonic()
    if base_url:
        import httpx
        transport = httpx.Client(base_url=base_url, timeout=60)
    else:
        transport = TestClient(main.app)
    with patch.object(main, 'store', store), patch.object(runner, 'store', store), patch.object(main, 'UPLOAD_DIR', out/'uploads'), patch.object(runner, 'UPLOAD_DIR', out/'uploads'), transport as client:
        response = client.post('/api/v1/checks', data={'destination_country': 'US'},
                               files=[('files', (name, (samples/name).read_bytes(), 'application/pdf')) for name in names])
        response.raise_for_status()
        task_id = response.json()['task_id']
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            task = store.get(task_id)
            if task['status'] not in {'PENDING', 'PROCESSING'}:
                break
            time.sleep(1)
        public = client.get('/api/v1/checks/' + task_id).json()
        (out/'task.json').write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
        (out/'public.json').write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding='utf-8')
        report = client.get('/api/v1/checks/'+task_id+'/report').json() if task['status'] in {'COMPLETED','PARTIAL','FAILED'} else None
        (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    checks = []
    def check(name, actual, expected):
        checks.append({'check': name, 'actual': actual, 'expected': expected, 'passed': actual == expected})
    check('task_completed', task['status'], 'COMPLETED')
    check('three_extractions', len(task['extractions']), 3)
    compact = lambda value: re.sub(r'[^a-z0-9]', '', str(value or '').casefold())
    for index, name in enumerate(names, 1):
        extraction = next((ext for ext in task['extractions'] if ext['file_id'] == f'f{index}'), None)
        if extraction is None:
            continue
        fields = {field['field_key']: field for field in extraction['fields']}
        # Public contract currently represents an explicit proforma as OTHER.
        check(name+'.type', extraction['doc_type'], ('OTHER', 'COMMERCIAL_INVOICE', 'PACKING_LIST')[index-1])
        own_no = ('PI','CI','PL')[index-1]+'-20260830-08300186'
        check(name+'.document_no', fields.get('document_no', {}).get('normalized_value'), own_no)
        check(name+'.seller', compact(fields.get('shipper', {}).get('normalized_value')), compact('Ningbo Qihang Export Co., Ltd.'))
        check(name+'.buyer', compact(fields.get('consignee', {}).get('normalized_value')), compact('Global Fashion Inc.'))
        check(name+'.one_row', len(extraction['line_items']), 1)
        if not extraction['line_items']:
            continue
        row = {field['field_key']: field for field in extraction['line_items'][0]['fields']}
        for field in extraction['fields'] + extraction['line_items'][0]['fields']:
            if field.get('normalized_value') is not None:
                check(name+'.'+field['field_key']+'.evidence', bool(field.get('raw_text') and field.get('raw_value') and field.get('page') == 1), True)
        check(name+'.SKU', row.get('item_code', {}).get('normalized_value'), 'CT-2408')
        check(name+'.quantity', row.get('quantity', {}).get('normalized_value'), 500)
        check(name+'.page', row.get('quantity', {}).get('page'), 1)
        check(name+'.quantity_unit', row.get('quantity', {}).get('unit'), 'PCS')
        check(name+'.quantity_box', bool(row.get('quantity', {}).get('bbox') and row.get('quantity', {}).get('bbox_unit') == 'PX'), True)
        if index < 3:
            check(name+'.unit_price', row.get('unit_price', {}).get('normalized_value'), 2.8)
            check(name+'.amount', row.get('amount', {}).get('normalized_value'), 1400)
            check(name+'.total_amount', fields.get('total_amount', {}).get('normalized_value'), 1400)
            check(name+'.amount_currency', row.get('amount', {}).get('unit'), 'USD')
        else:
            for key, expected in [('packages',20),('net_weight',150),('gross_weight',170),('volume',1.68)]:
                check(name+'.'+key, row.get(key, {}).get('normalized_value'), expected)
            check(name+'.no_amount', fields.get('total_amount', {}).get('normalized_value'), None)
            check(name+'.no_line_amount', row.get('amount', {}).get('normalized_value'), None)
    summary = {'status': 'PASSED' if all(item['passed'] for item in checks) else 'FAILED',
               'model': 'PaddleOCR-VL-'+os.getenv('PADDLE_VL_VERSION','v1.6'), 'device': os.getenv('PADDLE_VL_DEVICE','cpu'),
               'elapsed_seconds': round(time.monotonic()-started, 2),
               'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'task_id': task_id, 'checks': checks, 'scope': 'Three original shirt scan PDFs; not complete dataset accuracy'}
    summary['api_transport'] = base_url or 'in-process TestClient'
    (out/'acceptance.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary['status'] == 'PASSED'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path('backend/.out/paddle-vl-acceptance'))
    parser.add_argument('--base-url', help='Actual isolated API URL; --out must match its store directory')
    parser.add_argument('--serve', action='store_true', help='Run isolated acceptance API on 127.0.0.1:18081')
    args = parser.parse_args()
    out = args.out.resolve()
    if args.serve:
        import uvicorn
        out.mkdir(parents=True, exist_ok=True)
        store = TaskStore(out / 'tasks.db', out / 'legacy')
        with patch.object(main, 'store', store), patch.object(runner, 'store', store), patch.object(main, 'UPLOAD_DIR', out/'uploads'), patch.object(runner, 'UPLOAD_DIR', out/'uploads'):
            uvicorn.run(main.app, host='127.0.0.1', port=18081)
    else:
        raise SystemExit(0 if run(out, args.base_url) else 1)
