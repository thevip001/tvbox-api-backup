#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TVBOX_DIR = ROOT / "tvbox"
RY_DIR = ROOT / "ry"
TIMEOUT = float(os.environ.get("TVBOX_FETCH_TIMEOUT", "5"))
MAX_DEPTH = int(os.environ.get("TVBOX_MAX_DEPTH", "1"))
WORKERS = int(os.environ.get("TVBOX_FETCH_WORKERS", "16"))
UA = "Mozilla/5.0 TVBox-Source-Merger/fast"
REPO = os.environ.get("GITHUB_REPOSITORY", "thevip001/tvbox-api-backup")
REF = os.environ.get("GITHUB_REF_NAME", "main")
RAW_PREFIX = f"https://raw.githubusercontent.com/{REPO}/{REF}"


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> tuple[bool, Any]:
    try:
        return True, json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False, None


def encoded_url(value: Any) -> str:
    value = str(value or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    fragment = quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def fetch(url: str) -> tuple[str, Any, str]:
    safe = encoded_url(url)
    if not safe:
        return url, None, "invalid URL"
    try:
        request = Request(safe, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
        with urlopen(request, timeout=TIMEOUT) as response:
            text = response.read().decode("utf-8-sig", errors="replace")
        return url, json.loads(text), "ok"
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return url, None, f"{type(exc).__name__}: {exc}"


def identity(site: dict[str, Any]) -> str:
    values = (
        " ".join(str(site.get("name") or "").split()).casefold(),
        str(site.get("api") or "").strip(),
        str(site.get("type", 1)),
        str(site.get("jar") or "").strip(),
        str(site.get("spider") or "").strip(),
    )
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def local_configs() -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    configs: list[tuple[Path, dict[str, Any]]] = []
    packages: list[dict[str, Any]] = []
    for path in sorted(TVBOX_DIR.glob("*.json")) if TVBOX_DIR.exists() else []:
        if path.name.startswith("_"):
            continue
        ok, data = read_json(path)
        if ok and isinstance(data, dict) and isinstance(data.get("sites"), list):
            configs.append((path, data))
    for path in sorted(RY_DIR.glob("*.json")) if RY_DIR.exists() else []:
        if path.name.startswith("_"):
            continue
        ok, data = read_json(path)
        if ok and isinstance(data, list):
            packages.append({"path": path, "data": data})
    return configs, packages


def collect() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    configs, _ = local_configs()
    first_urls: dict[str, str] = {}
    local_sites: list[dict[str, Any]] = []
    lives: list[dict[str, Any]] = []

    for path, data in configs:
        for site in data.get("sites", []):
            if not isinstance(site, dict):
                continue
            api = encoded_url(site.get("api"))
            if api:
                first_urls.setdefault(api, path.name)
            elif site.get("type", 1) == 1:
                local_sites.append(dict(site))
        for live in data.get("lives", []):
            if isinstance(live, dict) and live.get("url"):
                lives.append(dict(live))

    fetched: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, WORKERS)) as pool:
        tasks = {pool.submit(fetch, url): (url, origin) for url, origin in first_urls.items()}
        for task in as_completed(tasks):
            url, origin = tasks[task]
            original, data, status = task.result()
            if data is None:
                failures.append({"url": original, "origin": origin, "error": status})
            else:
                fetched[original] = data

    sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for site in local_sites:
        key = identity(site)
        if key not in seen:
            seen.add(key)
            sites.append(site)

    second_urls: dict[str, str] = {}
    for data in fetched.values():
        if not isinstance(data, dict):
            continue
        for site in data.get("sites", []):
            if not isinstance(site, dict):
                continue
            copied = dict(site)
            if copied.get("type", 1) == 1 and copied.get("api"):
                key = identity(copied)
                if key not in seen:
                    seen.add(key)
                    sites.append(copied)
            api = encoded_url(copied.get("api"))
            if api and MAX_DEPTH >= 2:
                second_urls.setdefault(api, "nested")
        if isinstance(data.get("lives"), list):
            lives.extend(x for x in data["lives"] if isinstance(x, dict) and x.get("url"))

    if second_urls:
        with ThreadPoolExecutor(max_workers=max(1, WORKERS)) as pool:
            tasks = {pool.submit(fetch, url): url for url in second_urls if url not in fetched}
            for task in as_completed(tasks):
                original, data, status = task.result()
                if data is None:
                    failures.append({"url": original, "origin": "nested", "error": status})
                    continue
                if not isinstance(data, dict):
                    continue
                for site in data.get("sites", []):
                    if isinstance(site, dict) and site.get("type", 1) == 1 and site.get("api"):
                        key = identity(site)
                        if key not in seen:
                            seen.add(key)
                            sites.append(dict(site))
                if isinstance(data.get("lives"), list):
                    lives.extend(x for x in data["lives"] if isinstance(x, dict) and x.get("url"))

    unique_lives: list[dict[str, Any]] = []
    live_seen: set[str] = set()
    for live in lives:
        key = json.dumps(live, ensure_ascii=False, sort_keys=True)
        if key not in live_seen:
            live_seen.add(key)
            unique_lives.append(live)

    return sites, unique_lives, {"fetched": len(fetched), "failed": failures, "first_urls": len(first_urls), "nested_urls": len(second_urls)}


def main() -> int:
    configs, packages = local_configs()
    sites, lives, stats = collect()
    output: dict[str, Any] = {"sites": sites}
    if lives:
        output["lives"] = lives
    (ROOT / "tvbox-merged.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    tvbox_info = []
    for path, data in configs:
        tvbox_info.append({"filename": path.name, "path": path.relative_to(ROOT).as_posix(), "raw_url": f"{RAW_PREFIX}/{path.relative_to(ROOT).as_posix()}", "sites_count": len(data.get("sites", []))})
    (ROOT / "multiline.txt").write_text("\n".join(f"{Path(x['filename']).stem},{x['raw_url']}" for x in tvbox_info) + "\n", encoding="utf-8")
    (ROOT / "multiline-urls.txt").write_text("\n".join(x["raw_url"] for x in tvbox_info) + "\n", encoding="utf-8")
    report = {"timestamp": iso_now(), "merged_sites": len(sites), "merged_lives": len(lives), "local_tvbox_configs": len(configs), "local_ry_packages": len(packages), **stats}
    (ROOT / "interface_check_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"First-level endpoints: {stats['first_urls']}")
    print(f"Fetched endpoints: {stats['fetched']}")
    print(f"Nested endpoints: {stats['nested_urls']}")
    print(f"Failed endpoints: {len(stats['failed'])}")
    print(f"Merged sites: {len(sites)}")
    print(f"Merged lives: {len(lives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
