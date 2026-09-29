#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

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
    relative_path = path.relative_to(REPO_ROOT).as_posix()
    return f"{RAW_PREFIX}/{relative_path}"


def is_valid_tvbox_config(data: Any) -> bool:
    if not isinstance(data, dict):
        return False

    sites = data.get("sites")
    return isinstance(sites, list) and len(sites) > 0


def is_valid_ry_package(data: Any) -> bool:
    if not isinstance(data, list):
        return False

    for category in data:
        if not isinstance(category, dict):
            return False

        if "name" not in category or "list" not in category:
            return False

        if not isinstance(category["list"], list):
            return False

    return True


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
                "mtime": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "sites_count": len(sites),
                "type3_count": sum(
                    1
                    for site in sites
                    if isinstance(site, dict) and site.get("type") == 3
                ),
                "jar_count": sum(
                    1
                    for site in sites
                    if isinstance(site, dict) and "jar" in site
                ),
                "has_spider": bool(data.get("spider")),
                "has_lives": isinstance(data.get("lives"), list)
                and len(data["lives"]) > 0,
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

        item_count = sum(
            len(category.get("list", []))
            for category in data
            if isinstance(category, dict)
        )

        results.append(
            {
                "filename": path.name,
                "path": path.relative_to(REPO_ROOT).as_posix(),
                "raw_url": build_raw_url(path),
                "mtime": datetime.fromtimestamp(
                    path.stat().st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "categories": len(data),
                "items": item_count,
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
            if not isinstance(live, dict):
                continue

            url = live.get("url")

            if not url:
                continue

            results.append(
                {
                    "name": str(live.get("name") or "未知直播"),
                    "url": str(url),
                    "source": path.name,
                    "type": live.get("type", 0),
                }
            )

    return results


def write_multiline(
    tvbox_items: list[dict[str, Any]],
    named_path: Path,
    url_only_path: Path,
) -> None:
    named_lines: list[str] = []
    url_lines: list[str] = []

    for item in tvbox_items:
        config_name = Path(item["filename"]).stem
        raw_url = item["raw_url"]

        named_lines.append(f"{config_name},{raw_url}")
        url_lines.append(raw_url)

    named_path.write_text(
        "\n".join(named_lines) + ("\n" if named_lines else ""),
        encoding="utf-8",
    )

    url_only_path.write_text(
        "\n".join(url_lines) + ("\n" if url_lines else ""),
        encoding="utf-8",
    )


def render_tvbox_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">未发现可直接用于 TVBox 的配置文件</div>'

    cards: list[str] = []

    for item in items:
        filename = html.escape(str(item["filename"]))
        raw_url = html.escape(str(item["raw_url"]))
        raw_url_attribute = html.escape(
            str(item["raw_url"]),
            quote=True,
        )

        badges: list[str] = []

        if item["type3_count"]:
            badges.append(
                f'<span class="badge warn">type=3: '
                f'{item["type3_count"]}</span>'
            )

        if item["jar_count"]:
            badges.append(
                f'<span class="badge warn">jar: '
                f'{item["jar_count"]}</span>'
            )

        if item["has_spider"]:
            badges.append(
                '<span class="badge info">spider</span>'
            )

        cards.append(
            f"""
            <div class="card">
              <h3>{filename}</h3>
              <div class="meta"><b>站点数量：</b>{item["sites_count"]}</div>
              <div class="meta"><b>更新时间：</b>{item["mtime"]}</div>
              <div class="meta"><b>地址：</b>
                <span class="mono">{raw_url}</span>
              </div>
              <div class="badges">{"".join(badges)}</div>
              <div class="actions">
                <button
                  data-copy="{raw_url_attribute}"
                  class="copy-btn"
                >
                  复制 Raw 地址
                </button>
              </div>
            </div>
            """
        )

    return "\n".join(cards)


def render_ry_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">未发现本地包配置</div>'

    cards: list[str] = []

    for item in items:
        filename = html.escape(str(item["filename"]))
        raw_url = html.escape(str(item["raw_url"]))
        raw_url_attribute = html.escape(
            str(item["raw_url"]),
            quote=True,
        )

        cards.append(
            f"""
            <div class="card">
              <h3>{filename}</h3>
              <div class="meta"><b>类型：</b>本地包</div>
              <div class="meta"><b>分类数量：</b>{item["categories"]}</div>
              <div class="meta"><b>项目数量：</b>{item["items"]}</div>
              <div class="meta"><b>更新时间：</b>{item["mtime"]}</div>
              <div class="meta"><b>地址：</b>
                <span class="mono">{raw_url}</span>
              </div>
              <div class="actions">
                <button
                  data-copy="{raw_url_attribute}"
                  class="copy-btn"
                >
                  复制本地包地址
                </button>
              </div>
            </div>
            """
        )

    return "\n".join(cards)


def render_live_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">未提取到直播源</div>'

    cards: list[str] = []

    for item in items:
        name = html.escape(str(item["name"]))
        url = html.escape(str(item["url"]))
        url_attribute = html.escape(str(item["url"]), quote=True)
        source = html.escape(str(item["source"]))

        cards.append(
            f"""
            <div class="card">
              <h3>{name}</h3>
              <div class="meta"><b>来源：</b>{source}</div>
              <div class="meta"><b>类型：</b>{item["type"]}</div>
              <div class="meta"><b>地址：</b>
                <span class="mono">{url}</span>
              </div>
              <div class="actions">
                <button
                  data-copy="{url_attribute}"
                  class="copy-btn"
                >
                  复制直播地址
                </button>
              </div>
            </div>
            """
        )

    return "\n".join(cards)


def generate_html(
    tvbox_items: list[dict[str, Any]],
    ry_items: list[dict[str, Any]],
    live_items: list[dict[str, Any]],
) -> str:
    tvbox_html = render_tvbox_cards(tvbox_items)
    ry_html = render_ry_cards(ry_items)
    live_html = render_live_cards(live_items)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TVBox 接口导航</title>
  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      background: #0f172a;
      color: #0f172a;
      font-family: Arial, sans-serif;
    }}

    .container {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px 16px 48px;
    }}

    .header {{
      padding: 20px;
      color: white;
      border-radius: 16px;
      background: #1e293b;
      margin-bottom: 20px;
    }}

    h1 {{
      margin: 0 0 8px;
    }}

    .subtitle {{
      margin: 0;
      color: #cbd5e1;
    }}

    .search {{
      margin-bottom: 20px;
    }}

    .search input {{
      width: 100%;
      padding: 14px 16px;
      border: 0;
      border-radius: 10px;
      font-size: 16px;
    }}

    .tabs {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }}

    .tab {{
      padding: 10px 16px;
      border: 0;
      border-radius: 8px;
      cursor: pointer;
      font-weight: bold;
    }}

    .tab.active {{
      background: #2563eb;
      color: white;
    }}

    .section {{
      display: none;
    }}

    .section.active {{
      display: block;
    }}

    .panel {{
      padding: 18px;
      border-radius: 16px;
      background: white;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(
        auto-fit,
        minmax(280px, 1fr)
      );
      gap: 16px;
    }}

    .card {{
      padding: 16px;
      border: 1px solid #e2e8f0;
      border-radius: 12px;
      background: #f8fafc;
    }}

    .card h3 {{
      margin: 0 0 12px;
      word-break: break-all;
    }}

    .meta {{
      margin: 6px 0;
      color: #475569;
      word-break: break-all;
    }}

    .mono {{
      font-family: monospace;
      font-size: 13px;
    }}

    .badges {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}

    .badge {{
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: bold;
    }}

    .badge.warn {{
      color: #92400e;
      background: #fef3c7;
    }}

    .badge.info {{
      color: #1d4ed8;
      background: #dbeafe;
    }}

    .actions {{
      margin-top: 14px;
    }}

    .copy-btn {{
      width: 100%;
      padding: 10px;
      border: 0;
      border-radius: 8px;
      cursor: pointer;
      color: white;
      background: #2563eb;
    }}

    .empty {{
      padding: 20px;
      text-align: center;
      color: #475569;
    }}
  </style>
