"""Evaluate persisted real predictions against independent gold and preserve all mismatches."""
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
DATASET=Path(r'D:\hackson\ocr-local\inputs\trade_documents_hackathon_v2\trade_documents_hackathon_v2')
records=list(csv.DictReader((DATASET/'dataset_manifest.csv').open(encoding='utf-8-sig')))

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def maps(task,name):
    doc=next(d for d in task['documents'] if d['file_name']==name)
    ext=next(e for e in task['extractions'] if e['file_id']==doc['file_id'])
    header,rows={},defaultdict(dict)
    for f in ext['fields']:
        if f.get('line_no') is not None: rows[f['line_no']][f['field_key']]=f
        elif f.get('item_id') is None: header[f['field_key']]=f
    return doc,header,rows

def units(unit):
    return {'KGS':'KG','CARTONS':'CARTON','CTN':'CARTON','CTNS':'CARTON'}.get(unit,unit)

def business_description(value):
    # A printed, explicitly labelled SKU suffix is recorded separately, not guessed away.
    value=re.sub(r'\s*/\s*SKU\s*:\s*[A-Z0-9-]+\s*$','',str(value),flags=re.I)
    return re.sub(r'\s+',' ',value).strip().casefold()

doc_numbers,unit_checks,description_raw,country_checks,rows_checks=[],[],[],[],[]
for record in records:
    if record['sample_kind']!='synthetic':continue
    case=record['shipment_group_id']; task=json.loads((ROOT/'digital/public'/(case+'.json')).read_text(encoding='utf-8'))
    expected=json.loads((DATASET/record['extraction_path']).read_text(encoding='utf-8'))
    name=Path(record['local_path']).name; doc,header,rows=maps(task,name)
    for field in expected['fields']:
        key=field['field_key']; is_row=field.get('line_no') is not None
        actual=(rows.get(field['line_no'],{}) if is_row else header).get(key)
        if key=='document_no':
            doc_numbers.append({'case':case,'file':name,'expected':field['normalized_value'],
                                'actual':actual.get('normalized_value') if actual else None,
                                'passed':actual is not None and actual['normalized_value']==field['normalized_value']})
        if key=='description' and is_row:
            description_raw.append({'case':case,'file':name,'line_no':field['line_no'],'expected':field['raw_value'],
                                    'actual':actual.get('raw_value') if actual else None,
                                    'passed':actual is not None and business_description(actual['raw_value'])==business_description(field['raw_value'])})
        if key=='destination_country':
            country_checks.append({'case':case,'file':name,'expected':field['normalized_value'],
                                   'actual':actual.get('normalized_value') if actual else None,
                                   'raw_value':actual.get('raw_value') if actual else None,
                                   'status':actual.get('status') if actual else 'NO_FIELD',
                                   'passed':actual is not None and actual['normalized_value']==field['normalized_value']})
        if field.get('normalized_value') is not None and field.get('unit') is not None:
            unit_checks.append({'case':case,'file':name,'line_no':field.get('line_no'),'key':key,'expected_unit':field['unit'],
                                'actual_unit':actual.get('unit') if actual else None,
                                'passed':actual is not None and units(actual['unit'])==units(field['unit'])})
    if doc['doc_type']=='COMMERCIAL_INVOICE' and len(rows)==4:
        missing=[line for line,row in rows.items() if row.get('hs_code',{}).get('status')=='MISSING_IN_DOC']
        if missing:
            rows_checks.append({'case':case,'rows':len(rows),'missing_hs_rows':missing,
                                'quantities':{line:row['quantity']['normalized_value'] for line,row in rows.items()},
                                'amounts':{line:row['amount']['normalized_value'] for line,row in rows.items()}})
for name,values in [('document-number-checks',doc_numbers),('unit-checks',unit_checks),
                    ('description-raw-checks',description_raw),('destination-country-checks',country_checks),('four-row-empty-hs-checks',rows_checks)]:
    save(ROOT/'digital'/(name+'.json'),values)
summary={'document_numbers':{'checks':len(doc_numbers),'failed':sum(not x['passed'] for x in doc_numbers)},
         'unit_associations':{'checks':len(unit_checks),'failed':sum(not x['passed'] for x in unit_checks)},
         'description_raw_business_text':{'checks':len(description_raw),'failed':sum(not x['passed'] for x in description_raw),
          'convention':'case/space insensitive; explicitly labelled inline SKU suffix kept in evidence but omitted for business-description comparison'},
         'destination_country':{'checks':len(country_checks),'failed':sum(not x['passed'] for x in country_checks),
                               'failed_groups':len({x['case'] for x in country_checks if not x['passed']}),
                               'failed_raw_values':dict(Counter(x['raw_value'] for x in country_checks if not x['passed']))},
         'four_row_empty_hs_originals':rows_checks}
save(ROOT/'digital/supplemental-analysis.json',summary)
print(json.dumps(summary,ensure_ascii=False,indent=2))
