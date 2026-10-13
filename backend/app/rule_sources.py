"""读取运行时监测状态；未配置时仅返回未经检查的来源目录。"""
import json
import os
from pathlib import Path

STATIC = Path(__file__).resolve().parent / 'rules'


def status(*, source_ids=None):
    configured = os.getenv('RULE_SOURCE_DIR')
    root = Path(configured) if configured else STATIC
    def read(name, default):
        path = root / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    if configured:
        manifest = read('manifest.json', {'sources': []})
        pending = read('pending_review.json', {'updates': []})
    else:
        catalog = read('source_catalog.json', {'sources': []})
        manifest = {'sources': [{**source, 'status': 'NOT_CHECKED', 'legal_verified': False}
                                for source in catalog['sources']]}
        pending = {'updates': []}
    source_keys = {'source_id', 'url', 'authority', 'kind', 'review_status', 'status', 'checked_at', 'legal_verified'}
    update_keys = {'source_id', 'status', 'checked_at', 'reviewed_at'}
    selected = [s for s in manifest['sources'] if source_ids is None or s.get('source_id') in source_ids]
    sources = [{**{k:v for k,v in s.items() if k in source_keys}, 'legal_verified': False} for s in selected]
    updates = [{k:v for k,v in u.items() if k in update_keys} for u in pending['updates']
               if u.get('status') == 'PENDING_REVIEW' and (source_ids is None or u.get('source_id') in source_ids)]
    return {'mode': 'runtime_monitor' if configured else 'bundled_static', 'checked_at': manifest.get('checked_at'),
            'automatic_activation': False, 'sources': sources,
            'pending_updates': updates,
            'notice': ('来源内容变化不等于法规修订；待复核记录不会自动替换运行规则。' if configured else
                       '未配置来源监测；仅展示来源目录，尚未检查更新，空待复核列表不代表没有变更。')}
