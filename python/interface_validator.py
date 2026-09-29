#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TVBOX_DIR = ROOT / "tvbox"
TIMEOUT = float(os.environ.get("TVBOX_FETCH_TIMEOUT", "6"))
WORKERS = int(os.environ.get("TVBOX_FETCH_WORKERS", "16"))
UA = "Mozilla/5.0 TVBox-Source-Merger/2.2"
REPO = os.environ.get("GITHUB_REPOSITORY", "thevip001/tvbox-api-backup")
REF = os.environ.get("GITHUB_REF_NAME", "main")
RAW_PREFIX = f"https://raw.githubusercontent.com/{REPO}/{REF}"


def read_json(path: Path) -> tuple[bool, Any]:
    try:
        return True, json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, None


def safe_url(value: Any) -> str:
    value = str(value or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
            quote(parts.query, safe="/%?:@!$&'()*+,;=-._~"),
            quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~"),
        )
    )


def fetch(url: str) -> tuple[str, Any, str]:
    target = safe_url(url)
    if not target:
        return url, None, "invalid URL"
    try:
        request = Request(target, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
        return url, json.loads(body.decode("utf-8-sig", errors="replace")), "ok"
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return url, None, f"{type(exc).__name__}: {exc}"


def key(site: dict[str, Any]) -> str:
    fields = (
        str(site.get("name") or "").strip().casefold(),
        str(site.get("api") or "").strip(),
        str(site.get("type", 1)),
        str(site.get("jar") or "").strip(),
        str(site.get("spider") or "").strip(),
        json.dumps(site.get("ext"), ensure_ascii=False, sort_keys=True),
    )
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def keep_site(site: Any) -> bool:
    if not isinstance(site, dict):
        return False
    return bool(site.get("api") or site.get("jar") or site.get("spider"))


def main() -> int:
    source_urls: dict[str, str] = {}
    source_files: list[tuple[Path, dict[str, Any]]] = []
    if TVBOX_DIR.exists():
        for path in sorted(TVBOX_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            ok, data = read_json(path)
            if not ok or not isinstance(data, dict):
                continue
            source_files.append((path, data))
            for site in data.get("sites", []):
                if isinstance(site, dict) and site.get("api"):
                    url = safe_url(site["api"])
                    if url:
                        source_urls.setdefault(url, path.name)

    collected: list[dict[str, Any]] = []
    lives: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: list[dict[str, str]] = []

    def add(site: dict[str, Any]) -> None:
        if not keep_site(site):
            return
        copied = dict(site)
        identity = key(copied)
        if identity not in seen:
            seen.add(identity)
            collected.append(copied)

    with ThreadPoolExecutor(max_workers=max(1, WORKERS)) as pool:
        jobs = {pool.submit(fetch, url): (url, origin) for url, origin in source_urls.items()}
        for job in as_completed(jobs):
            url, origin = jobs[job]
            _, data, status = job.result()
            if data is None:
                failures.append({"url": url, "origin": origin, "error": status})
                continue
            if isinstance(data, dict):
                for site in data.get("sites", []):
                    add(site)
                for live in data.get("lives", []):
                    if isinstance(live, dict) and live.get("url"):
                        lives.append(dict(live))

    for _, data in source_files:
        for site in data.get("sites", []):
            add(site)
        for live in data.get("lives", []):
            if isinstance(live, dict) and live.get("url"):
                lives.append(dict(live))

    unique_lives: list[dict[str, Any]] = []
    live_seen: set[str] = set()
    for live in lives:
        identity = json.dumps(live, ensure_ascii=False, sort_keys=True)
        if identity not in live_seen:
            live_seen.add(identity)
            unique_lives.append(live)

    output: dict[str, Any] = {"sites": collected}
    if unique_lives:
        output["lives"] = unique_lives
    (ROOT / "tvbox-merged.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "merged_sites": len(collected),
        "merged_lives": len(unique_lives),
        "source_endpoints": len(source_urls),
        "failed_endpoints": len(failures),
        "failed_details": failures,
    }
    (ROOT / "interface_check_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Source endpoints: {len(source_urls)}")
    print(f"Failed endpoints: {len(failures)}")
    print(f"Merged sites: {len(collected)}")
    print(f"Merged lives: {len(unique_lives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
