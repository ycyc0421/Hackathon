"""Opt-in destructive test of an explicitly named isolated API systemd unit."""
import argparse
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import time
import httpx


def run(base, unit, samples, out):
    if unit != 'hackathon-vl-api-final.service' or base != 'http://127.0.0.1:18081':
        raise ValueError('Only the dedicated isolated acceptance API may be interrupted')
    out.mkdir(parents=True, exist_ok=True)
    originals = [(path.name, path.read_bytes()) for path in sorted(samples.glob('*.pdf'))]
    assert len(originals) == 3
    tasks, checks = [], []
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        for _ in range(60):
            try:
                if client.get('/health').is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Isolated API did not become ready')
        for _ in range(4):
            response = client.post('/api/v1/checks', data={'destination_country': 'SG'}, files=[('files', (name, data, 'application/pdf')) for name, data in originals])
            response.raise_for_status()
            task = response.json()
            tasks.append(task)
            checks.append({'check': 'all three originals published before inference completes', 'passed': len(task['documents']) == 3 and task['status'] in {'PENDING', 'PROCESSING'}})
        rejected = client.post('/api/v1/checks', data={'destination_country': 'SG'}, files=[('files', originals[0])])
        checks.append({'check': 'fifth active or queued task rejected', 'passed': rejected.status_code == 429 and rejected.json()['error']['code'] == 'CHECK_QUEUE_FULL'})
        pid = int(subprocess.check_output(['systemctl', '--user', 'show', unit, '--property=MainPID', '--value'], text=True))
        assert pid > 1 and b'accept_paddle_vl.py' in Path(f'/proc/{pid}/cmdline').read_bytes()
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        subprocess.run(['systemctl', '--user', 'restart', unit], check=True)
        for _ in range(60):
            try:
                if client.get('/health').is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        responses = []
        for submitted in tasks:
            task = client.get('/api/v1/checks/' + submitted['task_id']).json()
            responses.append(task)
            checks.append({'check': task['task_id'] + ' interrupted task and files finalized', 'passed': task['status'] == 'FAILED' and len(task['documents']) == 3 and all(doc['process_status'] == 'FAILED' for doc in task['documents']) and any(error['code'] == 'TASK_INTERRUPTED' for error in task['errors'])})
            for index, (name, data) in enumerate(originals, 1):
                downloaded = client.get(f"/api/v1/checks/{task['task_id']}/files/f{index}")
                checks.append({'check': task['task_id'] + '/' + name + ' source preserved', 'passed': downloaded.is_success and downloaded.content == data, 'sha256': hashlib.sha256(data).hexdigest()})
        (out/'responses.json').write_text(json.dumps(responses, ensure_ascii=False, indent=2))
    summary = {'status': 'PASSED' if all(check['passed'] for check in checks) else 'FAILED', 'scope': 'Actual SIGKILL of isolated API with four active/queued tasks; three originals each', 'checks': checks}
    (out/'acceptance.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return all(check['passed'] for check in checks)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--unit', required=True)
    parser.add_argument('--samples', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.base_url, args.unit, args.samples, args.out) else 1)
