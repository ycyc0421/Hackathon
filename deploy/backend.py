"""在已初始化的普通维护用户下发布后端；启动失败时恢复旧版本。"""

import argparse
import fcntl
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


def deployment_settings(root):
    """只读取发布所需的两个配置项，其他服务配置不输出、不改写。"""
    settings = {"BACKEND_PYTHON": str(root.parent / ".local/bin/python3.12"), "PADDLE_OCR_ENABLED": "0"}
    for line in (root / "shared/backend.env").read_text().splitlines():
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or name not in settings:
            continue
        tokens = shlex.split(value)
        if len(tokens) != 1:
            raise ValueError(f"{name} 必须配置一个值")
        settings[name] = tokens[0]
    if settings["PADDLE_OCR_ENABLED"] not in {"0", "1"}:
        raise ValueError("PADDLE_OCR_ENABLED 只能为 0 或 1")
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


def activate(root, release):
    current = root / "current"
    previous = current.resolve(strict=True)
    unit = root.parent / ".config/systemd/user" / SERVICE
    previous_unit = unit.read_bytes()
    (release / "previous-release.txt").write_text(str(previous) + "\n")
    (release / "previous-service.conf").write_bytes(previous_unit)
    try:
        unit.write_bytes((release / "deploy" / SERVICE).read_bytes())
        switch_release(current, release)
        run("systemctl", "--user", "daemon-reload")
        run("systemctl", "--user", "restart", SERVICE)
        wait_healthy()
        run("systemctl", "--user", "is-active", "--quiet", SERVICE)
    except BaseException:
        print("新版本启动失败，正在恢复旧版本。", flush=True)
        run("systemctl", "--user", "stop", SERVICE)
        switch_release(current, previous)
        unit.write_bytes(previous_unit)
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
    run(interpreter, "-c", "import sys; assert sys.version_info[:2] == (3, 12), '发布环境需要 Python 3.12'")
    archive = root / "incoming" / f"{release_id}.tar.gz"
    release = root / "releases" / release_id
    release.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(release, filter="data")
    prepare_frontend(release)

    # 每个版本使用独立依赖，失败时不会污染仍在运行的旧环境。
    run(interpreter, "-m", "venv", "--without-pip", str(release / ".venv"))
    installer = str(root / "venv/bin/python")
    python = str(release / ".venv/bin/python")
    requirements = "requirements-ocr.txt" if ocr_enabled else "requirements.txt"
    run(installer, "-m", "pip", "--python", python, "install", "-r", str(release / "backend" / requirements))
    if ocr_enabled:
        run(installer, "-m", "pip", "--python", python, "install", "paddlepaddle==3.2.0",
            "--index-url", "https://www.paddlepaddle.org.cn/packages/stable/cpu/")
    run(installer, "-m", "pip", "--python", python, "check")
    with (release / "requirements.lock").open("w") as lock:
        run(installer, "-m", "pip", "--python", python, "freeze", stdout=lock)

    # 候选版本先用自己的临时数据自检，避免测试读写共享的运行中任务。
    env = {**os.environ, "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": "",
           "PADDLE_OCR_ENABLED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    for script, args in (("test_sqlite_store.py", []), ("test_compare.py", []), ("test_review_regressions.py", []),
                         ("test_paddle_adapter.py", []), ("selftest.py", ["--no-node"]), ("run_challenge.py", [])):
        run(python, str(release / "backend/tools" / script), *args, cwd=release, env=env)
    if ocr_enabled:
        # 在切换服务前加载真实模型并验证图片；使用候选版本的临时任务数据。
        run(python, str(release / "backend/tools/run_ocr_probe.py"), "11_de_multiitem_mixed",
            cwd=release, env={**env, "PADDLE_OCR_ENABLED": "1"}, timeout=900)
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