</head>
<body>
  <main class="container">
    <header class="header">
      <h1>TVBox 接口导航</h1>
      <p class="subtitle">
        分离发布：TVBox 配置 / 本地包 / 直播源
      </p>
    </header>

    <div class="search">
      <input
        id="searchInput"
        type="search"
        placeholder="搜索接口名称或地址"
      >
    </div>

    <nav class="tabs">
      <button class="tab active" data-tab="tvbox">
        TVBox 配置
      </button>
      <button class="tab" data-tab="ry">
        本地包
      </button>
      <button class="tab" data-tab="live">
        直播源
      </button>
    </nav>

    <section id="tvbox" class="section active">
      <div class="panel">
        <p>
          仅显示合法 JSON 且包含 sites 字段的 TVBox 配置。
        </p>
        <div class="grid">
          {tvbox_html}
        </div>
      </div>
    </section>

    <section id="ry" class="section">
      <div class="panel">
        <p>
          ry/*.json 是本地包，不纳入 TVBox 多仓。
        </p>
        <div class="grid">
          {ry_html}
        </div>
      </div>
    </section>

    <section id="live" class="section">
      <div class="panel">
        <p>
          从 TVBox 配置的 lives 字段提取直播源。
        </p>
        <div class="grid">
          {live_html}
        </div>
      </div>
    </section>
  </main>

  <script>
    const tabs = document.querySelectorAll(".tab");

    tabs.forEach((tab) => {{
      tab.addEventListener("click", () => {{
        tabs.forEach((item) => item.classList.remove("active"));
        tab.classList.add("active");

        document.querySelectorAll(".section").forEach((section) => {{
          section.classList.toggle(
            "active",
            section.id === tab.dataset.tab
          );
        }});
      }});
    }});

    const searchInput = document.getElementById("searchInput");

    searchInput.addEventListener("input", (event) => {{
      const query = event.target.value.toLowerCase().trim();

      document.querySelectorAll(".card").forEach((card) => {{
        card.style.display = card.textContent
          .toLowerCase()
          .includes(query)
          ? ""
          : "none";
      }});
    }});

    document.querySelectorAll(".copy-btn").forEach((button) => {{
      button.addEventListener("click", async () => {{
        const text = button.dataset.copy;

        try {{
          await navigator.clipboard.writeText(text);
          const oldText = button.textContent;
          button.textContent = "已复制";
          setTimeout(() => {{
            button.textContent = oldText;
          }}, 1200);
        }} catch (error) {{
          button.textContent = "复制失败";
        }}
      }});
    }});
  </script>
</body>
</html>
"""


def main() -> int:
    tvbox_items = scan_tvbox()
    ry_items = scan_ry()
    live_items = scan_live_sources()

    write_multiline(
        tvbox_items,
        REPO_ROOT / "multiline.txt",
        REPO_ROOT / "multiline-urls.txt",
    )

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

    print(f"TVBox configs: {len(tvbox_items)}")
    print(f"RY packages: {len(ry_items)}")
    print(f"Live sources: {len(live_items)}")
    print(
        "Generated: api-list.html, multiline.txt, "
        "multiline-urls.txt, interface_check_summary.json"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
