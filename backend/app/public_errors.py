"""Public failure reasons are controlled text; diagnostics stay in server logs."""
import logging
import re

log = logging.getLogger(__name__)


def parse_failure(message):
    text = str(message or '')
    page = re.search(r'PDF 第 ([0-9, ]+) 页', text)
    prefix = f'PDF 第 {page[1]} 页：' if page else ''
    if '加密' in text:
        return prefix + '文件已加密，无法读取。请提供未加密的原件。'
    if '暂不支持' in text:
        return prefix + '暂不支持此文件格式。请使用支持的原始单证格式。'
    if '货号' in text:
        return prefix + '商品明细缺少可核验的货号或品名，相关商品尚未检查。请核对原件中的商品标识。'
    if '唯一' in text:
        return prefix + '未能识别唯一的商品明细表，相关商品尚未检查。请核对表格范围或提供更清晰的原件。'
    if '网格' in text or '表格' in text:
        return prefix + '无法可靠读取商品表格，未完成此文件的检查。请核对原件版式或提供更清晰的文件。'
    if '未配置' in text or '缺少' in text or '尚未启用' in text:
        return prefix + '当前无法识别此扫描件或图片。请稍后重试，或提供带文本层的 PDF。'
    return prefix + '此文件未能完成解析，相关数据尚未检查。请确认文件完整清晰后重试。'


def task_for_public_report(task):
    for doc in task['documents']:
        if doc.get('error_message'):
            doc['error_message'] = parse_failure(doc['error_message'])
    for error in task['errors']:
        if error['code'] in {'DOC_PARSE_FAILED', 'TASK_INTERNAL_ERROR', 'TASK_VALIDATION_FAILED'}:
            error['message'] = parse_failure(error['message'])
    return task
