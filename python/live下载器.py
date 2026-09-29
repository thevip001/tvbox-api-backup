#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox 直播源聚合下载器。"""

import json
import re
import time
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlunparse

import requests

TVBOX_UAS = [
    "okhttp/3.12.13",
    "Mozilla/5.0 (Linux; Android 9; Pixel 3 XL Build/PQ3A.190801.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/91.0.4472.120 Mobile Safari/537.36",
    "VLC/3.0.16 LibVLC/3.0.16",
    "AppleCoreMedia/1.0.0.19C56 (iPhone; U; CPU OS 15_2 like Mac OS X; en_us)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "bingcha/1.1 (mianfeifenxiang)",
]
TVBOX_HEADERS = {
    "X-Requested-With": "com.fongmi.android.tv",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIR = REPO_ROOT / "tvbox"
OUTPUT_LIVE_DIR = SCAN_DIR / "live"
AGGREGATE_JSON = SCAN_DIR / "海量直播线路.json"
LIVELIST_PATH = REPO_ROOT / "livelist.txt"
DOWNLOAD_TIMEOUT = 25
MAX_RETRIES = 3
MAX_UNWRAP_DEPTH = 5
TODAY = datetime.now().strftime("%Y%m%d")
DEBUG = False


def normalize_url(url):
    try:
        p = urlparse(str(url).strip())
        return urlunparse(p._replace(
            scheme=p.scheme.lower(),
            netloc=p.netloc.lower(),
            path=p.path.rstrip("/"),
            fragment="",
        ))
    except Exception:
        return str(url).strip()


def format_file_size(n):
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}K"
    return f"{n / (1024 * 1024):.1f}M"


def get_unique_name(base, used):
    if base not in used:
        used.add(base)
        return base
    idx = 1
    while True:
        name = f"{base}{idx}线"
        if name not in used:
            used.add(name)
            return name
        idx += 1


def sanitize_filename(name):
    p = Path(name)
    stem = p.stem
    suffix = p.suffix
    clean_stem = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", stem).strip()
    return (clean_stem or "live") + suffix


def ensure_suffix(name):
    return name if Path(name).suffix else name + ".txt"


def build_headers(ua):
    headers = dict(TVBOX_HEADERS)
    headers["User-Agent"] = (
        ua.strip()
        if isinstance(ua, str) and ua.strip()
        else TVBOX_UAS[int(time.time()) % len(TVBOX_UAS)]
    )
    return headers


def fetch_url(url, ua, timeout=DOWNLOAD_TIMEOUT):
    headers = build_headers(ua)
    last_exc = None
    for retry in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                verify=True,
            )
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_exc = exc
            if DEBUG and retry == MAX_RETRIES - 1:
                import traceback
                traceback.print_exc()
            if retry < MAX_RETRIES - 1:
                time.sleep(1)
    raise last_exc


def parse_urls_from_text(text):
    urls = []
    seen = set()
    for raw in re.findall(r"https?://\S+", text):
        url = raw.strip().strip('"').strip("'").rstrip(",").rstrip(")").rstrip(";")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def derive_filename(base_name, url):
    filename = Path(urlparse(url).path).name
    if not filename:
        return ensure_suffix(base_name)
    suffix = Path(filename).suffix
    return f"{base_name}{suffix}" if suffix else ensure_suffix(base_name)


def download_one(live, chain=None):
    name = live["name"]
    original_url = live["url"]
    ua = live.get("ua", "")
    chain = chain or []
    target = original_url if not chain else chain[-1]

    try:
        content = fetch_url(target, ua)
    except Exception:
        return False, 0, "", target

    text = content.decode("utf-8", errors="replace")
    urls = parse_urls_from_text(text)
    if len(urls) == 1 and urls[0] != original_url and urls[0] not in chain:
        if len(chain) < MAX_UNWRAP_DEPTH:
            return download_one(live, chain + [urls[0]])

    size = len(content)
    raw_filename = derive_filename(name, target)
    disk_filename = ensure_suffix(sanitize_filename(raw_filename))
    OUTPUT_LIVE_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_LIVE_DIR / disk_filename
    with output_path.open("wb") as file:
        file.write(b"#EXTM3U\n")
        file.write(f'#EXTINF:-1 tvg-name="{name}",{name}\n'.encode("utf-8"))
        file.write(content)
    return True, size, disk_filename, target


