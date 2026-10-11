"""Deterministic synthetic fixtures; internal format, not the API contract.

item_id=None denotes shipment scope. Document line_no is the physical item-row
order; item_order in the catalogue is only display order. Synthetic risks are
review hints, not destination-country legal conclusions.
"""

import argparse
import json
import random
import warnings
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'data' / 'generated'
CREATED_AT = '2026-10-10T00:00:00+00:00'


def field(key, value, unit=None, item_id=None, line_no=None,
          status='EXTRACTED', confidence=0.98):
    if value is None:
        raw = None
    elif unit:
        raw = f'{value} {unit}'
    else:
        raw = str(value)
    return dict(field_key=key, item_id=item_id, line_no=line_no,
                raw_value=raw, normalized_value=value, unit=unit, status=status,
                confidence=confidence if status in {'EXTRACTED', 'LOW_CONFIDENCE'} else None)


def item(item_id, name, description, hs_code, quantity, packages, item_order):
    return dict(item_id=item_id, display_name=name, description=description,
                hs_code=hs_code, quantity=quantity, packages=packages,
                item_order=item_order)


def document(file_id, doc_type, items, *, order=None, quantity_deltas=None,
             shipment_weight=None, item_weights=None, missing=None,
             unrecognized=None, low_confidence=None, parse_method='TEXT_LAYER',
             invoice_no='INV-2026-0001', amount=12500.0):
    """Scalar shipment_weight and keyed item_weights are mutually exclusive.

    missing describes a required test field not found; they emit placeholders.
    B/L hs_code/quantity are NOT_IN_DOC under this synthetic template profile.
    """
    if shipment_weight is not None and item_weights is not None:
        raise ValueError('Use shipment_weight OR item_weights, not both')
    order = [x['item_id'] for x in items] if order is None else order
    by_id = {x['item_id']: x for x in items}
    if len(order) != len(by_id) or set(order) != set(by_id):
        raise ValueError('order must contain every item exactly once')
    if item_weights is not None and set(item_weights) != set(by_id):
        raise ValueError('item_weights must specify every item')
    absent = set(missing or ())
    unreadable = set(unrecognized or ())
    low = set(low_confidence or ())
    fields = []
    for line_no, identity in enumerate(order, 1):
        source = by_id[identity]
        for key, unit in [('description', None), ('hs_code', None),
                          ('quantity', 'PCS'), ('packages', 'CARTON')]:
            value = source[key]
            status = 'EXTRACTED'
            if doc_type == 'BILL_OF_LADING' and key in {'hs_code', 'quantity'}:
                value, status = None, 'NOT_IN_DOC'
            elif key in absent or (identity, key) in absent:
                value, status = None, 'MISSING_IN_DOC'
            elif key in unreadable or (identity, key) in unreadable:
                value, status = None, 'UNRECOGNIZED'
            elif key in low or (identity, key) in low:
                status = 'LOW_CONFIDENCE'
            if key == 'quantity' and value is not None:
                value += (quantity_deltas or {}).get(identity, 0)
            fields.append(field(key, value, unit, identity, line_no, status,
                                0.72 if status == 'LOW_CONFIDENCE' else 0.98))
        if item_weights is not None:
            fields.append(field('gross_weight', item_weights[identity], 'KGS', identity, line_no))
    if shipment_weight is not None:
        fields.append(field('gross_weight', shipment_weight, 'KGS'))
    if doc_type == 'COMMERCIAL_INVOICE':
        fields.extend([field('invoice_no', invoice_no), field('total_amount', amount, 'USD'),
                       field('currency', 'USD'), field('shipment_date', '2026-10-08')])
    return dict(file_id=file_id, file_name=f'{doc_type.lower()}-{file_id}.json',
                doc_type=doc_type, parse_method=parse_method, fields=fields)


def comparison_value(value):
    # Numeric equality is exact decimal equality; bool is not a number here.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return ('number', Decimal(str(value)))
    return (type(value).__name__, json.dumps(value, sort_keys=True))


