"""Report projection of one stored task. Presentation belongs to the client."""
import copy
from .pipeline import rules
from . import rule_sources


def content(task, corrections):
    def unique(records, key, value):
        matches = [record for record in records if record.get(key) == value]
        return matches[0] if len(matches) == 1 else {}
    current = rules.load_rules()
    # These definitions are current export metadata, never a historical snapshot.
    definitions = {}
    for country in current.get('countries', {}).values():
        for collection in ('required_documents', 'hs_rules', 'certificate_rules'):
            for entry in country.get(collection, []):
                if isinstance(entry, dict) and entry.get('rule_id'):
                    definitions[entry['rule_id']] = entry
    source_ids = set()
    risks = copy.deepcopy(task['risks'])
    for risk in risks:
        entry = definitions.get(risk.get('rule_id'), {})
        ids = entry.get('source_ids', [])
        source_ids.update(ids)
        unverified = rules.UNVERIFIED_PREFIX in risk['title'] or rules.UNVERIFIED_DISCLAIMER in risk['detail']
        risk['title'] = risk['title'].replace(rules.UNVERIFIED_PREFIX, '')
        risk['detail'] = risk['detail'].replace(rules.UNVERIFIED_DISCLAIMER, '')
        risk['rule_source'] = (risk.get('rule_source') or '').replace(rules.UNVERIFIED_SOURCE_SUFFIX, '').replace('（官方来源候选；适用条件未经人工核实）', '') or None
        risk['rule_context'] = {
            'verification_status': 'UNVERIFIED' if unverified else ('NOT_CHECKED' if not risk.get('rule_id') else 'UNKNOWN'),
            'source_ids': ids,
            'applicability': copy.deepcopy(entry.get('applicability')),
            'definition_scope': 'CURRENT_AT_EXPORT' if entry else 'UNKNOWN',
        }
    documents = copy.deepcopy(task['documents'])
    # 仅补齐未在票级比对中出现的字段，避免把完整抽取结果重复导出。
    compared = {(value['file_id'], comparison['field_key'])
                for comparison in task['comparisons'] if comparison.get('scope', 'DOCUMENT') == 'DOCUMENT'
                for value in comparison['values']}
    for document in documents:
        extraction = unique(task['extractions'], 'file_id', document['file_id'])
        document['identifiers'] = [copy.deepcopy(f) for f in extraction.get('fields', [])
                                   if f['field_key'] in {'document_no', 'invoice_no'}]
        document['fields'] = [copy.deepcopy(f) for f in extraction.get('fields', [])
                              if f['status'] != 'NOT_IN_DOC'
                              and f['field_key'] not in {'document_no', 'invoice_no'}
                              and (document['file_id'], f['field_key']) not in compared]
        document['original_url'] = f"/api/v1/checks/{task['task_id']}/files/{document['file_id']}"
    comparisons = copy.deepcopy(task['comparisons'])
    for comparison in comparisons:
        item = unique(task['items'], 'item_id', comparison.get('item_id'))
        for value in comparison['values']:
            extraction = unique(task['extractions'], 'file_id', value['file_id'])
            row_no = None
            fields = extraction.get('fields', [])
            if comparison.get('scope') == 'ITEM':
                members = [m for m in item.get('members', []) if m['file_id'] == value['file_id']]
                row_no = members[0]['item_no'] if len(members) == 1 else None
                row = unique(extraction.get('line_items', []), 'item_no', row_no)
                fields = row.get('fields', [])
            candidates = [f for f in fields if f['field_key'] == comparison['field_key']]
            source = candidates[0] if len(candidates) == 1 else {}
            value['evidence'] = {'raw_text': source.get('raw_text'), 'bbox_unit': source.get('bbox_unit'),
                                 'line_no': row_no, 'status': 'LOCATED' if source else 'UNAVAILABLE'}
    # Keep unaligned evidence accessible without duplicating every comparison field.
    evidence = []
    aligned = {(m['file_id'], m['item_no']) for i in task['items'] for m in i['members']}
    for extraction in task['extractions']:
        for row in extraction.get('line_items', []):
            if (extraction['file_id'], row['item_no']) not in aligned:
                evidence.append({'file_id': extraction['file_id'], 'item_no': row['item_no'], **copy.deepcopy(row)})
    history = []
    for audit in corrections:
        record = {k: copy.deepcopy(v) for k, v in audit.items() if k != 'changes'}
        record['changes'] = []
        for change in audit['changes']:
            reduced = {k: copy.deepcopy(v) for k, v in change.items() if k not in {'before', 'after'}}
            for key in ('before', 'after'):
                reduced[key] = {k: copy.deepcopy(v) for k, v in change[key].items()
                                if k in {'normalized_value', 'unit', 'status'}}
            record['changes'].append(reduced)
        history.append(record)
    sources = rule_sources.status(source_ids=source_ids)
    return {
        'task': {k: copy.deepcopy(task[k]) for k in ('task_id', 'status', 'created_at', 'finished_at', 'input', 'summary')},
        'documents': documents, 'items': copy.deepcopy(task['items']),
        'comparisons': comparisons, 'risks': risks,
        'errors': [copy.deepcopy(e) for e in task['errors'] if e['code'] != 'RULES_UNVERIFIED'], 'unaligned_evidence': evidence,
        'corrections': history,
        'provenance': {
            'execution_rule_version': corrections[-1]['rule_version'] if corrections else None,
            'execution_version_status': 'RECORDED_IN_CORRECTION' if corrections else 'UNKNOWN',
            'rule_verification_status': 'UNVERIFIED' if any(e['code'] == 'RULES_UNVERIFIED' for e in task['errors']) or any(r['rule_context']['verification_status'] == 'UNVERIFIED' for r in risks) else 'UNKNOWN',
            'source_metadata_scope': 'CURRENT_AT_EXPORT',
            'current_definition_version': current.get('version'),
            'monitor_mode': sources['mode'], 'monitor_checked_at': sources['checked_at'],
            'sources': sources['sources'], 'pending_updates': sources['pending_updates'],
        },
        'limitations': ['PROCESSING_IS_NOT_COMPLIANCE', 'UNKNOWN_HISTORY_IS_NOT_CURRENT_VERSION',
                        'UNVERIFIED_RULES_REQUIRE_REVIEW'],
    }
