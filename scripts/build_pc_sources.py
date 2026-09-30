#!/usr/bin/env python3
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tvbox-merged.json"
OUT_DIR = ROOT / "output"

OUT_DIR.mkdir(parents=True, exist_ok=True)

with SOURCE.open("r", encoding="utf-8-sig") as f:
    config = json.load(f)

URL_RE = re.compile(r"^https?://", re.I)
BLOCKED_API_RE = re.compile(
    r"^(csp_|.*\.js(?:\?.*)?$|.*\.py(?:\?.*)?$|.*drpy|.*dr2|.*dr3|.*jar)",
    re.I,
)

def is_http_url(value):
    return isinstance(value, str) and bool(URL_RE.match(value.strip()))

def is_pc_compatible_site(site):
    api = str(site.get("api", "")).strip()
    ext = site.get("ext", "")

    if not api or not is_http_url(api):
        return False, "api_not_http_url"

    if BLOCKED_API_RE.search(api):
        return False, "android_spider_or_script"

    if isinstance(ext, str) and (
        "csp_" in ext.lower()
        or ext.lower().endswith((".js", ".py", ".jar"))
    ):
        return False, "android_extension"

    if str(site.get("key", "")).lower().startswith("csp_"):
        return False, "csp_key"

    return True, "standard_remote_api"

sites_in = config.get("sites", [])
kept_sites = []
skipped_sites = []

for site in sites_in:
    if not isinstance(site, dict):
        continue

    ok, reason = is_pc_compatible_site(site)

    item = {
        "key": site.get("key", ""),
        "name": site.get("name", ""),
        "type": site.get("type", ""),
        "api": site.get("api", ""),
        "ext": site.get("ext", ""),
    }

    if ok:
        kept_sites.append(site)
    else:
        skipped_sites.append({**item, "reason": reason})

live_sources = []
for live in config.get("lives", []):
    if not isinstance(live, dict):
        continue

    url = str(live.get("url", "")).strip()
    if is_http_url(url):
        live_sources.append({
            "name": live.get("name", "未命名直播源"),
            "url": url,
            "type": live.get("type", 0),
        })

pc_config = {
    "sites": kept_sites,
    "lives": live_sources
}

report = {
    "source_file": str(SOURCE.name),
    "total_sites": len(sites_in),
    "kept_sites": len(kept_sites),
    "skipped_sites": len(skipped_sites),
    "live_sources": len(live_sources),
    "skipped": skipped_sites,
}

with (OUT_DIR / "pc-cms.json").open("w", encoding="utf-8") as f:
    json.dump(pc_config, f, ensure_ascii=False, indent=2)

with (OUT_DIR / "pc-live.txt").open("w", encoding="utf-8") as f:
    for item in live_sources:
        f.write(f"{item['name']},{item['url']}\n")

with (OUT_DIR / "pc-report.json").open("w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(
    f"完成：保留 {len(kept_sites)} 个 PC 兼容点播源，"
    f"{len(live_sources)} 个直播源；"
    f"跳过 {len(skipped_sites)} 个 Android 专用源。"
)
