"""对数据包原始文本 PDF 跑隔离后端，并保存真实结果、错例和可发布摘要。"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from tools.evaluation_scoring import SCORER_VERSION, score_task


def read_dataset(dataset, split):
    dataset = dataset.resolve()
    def read(relative):
        path = (dataset / relative).resolve()
        if not path.is_relative_to(dataset):
            raise ValueError('数据清单包含目录外路径')
        return path.read_bytes()
    rows = list(csv.DictReader(read('dataset_manifest.csv').decode('utf-8-sig').splitlines()))
    hashes = json.loads(read('input_sha256.json'))
    groups = {}
    fingerprints = {}
    for row in rows:
        if row['parent_document_id'] or row['file_type'] != 'PDF' or (split != 'all' and row['split'] != split):
            continue
        raw = read(row['local_path'])
        digest = hashlib.sha256(raw).hexdigest()
        if digest != hashes[row['local_path']]:
            raise ValueError('输入文件哈希不符：' + row['local_path'])
        fingerprints[row['local_path']] = digest
        groups.setdefault(row['shipment_group_id'], []).append((row, raw))
    if not groups:
        raise ValueError('指定划分没有文本 PDF')
    cases = []
    for shipment, documents in sorted(groups.items()):
        gold_path = f'docs/fixtures/result/{shipment}.json'
        raw = read(gold_path)
        fingerprints[gold_path] = hashlib.sha256(raw).hexdigest()
        gold = json.loads(raw)
        names = [Path(row['local_path']).name for row, _ in documents]
        if len(set(names)) != len(names) or set(names) != {d['file_name'] for d in gold['documents']}:
            raise ValueError('输入文件与金标文件清单不一致：' + shipment)
        if len({row['split'] for row, _ in documents}) != 1:
            raise ValueError('同票跨数据划分：' + shipment)
        cases.append((shipment, documents, gold))
    for name in ('dataset_provenance.json', 'dataset_manifest.csv', 'input_sha256.json'):
        fingerprints[name] = hashlib.sha256(read(name)).hexdigest()
    digest = hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()
    return cases, json.loads(read('dataset_provenance.json')), fingerprints, digest


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def run(dataset, output, split='test'):
    cases, provenance, fingerprints, dataset_hash = read_dataset(dataset, split)
    output.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip():
        raise ValueError('被测工作区须先提交，避免版本记录与实际代码不一致')
    started = time.monotonic()
    counts = {name: Counter(tp=0, fp=0, fn=0) for name in ('field_extraction', 'conflict_detection')}
    tasks, summaries = [], []
    # 首次导入应用前隔离运行库及外部推理配置；金标从不作为上传输入。
    with TemporaryDirectory(prefix='dataset-evaluation-') as temporary:
        temporary = Path(temporary)
        os.environ.update(TASK_DB_PATH=str(temporary / 'tasks.db'), PADDLE_OCR_ENABLED='0',
                          LLM_BASE_URL='', LLM_API_KEY='', LLM_MODEL='')
        from fastapi.testclient import TestClient
        from app import config, main
        from app.evaluation import scores, validate_result
        from app.pipeline import runner
        from app.sqlite_store import TaskStore
        store = TaskStore(temporary / 'isolated.db', temporary / 'legacy')
        with patch.object(main, 'store', store), patch.object(runner, 'store', store), +             patch.object(main, 'UPLOAD_DIR', temporary / 'uploads'), +             patch.object(runner, 'UPLOAD_DIR', temporary / 'uploads'), +             patch.object(config, 'DATA_DIR', temporary), +             patch.object(config, 'TASK_DIR', temporary / 'legacy'), +             patch.object(config, 'UPLOAD_DIR', temporary / 'uploads'), TestClient(main.app) as client:
            for index, (shipment, documents, gold) in enumerate(cases, 1):
                response = client.post('/api/v1/checks', data={'destination_country': gold['input']['destination_country']},
                                       files=[('files', (Path(row['local_path']).name, raw, 'application/pdf'))
                                              for row, raw in documents])
                response.raise_for_status()
                task_id = response.json()['task_id']
                deadline = time.monotonic() + 90
                while True:
                    response = client.get('/api/v1/checks/' + task_id)
                    response.raise_for_status()
                    task = response.json()
                    if task['status'] in ('COMPLETED', 'PARTIAL', 'FAILED'):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('评测任务超时：' + shipment)
                    time.sleep(0.1)
                (output / 'tasks').mkdir(exist_ok=True)
                write_json(output / 'tasks' / f'{shipment}.json', task)
                result = score_task(gold, task)
                for name in counts:
                    counts[name].update(result['counts'][name])
                tasks.append(task)
                summaries.append({'shipment': shipment, 'split': documents[0][0]['split'],
                                  'status': task['status'], **result})
                print(f'{index}/{len(cases)} {shipment}: {task["status"]}', flush=True)
    result = {
        'status': 'DONE', 'dataset_version': provenance['dataset_version'], 'sample_count': len(cases),
        'model_version': f'text-layer-pipeline@{revision[:12]}（未运行 OCR）',
        'metrics': {name: scores(count) for name, count in counts.items()},
        'error_breakdown': {'字段漏读或值不符': counts['field_extraction']['fn'],
                            '字段多读或值不符': counts['field_extraction']['fp'],
                            '冲突漏检': counts['conflict_detection']['fn'],
                            '冲突误报': counts['conflict_detection']['fp'],
                            '未完整完成的货票': sum(t['status'] != 'COMPLETED' for t in tasks)},
        'run_at': datetime.now(timezone.utc).isoformat(),
        'scope': {
            'dataset_kind': '合成数据，单一英文版式', 'input_kind': '文本 PDF（非 OCR）', 'split': split,
            'document_count': sum(len(documents) for _, documents, _ in cases), 'code_revision': revision,
            'scorer_version': SCORER_VERSION, 'dataset_sha256': dataset_hash,
            'limitations': ['本数据集曾用于开发和回归，不能视为未见测试集或泛化准确率。',
                            '仅执行文本 PDF；PNG、扫描 PDF、EDI 和多版式 OCR 未计入。',
                            '金标为数据包生成预期；包含尚未实现的字段，未按支持范围删减分母。',
                            '字符串仅做 Unicode、大小写和空白归一；不自动等同中英品名或业务近义词。',
                            '目的国规则未核实，风险提示未评分；字段错误可能同时计为漏读与多读，分类不可直接相加。'],
            'metric_definitions': {
                'field_extraction': '以文件名、货号、字段键、归一值和单位组成事实，多重集合微平均；错误值计 FP 和 FN。只评分金标定义的字段键，不评分页码坐标。',
                'conflict_detection': '以货号和字段键标识冲突；CONFLICT 为正类，漏检或未检查计 FN，多报计 FP；内部风险不充作冲突。',
            },
            'counts': {name: dict(count) for name, count in counts.items()},
        },
    }
    validate_result(result)
    write_json(output / 'evaluation.json', result)
    write_json(output / 'details.json', {'elapsed_seconds': time.monotonic() - started, 'cases': summaries})
    write_json(output / 'manifest.json', {'dataset_sha256': dataset_hash, 'files': fingerprints})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--split', choices=['train', 'validation', 'test', 'all'], default='test')
    args = parser.parse_args()
    run(args.dataset, args.out, args.split)
