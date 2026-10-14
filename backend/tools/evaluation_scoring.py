"""合成金标的严格微平均计分；不使用被测系统的归一函数修正答案。"""

from collections import Counter, defaultdict
from decimal import Decimal
import unicodedata

SCORER_VERSION = 'synthetic-exact-v1'


def canonical(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(Decimal(str(value)).normalize())
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def item_scopes(task):
    """商品身份只取其货号；不按行序或显示名称猜测跨文件对应。"""
    codes = defaultdict(set)
    for extraction in task.get('extractions', []):
        for field in extraction['fields']:
            if field.get('item_id') and field['field_key'] == 'item_code' and field.get('normalized_value') is not None:
                codes[field['item_id']].add(canonical(field['normalized_value']))
    return {item: next(iter(values)) for item, values in codes.items() if len(values) == 1}


def item_ids(task):
    """任务里出现过的商品行标识（有 item_id 的字段即视为商品级）。"""
    return {field['item_id'] for extraction in task.get('extractions', [])
            for field in extraction['fields'] if field.get('item_id')}


def unidentifiable_items(task):
    """有商品行、但拿不到唯一货号的商品。

    这些行会被 scope() 归入 unaligned 并带上来源侧前缀，金标与预测永远对不上，
    于是同时计 FP 和 FN——一份完全正确的预测也会得到很低的分数。
    金标缺行级货号属于数据问题，必须显式失败，不能让分数静默失真。
    """
    return sorted(item_ids(task) - set(item_scopes(task)))


def scope(field, scopes, source):
    item = field.get('item_id')
    if item is None and field.get('line_no') is None:
        return 'document'
    return 'sku:' + scopes[item] if item in scopes else f'unaligned:{source}:{item}:{field.get("line_no")}'


def facts(task, source, field_keys=None):
    files = {d['file_id']: d['file_name'] for d in task.get('documents', [])}
    scopes = item_scopes(task)
    result = Counter()
    for extraction in task.get('extractions', []):
        for field in extraction['fields']:
            if field_keys is not None and field['field_key'] not in field_keys:
                continue
            if field.get('normalized_value') is None:
                continue
            # 金标和预测都只取实际值；失败任务不凭状态获得任何正确分。
            fact = (files.get(extraction['file_id'], extraction['file_id']),
                    scope(field, scopes, source), field['field_key'],
                    canonical(field['normalized_value']), canonical(field.get('unit')))
            result[fact] += 1
    return result


def conflicts(task, source):
    scopes = item_scopes(task)
    return Counter((scope(c, scopes, source), c['field_key'])
                   for c in task.get('comparisons', []) if c['status'] == 'CONFLICT')


def compare(expected, actual):
    return {'tp': sum((expected & actual).values()),
            'fp': sum((actual - expected).values()),
            'fn': sum((expected - actual).values())}


def score_task(gold, actual):
    # 金标有商品行却拿不到唯一货号时，这些行必然与预测对不上并同时计 FP/FN，
    # 分数会静默失真（正确预测也可能拿很低的分）。这是数据问题，直接失败。
    missing = unidentifiable_items(gold)
    if missing:
        raise ValueError('金标商品行缺少唯一货号，无法对齐：' + ', '.join(missing))
    # 字段范围由整个金标定义，包括尚未实现的字段；不能按模型当前支持列表缩小分母。
    keys = {f['field_key'] for e in gold['extractions'] for f in e['fields']}
    expected, predicted = facts(gold, 'gold'), facts(actual, 'actual', keys)
    gold_conflicts, actual_conflicts = conflicts(gold, 'gold'), conflicts(actual, 'actual')
    return {
        'counts': {'field_extraction': compare(expected, predicted),
                   'conflict_detection': compare(gold_conflicts, actual_conflicts)},
        'errors': {
            'missing_or_wrong_fields': [list(fact) + [count] for fact, count in (expected - predicted).items()],
            'extra_or_wrong_fields': [list(fact) + [count] for fact, count in (predicted - expected).items()],
            'missed_conflicts': [list(key) + [count] for key, count in (gold_conflicts - actual_conflicts).items()],
            'extra_conflicts': [list(key) + [count] for key, count in (actual_conflicts - gold_conflicts).items()],
        },
    }
