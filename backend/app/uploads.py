"""Persist every submitted original before starting document inference."""
import os
from pathlib import Path
from .util import make_file_id
from .pipeline.reader import guess_file_type


def stage_uploads(root: Path, task_id: str, uploads: list[tuple[str, bytes]]) -> list[dict]:
    root = root.resolve()
    directory = (root / task_id).resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError('上传目录超出任务范围')
    directory.mkdir(parents=True, exist_ok=True)
    documents = []
    for index, (filename, data) in enumerate(uploads, 1):
        file_id = make_file_id(index)
        temporary = directory / f'{file_id}.upload'
        destination = directory / f'{file_id}.source'
        try:
            with temporary.open('wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        documents.append({'file_id': file_id, 'file_name': filename,
                          'file_type': guess_file_type(filename).value, 'doc_type': None,
                          'process_status': 'UPLOADED', 'page_count': None, 'error_message': None})
    return documents
