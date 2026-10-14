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


def test_done_without_scope_is_read_not_failed():
    """契约里 scope 是可选的（旧结果可缺省）。缺范围只表示不知道分数的适用边界，
    页面如实说明即可，不能把一份真实跑出来的分数整份判成失败。"""
    data = result()
    del data['scope']
    assert validate_result(data).status.value == 'DONE'


def test_count_without_score_is_allowed_but_score_without_count_is_not():
    """计数可以多于指标（未评分的指标如实留空），反过来则不允许。"""
    data = result()
    data['scope']['counts']['risk_hint'] = {'tp': 0, 'fp': 0, 'fn': 0}
    assert validate_result(data).status.value == 'DONE'
    data = result()
    del data['scope']['counts']['field_extraction']
    with pytest.raises(ValueError, match='范围'):
        validate_result(data)


def test_rounded_scores_are_accepted_but_fabricated_ones_are_not():
    """结果文件按展示精度保存分数，容差要容忍舍入；伪造的满分仍须被挡住。"""
    data = result()
    data['metrics']['field_extraction'] = {'precision': 0.5, 'recall': 0.5, 'f1': 0.5}
    assert validate_result(data).status.value == 'DONE'
    data['metrics']['field_extraction'] = {'precision': 1.0, 'recall': 1.0, 'f1': 1.0}
    with pytest.raises(ValueError, match='不一致'):
        validate_result(data)


def test_publication_survives_client_restart_and_preserves_history(client, tmp_path, monkeypatch):
    monkeypatch.setenv('EVALUATION_RESULT_PATH', str(tmp_path / 'latest.json'))
    from tools.evaluate_dataset import publish
    first = result()
    publish(first, tmp_path)
    second = deepcopy(first)
    second['run_at'] = '2026-10-14T01:00:00Z'
    second['scope']['input_kind'] = '模拟扫描 PNG'
    publish(second, tmp_path)
    # 新建客户端仍从磁盘读取；发布不修改第一批记录。
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as restarted:
        latest = restarted.get('/api/v1/evaluation/latest').json()
        history = restarted.get('/api/v1/evaluation/runs').json()
    assert latest['run_at'] == second['run_at']
    assert [entry['run_at'] for entry in history] == [second['run_at'], first['run_at']]
    invalid = deepcopy(second)
    invalid['metrics']['field_extraction']['f1'] = 1
    with pytest.raises(ValueError):
        publish(invalid, tmp_path)
    assert json.loads((tmp_path / 'latest.json').read_text()) == second


def test_dataset_hash_and_scan_gold_mapping(tmp_path):
    import csv
    import hashlib
    from tools.evaluate_dataset import read_dataset
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'docs/fixtures/result').mkdir(parents=True)
    gold = task()
    gold['documents'][0]['file_name'] = 'invoice.pdf'
    (tmp_path / 'docs/fixtures/result/one.json').write_text(json.dumps(gold))
    extraction = deepcopy(gold['extractions'][0])
    extraction['file_id'] = 'f1_scan'
    (tmp_path / 'scan-gold.json').write_text(json.dumps(extraction))
    (tmp_path / 'inputs/invoice.pdf').write_bytes(b'%PDF-source')
    (tmp_path / 'inputs/invoice.scan.png').write_bytes(b'png-source')
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
              for name in ['inputs/invoice.pdf', 'inputs/invoice.scan.png']}
    (tmp_path / 'input_sha256.json').write_text(json.dumps(hashes))
    (tmp_path / 'dataset_provenance.json').write_text('{"dataset_version":"unit"}')
    fields = ['shipment_group_id', 'file_type', 'parent_document_id', 'local_path', 'split', 'extraction_path']
    with (tmp_path / 'dataset_manifest.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            dict(zip(fields, ['one', 'PDF', '', 'inputs/invoice.pdf', 'test', 'unused'])),
            dict(zip(fields, ['one', 'IMAGE', 'f1', 'inputs/invoice.scan.png', 'test', 'scan-gold.json'])),
        ])
    cases, _, _, text_hash = read_dataset(tmp_path, 'test', 'text')
    scanned, _, _, scan_hash = read_dataset(tmp_path, 'test', 'png')
    assert len(cases) == len(scanned) == 1
    assert text_hash != scan_hash
    assert scanned[0][2]['documents'][0]['file_name'] == 'invoice.scan.png'
    assert scanned[0][2]['extractions'][0]['file_id'] == 'f1'
    (tmp_path / 'inputs/invoice.pdf').write_bytes(b'changed')
    with pytest.raises(ValueError, match='哈希'):
        read_dataset(tmp_path, 'test', 'text')
