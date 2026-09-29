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
USER_AGENT = "Mozilla/5.0 TVBox-Source-Merger/daily-final"
REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "thevip001/tvbox-api-backup")
REF = os.environ.get("GITHUB_REF_NAME", "main")
RAW_PREFIX = f"https://raw.githubusercontent.com/{REPOSITORY}/{REF}"


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


def fetch_json(url: str) -> tuple[Any, str]:
    target = safe_url(url)
    if not target:
        return None, "invalid URL"
    try:
        request = Request(
            target,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,*/*"},
        )
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read()
        return json.loads(body.decode("utf-8-sig", errors="replace")), "ok"
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def site_key(site: dict[str, Any]) -> str:
    identity = {
        "name": str(site.get("name") or "").strip().casefold(),
        "api": str(site.get("api") or "").strip(),
        "type": site.get("type", 1),
        "jar": str(site.get("jar") or "").strip(),
        "spider": str(site.get("spider") or "").strip(),
        "ext": site.get("ext"),
    }
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def live_key(live: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(live, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def is_site(value: Any) -> bool:
    return isinstance(value, dict) and bool(
        value.get("api") or value.get("jar") or value.get("spider")
    )


def extract_sites(data: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def add(value: Any) -> None:
        if isinstance(value, dict) and is_site(value):
            result.append(dict(value))
        elif isinstance(value, dict) and isinstance(value.get("list"), list):
            for item in value["list"]:
                add(item)

    if isinstance(data, dict):
        if isinstance(data.get("sites"), list):
            for item in data["sites"]:
                add(item)
    elif isinstance(data, list):
        for item in data:
            add(item)

    return result


def extract_lives(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("lives"), list):
        return [
            dict(item)
            for item in data["lives"]
            if isinstance(item, dict) and item.get("url")
        ]
    return []


def main() -> int:
    configs: list[tuple[Path, dict[str, Any]]] = []
    endpoint_origins: dict[str, str] = {}

    if TVBOX_DIR.exists():
        for path in sorted(TVBOX_DIR.glob("*.json")):
            if path.name.startswith("_"):
                continue
            ok, data = read_json(path)
            if not ok or not isinstance(data, dict):
                continue
            configs.append((path, data))
            for site in extract_sites(data):
                api = safe_url(site.get("api"))
                if api:
                    endpoint_origins.setdefault(api, path.name)

    sites: list[dict[str, Any]] = []
    lives: list[dict[str, Any]] = []
    site_seen: set[str] = set()
    live_seen: set[str] = set()
    failures: list[dict[str, str]] = []

    def add_site(site: dict[str, Any]) -> None:
        identity = site_key(site)
        if identity not in site_seen:
            site_seen.add(identity)
            sites.append(dict(site))

    def add_live(live: dict[str, Any]) -> None:
        identity = live_key(live)
        if identity not in live_seen:
            live_seen.add(identity)
            lives.append(dict(live))

    for _, data in configs:
        for site in extract_sites(data):
            add_site(site)
        for live in extract_lives(data):
            add_live(live)

    with ThreadPoolExecutor(max_workers=max(1, WORKERS)) as pool:
        jobs = {
            pool.submit(fetch_json, url): (url, origin)
            for url, origin in endpoint_origins.items()
        }
        for job in as_completed(jobs):
            url, origin = jobs[job]
            data, status = job.result()
            if data is None:
                failures.append({"url": url, "origin": origin, "error": status})
                continue
            for site in extract_sites(data):
                add_site(site)
            for live in extract_lives(data):
                add_live(live)

    output: dict[str, Any] = {"sites": sites}
    if lives:
        output["lives"] = lives

    (ROOT / "tvbox-merged.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    tvbox_files = [
        {
            "filename": path.name,
            "raw_url": f"{RAW_PREFIX}/{path.relative_to(ROOT).as_posix()}",
            "sites_count": len(data.get("sites", [])),
        }
        for path, data in configs
    ]
    (ROOT / "multiline.txt").write_text(
        "\n".join(
            f"{Path(item['filename']).stem},{item['raw_url']}"
            for item in tvbox_files
        )
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "multiline-urls.txt").write_text(
        "\n".join(item["raw_url"] for item in tvbox_files) + "\n",
        encoding="utf-8",
    )

    summary = {
        "source_endpoints": len(endpoint_origins),
        "failed_endpoints": len(failures),
        "merged_sites": len(sites),
        "merged_lives": len(lives),
        "failed_details": failures,
        "includes_ry_package_data": False,
    }
    (ROOT / "interface_check_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Source endpoints: {len(endpoint_origins)}")
    print(f"Failed endpoints: {len(failures)}")
    print(f"Merged sites: {len(sites)}")
    print(f"Merged lives: {len(lives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