def expected_comparison(documents):
    groups = {}
    for doc in documents:
        for f in doc['fields']:
            key = (f['item_id'], f['field_key'])
            groups.setdefault(key, []).append(dict(file_id=doc['file_id'],
                line_no=f['line_no'], unit=f['unit'], raw_value=f['raw_value'],
                normalized_value=f['normalized_value'], field_status=f['status']))
    result = []
    for index, ((identity, key), entries) in enumerate(
            sorted(groups.items(), key=lambda kv: (kv[0][0] or '', kv[0][1])), 1):
        applicable = [v for v in entries if v['field_status'] != 'NOT_IN_DOC']
        usable = [v for v in applicable if v['normalized_value'] is not None]
        encoded = {(v['unit'], comparison_value(v['normalized_value'])) for v in usable}
        invalid = [v for v in applicable if v['normalized_value'] is None]
        if len(encoded) > 1:
            status, note = 'CONFLICT', 'Usable evidence disagrees; review all sources.'
        elif not applicable:
            status, note = 'NOT_CHECKED', 'Field is not applicable in these templates.'
        elif not usable:
            if all(v['field_status'] == 'UNRECOGNIZED' for v in applicable):
                status, note = 'UNRECOGNIZED', 'All applicable sources are unreadable.'
            elif all(v['field_status'] == 'MISSING_IN_DOC' for v in applicable):
                # The public contract has no ALL_MISSING enum. Keep the
                # contract value and make the narrower meaning explicit.
                status, note = 'MISSING_IN_SOME', 'All applicable sources are missing this field.'
            else:
                status, note = 'NOT_CHECKED', 'No usable evidence; all applicable sources missing or unreadable.'
        elif invalid:
            if any(v['field_status'] == 'MISSING_IN_DOC' for v in invalid):
                status = 'MISSING_IN_SOME'
            else:
                status = 'NOT_CHECKED'
            kinds = ', '.join(sorted({v['field_status'] for v in invalid}))
            note = f'{len(usable)} usable source(s); {len(invalid)} source(s) unavailable ({kinds}).'
        elif len(usable) == 1:
            status, note = 'SINGLE_SOURCE', 'Only one applicable usable source.'
        else:
            status, note = 'MATCH', 'Applicable usable sources agree.'
        if any(v['field_status'] == 'LOW_CONFIDENCE' for v in applicable):
            note += ' Low-confidence evidence requires review.'
        result.append(dict(comparison_id=f'cmp_{index:03d}', item_id=identity,
                           field_key=key, status=status, canonical_value=None,
                           note=note, values=entries))
    return result


def make_case(name, items, documents):
    comparisons = expected_comparison(documents)
    risks = []
    for c in comparisons:
        if c['status'] in {'CONFLICT', 'MISSING_IN_SOME', 'UNRECOGNIZED', 'NOT_CHECKED'} or any(v['field_status'] == 'LOW_CONFIDENCE' for v in c['values']):
            risks.append(dict(risk_id=f'risk_{len(risks)+1:03d}', type='OTHER',
                severity='WARNING', item_id=c['item_id'], related_field_keys=[c['field_key']],
                related_file_ids=[v['file_id'] for v in c['values'] if v['field_status'] != 'NOT_IN_DOC'],
                comparison_id=c['comparison_id'], rule_id=f"SYNTHETIC_REVIEW_{'LOW_CONFIDENCE' if any(v['field_status'] == 'LOW_CONFIDENCE' for v in c['values']) else c['status']}",
                rule_source='Synthetic test profile v1; not legal guidance',
                title=f"Review {c['field_key']}: {c['status']}"))
    return dict(case_id=name, description=name.replace('_', ' '),
        task=dict(task_id=f'generated_{name}', destination_country='DE', created_at=CREATED_AT),
        items=[{k: x[k] for k in ('item_id', 'display_name', 'description', 'item_order')} for x in items],
        documents=documents, expected=dict(comparisons=comparisons, risks=risks))