def extract_lives(data):
    """兼容标准对象和数组格式，数组格式没有 lives 时安全跳过。"""
    if not isinstance(data, dict):
        return []
    lives = data.get("lives", [])
    return lives if isinstance(lives, list) else []


def scan_interfaces():
    print("\n[1/4] 扫描接口文件，提取 lives ...")
    all_lives = []
    used_urls = set()
    if not SCAN_DIR.exists():
        print(f"  目录不存在: {SCAN_DIR}")
        return all_lives

    for json_file in sorted(SCAN_DIR.glob("*.json")):
        if json_file.name == AGGREGATE_JSON.name:
            continue
        source = json_file.stem
        try:
            with json_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as exc:
            print(f"  跳过 {json_file.name}: {exc}")
            continue

        lives = extract_lives(data)
        valid = 0
        for item in lives:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if not name or not url or not url.startswith(("http://", "https://")):
                continue
            normalized = normalize_url(url)
            if normalized in used_urls:
                continue
            used_urls.add(normalized)
            all_lives.append({
                "name": name,
                "url": url,
                "ua": item.get("ua", ""),
                "source": source,
            })
            valid += 1
        print(f"  {json_file.name}: {valid} 条")

    print(f"  合计（去重后）: {len(all_lives)}")
    return all_lives


def aggregate(lives):
    print("\n[2/4] 聚合命名 ...")
    used_names = set()
    aggregated = []
    for item in lives:
        item = dict(item)
        item["name"] = get_unique_name(item["name"], used_names)
        aggregated.append(item)
        if len(aggregated) <= 10:
            print(f"      {len(aggregated)}. {item['name']} <= {item['url'][:60]}")
    if len(aggregated) > 10:
        print(f"      ... 共 {len(aggregated)} 条")

    OUTPUT_LIVE_DIR.mkdir(parents=True, exist_ok=True)
    with AGGREGATE_JSON.open("w", encoding="utf-8") as file:
        json.dump({"lives": aggregated}, file, ensure_ascii=False, indent=2)
    print(f"  索引 -> {AGGREGATE_JSON}")
    return aggregated


def batch_download(lives):
    print("\n[3/4] 下载直播源 ...")
    print(f"  输出目录: {OUTPUT_LIVE_DIR}")
    results = {}
    failures = []
    for index, live in enumerate(lives, 1):
        ok, size, filename, final_url = download_one(live)
        results[live["name"]] = (ok, size, filename, final_url)
        status = "ok" if ok else "FAIL"
        print(f"  [{index}/{len(lives)}] {live['name']} {status} ({format_file_size(size) if ok else '0B'})")
        if not ok:
            failures.append(live["name"])
    ok_count = sum(1 for value in results.values() if value[0])
    print(f"\n  完成: {ok_count}/{len(lives)} 成功")
    if failures:
        print(f"  失败: {', '.join(failures)}")
    return results


def generate_livelist(lives, results):
    print("\n[4/4] 生成/合并 livelist.txt ...")
    old_records = {}
    if LIVELIST_PATH.exists():
        with LIVELIST_PATH.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    old_records[line.split("|")[0]] = line

    new_records = {}
    for live in lives:
        name = live["name"]
        if name not in results or not results[name][0]:
            continue
        _, size, disk_filename, _ = results[name]
        source = Path(live["source"]).stem
        ua = (live.get("ua") or "").strip() or "null"
        new_records[disk_filename] = (
            f"{disk_filename}|{TODAY}|{format_file_size(size)}|"
            f"{live['url']}|{source}|{ua}|"
        )

    final_lines = list(new_records.values())
    for filename, line in old_records.items():
        if filename not in new_records:
            final_lines.append(line)
    LIVELIST_PATH.write_text("\n".join(final_lines), encoding="utf-8")
    print(f"  -> {LIVELIST_PATH}")
    print(f"  更新: {len(new_records)}, 保留旧记录: {max(0, len(old_records) - len(new_records))}")


def main():
    global DEBUG
    import argparse
    parser = argparse.ArgumentParser(description="TVBox 直播源聚合器")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    DEBUG = args.debug

    start = time.time()
    print("=" * 60)
    print("TVBox Live aggregator")
    print("=" * 60)
    lives = scan_interfaces()
    if not lives:
        print("\n没有有效的直播源，退出")
        return
    aggregated = aggregate(lives)
    results = batch_download(aggregated)
    generate_livelist(aggregated, results)
    print("\n" + "=" * 60)
    print(f"完成，耗时 {time.time() - start:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
