import json
from pathlib import Path
import sys
import time
from urllib.parse import quote

import httpx


def verify_response(response, origin, description):
    challenge = '，Cloudflare 人机验证拦截' if response.headers.get('cf-mitigated') == 'challenge' else ''
    assert response.is_success, f'{description} 返回 HTTP {response.status_code}{challenge}'
    assert response.headers.get('access-control-allow-origin') in ('*', origin), f'{description} 未允许前端跨域读取'


def run(base, origin, output):
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={'Origin': origin}, timeout=30) as client:
        def request_json(path, method='GET', **kwargs):
            response = client.request(method, f'{base}{path}', **kwargs)
            verify_response(response, origin, path)
            return response.json()

        # 从部署服务器访问公开 HTTPS 域名，完整经过边缘代理和跨域检查。
        preflight = client.options(f'{base}/checks', headers={
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        }, timeout=15)
        verify_response(preflight, origin, '跨域预检')
        methods = preflight.headers.get('access-control-allow-methods', '').split(',')
        assert 'POST' in [method.strip() for method in methods], '未允许跨域 POST'

        for name, country in [
            ('01_us_consistent', 'US'),
            ('02_de_conflict', 'DE'),
            ('04_de_multiitem', 'DE'),
        ]:
            files = [
                ('files', (path.name, path.read_bytes(), 'application/pdf'))
                for path in sorted((Path('backend/samples') / name).glob('*.pdf'))
            ]
            created = request_json('/checks', 'POST', files=files, data={
                'destination_country': country,
                'notes': '自动部署联调验证：合成单证',
            })
            assert created.get('task_id'), '未返回任务编号'
            deadline = time.monotonic() + 90
            while True:
                task = request_json(f'/checks/{quote(created["task_id"], safe="")}')
                if task['status'] not in ('PENDING', 'PROCESSING'):
                    break
                assert time.monotonic() < deadline, '任务轮询超时'
                time.sleep(1)
            assert task['status'] == 'COMPLETED', f'{name}：任务未完成'
            if name == '01_us_consistent':
                assert task['summary']['conflict_count'] == 0
            if name == '02_de_conflict':
                assert task['summary']['conflict_count'] > 0
            if name == '04_de_multiitem':
                assert len(task['items']) > 1
            (output / f'{name}.json').write_text(json.dumps(task, ensure_ascii=False), encoding='utf-8')
            print(f'联调通过：{name}，{task["status"]}', flush=True)

        missing = client.get(f'{base}/checks/tsk_missing_deployment_probe', timeout=15)
        assert missing.status_code == 404
        assert missing.json()['error']['code'] == 'TASK_NOT_FOUND'
        evaluation = request_json('/evaluation/latest')
        (output / 'evaluation.json').write_text(json.dumps(evaluation, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    # 配置通过标准输入传递，避免把地址插入远端 shell 命令。
    config = json.load(sys.stdin)
    run(config['VITE_API_BASE'], config['FRONTEND_ORIGIN'].rstrip('/'), Path(sys.argv[1]))
