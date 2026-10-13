import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, urljoin

import httpx


def verify_response(response, origin, description):
    challenge = '，Cloudflare 人机验证拦截' if response.headers.get('cf-mitigated') == 'challenge' else ''
    assert response.is_success, f'{description} 返回 HTTP {response.status_code}{challenge}'
    assert response.headers.get('access-control-allow-origin') in ('*', origin), f'{description} 未允许前端跨域读取'


def verify_frontend(client, origin):
    page = client.get(origin + '/')
    assert page.is_success and 'id="app"' in page.text, '前端首页不可用'
    assets = re.findall(r'(?:src|href)="(\.?/assets/[^"]+)"', page.text)
    assert any(path.endswith('.js') for path in assets), '前端首页缺少构建脚本'
    for path in assets:
        response = client.get(urljoin(origin + '/', path))
        expected = 'javascript' if path.endswith('.js') else 'text/css'
        assert response.is_success and expected in response.headers.get('content-type', ''), f'前端资源不可用：{path}'
    print('联调通过：前端首页与静态资源', flush=True)


def ocr_uploads(scan=False):
    """扫描 PDF 由已有 PNG 生成，不附加文本层，确保验证到渲染和 OCR 通道。"""
    from PIL import Image
    from fpdf import FPDF
    files = []
    for path in sorted(Path('backend/samples/11_de_multiitem_mixed').glob('*.png')):
        if scan:
            with Image.open(path) as source:
                width, height = (size * 72 / 200 for size in source.size)
            # 无损嵌入；与读取层的 200 DPI 对齐，避免探针额外压缩、缩放原图。
            pdf = FPDF(unit='pt', format=(width, height))
            pdf.add_page()
            pdf.image(str(path), x=0, y=0, w=width, h=height)
            files.append(('files', (path.stem + '-scan.pdf', bytes(pdf.output()), 'application/pdf')))
        else:
            files.append(('files', (path.name, path.read_bytes(), 'image/png')))
    assert len(files) == 3, 'OCR 联调样例文件不完整'
    return files


def run(base, origin, output, ocr_enabled=False):
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={'Origin': origin}, timeout=30) as client:
        def request_json(path, method='GET', **kwargs):
            response = client.request(method, f'{base}{path}', **kwargs)
            verify_response(response, origin, path)
            return response.json()

        # 从部署服务器访问公开地址，完整经过反向代理和跨域检查。
        preflight = client.options(f'{base}/checks', headers={
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        }, timeout=15)
        verify_response(preflight, origin, '跨域预检')
        methods = preflight.headers.get('access-control-allow-methods', '').split(',')
        assert 'POST' in [method.strip() for method in methods], '未允许跨域 POST'

        cases = [('01_us_consistent', 'US'), ('02_de_conflict', 'DE'), ('04_de_multiitem', 'DE')]
        if ocr_enabled:
            cases += [('ocr_png', 'DE'), ('ocr_scan', 'DE')]
        print('OCR 公网验证：' + ('包含图片和扫描 PDF' if ocr_enabled else '共享配置未启用，仅验证文本 PDF'), flush=True)
        for name, country in cases:
            is_ocr = name in ('ocr_png', 'ocr_scan')
            files = ocr_uploads(scan=name == 'ocr_scan') if is_ocr else [
                ('files', (path.name, path.read_bytes(), 'application/pdf'))
                for path in sorted((Path('backend/samples') / name).glob('*.pdf'))
            ]
            created = request_json('/checks', 'POST', files=files, data={
                'destination_country': country,
                'notes': '自动部署联调验证：合成单证',
            })
            assert created.get('task_id'), '未返回任务编号'
            deadline = time.monotonic() + (1800 if is_ocr else 90)
            while True:
                task = request_json(f'/checks/{quote(created["task_id"], safe="")}')
                if task['status'] not in ('PENDING', 'PROCESSING'):
                    break
                assert time.monotonic() < deadline, '任务轮询超时'
                time.sleep(1)
            assert task['status'] == 'COMPLETED', (
                f'{name}：任务未完成；任务 {created["task_id"]} 状态为 {task["status"]}，'
                f'错误码：{", ".join(error["code"] for error in task.get("errors", []))}'
            )
            if name == '01_us_consistent':
                assert task['summary']['conflict_count'] == 0
            if name == '02_de_conflict':
                assert task['summary']['conflict_count'] > 0
            if name == '04_de_multiitem':
                assert len(task['items']) > 1
            if is_ocr:
                assert len(task['documents']) == len(files) and all(
                    d['process_status'] == 'EXTRACTED' for d in task['documents']
                ), f'{name}：OCR 文件未全部成功'
                assert len(task['extractions']) == len(files) and all(
                    e['parse_method'] == 'OCR' for e in task['extractions']
                ), f'{name}：未完整经过 OCR 通道'
                assert len(task['items']) == 4, f'{name}：商品行不完整'
                assert any(c['field_key'] == 'description' and c['item_id'] is not None
                           and c['status'] == 'CONFLICT' for c in task['comparisons']), f'{name}：未检出真实颜色差异'
            (output / f'{name}.json').write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
            print(f'联调通过：{name}，{task["status"]}', flush=True)

        verify_frontend(client, origin)
        missing = client.get(f'{base}/checks/tsk_missing_deployment_probe', timeout=15)
        assert missing.status_code == 404
        assert missing.json()['error']['code'] == 'TASK_NOT_FOUND'
        evaluation = request_json('/evaluation/latest')
        (output / 'evaluation.json').write_text(json.dumps(evaluation, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    from backend import deployment_settings
    # 配置通过标准输入传递，避免把地址插入远端 shell 命令。
    config = json.load(sys.stdin)
    settings = deployment_settings(Path.home() / 'app')
    origin = config['SITE_ORIGIN'].rstrip('/')
    run(origin + '/api/v1', origin, Path(sys.argv[1]),
        ocr_enabled=settings['PADDLE_OCR_ENABLED'] == '1')
