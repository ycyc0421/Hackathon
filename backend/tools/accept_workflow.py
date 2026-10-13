"""Repeatable candidate acceptance; uses an isolated database, never production."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def run(output):
    from fastapi.testclient import TestClient
    from app import main
    from app.models import CheckTask
    from app.sqlite_store import TaskStore
    from app.pipeline import runner

    output.mkdir(parents=True, exist_ok=True)
    samples = output / 'samples'
    samples.mkdir(exist_ok=True)
    for name, kind in [('invoice', 'COMMERCIAL_INVOICE'), ('packing', 'PACKING_LIST')]:
        data = {'format': 'hackathon-trade-json-v1', 'doc_type': kind,
                'fields': {'packages': '120 CARTONS', 'gross_weight': '2800 KGS'},
                'line_items': [{'item_no': 1, 'fields': {'item_code': 'MUG-1',
                    'description': 'CERAMIC MUG WHITE', 'quantity': '100 PCS'}}]}
        (samples / (name + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    checks = []

    def verify(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with TemporaryDirectory(prefix='workflow-accept-') as tmp:
        root = Path(tmp)
        store = TaskStore(root / 'tasks.db', root / 'legacy')
        with patch.object(main, 'store', store), patch.object(runner, 'store', store), patch.object(runner, 'UPLOAD_DIR', root / 'uploads'):
            with TestClient(main.app) as client:
                response = client.post('/api/v1/checks', data={'destination_country': 'DE'}, files=[
                    ('files', (p.name, p.read_bytes(), 'application/json')) for p in sorted(samples.glob('*.json'))])
                verify('upload_http_200', response.status_code == 200)
                source_id = response.json()['task_id']
                source = store.get(source_id)
                CheckTask.model_validate(source)
                verify('two_documents_completed', source['status'] == 'COMPLETED' and len(source['documents']) == 2)
                verify('original_packages_match', any(c['field_key'] == 'packages' and c['status'] == 'MATCH' for c in source['comparisons']))
                metadata = client.get(f'/api/v1/checks/{source_id}/corrections').json()
                request = {'request_id': 'accept-packages-1', 'source_hash': metadata['result_hash'],
                           'reason': '验收样例：模拟核对原件后修正件数', 'changes': [
                               {'file_id': source['extractions'][0]['file_id'], 'field_key': 'packages', 'value': '121 CARTONS'}]}
                changed = client.post(f'/api/v1/checks/{source_id}/corrections', json=request)
                verify('correction_http_200', changed.status_code == 200)
                child_id = changed.json()['task_id']
                child = store.get(child_id)
                CheckTask.model_validate(child)
                verify('derived_task_and_original_unchanged', child_id != source_id and store.get(source_id) == source)
                verify('recomputed_packages_conflict', any(c['field_key'] == 'packages' and c['status'] == 'CONFLICT' for c in child['comparisons']))
                original_field = next(f for f in source['extractions'][0]['fields'] if f['field_key'] == 'packages')
                revised_field = next(f for f in child['extractions'][0]['fields'] if f['field_key'] == 'packages')
                verify('raw_evidence_retained', all(original_field.get(k) == revised_field.get(k) for k in ['raw_value', 'raw_text', 'page', 'bbox', 'confidence']))
                verify('effective_value_cautious', revised_field['normalized_value'] == 121 and revised_field['status'] == 'LOW_CONFIDENCE')
                repeat = client.post(f'/api/v1/checks/{source_id}/corrections', json=request)
                verify('retry_idempotent', repeat.status_code == 200 and repeat.json()['task_id'] == child_id)
                bad = {**request, 'request_id': 'accept-stale', 'source_hash': '0' * 64}
                verify('stale_hash_rejected', client.post(f'/api/v1/checks/{source_id}/corrections', json=bad).status_code == 409)
                exported = client.get(f'/api/v1/checks/{child_id}/report?format=json')
                envelope = exported.json()
                verify('json_report_and_audit', exported.status_code == 200 and envelope['task']['task_id'] == child_id and len(store.correction_history(child_id)) == 1)
                rendered = client.get(f'/api/v1/checks/{child_id}/report?format=html')
                verify('html_presentation_moved', rendered.status_code == 410 and rendered.json()['error']['code'] == 'REPORT_PRESENTATION_MOVED')
                (output / 'report.json').write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding='utf-8')
                (output / 'html-migration.json').write_bytes(rendered.content)
                verify('unknown_task_404', client.get('/api/v1/checks/accept-missing').status_code == 404)
                reopened = TaskStore(root / 'tasks.db', root / 'legacy')
                with patch.object(main, 'store', reopened):
                    verify('reopened_database_readable', client.get(f'/api/v1/checks/{child_id}').status_code == 200 and reopened.get(child_id) == child and len(reopened.correction_history(child_id)) == 1)
        result = {'status': 'PASSED', 'checks': checks, 'sample_type': 'synthetic structured JSON',
                  'limits': ['Not browser UI acceptance', 'Not production restart acceptance', 'Not OCR accuracy evaluation'],
                  'source_task_id': source_id, 'derived_task_id': child_id}
        (output / 'acceptance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('backend/.out/workflow-acceptance'))
    run(parser.parse_args().output)
