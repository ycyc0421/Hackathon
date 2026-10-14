"""在已初始化的普通维护用户下发布后端；启动失败时恢复旧版本。"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import time
from urllib.error import URLError
from urllib.request import urlopen


SERVICE = "hackathon-backend.service"
MODEL_SERVICES = ('hackathon-vl-rec.service', 'hackathon-paddle-vl.service')
PADDLE_PACKAGE = 'paddlepaddle==3.2.0'
PADDLE_INDEX = 'https://www.paddlepaddle.org.cn/packages/stable/cpu/'


def wait_model_healthy():
    deadline = time.monotonic() + 120
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urlopen('http://127.0.0.1:18082/health', timeout=3) as response:
                health = json.load(response)
            # 包装服务启动不代表底层权重已加载；后者此时可能仍返回 503 Loading model。
            with urlopen('http://127.0.0.1:18083/health', timeout=3) as response:
                recognition = json.load(response)
            if recognition.get('status') == 'ok' and health.get('status') == 'ok' and health.get('pipeline_version') == 'v1.6' and health.get('rec_backend') == 'llama-cpp-server' and not health.get('busy'):
                return
        except (URLError, TimeoutError, ValueError) as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError('VL 服务或底层识别模型未能在 120 秒内通过健康检查') from last_error


def restore_model_units(unit_directory, release):
    backup = release / 'previous-model-services.json'
    if not backup.exists():
        return
    run('systemctl', '--user', 'stop', *MODEL_SERVICES)
    previous = json.loads(backup.read_text())
    for name, content in previous.items():
        path = unit_directory / name
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(content)
    run('systemctl', '--user', 'daemon-reload')
    if all(previous.get(name) is not None for name in MODEL_SERVICES):
        run('systemctl', '--user', 'restart', *MODEL_SERVICES)
        wait_model_healthy()


def deployment_settings(root):
    """只读取发布所需配置，密钥和其他服务配置不输出、不改写。"""
    settings = {"BACKEND_PYTHON": str(root.parent / ".local/bin/python3.12"), "PADDLE_OCR_ENABLED": "0",
                "PADDLE_OCR_ENGINE": "legacy", "PADDLE_VL_SERVICE_URL": "",
                "PADDLE_VL_REC_BACKEND": "native",
                "PADDLE_VL_VERSION": "v1.6", "PADDLE_VL_TIMEOUT_SECONDS": "900"}
    for line in (root / "shared/backend.env").read_text().splitlines():
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in settings:
            continue
        tokens = shlex.split(value)
        if not tokens and name == "PADDLE_VL_SERVICE_URL":
            settings[name] = ""
            continue
        if len(tokens) != 1:
            raise ValueError(f"{name} 必须配置一个值")
        settings[name] = tokens[0]
    if settings["PADDLE_OCR_ENABLED"] not in {"0", "1"}:
        raise ValueError("PADDLE_OCR_ENABLED 只能为 0 或 1")
    if settings["PADDLE_OCR_ENGINE"] not in {"legacy", "vl"}:
        raise ValueError("PADDLE_OCR_ENGINE 必须为 legacy 或 vl")
    if settings["PADDLE_OCR_ENABLED"] == "1" and settings["PADDLE_OCR_ENGINE"] == "vl":
        if settings["PADDLE_VL_SERVICE_URL"] != "http://127.0.0.1:18082":
            raise ValueError("VL 发布必须使用已预热的本机独立模型服务 http://127.0.0.1:18082；禁止在 8 GiB API 进程直接加载模型")
    return settings


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def wait_healthy():
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:18000/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return
        except (URLError, TimeoutError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError("后端未能在 30 秒内通过健康检查")


def switch_release(current, target):
    temporary = current.with_name(".current-next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(current)


def prepare_frontend(release):
    """只开放静态产物的读取权限，供反向代理通过 current 提供前端。"""
    frontend = release / "web/dist"
    if not (frontend / "index.html").is_file():
        raise RuntimeError("发布归档缺少前端构建产物")
    release.chmod(0o711)
    (release / "web").chmod(0o711)
    frontend.chmod(0o755)
    for path in frontend.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)


def prepare_environment(root, release, interpreter, ocr_enabled):
    """按安装输入复用完整环境；已发布环境只读，新依赖另建目录。"""
    started = time.monotonic()
    identity = run(interpreter, '-c',
                   'import json, platform, sys; '
                   'assert sys.version_info[:2] == (3, 12), "发布环境需要 Python 3.12"; '
                   'print(json.dumps([sys.executable, sys.version, sys.implementation.cache_tag, '
                   'platform.machine(), platform.platform()]))',
                   capture_output=True, text=True).stdout.strip()
    requirements = 'requirements-ocr.txt' if ocr_enabled else 'requirements.txt'
    names = ['requirements.txt', 'requirements-ocr.txt'] if ocr_enabled else ['requirements.txt']
    inputs = {'format': 1, 'python': identity,
              'requirements': {name: (release / 'backend' / name).read_text() for name in names},
              'paddle': [PADDLE_PACKAGE, PADDLE_INDEX] if ocr_enabled else None}
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    environment = root / 'shared/python-envs' / key
    ready = environment / '.complete'
    installer = str(root / 'venv/bin/python')
    python = str(environment / 'bin/python')
    reused = ready.is_file()
    if not reused:
        # 未写完成标记的目录从未交给版本使用，可清理被中断的安装。
        if environment.exists():
            shutil.rmtree(environment)
        environment.mkdir(parents=True)
        try:
            run(interpreter, '-m', 'venv', '--without-pip', str(environment))
            run(installer, '-m', 'pip', '--python', python, 'install', '-r',
                str(release / 'backend' / requirements))
            if ocr_enabled:
                run(installer, '-m', 'pip', '--python', python, 'install',
                    PADDLE_PACKAGE, '--index-url', PADDLE_INDEX)
            run(installer, '-m', 'pip', '--python', python, 'check')
            with (environment / 'requirements.lock').open('w') as lock:
                run(installer, '-m', 'pip', '--python', python, 'freeze', stdout=lock)
            ready.write_text(key + '\n')
        except BaseException:
            shutil.rmtree(environment)
            raise
    else:
        # 命中也检查依赖一致性；异常时拒绝发布，不原地修补正在使用的环境。
        run(installer, '-m', 'pip', '--python', python, 'check')
    (release / '.venv').symlink_to(environment, target_is_directory=True)
    shutil.copyfile(environment / 'requirements.lock', release / 'requirements.lock')
    action = '复用' if reused else '新建'
    print(f'依赖环境：{action} {key[:12]}，耗时 {time.monotonic() - started:.1f} 秒', flush=True)
    return str(release / '.venv/bin/python')


def activate(root, release):
    current = root / "current"
    previous = current.resolve(strict=True)
    unit = root.parent / ".config/systemd/user" / SERVICE
    previous_unit = unit.read_bytes()
    settings = deployment_settings(root)
    vl_enabled = settings['PADDLE_OCR_ENABLED'] == '1' and settings['PADDLE_OCR_ENGINE'] == 'vl'
    if vl_enabled:
        previous_models = {name: (unit.parent / name).read_text() if (unit.parent / name).exists() else None for name in MODEL_SERVICES}
        (release / 'previous-model-services.json').write_text(json.dumps(previous_models))
    (release / "previous-release.txt").write_text(str(previous) + "\n")
    (release / "previous-service.conf").write_bytes(previous_unit)
    try:
        (unit.parent / "hackathon.slice").write_bytes((release / "deploy/hackathon.slice").read_bytes())
        unit.write_bytes((release / "deploy" / SERVICE).read_bytes())
        if vl_enabled:
            for name in MODEL_SERVICES:
                (unit.parent / name).write_bytes((release / 'deploy' / name).read_bytes())
        switch_release(current, release)
        run("systemctl", "--user", "daemon-reload")
        if vl_enabled:
            run('systemctl', '--user', 'restart', *MODEL_SERVICES)
            wait_model_healthy()
        run("systemctl", "--user", "restart", SERVICE)
        wait_healthy()
        run("systemctl", "--user", "is-active", "--quiet", SERVICE)
    except BaseException:
        print("新版本启动失败，正在恢复旧版本。", flush=True)
        run("systemctl", "--user", "stop", SERVICE)
        switch_release(current, previous)
        unit.write_bytes(previous_unit)
        restore_model_units(unit.parent, release)
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "restart", SERVICE)
        wait_healthy()
        raise


def rollback(root, release):
    current = root / "current"
    if current.resolve() != release:
        raise RuntimeError("当前版本已变化，拒绝回退其他发布")
    previous = Path((release / "previous-release.txt").read_text().strip())
    if not previous.is_dir():
        raise RuntimeError("旧版本目录已不存在，无法回退")
    # 先停新进程，避免恢复较低的旧内存上限时触发 OOM。
    run("systemctl", "--user", "stop", SERVICE)
    unit = root.parent / ".config/systemd/user" / SERVICE
    unit.write_bytes((release / "previous-service.conf").read_bytes())
    switch_release(current, previous)
    previous_environment = release / 'previous-backend.env'
    if previous_environment.exists():
        shutil.copyfile(previous_environment, root / 'shared/backend.env')
    restore_model_units(unit.parent, release)
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "restart", SERVICE)
    wait_healthy()
    run("systemctl", "--user", "is-active", "--quiet", SERVICE)
    print("后端已恢复为上一个版本。", flush=True)


def deploy(root, release_id):
    if not re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+", release_id):
        raise ValueError("发布标识必须是提交 SHA、运行编号和重试编号")
    # 主机初始化由管理员完成；发布过程不创建账号、不覆盖配置，也不使用 sudo。
    for path in (root / "shared/backend.env", root / "venv/bin/python",
                 root.parent / ".config/systemd/user" / SERVICE):
        if not path.is_file():
            raise RuntimeError(f"缺少预先初始化的文件：{path}")
    if not (root / "current").is_symlink():
        raise RuntimeError("current 必须指向已有的可回退版本")
    settings = deployment_settings(root)
    ocr_enabled = settings["PADDLE_OCR_ENABLED"] == "1"
    interpreter = str(Path(settings["BACKEND_PYTHON"]).expanduser())
    archive = root / "incoming" / f"{release_id}.tar.gz"
    release = root / "releases" / release_id
    release.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(release, filter="data")
    prepare_frontend(release)

    python = prepare_environment(root, release, interpreter, ocr_enabled)

    # 候选版本先用自己的临时数据自检，避免测试读写共享的运行中任务。
    env = {**os.environ, "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": "",
           "PADDLE_OCR_ENABLED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for script, args in (("test_review38.py", []), ("test_rule_monitor.py", []), ("test_workflow.py", []), ("test_trade_json.py", []), ("test_static_rules.py", []), ("test_sqlite_store.py", []), ("test_compare.py", []), ("test_review_regressions.py", []),
                         ("test_paddle_adapter.py", []), ("test_paddle_vl.py", []), ("test_vl_service.py", []), ("test_delivery_boundaries.py", []), ("selftest.py", ["--no-node"]), ("run_challenge.py", [])):
        directory = "backend/tests" if script.startswith("test_") else "backend/tools"
        run(python, str(release / directory / script), *args, cwd=release, env=env)
    if ocr_enabled:
        probe_started = time.monotonic()
        print('开始真实 OCR 预检。', flush=True)
        # 在切换服务前加载真实模型并验证图片；使用候选版本的临时任务数据。
        probe_env = {**env, **{key: value for key, value in settings.items() if key.startswith("PADDLE_")}}
        if settings["PADDLE_OCR_ENGINE"] == "vl":
            with urlopen(settings["PADDLE_VL_SERVICE_URL"] + "/health", timeout=5) as response:
                health = json.load(response)
            if health.get("status") != "ok" or health.get("pipeline_version") != settings["PADDLE_VL_VERSION"] or health.get("rec_backend") != "llama-cpp-server" or health.get("busy"):
                raise RuntimeError("独立 VL 服务尚未就绪、版本不符或正在推理，拒绝发布")
            wait_model_healthy()
            run(python, str(release / "backend/tools/accept_paddle_vl.py"), cwd=release, env=probe_env, timeout=2100)
        else:
            run(python, str(release / "backend/tools/run_ocr_probe.py"), "11_de_multiitem_mixed",
                cwd=release, env=probe_env, timeout=900)
        print(f'真实 OCR 预检通过，耗时 {time.monotonic() - probe_started:.1f} 秒', flush=True)
    temporary_data = release / "backend/.data"
    if temporary_data.exists():
        shutil.rmtree(temporary_data)
    shared_data = root / "shared/data"
    shared_data.mkdir(exist_ok=True)
    temporary_data.symlink_to(shared_data, target_is_directory=True)
    activate(root, release)
    archive.unlink()
    print(f"后端发布完成：{release_id}", flush=True)


if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("请使用专用普通用户发布后端")
    os.umask(0o077)
    os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={os.environ['XDG_RUNTIME_DIR']}/bus")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_id")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+", args.release_id):
        raise SystemExit("发布标识格式不合法")
    root = Path.home() / "app"
    # 同时防止手工发布与工作流发布互相覆盖。
    with (root / ".deploy.lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.rollback:
            rollback(root, root / "releases" / args.release_id)
        else:
            deploy(root, args.release_id)
