"""Human revisions preserve source evidence; reports never imply compliance approval."""
import copy
import hashlib
import json
import math
import re
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .models import CheckTask, dump
from .schema_fields import CORE_COMPARABLE, IDENTIFIERS, ITEM_LEVEL_BY_KEY
from .util import make_task_id, now_iso
from .pipeline import normalize as N, rules
from .pipeline.align import align_items
from .pipeline.compare import build_comparisons, build_item_comparisons
from .pipeline.internal_checks import check_rows
from . import rule_sources

class WorkflowError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)

class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: str = Field(min_length=1, max_length=100)
    item_no: int | None = Field(default=None, ge=1)
    field_key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2000)

class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    source_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    reason: str = Field(min_length=1, max_length=1000)
    changes: list[Change] = Field(min_length=1, max_length=100)

def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()

def _normalize(key, text, field):
    text = text.strip()
    if not text:
        raise WorkflowError(422, 'INVALID_CORRECTION', '修正值不能为空')
    unit = field.get('unit')
    if key in N._MEASURE_UNITS:
        value, unit = N.to_measure(text, key)
    elif key in {'total_amount', 'unit_price', 'amount'}:
        if not re.fullmatch(r'[+]?\d[\d,.]*', text):
            raise WorkflowError(422, 'INVALID_CORRECTION', '金额仅接受非负数字，币种单独修正')
        value = N.to_number(text)
    elif key == 'hs_code':
        value = N.to_hs_code(text) if re.fullmatch(r'[0-9. ]+', text) else None
    elif key == 'currency':
        value = text.upper() if re.fullmatch(r'[A-Za-z]{3}', text) else None
    elif key == 'shipment_date':
        value = N.to_date(text)
    elif key == 'description':
        value = N.normalize_description(text)
    elif key.startswith('port_of_'):
        value = N.to_port(text)
    elif key == 'destination_country':
        value = N.to_country(text)
    elif key in {'shipper_address', 'consignee_address'}:
        from .pipeline.addresses import normalize_address
        value = normalize_address(text)
    else:
        value = N.to_text(text)
    if value is None or isinstance(value, (int, float)) and (not math.isfinite(value) or value < 0):
        raise WorkflowError(422, 'INVALID_CORRECTION', f'{key} 无法归一')
    if key in {'quantity','packages'} and value != int(value):
        raise WorkflowError(422, 'INVALID_CORRECTION', '数量和件数必须为整数')
    return value, unit

