"""Versioned official source checks; changes require review, never legal activation."""
import argparse
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1] / "app/rules"
HOSTS = {"food.ec.europa.eu", "eur-lex.europa.eu", "publications.europa.eu", "op.europa.eu", "www.fda.gov", "www.gov.uk", "www.food.gov.uk"}
MAX_BYTES = 5 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def official(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Only allowlisted official HTTPS sources are permitted")


class OfficialRedirectError(ValueError):
    pass


class OfficialRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        # CELLAR advertises canonical identifiers as HTTP URIs; fetch their HTTPS equivalent.
        if parsed.scheme == "http" and parsed.hostname == "publications.europa.eu" and parsed.path.startswith("/resource/cellar/") and parsed.port is None:
            newurl = urlunparse(parsed._replace(scheme="https"))
        official(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _snapshot_exists(previous, output):
    if not previous.get("snapshot") or not previous.get("sha256"):
        return False
    path = (output / previous["snapshot"]).resolve()
    return path.is_relative_to(output.resolve()) and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == previous["sha256"]


def fetch_source(source, output, previous=None):
    previous = previous or {}
    urls = [source["url"], *source.get("fallback_urls", [])]
    for url in urls:
        official(url)
    if previous.get("retrieval_url") in urls:
        urls.remove(previous["retrieval_url"])
        urls.insert(0, previous["retrieval_url"])
    record = {"source_id": source["source_id"], "url": source["url"], "checked_at": now(), "legal_verified": False}
    attempts = []
    for url in urls:
        headers = {"User-Agent": "HackathonRuleSourceCollector/2.0", "Accept": source.get("accept", "text/html,application/pdf"), "Accept-Language": source.get("accept_language", "en")}
        cached = previous.get("retrieval_url", previous.get("url")) == url and _snapshot_exists(previous, output)
        if cached:
            for field, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
                if previous.get(field):
                    headers[header] = previous[field]
        try:
            with build_opener(OfficialRedirectHandler()).open(Request(url, headers=headers), timeout=30) as response:
                official(response.url)
                raw = response.read(MAX_BYTES + 1)
                if not raw or len(raw) > MAX_BYTES:
                    raise ValueError("Empty source or source exceeds 5 MiB")
                content_type = response.headers.get_content_type()
                if content_type not in {"text/html", "application/pdf", "text/plain"}:
                    raise ValueError("Unexpected source content type")
                if b"verify that you're not a robot" in raw or b"Access Denied" in raw:
                    raise ValueError("Official site returned a challenge; no bypass attempted")
                if source.get("accept") == "application/pdf" and (content_type != "application/pdf" or not raw.startswith(b"%PDF-")):
                    raise ValueError("Expected real PDF, not an HTML error page")
                if source.get("expected_pdf_text"):
                    from pypdf import PdfReader
                    from io import BytesIO
                    pdf = PdfReader(BytesIO(raw))
                    text = "\n".join(page.extract_text() or "" for page in pdf.pages[:2])
                    if any(token not in text for token in source["expected_pdf_text"]):
                        raise ValueError("PDF identity does not match catalog")
                digest = hashlib.sha256(raw).hexdigest()
                path = output / "snapshots" / (digest + (".pdf" if content_type == "application/pdf" else ".html"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                record.update(status="FETCHED", sha256=digest, bytes=len(raw), content_type=content_type,
                              retrieval_url=url, final_url=response.url, etag=response.headers.get("ETag"),
                              last_modified=response.headers.get("Last-Modified"), snapshot=path.relative_to(output).as_posix(),
                              fetched_at=now(), last_success_at=now(), consecutive_failures=0, attempts=attempts)
                return record
        except HTTPError as exc:
            if exc.code == 304 and cached:
                result = {**previous, **record, "status": "NOT_MODIFIED", "last_success_at": now(), "consecutive_failures": 0, "attempts": attempts}
                result.pop("error", None)
                return result
            attempts.append({"url": url, "error": f"HTTP {exc.code}"})
        except Exception as exc:
            attempts.append({"url": url, "error": str(exc)})
    return {**previous, **record, "status": "FETCH_FAILED", "error": attempts[-1]["error"], "attempts": attempts,
            "consecutive_failures": previous.get("consecutive_failures", 0) + 1}


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def check_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".check.lock").open("a+b") as lock:
        if os.name != "nt":
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0"); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            if os.name != "nt":
                fcntl.flock(lock, fcntl.LOCK_UN)
            else:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def check_sources(catalog, output):
    with check_lock(output):
        manifest = output / "manifest.json"
        old = {s["source_id"]: s for s in json.loads(manifest.read_text(encoding="utf-8"))["sources"]} if manifest.exists() else {}
        pending_path = output / "pending_review.json"
        pending = json.loads(pending_path.read_text(encoding="utf-8")) if pending_path.exists() else {"updates": []}
        records, events = [], []
        for source in catalog["sources"]:
            prior = old.get(source["source_id"], {})
            record = fetch_source(source, output, prior)
            success = record["status"] in {"FETCHED", "NOT_MODIFIED"}
            changed = success and bool(prior.get("sha256")) and record["sha256"] != prior["sha256"]
            record["changed"] = changed if success else None
            event = {"source_id": source["source_id"], "checked_at": record["checked_at"], "event": "SOURCE_CHANGED" if changed else "FETCH_FAILED" if not success else "SOURCE_INITIALIZED" if not prior.get("sha256") else "UNCHANGED", "old_sha256": prior.get("sha256"), "sha256": record.get("sha256"), "error": record.get("error")}
            events.append(event)
            if changed:
                update_id = hashlib.sha256((source["source_id"]+prior["sha256"]+record["sha256"]).encode()).hexdigest()
                if not any(u["update_id"] == update_id for u in pending["updates"]):
                    pending["updates"].append({**event, "update_id": update_id, "status": "PENDING_REVIEW", "old_snapshot": prior.get("snapshot"), "new_snapshot": record["snapshot"], "source_url": source["url"], "notice": "Source bytes changed; this does not establish a legal amendment or applicability."})
            records.append(record)
            print(record["source_id"], record["status"], "changed=", record["changed"], flush=True)
        atomic_json(pending_path, pending)
        atomic_json(manifest, {"checked_at": now(), "sources": records, "automatic_activation": False,
                               "pending_review_count": sum(u["status"] == "PENDING_REVIEW" for u in pending["updates"])})
        with (output / "history.jsonl").open("a", encoding="utf-8") as history:
            for event in events:
                history.write(json.dumps(event, ensure_ascii=False)+"\n")
        return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sources")
    parser.add_argument("--catalog", type=Path, default=ROOT / "source_catalog.json")
    args = parser.parse_args()
    records = check_sources(json.loads(args.catalog.read_text(encoding="utf-8")), args.output)
    return 1 if any(r["status"] == "FETCH_FAILED" for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
