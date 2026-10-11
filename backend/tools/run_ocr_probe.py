"""Manual OCR integration probe; requires the optional OCR environment."""

from __future__ import annotations

import os
import sys

os.environ["PADDLE_OCR_ENABLED"] = "1"

from run_challenge import report, upload  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main() -> None:
    with TestClient(app) as client:
        for case, country, name in [
            ("09_us_format_mixed", "US", "美国"),
            ("10_de_ambiguity_conflict", "DE", "德国"),
            ("11_de_multiitem_mixed", "DE", "德国"),
        ]:
            if len(sys.argv) > 1 and case not in sys.argv[1:]:
                continue
            task = upload(client, case, country, name, [".png"], wait_seconds=300)
            report(task, f"OCR {case}")
            assert any(d["process_status"] == "EXTRACTED" for d in task["documents"]), case


if __name__ == "__main__":
    main()
