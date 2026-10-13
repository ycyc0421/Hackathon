"""Public failure reasons are controlled text; diagnostics stay in server logs."""
import logging
import re

log = logging.getLogger(__name__)

# 只返回受控文案；已整理的原因再次经过报告投影时保持不变。
_FAILURES = [
    (('加密',), '文件已加密，无法读取。请提供未加密的原件。'),
    (('暂不支持',), '暂不支持此文件格式。请使用支持的原始单证格式。'),
    (('货号',), '商品明细缺少可核验的货号或品名，相关商品尚未检查。请核对原件中的商品标识。'),
    (('唯一',), '未能识别唯一的商品明细表，相关商品尚未检查。请核对表格范围或提供更清晰的原件。'),
    (('网格', '表格'), '无法可靠读取商品表格，未完成此文件的检查。请核对原件版式或提供更清晰的文件。'),
    (('未配置', '缺少', '尚未启用', '当前无法识别', '无法读取扫描页'),
     '当前无法识别此扫描件或图片。请稍后重试，或提供带文本层的 PDF。'),
    (('识别服务暂时不可用', '识别服务未能完成'), '识别服务暂时不可用，请稍后重试。'),
    ((), '此文件未能完成解析，相关数据尚未检查。请确认文件完整清晰后重试。'),
]

# 输入校验原因不含用户值或底层异常，可以保留给用户修正文件。
_JSON_REASONS = {
    '对象缺少必填键或含不支持的键', '不支持的字段',
    '字段必须是 1–2000 字符的原始字符串', '项目交换 JSON 最大 1 MiB',
    '非有限数字', '票级字段必须是字符串对象', '商品行必须是数组，最多 200 行',
    '商品行号必须为不重复的正整数', '商品行必须包含货号和描述',
    '仅支持 hackathon-trade-json-v1 的发票、装箱单、提单；不支持标准 EDIFACT/X12',
    '存在重复 JSON 键',
}


def parse_failure(message):
    text = str(message or '')
    page = re.search(r'PDF 第 ([0-9, ]+) 页', text)
    prefix = f'PDF 第 {page[1]} 页：' if page else ''
    if '重复 JSON 键：' in text:
        text = '存在重复 JSON 键'
    for reason in _JSON_REASONS:
        public = f'项目交换 JSON 无效：{reason}。请按要求修正后重试。'
        if text.endswith(reason) or text.endswith(public):
            return prefix + public
    for _, public in _FAILURES:
        if text.endswith(public):
            return prefix + public
    for tokens, public in _FAILURES:
        if not tokens or any(token in text for token in tokens):
            return prefix + public


def task_for_public_report(task):
    for doc in task['documents']:
        if doc.get('error_message'):
            doc['error_message'] = parse_failure(doc['error_message'])
    for error in task['errors']:
        if error['code'] in {'DOC_PARSE_FAILED', 'TASK_INTERNAL_ERROR', 'TASK_VALIDATION_FAILED'}:
            error['message'] = parse_failure(error['message'])
    return task
