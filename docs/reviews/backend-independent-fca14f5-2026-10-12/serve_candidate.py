"""Start the pinned backend with isolated runtime paths and optional OCR observation."""
import argparse
import json
import os
from pathlib import Path
import sys

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--runtime', type=Path, required=True)
p.add_argument('--port', type=int, required=True)
p.add_argument('--ocr', action='store_true')
p.add_argument('--disable-mkldnn', action='store_true')
p.add_argument('--ocr-cache', type=Path)
a = p.parse_args()
os.environ['TASK_DB_PATH'] = str(a.runtime / 'tasks.sqlite3')
os.environ['PADDLE_OCR_ENABLED'] = '1' if a.ocr else '0'
for k in ['LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'RULE_SOURCE_DIR']:
    os.environ[k] = ''
cache = a.ocr_cache or Path(os.environ.get('B_REVIEW_OCR_CACHE', r'D:\hackson\ocr-local\paddlex-cache'))
if cache.is_dir(): os.environ['PADDLE_PDX_CACHE_HOME'] = str(cache)
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
sys.path.insert(0, str(a.repo / 'backend'))
from app import config
config.DATA_DIR = a.runtime
config.UPLOAD_DIR = a.runtime / 'uploads'
config.TASK_DIR = a.runtime / 'legacy'
if a.ocr:
    from app.pipeline import paddle_reader
    class Observer:
        def __init__(self, model, name):
            self.model, self.name, self.count = model, name, 0
        def predict(self, **kwargs):
            values = list(self.model.predict(**kwargs))
            self.count += 1
            target = a.runtime.parent / 'ocr-traces'
            target.mkdir(exist_ok=True)
            for i, value in enumerate(values):
                stem = f'{self.name}-{self.count}-{i}'
                try:
                    value.save_to_json(str(target / (stem + '.json')))
                    text = ('\n'.join(map(str, value.json['res']['rec_texts'])) if self.name == 'ordinary'
                            else value.markdown['markdown_texts'])
                    (target / (stem + ('.txt' if self.name == 'ordinary' else '.md'))).write_text(text, encoding='utf-8')
                except Exception as e:
                    (target / (stem + '.trace-error.txt')).write_text(str(e), encoding='utf-8')
            return values
    original_ordinary, original_structure = paddle_reader._get_ocr, paddle_reader._get_structure
    observed = {}
    def get(name):
        if name not in observed:
            if a.disable_mkldnn:
                from paddleocr import PaddleOCR, PPStructureV3
                model = (PaddleOCR(cpu_threads=4, enable_mkldnn=False, use_doc_orientation_classify=False,
                                  use_doc_unwarping=False, use_textline_orientation=False) if name == 'ordinary'
                         else PPStructureV3(cpu_threads=4, enable_mkldnn=False, use_doc_orientation_classify=False,
                                            use_doc_unwarping=False, use_formula_recognition=False, use_seal_recognition=False))
            else:
                model = original_ordinary() if name == 'ordinary' else original_structure()
            observed[name] = Observer(model, name)
        return observed[name]
    paddle_reader._get_ocr = lambda: get('ordinary')
    paddle_reader._get_structure = lambda: get('structure')
import uvicorn
uvicorn.run('app.main:app', host='127.0.0.1', port=a.port, log_level='warning')
