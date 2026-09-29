#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TVBOX_DIR = REPO_ROOT / "tvbox"
RY_DIR = REPO_ROOT / "ry"

GITHUB_REPOSITORY = os.environ.get(
    "GITHUB_REPOSITORY",
    "thevip001/tvbox-api-backup",
)
GITHUB_REF_NAME = os.environ.get("GITHUB_REF_NAME", "main")
RAW_PREFIX = (
    f"https://raw.githubusercontent.com/"
    f"{GITHUB_REPOSITORY}/{GITHUB_REF_NAME}"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> tuple[bool, Any, str]:
    try:
        with path.open("r", encoding="utf-8") as file:
            return True, json.load(file), "ok"
    except Exception as exc:
        return False, None, str(exc)


def build_raw_url(path: Path) -> str:
    return f"{RAW_PREFIX}/{path.relative_to(REPO_ROOT).as_posix()}"


def is_valid_tvbox_config(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("sites"), list)
        and bool(data["sites"])
    )


def is_valid_ry_package(data: Any) -> bool:
    if not isinstance(data, list):
        return False
    return all(
        isinstance(item, dict)
        and "name" in item
        and isinstance(item.get("list"), list)
        for item in data
    )


def scan_tvbox() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not TVBOX_DIR.exists():
        return results

    for path in sorted(TVBOX_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        valid, data, _ = read_json(path)
        if not valid or not is_valid_tvbox_config(data):
            continue

        sites = data["sites"]
        results.append(
            {
                "filename": path.name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "raw_url": build_raw_url(path),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "sites_count": len(sites),
                "type3_count": sum(
                    1 for site in sites
                    if isinstance(site, dict) and site.get("type") == 3
                ),
                "jar_count": sum(
                    1 for site in sites
                    if isinstance(site, dict) and "jar" in site
                ),
                "has_spider": bool(data.get("spider")),
                "has_lives": isinstance(data.get("lives"), list)
                and bool(data["lives"]),
            }
        )
    return results


def scan_ry() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not RY_DIR.exists():
        return results

    for path in sorted(RY_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        valid, data, _ = read_json(path)
        if not valid or not is_valid_ry_package(data):
            continue

        results.append(
            {
                "filename": path.name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "raw_url": build_raw_url(path),
                "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "categories": len(data),
                "items": sum(len(item["list"]) for item in data),
                "type": "local_package",
            }
        )
    return results


def scan_live_sources() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not TVBOX_DIR.exists():
        return results

    for path in sorted(TVBOX_DIR.glob("*.json")):
        valid, data, _ = read_json(path)
        if not valid or not isinstance(data, dict):
            continue
        lives = data.get("lives")
        if not isinstance(lives, list):
            continue
        for live in lives:
            if isinstance(live, dict) and live.get("url"):
                results.append(
                    {
                        "name": str(live.get("name") or "未知直播"),
                        "url": str(live["url"]),
                        "source": path.name,
                        "type": live.get("type", 0),
                    }
                )
    return results


def make_site_key(site: dict[str, Any]) -> str:
    name = str(site.get("name") or "")
    api = str(site.get("api") or "")
    source = f"{name}|{api}".strip("|")
    if not source:
        source = json.dumps(site, ensure_ascii=False, sort_keys=True)
    digest = hashlib.md5(source.encode("utf-8")).hexdigest()[:12]
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "_-." )[:32]
    return f"{safe or 'site'}_{digest}"


def merge_tvbox_configs() -> dict[str, Any] | None:
    if not TVBOX_DIR.exists():
        return None

    sites: list[dict[str, Any]] = []
    site_keys: set[str] = set()
    lives: list[dict[str, Any]] = []
    live_urls: set[str] = set()

    for path in sorted(TVBOX_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        valid, data, _ = read_json(path)
        if not valid or not is_valid_tvbox_config(data):
            continue

        for site in data["sites"]:
            if not isinstance(site, dict):
                continue
            if site.get("type") != 1:
                continue
            if "jar" in site or "spider" in site or not site.get("api"):
                continue

            copied = dict(site)
            copied["key"] = make_site_key(copied)
            if copied["key"] not in site_keys:
                site_keys.add(copied["key"])
                sites.append(copied)

        for live in data.get("lives", []):
            if not isinstance(live, dict) or not live.get("url"):
                continue
            url = str(live["url"])
            if url not in live_urls:
                live_urls.add(url)
                lives.append(live)

    if not sites and not lives:
        return None

    result: dict[str, Any] = {"sites": sites}
    if lives:
        result["lives"] = lives
    return result


def write_outputs(tvbox_items: list[dict[str, Any]]) -> None:
    named = [
        f"{Path(item['filename']).stem},{item['raw_url']}"
        for item in tvbox_items
    ]
    urls = [item["raw_url"] for item in tvbox_items]
    (REPO_ROOT / "multiline.txt").write_text(
        "\n".join(named) + ("\n" if named else ""),
        encoding="utf-8",
    )
    (REPO_ROOT / "multiline-urls.txt").write_text(
        "\n".join(urls) + ("\n" if urls else ""),
        encoding="utf-8",
    )

    merged = merge_tvbox_configs()
    merged_path = REPO_ROOT / "tvbox-merged.json"
    if merged is None:
        merged_path.write_text(
            json.dumps({"sites": [], "lives": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        merged_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def esc(value: Any, quote: bool = False) -> str:
    return html.escape(str(value), quote=quote)


def card(title: str, fields: list[tuple[str, Any]], copy_url: str | None = None) -> str:
    body = "".join(
        f'<div class="meta"><b>{esc(label)}：</b>{esc(value)}</div>'
        for label, value in fields
    )
    button = ""
    if copy_url:
        button = (
            f'<button class="copy-btn" data-copy="{esc(copy_url, True)}">'
            "复制地址</button>"
        )
    return f'<div class="card"><h3>{esc(title)}</h3>{body}{button}</div>'


def generate_html(
    tvbox_items: list[dict[str, Any]],
    ry_items: list[dict[str, Any]],
    live_items: list[dict[str, Any]],
) -> str:
    tvbox_cards = []
    for item in tvbox_items:
        warnings = []
        if item["type3_count"]:
            warnings.append(f"type=3:{item['type3_count']}")
        if item["jar_count"]:
            warnings.append(f"jar:{item['jar_count']}")
        if item["has_spider"]:
            warnings.append("spider")
        tvbox_cards.append(
            card(
                item["filename"],
                [
                    ("站点数量", item["sites_count"]),
                    ("更新时间", item["mtime"]),
                    ("Raw 地址", item["raw_url"]),
                    ("警告", ", ".join(warnings) or "无"),
                ],
                item["raw_url"],
            )
        )

    ry_cards = [
        card(
            item["filename"],
            [
                ("类型", "本地包"),
                ("分类数量", item["categories"]),
                ("项目数量", item["items"]),
                ("更新时间", item["mtime"]),
                ("Raw 地址", item["raw_url"]),
            ],
            item["raw_url"],
        )
        for item in ry_items
    ]

    live_cards = [
        card(
            item["name"],
            [
                ("来源", item["source"]),
                ("类型", item["type"]),
                ("地址", item["url"]),
            ],
            item["url"],
        )
        for item in live_items
    ]

    def section(items: list[str]) -> str:
        return "".join(items) or '<div class="empty">暂无内容</div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVBox 接口导航</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0f172a;font-family:Arial,sans-serif}}
.container{{max-width:1200px;margin:auto;padding:24px 16px 48px}}
.header{{color:#fff;background:#1e293b;border-radius:16px;padding:20px;margin-bottom:20px}}
.header h1{{margin:0 0 8px}}.header p{{margin:0;color:#cbd5e1}}
input{{width:100%;padding:14px;border:0;border-radius:10px;font-size:16px;margin-bottom:16px}}
.tabs{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}}
.tab{{padding:10px 16px;border:0;border-radius:8px;cursor:pointer;font-weight:bold}}
.tab.active{{background:#2563eb;color:#fff}}.section{{display:none}}.section.active{{display:block}}
.panel{{background:#fff;border-radius:16px;padding:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}
.card{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px}}
.card h3{{margin:0 0 12px;word-break:break-all}}.meta{{margin:7px 0;color:#475569;word-break:break-all}}
.copy-btn{{width:100%;padding:10px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer;margin-top:12px}}
.empty{{padding:20px;text-align:center;color:#475569}}
</style>
</head>
<body>
<main class="container">
<header class="header"><h1>TVBox 接口导航</h1><p>TVBox 配置 / 本地包 / 直播源</p></header>
<input id="search" type="search" placeholder="搜索名称或地址">
<nav class="tabs"><button class="tab active" data-tab="tvbox">TVBox 配置</button><button class="tab" data-tab="ry">本地包</button><button class="tab" data-tab="live">直播源</button></nav>
<section id="tvbox" class="section active"><div class="panel"><p>合法 JSON 且包含 sites 的配置。</p><div class="grid">{section(tvbox_cards)}</div></div></section>
<section id="ry" class="section"><div class="panel"><p>ry/*.json 仅作为本地包。</p><div class="grid">{section(ry_cards)}</div></div></section>
<section id="live" class="section"><div class="panel"><p>从 lives 字段提取。</p><div class="grid">{section(live_cards)}</div></div></section>
</main>
<script>
for (const tab of document.querySelectorAll('.tab')) {{ tab.onclick=()=>{{ document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active')); tab.classList.add('active'); document.querySelectorAll('.section').forEach(x=>x.classList.toggle('active',x.id===tab.dataset.tab)); }}; }}
document.querySelector('#search').oninput=e=>{{ const q=e.target.value.toLowerCase(); document.querySelectorAll('.card').forEach(x=>x.style.display=x.textContent.toLowerCase().includes(q)?'':'none'); }};
for (const button of document.querySelectorAll('.copy-btn')) {{ button.onclick=async()=>{{ try{{ await navigator.clipboard.writeText(button.dataset.copy); button.textContent='已复制'; setTimeout(()=>button.textContent='复制地址',1200); }}catch(e){{ button.textContent='复制失败'; }} }}; }}
</script>
</body>
</html>"""


def main() -> int:
    tvbox_items = scan_tvbox()
    ry_items = scan_ry()
    live_items = scan_live_sources()

    write_outputs(tvbox_items)
    (REPO_ROOT / "api-list.html").write_text(
        generate_html(tvbox_items, ry_items, live_items),
        encoding="utf-8",
    )

    summary = {
        "timestamp": now_iso(),
        "raw_prefix": RAW_PREFIX,
        "tvbox_valid": len(tvbox_items),
        "ry_valid": len(ry_items),
        "live_total": len(live_items),
        "tvbox_files": tvbox_items,
        "ry_files": ry_items,
    }
    (REPO_ROOT / "interface_check_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    merged_path = REPO_ROOT / "tvbox-merged.json"
    merged_valid, merged_data, merged_error = read_json(merged_path)
    if not merged_valid or not isinstance(merged_data, dict):
        raise RuntimeError(f"tvbox-merged.json invalid: {merged_error}")
    if not isinstance(merged_data.get("sites"), list):
        raise RuntimeError("tvbox-merged.json missing sites list")

    print(f"TVBox configs: {len(tvbox_items)}")
    print(f"RY packages: {len(ry_items)}")
    print(f"Live sources: {len(live_items)}")
    print(f"Merged sites: {len(merged_data['sites'])}")
    print("Generated: api-list.html, multiline.txt, multiline-urls.txt,")
    print("interface_check_summary.json, tvbox-merged.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
