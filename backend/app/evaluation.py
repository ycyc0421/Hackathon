"""读取已保存的评测结果；普通上传与读取接口都不启动评测。"""

import json
import logging
import math
import os
from pathlib import Path

from .models import Evaluation, dump, not_run_evaluation
from .config import DATA_DIR

DEFAULT_RESULT = DATA_DIR / 'evaluation/latest.json'


def scores(counts):
    tp, fp, fn = (counts[key] for key in ('tp', 'fp', 'fn'))
    return {
        'precision': tp / (tp + fp) if tp + fp else None,
        'recall': tp / (tp + fn) if tp + fn else None,
        'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    }


def validate_result(data):
    result = Evaluation.model_validate(data)
    if result.status.value == 'DONE':
        # scope 在契约里是可选字段（旧结果可缺省），所以这里不要求它。
        # 缺 scope 只意味着「不知道这份分数在什么范围内成立」，由页面如实说明，
        # 不能因此把一份真实跑出来的分数整份判成失败。
        if not result.run_at or not result.metrics or result.sample_count < 1:
            raise ValueError('完成结果缺少时间、样本或指标')
        metrics = result.metrics.model_dump(exclude_none=True)
        if not metrics:
            raise ValueError('完成结果缺少指标')
        counts = result.scope.counts if result.scope else {}
        # 每个计了分的指标都必须有计数，但计数可以多于指标：
        # 契约允许 risk_hint 这类指标只给计数、不给分数（当前跑分脚本就不计风险提示）。
        # 缺 scope 时没有计数可比，只校验分数本身（见上一条注释）。
        if result.scope and not set(metrics) <= set(counts):
            raise ValueError('指标与计数范围不一致')
        for name, count in counts.items():
            if name not in ('field_extraction', 'conflict_detection', 'risk_hint'):
                raise ValueError('未知指标')
            if name not in metrics:
                continue
            for key, expected in scores(count.model_dump()).items():
                actual = metrics[name].get(key)
                # 结果文件按展示精度保存分数，容差要能容忍舍入；仍能挡住伪造的满分
                # （计数全 0 却写 1.0 这类差异远大于容差）。
                if (expected is None and actual is not None) or (expected is not None and
                        (actual is None or not math.isclose(actual, expected, rel_tol=1e-6, abs_tol=1e-9))):
                    raise ValueError('计数与分数不一致')
    return result


def latest():
    path = Path(os.environ.get('EVALUATION_RESULT_PATH') or DEFAULT_RESULT)
    try:
        if not path.exists():
            return dump(not_run_evaluation())
        result = dump(validate_result(json.loads(path.read_text(encoding='utf-8'))))
        if result['metrics'] is not None:
            result['metrics'] = {key: value for key, value in result['metrics'].items() if value is not None}
        return result
    except (OSError, ValueError, TypeError):
        logging.getLogger(__name__).exception('读取评测文件失败')
        return dump(Evaluation(status='FAILED', sample_count=0, metrics=None))


def history():
    directory = Path(os.environ.get('EVALUATION_RESULT_PATH') or DEFAULT_RESULT).parent / 'runs'
    results = []
    for path in sorted(directory.glob('*.json'), reverse=True)[:30]:
        try:
            data = dump(validate_result(json.loads(path.read_text(encoding='utf-8'))))
            if data['metrics'] is not None:
                data['metrics'] = {key: value for key, value in data['metrics'].items() if value is not None}
            results.append(data)
        except (OSError, ValueError, TypeError):
            logging.getLogger(__name__).exception('读取历史评测文件失败')
            results.append(dump(Evaluation(status='FAILED', sample_count=0, metrics=None)))
    return results
