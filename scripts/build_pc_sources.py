#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SOURCE_FILE = ROOT / "tvbox-merged.json"
OUTPUT_FILE = ROOT / "pc.json"

HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

ANDROID_ONLY_API_RE = re.compile(
    r"(^csp_)|"
    r"(^drpy)|"
    r"(^dr2)|"
    r"(^dr3)|"
    r"(\.jar(?:\?.*)?$)|"
    r"(\.js(?:\?.*)?$)|"
    r"(\.py(?:\?.*)?$)",
    re.IGNORECASE,
)

ANDROID_ONLY_EXT_RE = re.compile(
    r"(^csp_)|"
    r"(\.jar(?:\?.*)?$)|"
    r"(\.js(?:\?.*)?$)|"
    r"(\.py(?:\?.*)?$)|"
    r"(drpy)|"
    r"(dr2)|"
    r"(dr3)",
    re.IGNORECASE,
)

# 不要出现在电脑端 pc.json 中的“说明/广告/公告”站点。
# 匹配 key、name 或 api 中的任意一个就删除。
BLOCKED_SITE_KEYWORDS = (
    "说明",
    "公告",
    "广告",
    "扫码",
    "加群",
    "二维码",
    "多地址说明",
)


def is_http_url(value):
    return isinstance(value, str) and bool(HTTP_URL_RE.match(value.strip()))


def text_contains_blocked_keyword(value):
    text = str(value or "").strip().lower()

    return any(keyword.lower() in text for keyword in BLOCKED_SITE_KEYWORDS)


def is_notice_or_ad_site(site):
    key = site.get("key", "")
    name = site.get("name", "")
    api = site.get("api", "")

    return (
        text_contains_blocked_keyword(key)
        or text_contains_blocked_keyword(name)
        or text_contains_blocked_keyword(api)
    )


def is_android_only_site(site):
    key = str(site.get("key", "")).strip()
    api = str(site.get("api", "")).strip()
    ext = site.get("ext", "")

    if key.lower().startswith("csp_"):
        return True

    if ANDROID_ONLY_API_RE.search(api):
        return True

    if isinstance(ext, str) and ANDROID_ONLY_EXT_RE.search(ext):
        return True

    return False


def is_pc_compatible_site(site):
    if not isinstance(site, dict):
        return False

    api = str(site.get("api", "")).strip()

    # 删除 “⚠️说明” / 公告 / 广告 / 扫码加群等非影视站点。
    if is_notice_or_ad_site(site):
        return False

    # 电脑端只保留可直接访问的 HTTP(S) API。
    if not is_http_url(api):
        return False

    # 删除 TVBox 安卓端 Spider、JAR、JS、PY、DRPY 等专用源。
    if is_android_only_site(site):
        return False

    return True


def get_pc_safe_site(site):
    # 白名单输出：只保留电脑端导入必要的字段。
    # 故意不复制 ext、jar、spider、parse、wallpaper、ads、notice 等字段。
    safe_fields = (
        "key",
        "name",
        "type",
        "api",
        "searchable",
        "quickSearch",
        "filterable",
        "filter",
        "categories",
        "playUrl",
        "timeout",
    )

    return {
        field: site[field]
        for field in safe_fields
        if field in site
    }


def get_pc_safe_live(live):
    if not isinstance(live, dict):
        return None

    url = str(live.get("url", "")).strip()

    if not is_http_url(url):
        return None

    # 直播只保留必要内容；不复制说明图片、广告、推荐信息等字段。
    safe_live = {
        "name": str(live.get("name", "直播源")).strip() or "直播源",
        "type": live.get("type", 0),
        "url": url,
    }

    if "ua" in live and isinstance(live["ua"], str):
        safe_live["ua"] = live["ua"]

    if "epg" in live and isinstance(live["epg"], str):
        safe_live["epg"] = live["epg"]

    if "logo" in live and isinstance(live["logo"], str):
        safe_live["logo"] = live["logo"]

    return safe_live


def main():
    if not SOURCE_FILE.exists():
        print(f"错误：找不到源文件：{SOURCE_FILE}")
        sys.exit(1)

    try:
        with SOURCE_FILE.open("r", encoding="utf-8-sig") as file:
            source_config = json.load(file)
    except json.JSONDecodeError as error:
        print(f"错误：tvbox-merged.json 不是有效 JSON：{error}")
        sys.exit(1)

    if not isinstance(source_config, dict):
        print("错误：tvbox-merged.json 的顶层结构必须是 JSON 对象。")
        sys.exit(1)

    original_sites = source_config.get("sites", [])
    original_lives = source_config.get("lives", [])

    if not isinstance(original_sites, list):
        original_sites = []

    if not isinstance(original_lives, list):
        original_lives = []

    pc_sites = []
    used_sites = set()
    filtered_notice_count = 0
    filtered_android_count = 0
    filtered_other_count = 0

    for site in original_sites:
        if not isinstance(site, dict):
            filtered_other_count += 1
            continue

        if is_notice_or_ad_site(site):
            filtered_notice_count += 1
            continue

        if is_android_only_site(site):
            filtered_android_count += 1
            continue

        if not is_pc_compatible_site(site):
            filtered_other_count += 1
            continue

        safe_site = get_pc_safe_site(site)

        site_key = str(safe_site.get("key", "")).strip()
        site_api = str(safe_site.get("api", "")).strip()

        if not site_key or not site_api:
            filtered_other_count += 1
            continue

        unique_id = (site_key, site_api)

        if unique_id in used_sites:
            continue

        used_sites.add(unique_id)
        pc_sites.append(safe_site)

    pc_lives = []

    for live in original_lives:
        safe_live = get_pc_safe_live(live)

        if safe_live is not None:
            pc_lives.append(safe_live)

    # 从零创建最终文件；绝不复制完整电视端配置，
    # 因此 ads、notice、wallpaper、spider、parse、二维码说明均不会进入 pc.json。
    pc_config = {
        "sites": pc_sites
    }

    if pc_lives:
        pc_config["lives"] = pc_lives

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(pc_config, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"已生成：{OUTPUT_FILE.name}")
    print(f"原始点播源：{len(original_sites)} 个")
    print(f"电脑端保留点播源：{len(pc_sites)} 个")
    print(f"删除说明/广告源：{filtered_notice_count} 个")
    print(f"删除 Android 专用源：{filtered_android_count} 个")
    print(f"删除其他不兼容源：{filtered_other_count} 个")
    print(f"原始直播源：{len(original_lives)} 个")
    print(f"电脑端保留直播源：{len(pc_lives)} 个")


if __name__ == "__main__":
    main()