def build_cases(seed=20261010):
    rng = random.Random(seed)
    quantity = rng.randrange(80, 121) * 24
    delta = rng.randrange(1, 6) * 24
    one = [item('item_001', '陶瓷马克杯', 'CERAMIC MUG 350ML WHITE', '691110', quantity, quantity // 24, 1)]
    two = one + [item('item_002', '玻璃水杯', 'GLASS CUP 500ML', '701349', 800, 40, 2)]
    cases = []

    def add(name, cargo, invoice_kwargs=None, packing_kwargs=None, bill_kwargs=None):
        docs = [document('f1', 'COMMERCIAL_INVOICE', cargo,
                         invoice_no=f'INV-{seed}-{name}', amount=float(sum(x['quantity'] for x in cargo)*5),
                         **(invoice_kwargs or {})),
                document('f2', 'PACKING_LIST', cargo, **(packing_kwargs or {}))]
        if bill_kwargs is not None:
            docs.append(document('f3', 'BILL_OF_LADING', cargo, **bill_kwargs))
        cases.append(make_case(name, cargo, docs))

    add('normal_single', one, packing_kwargs={'shipment_weight': 2400}, bill_kwargs={'shipment_weight': 2400})
    add('quantity_conflict_single', one, packing_kwargs={'quantity_deltas': {'item_001': delta}})
    add('weight_conflict_single', one, {'shipment_weight': 2380}, {'shipment_weight': 2400})
    add('missing_hs_single', one, {'missing': {'hs_code'}})
    add('normal_multi', two)
    add('one_item_conflict_multi', two, packing_kwargs={'quantity_deltas': {'item_001': delta}})
    add('different_order_multi', two, {'item_weights': {'item_001': 2400, 'item_002': 800}},
        {'order': ['item_002', 'item_001'], 'item_weights': {'item_001': 2400, 'item_002': 800}})
    add('whole_shipment_weight_multi', two, {'shipment_weight': 3200}, {'shipment_weight': 3200})
    add('unrecognized_single', one, {'unrecognized': {'description'}}, {'unrecognized': {'description'}})
    add('low_confidence_single', one, {'low_confidence': {'description'}})
    add('partial_unrecognized_single', one, {'unrecognized': {'description'}})
    add('all_missing_single', one, {'missing': {'hs_code'}}, {'missing': {'hs_code'}})
    add('one_item_missing_multi', two, {'missing': {('item_002', 'hs_code')}})
    weight = quantity * 0.5
    add('scope_mismatch_multi', two, {'item_weights': {'item_001': weight, 'item_002': 400}},
        {'shipment_weight': weight + 400})
    add('bill_weight_conflict', one, packing_kwargs={'shipment_weight': weight},
        bill_kwargs={'shipment_weight': weight + 20, 'parse_method': 'OCR'})
    add('multiple_errors_multi', two, {'missing': {('item_002', 'hs_code')}},
        {'quantity_deltas': {'item_001': delta}, 'unrecognized': {('item_002', 'description')}})
    # Source formatting is deliberately different while normalized values agree.
    dirty = next(c for c in cases if c['case_id'] == 'normal_single')
    for doc in dirty['documents']:
        for f in doc['fields']:
            if f['field_key'] == 'gross_weight':
                f['raw_value'] = '2,400.00 KG' if doc['file_id'] == 'f2' else '2400KGS'
    return cases


def write_json(path, value):
    with path.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def write_cases(output, seed):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cases = build_cases(seed)
    # Manifest is authoritative; unknown or stale files are preserved.
    names = {c['case_id'] + '.json' for c in cases} | {'manifest.json'}
    stale = sorted(p.name for p in output.glob('*.json') if p.name not in names)
    if stale:
        warnings.warn(f'JSON files outside current manifest (preserved): {stale}')
    manifest = dict(format_version='synthetic-v3', generator_seed=seed, case_count=len(cases), cases=[])
    for case in cases:
        filename = f"{case['case_id']}.json"
        write_json(output / filename, case)
        manifest['cases'].append(dict(case_id=case['case_id'], file=filename))
    write_json(output / 'manifest.json', manifest)
    return len(cases)


def main():
    parser = argparse.ArgumentParser(description='生成可复现的模拟单证 JSON')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--seed', type=int, default=20261010)
    args = parser.parse_args()
    count = write_cases(args.output, args.seed)
    print(f'已生成 {count} 组样例：{args.output}')


if __name__ == '__main__':
    main()
