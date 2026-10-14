"""读取已保存的评测结果；普通上传与读取接口都不启动评测。"""

import json
import logging
import math
import os
from pathlib import Path

from .models import Evaluation, dump, not_run_evaluation

DEFAULT_RESULT = Path(__file__).resolve().parents[1] / 'evaluation/latest.json'


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
        if not result.scope or not result.run_at or not result.metrics or result.sample_count < 1:
            raise ValueError('完成结果缺少范围、时间、样本或指标')
        metrics = result.metrics.model_dump(exclude_none=True)
        counts = result.scope.counts
        if set(metrics) != set(counts) or not metrics:
            raise ValueError('指标与计数范围不一致')
        for name, count in counts.items():
            if name not in ('field_extraction', 'conflict_detection', 'risk_hint'):
                raise ValueError('未知指标')
            for key, expected in scores(count.model_dump()).items():
                actual = metrics[name].get(key)
                if (expected is None and actual is not None) or (expected is not None and
                        (actual is None or not math.isclose(actual, expected, abs_tol=1e-9))):
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
