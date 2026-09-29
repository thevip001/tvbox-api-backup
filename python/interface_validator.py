#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
TVBOX_DIR = REPO_ROOT / "tvbox"
RY_DIR = REPO_ROOT / "ry"
TIMEOUT = float(os.environ.get("TVBOX_FETCH_TIMEOUT", "12"))
MAX_DEPTH = int(os.environ.get("TVBOX_MAX_DEPTH", "2"))
USER_AGENT = "Mozilla/5.0 TVBox-Source-Merger/2.1"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "thevip001/tvbox-api-backup")
REF = os.environ.get("GITHUB_REF_NAME", "main")
RAW_PREFIX = f"https://raw.githubusercontent.com/{REPOSITORY}/{REF}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> tuple[bool, Any, str]:
    try:
        return True, json.loads(path.read_text(encoding="utf-8")), "ok"
    except Exception as exc:
        return False, None, str(exc)


def valid_config(data: Any) -> bool:
    return isinstance(data, dict) and isinstance(data.get("sites"), list)


def valid_package(data: Any) -> bool:
    return isinstance(data, list) and all(
        isinstance(item, dict) and isinstance(item.get("list"), list)
        for item in data
    )


def raw_url(path: Path) -> str:
    return f"{RAW_PREFIX}/{path.relative_to(REPO_ROOT).as_posix()}"


def normalise_url(value: Any) -> str:
    return str(value or "").strip()


def request_url(value: Any) -> str:
    value = normalise_url(value)
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    fragment = quote(parts.fragment, safe="/%?:@!$&'()*+,;=-._~")
    return urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def site_identity(site: dict[str, Any]) -> str:
    name = " ".join(str(site.get("name") or "").split()).casefold()
    api = normalise_url(site.get("api"))
    site_type = str(site.get("type", 1))
    jar = normalise_url(site.get("jar"))
    spider = normalise_url(site.get("spider"))
    payload = "|".join((name, api, site_type, jar, spider))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_json(url: str) -> tuple[bool, Any, str, str]:
    safe_url = request_url(url)
    if not safe_url:
        return False, None, "invalid URL", ""
    request = Request(
        safe_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"},
    )
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
        if not body:
            return False, None, "empty response", safe_url
        text = body.decode("utf-8-sig", errors="replace")
        return True, json.loads(text), "ok", safe_url
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return False, None, f"{type(exc).__name__}: {exc}", safe_url


def local_entries() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    configs: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    if TVBOX_DIR.exists():
        for path in sorted(TVBOX_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            ok, data, _ = read_json(path)
            if ok and valid_config(data):
                configs.append({"path": path, "data": data})
    if RY_DIR.exists():
        for path in sorted(RY_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            ok, data, _ = read_json(path)
            if ok and valid_package(data):
                packages.append({"path": path, "data": data})
    return configs, packages


def add_sites(
    data: Any,
    origin: str,
    depth: int,
    queue: list[tuple[str, str, int]],
    seen_urls: set[str],
    sites: list[dict[str, Any]],
    identities: set[str],
) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("sites"), list):
        return
    for site in data["sites"]:
        if not isinstance(site, dict):
            continue
        copied = dict(site)
        api = normalise_url(copied.get("api"))
        if api and depth < MAX_DEPTH:
            safe = request_url(api)
            if safe and safe not in seen_urls:
                seen_urls.add(safe)
                queue.append((safe, origin, depth + 1))
        if copied.get("type", 1) != 1:
            continue
        if not copied.get("api"):
            continue
        identity = site_identity(copied)
        if identity not in identities:
            identities.add(identity)
            sites.append(copied)


def collect_remote_sources() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]
]:
    configs, _ = local_entries()
    queue: list[tuple[str, str, int]] = []
    seen_urls: set[str] = set()
    sites: list[dict[str, Any]] = []
    lives: list[dict[str, Any]] = []
    identities: set[str] = set()
    failures: list[dict[str, str]] = []
    fetched: list[dict[str, Any]] = []

    for item in configs:
        origin = item["path"].name
        config = item["data"]
        add_sites(config, origin, 0, queue, seen_urls, sites, identities)
        for live in config.get("lives", []):
            if isinstance(live, dict) and live.get("url"):
                lives.append(dict(live))

    while queue:
        url, origin, depth = queue.pop(0)
        ok, data, error, safe_url = fetch_json(url)
        if not ok:
            failures.append(
                {
                    "url": url,
                    "request_url": safe_url,
                    "origin": origin,
                    "error": error,
                }
            )
            continue
        fetched.append({"url": url, "origin": origin, "depth": depth})
        add_sites(data, url, depth, queue, seen_urls, sites, identities)
        if isinstance(data, dict) and isinstance(data.get("lives"), list):
            for live in data["lives"]:
                if isinstance(live, dict) and live.get("url"):
                    lives.append(dict(live))
        time.sleep(0.05)

    unique_lives: list[dict[str, Any]] = []
    live_keys: set[str] = set()
    for live in lives:
        key = json.dumps(live, ensure_ascii=False, sort_keys=True)
        if key not in live_keys:
            live_keys.add(key)
            unique_lives.append(live)

    return sites, unique_lives, {"fetched": fetched, "failed": failures}


def scan_summary() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tvbox: list[dict[str, Any]] = []
    ry: list[dict[str, Any]] = []
    configs, packages = local_entries()
    for item in configs:
        path, data = item["path"], item["data"]
        tvbox.append(
            {
                "filename": path.name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "raw_url": raw_url(path),
                "sites_count": len(data.get("sites", [])),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    for item in packages:
        path, data = item["path"], item["data"]
        ry.append(
            {
                "filename": path.name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "raw_url": raw_url(path),
                "categories": len(data),
                "items": sum(len(x.get("list", [])) for x in data),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            }
        )
    return tvbox, ry


def main() -> int:
    tvbox, ry = scan_summary()
    sites, lives, network = collect_remote_sources()
    result: dict[str, Any] = {"sites": sites}
    if lives:
        result["lives"] = lives

    (REPO_ROOT / "tvbox-merged.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REPO_ROOT / "multiline.txt").write_text(
        "\n".join(
            f"{Path(item['filename']).stem},{item['raw_url']}"
            for item in tvbox
        )
        + "\n",
        encoding="utf-8",
    )
    (REPO_ROOT / "multiline-urls.txt").write_text(
        "\n".join(item["raw_url"] for item in tvbox) + "\n",
        encoding="utf-8",
    )

    report = {
        "timestamp": now_iso(),
        "fetched_sites": len(sites),
        "lives": len(lives),
        "local_tvbox_configs": len(tvbox),
        "local_ry_packages": len(ry),
        "fetched_endpoints": len(network["fetched"]),
        "failed_endpoints": len(network["failed"]),
        "failed_endpoint_details": network["failed"],
    }
    (REPO_ROOT / "interface_check_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Local TVBox configs: {len(tvbox)}")
    print(f"Local RY packages: {len(ry)}")
    print(f"Merged remote sites: {len(sites)}")
    print(f"Merged live sources: {len(lives)}")
    print(f"Fetched endpoints: {len(network['fetched'])}")
    print(f"Failed endpoints: {len(network['failed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
