"""Replay the nine untouched PDF groups supplied with B's follow-up evidence."""
import json
from pathlib import Path
import test_shirt_originals as http

backend = Path(__file__).resolve().parents[1]
source = backend / '.out/followup/inputs'
destination = backend / '.out/followup-fixed'
destination.mkdir(parents=True, exist_ok=True)
for group in sorted(source.glob('SHP-*')):
    http.ROOT = group
    result = http.run()
    (destination / (group.name + '.json')).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    task = result['task']
    assert len(task['documents']) == 3
    assert all(d['process_status'] == 'EXTRACTED' for d in task['documents']), task['documents']
    for extraction in task['extractions']:
        fields = {field['field_key']: field for field in extraction['fields']}
        assert fields['invoice_no']['normalized_value'] == group.name.replace('SHP-', 'CI-')
        assert extraction['line_items'], (group.name, extraction['file_id'])
        for row in extraction['line_items']:
            for field in row['fields']:
                if field['normalized_value'] is not None:
                    assert field['page'] == 1, (group.name, field)
    if group.name == 'SHP-00017':
        ci = next(e for e in task['extractions'] if e['doc_type'] == 'COMMERCIAL_INVOICE')
        fields = {field['field_key']: field for field in ci['line_items'][0]['fields']}
        assert fields['hs_code']['status'] == 'MISSING_IN_DOC'
        assert fields['quantity']['normalized_value'] == 200
        assert fields['amount']['normalized_value'] == 454
    for target, code in [('SHP-00015', 'LINE_AMOUNT_MISMATCH'), ('SHP-00016', 'GROSS_BELOW_NET')]:
        if group.name == target:
            assert any(error['code'] == code for error in task['errors']), task['errors']
    print(group.name, task['status'], task['summary'], flush=True)

# Controlled two-page copy checks orchestration source attribution. This is
# synthetic input, not a claim that B supplied a two-page original.
from io import BytesIO
from pypdf import PdfReader, PdfWriter
multi = destination / 'controlled-multipage'
multi.mkdir(exist_ok=True)
reader = PdfReader(source / 'SHP-00019/commercial_invoice.pdf')
writer = PdfWriter()
writer.add_page(reader.pages[0])
writer.add_page(reader.pages[0])
buffer = BytesIO()
writer.write(buffer)
(multi / 'commercial_invoice.pdf').write_bytes(buffer.getvalue())
http.ROOT = multi
result = http.run()
(destination / 'controlled-multipage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
rows = result['task']['extractions'][0]['line_items']
assert len(rows) == 8
assert [next(f['page'] for f in row['fields'] if f['field_key'] == 'quantity') for row in rows] == [1] * 4 + [2] * 4
print('Controlled two-page HTTP source attribution passed', flush=True)
