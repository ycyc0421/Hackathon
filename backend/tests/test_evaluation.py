"""评测必须使用实际输出，错值、漏检与失败不能计为正确。"""

from copy import deepcopy
import json

import pytest
from test_api_samples import validate_response

from app.evaluation import scores, validate_result
from tools.evaluation_scoring import score_task


def task():
    return {'documents': [{'file_id': 'f1', 'file_name': 'invoice.pdf'}],
            'extractions': [{'file_id': 'f1', 'fields': [
                {'field_key': 'item_code', 'item_id': 'i1', 'line_no': 1, 'normalized_value': 'SKU-A', 'unit': None},
                {'field_key': 'quantity', 'item_id': 'i1', 'line_no': 1, 'normalized_value': 10, 'unit': 'PCS'},
            ]}], 'comparisons': [{'item_id': 'i1', 'field_key': 'quantity', 'status': 'CONFLICT'}]}


def test_correct_values_match_by_sku_not_runtime_ids():
    gold = task()
    actual = deepcopy(gold)
    for f in actual['extractions'][0]['fields']:
        f['item_id'] = 'other-id'
        f['line_no'] = 8
    actual['comparisons'][0]['item_id'] = 'other-id'
    result = score_task(gold, actual)['counts']
    assert result['field_extraction'] == {'tp': 2, 'fp': 0, 'fn': 0}
    assert result['conflict_detection'] == {'tp': 1, 'fp': 0, 'fn': 0}


def test_wrong_values_and_missed_conflict_reduce_scores():
    gold = task()
    actual = deepcopy(gold)
    actual['extractions'][0]['fields'][1]['normalized_value'] = 11
    actual['comparisons'][0]['status'] = 'NOT_CHECKED'
    result = score_task(gold, actual)['counts']
    assert result['field_extraction'] == {'tp': 1, 'fp': 1, 'fn': 1}
    assert result['conflict_detection'] == {'tp': 0, 'fp': 0, 'fn': 1}


def test_failed_tasks_keep_all_expected_facts_in_denominator():
    result = score_task(task(), {'status': 'FAILED'})['counts']
    assert result['field_extraction'] == {'tp': 0, 'fp': 0, 'fn': 2}
    assert result['conflict_detection'] == {'tp': 0, 'fp': 0, 'fn': 1}


def test_duplicates_wrong_units_and_unaligned_rows_are_not_hidden():
    gold = task()
    actual = deepcopy(gold)
    fields = actual['extractions'][0]['fields']
    fields[1]['unit'] = 'CARTON'
    fields.append(deepcopy(fields[0]))
    assert score_task(gold, actual)['counts']['field_extraction'] == {'tp': 1, 'fp': 2, 'fn': 1}
    fields[:] = [fields[1]]
    assert score_task(gold, actual)['counts']['field_extraction'] == {'tp': 0, 'fp': 1, 'fn': 2}


def test_no_denominator_is_not_a_perfect_score():
    assert scores({'tp': 0, 'fp': 0, 'fn': 0}) == {'precision': None, 'recall': None, 'f1': None}
    assert scores({'tp': 0, 'fp': 0, 'fn': 3}) == {'precision': None, 'recall': 0, 'f1': 0}


def result():
    return {'status': 'DONE', 'dataset_version': 'synthetic-test', 'sample_count': 1,
            'model_version': 'text-only', 'run_at': '2026-10-14T00:00:00Z',
            'metrics': {'field_extraction': scores({'tp': 1, 'fp': 1, 'fn': 1})},
            'scope': {'dataset_kind': '合成', 'input_kind': '文本 PDF', 'split': 'test',
                      'document_count': 1, 'code_revision': 'abc', 'scorer_version': 'v1',
                      'dataset_sha256': 'abc', 'limitations': ['未运行 OCR'],
                      'metric_definitions': {'field_extraction': '严格计分'},
                      'counts': {'field_extraction': {'tp': 1, 'fp': 1, 'fn': 1}}}}


def test_saved_evaluation_is_read_and_matches_contract(client, tmp_path, validate_response):
    expected = result()
    (tmp_path / 'evaluation.json').write_text(json.dumps(expected))
    response = client.get('/api/v1/evaluation/latest')
    assert response.status_code == 200
    actual = response.json()
    validate_response(actual, 'evaluation')
    assert actual['status'] == 'DONE'
    assert actual['scope'] == expected['scope']
    assert actual['metrics']['field_extraction'] == expected['metrics']['field_extraction']


@pytest.mark.parametrize('contents', ['invalid JSON', '{"status":"DONE"}', 'tampered'])
def test_corrupt_or_tampered_result_fails_without_scores(client, tmp_path, contents):
    if contents == 'tampered':
        data = result()
        data['metrics']['field_extraction']['recall'] = 1
        contents = json.dumps(data)
    (tmp_path / 'evaluation.json').write_text(contents)
    response = client.get('/api/v1/evaluation/latest').json()
    assert response['status'] == 'FAILED'
    assert response['metrics'] is None


def test_unsupported_risk_score_cannot_appear_without_counts():
    data = result()
    data['metrics']['risk_hint'] = {'precision': 1}
    with pytest.raises(ValueError, match='范围'):
        validate_result(data)