def correct(store, task_id, request):
    if not request.reason.strip():
        raise WorkflowError(422, 'INVALID_CORRECTION', '请填写修正原因')
    def build(source):
        if source['status'] not in {'COMPLETED','PARTIAL'}:
            raise WorkflowError(409, 'TASK_NOT_EDITABLE', '仅可修正已完成或部分完成任务')
        task = copy.deepcopy(source)
        # OCR uncertainty survives unrelated edits and subsequent revisions.
        # Only an explicit human correction of that description releases it.
        ocr_files = {file_id for error in source['errors'] if error['code'] == 'OCR_TEXT_DISAGREEMENT'
                     for file_id in error.get('file_ids', [])}
        pending_items = {comparison.get('item_id') for comparison in source['comparisons']
                         if comparison['field_key'] == 'description' and comparison['status'] == 'NOT_CHECKED'}
        unchecked = {(member['file_id'], member['item_no'])
                     for item in source.get('items', []) if item['item_id'] in pending_items
                     for member in item['members'] if member['file_id'] in ocr_files}
        changes, seen = [], set()
        document_keys = {x.key for x in CORE_COMPARABLE + IDENTIFIERS}
        for change in request.changes:
            if change.field_key == 'destination_country':
                raise WorkflowError(422,'DESTINATION_REQUIRES_NEW_TASK','目的国影响任务输入与规则适用范围，请使用正确目的国重新上传创建任务')
            identity = (change.file_id,change.item_no,change.field_key)
            if identity in seen:
                raise WorkflowError(422, 'DUPLICATE_FIELD', '同一字段不能重复修改')
            seen.add(identity)
            allowed = ITEM_LEVEL_BY_KEY if change.item_no is not None else document_keys
            if change.field_key not in allowed:
                raise WorkflowError(422, 'FIELD_NOT_EDITABLE', '字段不在修正范围内')
            extraction = next((e for e in task['extractions'] if e['file_id']==change.file_id), None)
            doc = next((d for d in task['documents'] if d['file_id']==change.file_id), None)
            if extraction is None or doc is None or doc['process_status'] != 'EXTRACTED':
                raise WorkflowError(422, 'FIELD_NOT_FOUND', '文件没有可修正的抽取结果')
            container = extraction
            if change.item_no is not None:
                container = next((li for li in extraction['line_items'] if li['item_no']==change.item_no), {})
            candidates = [f for f in container.get('fields',[]) if f['field_key']==change.field_key]
            if len(candidates) != 1:
                raise WorkflowError(422, 'FIELD_NOT_FOUND', '字段不存在或身份不唯一')
            field = candidates[0]
            before = copy.deepcopy(field)
            value, unit = _normalize(change.field_key, change.value, field)
            field.update(normalized_value=value, unit=unit, status='LOW_CONFIDENCE')
            if change.field_key == 'description' and change.item_no is not None:
                unchecked.discard((change.file_id, change.item_no))
            # raw values, coordinates and measured confidence remain source evidence.
            changes.append({**change.model_dump(), 'before':before, 'after':copy.deepcopy(field)})
        # 修改币种时同步金额单位；补填金额缺少单位时继承文件已确认的币种，并记录审计。
        for extraction in task['extractions']:
            currency_changed = (extraction['file_id'],None,'currency') in seen
            currency = next((f['normalized_value'] for f in extraction['fields']
                             if f['field_key']=='currency' and f['status'] in {'EXTRACTED','LOW_CONFIDENCE'}), None)
            if not currency:
                continue
            groups = [(None,extraction['fields'])] + [(li['item_no'],li['fields']) for li in extraction['line_items']]
            for item_no, fields in groups:
                for field in fields:
                    if field['field_key'] in {'total_amount','amount','unit_price'} and field.get('normalized_value') is not None:
                        if not currency_changed and (field.get('unit') is not None or
                                (extraction['file_id'],item_no,field['field_key']) not in seen):
                            continue
                        before = copy.deepcopy(field)
                        field['unit'] = currency
                        if before != field:
                            changes.append({'file_id':extraction['file_id'],'item_no':item_no,'field_key':field['field_key'],'implied_currency_update':True,'before':before,'after':copy.deepcopy(field)})
        task['items'] = align_items(task['extractions'],task['documents'])
        args = dict(destination_country=task['input'].get('destination_country'),destination_country_name=task['input'].get('destination_country_name'))
        comparisons = build_comparisons(task['documents'],task['extractions'],rules.hs_covered,**args)
        comparisons += build_item_comparisons(task['items'],task['documents'],task['extractions'],rules.hs_covered,start_index=len(comparisons),unchecked_descriptions=unchecked,**args)
        task['comparisons'] = comparisons
        task['risks'] = rules.evaluate_risks(task['input'],task['documents'],task['extractions'],task['items'])
        pending_files = {file_id for file_id, _ in unchecked}
        task['errors'] = [e for e in task['errors'] if e['code'] not in {'RULES_UNVERIFIED', 'GROSS_BELOW_NET', 'LINE_AMOUNT_MISMATCH', 'OCR_TEXT_DISAGREEMENT'}]
        if pending_files:
            task['errors'].append({'code':'OCR_TEXT_DISAGREEMENT','level':'WARNING',
                                  'file_ids':sorted(pending_files),
                                  'message':'仍有商品品名未完成同一货号区域的 OCR 核验；本次其他字段修正不代表品名已确认，请人工复核对应 NOT_CHECKED 条目。'})
        task['errors'].extend(check_rows(task['extractions']))
        if task['risks'] and not rules.ruleset_verified():
            task['errors'].append({'code':'RULES_UNVERIFIED','message':'规则适用条件尚需核实，风险提示不代表合规结论','level':'WARNING','file_ids':[]})
        task['errors'].append({'code':'HUMAN_CORRECTED','message':'有效抽取值经人工修正并重算；原始证据保留，操作者身份未认证','level':'WARNING','file_ids':sorted({c.file_id for c in request.changes})})
        task['task_id'], task['created_at'], task['finished_at'] = make_task_id(store.next_seq()), now_iso(), now_iso()
        task['summary'].update(item_count=len(task['items']),risk_count=len(task['risks']),conflict_count=sum(c['status']=='CONFLICT' for c in comparisons),missing_count=sum(c['status']=='MISSING_IN_SOME' for c in comparisons),unrecognized_count=sum(c['status']=='UNRECOGNIZED' for c in comparisons))
        task = dump(CheckTask.model_validate(task))
        audit = {'source_task_id':task_id,'derived_task_id':task['task_id'],'source_hash':request.source_hash,'request_id':request.request_id,'reason':request.reason.strip(),'actor':'anonymous','actor_verified':False,'created_at':task['created_at'],'rule_version':rules.rule_version(),'changes':changes}
        return task,audit
    task = store.derive(task_id,request.source_hash,request.request_id,payload_hash(request.model_dump()),build)
    store.persist(task['task_id'])
    return task

def report(store, task_id, *, view='content'):
    from .report_content import content
    task = store.get(task_id)
    if task is None:
        raise WorkflowError(404, 'TASK_NOT_FOUND', '任务不存在')
    if task['status'] in {'PENDING', 'PROCESSING'}:
        raise WorkflowError(409, 'TASK_NOT_FINISHED', '任务尚未结束')
    task = dump(CheckTask.model_validate(task))
    corrections = store.correction_history(task_id)
    original_hash = payload_hash(task)
    from .public_errors import task_for_public_report
    task = task_for_public_report(task)
    envelope = {'report_version': '2', 'view': view, 'generated_at': now_iso(),
                'result_hash': original_hash}
    if view == 'archive':
        return {**envelope, 'task': task, 'corrections': corrections}
    return {**envelope, **content(task, corrections)}
