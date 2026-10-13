"""Prepare official VL CPU artifacts with fixed hashes; never switch the API."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
from urllib.request import urlopen

REVISION = '511b09642bb324401f15f97cc23bc67e8f0a291d'
ENGINE_VERSION = 'b11429'
ARTIFACTS = {
    'PaddleOCR-VL-1.6-GGUF.gguf': 'f3ae46ec885050acf4b3d31944431e1fd90d50664fb09126af4a3c050ba14ee8',
    'PaddleOCR-VL-1.6-GGUF-mmproj.gguf': '204d757d7610d9b3faab10d506d69e5b244e32bf765e2bab2d0167e65e0a058a',
}
ENGINE_HASH = 'f6d25dde8f51133143d1453da4fd5f73b145127177612a283bf7995957af3392'
LAYOUT_REVISION = '241f8bdfc77a7c7bee915a5057aaee58c235a8d3'
LAYOUT_ARTIFACTS = {
    'inference.json': '2b68367c5b312a03de5a6e1642c597c8f95165a7e40cd59c6700cf4a5042f4fd',
    'inference.pdiparams': '70bd316b0582769ec968829fd1feb1a6a58b7c941b938327e551b6b12b45c137',
    'inference.yml': '506fcfac13b3b546ae40d7886b44126420f392adb694e3f8bb6a6286a1f90fdc',
}


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def obtain(target, url, expected, cached=None):
    if target.exists():
        if digest(target) != expected:
            raise RuntimeError(f'已有文件哈希不符，拒绝覆盖：{target.name}')
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.download')
    try:
        if cached and cached.is_file():
            shutil.copyfile(cached, temporary)
        else:
            with urlopen(url, timeout=60) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        if digest(temporary) != expected:
            raise RuntimeError(f'下载文件哈希不符：{target.name}')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(root, cache, layout_cache=None):
    models = root / 'shared/models/PaddleOCR-VL-1.6-GGUF'
    for name, expected in ARTIFACTS.items():
        url = f'https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/resolve/{REVISION}/{name}'
        obtain(models / name, url, expected, cache / name if cache else None)
    layout = root / 'shared/models/PP-DocLayoutV3'
    for name, expected in LAYOUT_ARTIFACTS.items():
        url = f'https://huggingface.co/PaddlePaddle/PP-DocLayoutV3/resolve/{LAYOUT_REVISION}/{name}'
        obtain(layout / name, url, expected, layout_cache / name if layout_cache else None)
    runtime = root / 'shared/vl-runtime'
    archive = runtime / f'llama-{ENGINE_VERSION}.tar.gz'
    obtain(archive, f'https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_VERSION}/llama-{ENGINE_VERSION}-bin-ubuntu-x64.tar.gz', ENGINE_HASH,
           cache / f'llama-{ENGINE_VERSION}.tar.gz' if cache else None)
    # Runtime directory is fixed by the verified official release archive.
    if not (runtime / f'llama-{ENGINE_VERSION}/llama-server').is_file():
        with tarfile.open(archive) as source:
            source.extractall(runtime, filter='data')
    manifest = {'model': 'PaddleOCR-VL-1.6', 'source_revision': REVISION,
                'model_hashes': ARTIFACTS, 'engine_version': ENGINE_VERSION,
                'layout_revision': LAYOUT_REVISION, 'layout_hashes': LAYOUT_ARTIFACTS,
                'engine_archive_sha256': ENGINE_HASH}
    (models / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('官方模型及 CPU 引擎准备完成；未切换 API，也未改写运行配置。')


if __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home() / 'app')
    parser.add_argument('--cache', type=Path, help='Existing verified download directory to reuse')
    parser.add_argument('--layout-cache', type=Path, help='Existing official PP-DocLayoutV3 directory')
    args = parser.parse_args()
    prepare(args.root.resolve(), args.cache.resolve() if args.cache else None,
            args.layout_cache.resolve() if args.layout_cache else None)
