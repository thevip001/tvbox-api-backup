#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TVBox 接口检测和页面生成脚本（分离方案 A）

功能：
1. 扫描 tvbox/ 和 ry/ 目录
2. 检测 JSON 合法性和格式
3. tvbox/*.json: 只有包含 sites 字段的才加入 multiline.txt
4. ry/*.json: 作为本地包展示，不纳入 TVBox 多仓
5. 生成分类网页（TVBox配置、本地包、直播源）
6. 支持搜索、复制、实时检测状态

使用：
  python3 python/interface_validator.py [--debug]
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import hashlib


class InterfaceValidator:
    """接口检测器"""

    def __init__(self, debug=False):
        self.debug = debug
        self.repo_root = Path.cwd()
        self.tvbox_dir = self.repo_root / "tvbox"
        self.ry_dir = self.repo_root / "ry"
        self.results = {
            "tvbox_valid": [],      # 合法的 TVBox 配置
            "tvbox_invalid": [],    # 格式错误或无 sites 的 TVBox 配置
            "ry_valid": [],         # 本地包
            "lives": [],            # 直播源
            "timestamp": datetime.now().isoformat(),
            "stats": {}
        }

    def log(self, msg, level="INFO"):
        """日志输出"""
        if level == "DEBUG" and not self.debug:
            return
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix} {msg}")

    def validate_json(self, file_path: Path) -> Tuple[bool, Optional[dict], str]:
        """验证 JSON 文件合法性"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return True, data, "valid"
        except json.JSONDecodeError as e:
            return False, None, f"JSON 语法错误: {str(e)[:50]}"
        except Exception as e:
            return False, None, f"读取失败: {str(e)[:50]}"

    def check_tvbox_config(self, file_path: Path, data: dict) -> Tuple[bool, str, List]:
        """检查 TVBox 配置格式
        
        合法条件：
        1. 是 dict 类型
        2. 包含 sites 字段（至少一个有效 site）
        3. sites 是数组
        """
        if not isinstance(data, dict):
            return False, "根元素不是对象", []

        if "sites" not in data:
            return False, "缺少 sites 字段", []

        sites = data.get("sites", [])
        if not isinstance(sites, list):
            return False, "sites 不是数组", []

        if len(sites) == 0:
            return False, "sites 数组为空", []

        # 统计 sites 中的关键字段
        site_stats = {
            "total": len(sites),
            "with_type3": sum(1 for s in sites if isinstance(s, dict) and s.get("type") == 3),
            "with_jar": sum(1 for s in sites if isinstance(s, dict) and "jar" in s),
        }

        return True, "valid", site_stats

    def check_ry_config(self, file_path: Path, data: dict) -> Tuple[bool, str]:
        """检查本地包格式
        
        标准格式：
        [
          {
            "name": "分类",
            "list": [
              { "name": "...", "url": "...", "icon": "...", "version": "..." }
            ]
          }
        ]
        """
        if not isinstance(data, list):
            return False, "根元素不是数组"

        if len(data) == 0:
            return False, "数组为空"

        for category in data:
            if not isinstance(category, dict):
                return False, "分类元素不是对象"
            if "name" not in category or "list" not in category:
                return False, "缺少 name 或 list 字段"
            if not isinstance(category.get("list"), list):
                return False, "list 不是数组"

        return True, "valid"

    def extract_lives(self, data: dict) -> List[dict]:
        """从 TVBox 配置中提取直播源"""
        lives = []
        if isinstance(data, dict) and "lives" in data:
            live_array = data.get("lives", [])
            if isinstance(live_array, list):
                for live in live_array:
                    if isinstance(live, dict) and "name" in live and "url" in live:
                        lives.append({
                            "name": live.get("name", "Unknown"),
                            "url": live.get("url", ""),
                            "type": live.get("type", 0)
                        })
        return lives

    def get_file_info(self, file_path: Path) -> dict:
        """获取文件信息"""
        stat = file_path.stat()
        return {
            "filename": file_path.name,
            "path": str(file_path.relative_to(self.repo_root)),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "raw_url": self._build_raw_url(file_path)
        }

    def _build_raw_url(self, file_path: Path) -> str:
        """构建原始文件 GitHub Raw URL"""
        rel_path = file_path.relative_to(self.repo_root)
        return f"https://raw.githubusercontent.com/thevip001/tvbox-api-backup/feature/api-interface-pages/{rel_path}"

    def scan_tvbox(self):
        """扫描 tvbox/ 目录"""
        self.log(f"扫描 {self.tvbox_dir}...")

        if not self.tvbox_dir.exists():
            self.log(f"目录不存在: {self.tvbox_dir}", "WARN")
            return

        for json_file in sorted(self.tvbox_dir.glob("*.json")):
            # 跳过内部产物文件
            if json_file.name.startswith("_"):
                self.log(f"跳过内部文件: {json_file.name}", "DEBUG")
                continue

            self.log(f"检查 {json_file.name}", "DEBUG")
            valid, data, error = self.validate_json(json_file)

            if not valid:
                self.results["tvbox_invalid"].append({
                    **self.get_file_info(json_file),
                    "reason": error
                })
                self.log(f"  ✗ {json_file.name}: {error}", "WARN")
                continue

            # 检查 TVBox 格式
            is_valid, msg, site_stats = self.check_tvbox_config(json_file, data)

            if is_valid:
                entry = {
                    **self.get_file_info(json_file),
                    "status": "valid",
                    "sites_count": site_stats["total"],
                    "type3_count": site_stats["with_type3"],
                    "jar_count": site_stats["with_jar"],
                    "has_spider": "spider" in data,
                    "has_lives": "lives" in data and len(data.get("lives", [])) > 0
                }
                self.results["tvbox_valid"].append(entry)
                self.log(f"  ✓ {json_file.name} ({site_stats['total']} sites)")

                # 提取直播源
                lives = self.extract_lives(data)
                if lives:
                    for live in lives:
                        self.results["lives"].append({
                            "name": live["name"],
                            "url": live["url"],
                            "source": json_file.name,
                            "type": live.get("type", 0)
                        })
            else:
                self.results["tvbox_invalid"].append({
                    **self.get_file_info(json_file),
                    "reason": msg
                })
                self.log(f"  ✗ {json_file.name}: {msg}", "WARN")

    def scan_ry(self):
        """扫描 ry/ 目录"""
        self.log(f"扫描 {self.ry_dir}...")

        if not self.ry_dir.exists():
            self.log(f"目录不存在: {self.ry_dir}", "WARN")
            return

        for json_file in sorted(self.ry_dir.glob("*.json")):
            # 跳过内部产物文件
            if json_file.name.startswith("_"):
                self.log(f"跳过内部文件: {json_file.name}", "DEBUG")
                continue

            self.log(f"检查 {json_file.name}", "DEBUG")
            valid, data, error = self.validate_json(json_file)

            if not valid:
                self.log(f"  ✗ {json_file.name}: {error}", "WARN")
                continue

            # 检查本地包格式
            is_valid, msg = self.check_ry_config(json_file, data)

            if is_valid:
                # 计算包内项目数
                item_count = sum(len(cat.get("list", [])) for cat in data)
                entry = {
                    **self.get_file_info(json_file),
                    "status": "valid",
                    "categories": len(data),
                    "items": item_count,
                    "type": "local_package"
                }
                self.results["ry_valid"].append(entry)
                self.log(f"  ✓ {json_file.name} ({len(data)} 分类，{item_count} 项)")
            else:
                self.log(f"  ✗ {json_file.name}: {msg}", "WARN")

    def generate_multiline_txt(self, output_path: Path = None):
        """生成 multiline.txt
        
        仅收录可以直接作为 TVBox 配置的 tvbox/*.json
        （合法 JSON + 包含 sites 字段）
        """
        if output_path is None:
            output_path = self.repo_root / "multiline.txt"

        lines = []
        for item in self.results["tvbox_valid"]:
            lines.append(item["raw_url"])

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        self.log(f"生成 multiline.txt: {len(lines)} 条配置")
        return output_path, len(lines)

    def generate_html_page(self, output_path: Path = None):
        """生成静态网页"""
        if output_path is None:
            output_path = self.repo_root / "api-list.html"

        tvbox_items = self.results["tvbox_valid"]
        ry_items = self.results["ry_valid"]
        live_items = self.results["lives"]

        html = self._build_html(tvbox_items, ry_items, live_items)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        self.log(f"生成网页: {output_path}")
        return output_path

    def _build_html(self, tvbox_items, ry_items, live_items) -> str:
        """构建 HTML 内容"""
        tvbox_html = self._render_tvbox_section(tvbox_items)
        ry_html = self._render_ry_section(ry_items)
        live_html = self._render_live_section(live_items)

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TVBox 接口导航 - 分类汇总</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        
        header {{
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }}
        
        header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        header p {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .search-box {{
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        
        .search-box input {{
            width: 100%;
            padding: 12px 20px;
            font-size: 1em;
            border: 2px solid #667eea;
            border-radius: 5px;
            transition: all 0.3s;
        }}
        
        .search-box input:focus {{
            outline: none;
            border-color: #764ba2;
            box-shadow: 0 0 10px rgba(118, 75, 162, 0.3);
        }}
        
        .tabs {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        
        .tab-btn {{
            padding: 12px 25px;
            border: none;
            background: rgba(255, 255, 255, 0.2);
            color: white;
            cursor: pointer;
            border-radius: 5px;
            font-size: 1em;
            font-weight: 600;
            transition: all 0.3s;
        }}
        
        .tab-btn:hover {{
            background: rgba(255, 255, 255, 0.3);
        }}
        
        .tab-btn.active {{
            background: white;
            color: #667eea;
        }}
        
        .section {{
            display: none;
            animation: fadeIn 0.3s;
        }}
        
        .section.active {{
            display: block;
        }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        
        .items-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
        }}
        
        .item-card {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: all 0.3s;
            cursor: pointer;
        }}
        
        .item-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0,0,0,0.15);
        }}
        
        .item-card h3 {{
            color: #333;
            margin-bottom: 10px;
            word-break: break-all;
        }}
        
        .item-meta {{
            font-size: 0.9em;
            color: #666;
            margin: 10px 0;
            word-break: break-all;
        }}
        
        .item-meta strong {{
            color: #333;
        }}
        
        .status-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 3px;
            font-size: 0.85em;
            font-weight: 600;
            margin: 5px 0;
        }}
        
        .status-valid {{
            background: #d4edda;
            color: #155724;
        }}
        
        .status-invalid {{
            background: #f8d7da;
            color: #721c24;
        }}
        
        .status-warning {{
            background: #fff3cd;
            color: #856404;
        }}
        
        .action-buttons {{
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }}
        
        .btn {{
            flex: 1;
            padding: 8px 12px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.9em;
            font-weight: 600;
            transition: all 0.3s;
        }}
        
        .btn-copy {{
            background: #667eea;
            color: white;
        }}
        
        .btn-copy:hover {{
            background: #5568d3;
        }}
        
        .btn-copy.copied {{
            background: #28a745;
        }}
        
        .btn-open {{
            background: #f0f0f0;
            color: #333;
        }}
        
        .btn-open:hover {{
            background: #e0e0e0;
        }}
        
        .stats {{
            background: rgba(255, 255, 255, 0.1);
            color: white;
            padding: 15px 20px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-size: 0.95em;
        }}
        
        .stats strong {{
            color: #ffd700;
        }}
        
        .hidden {{
            display: none;
        }}
        
        footer {{
            text-align: center;
            color: white;
            margin-top: 40px;
            padding: 20px;
            opacity: 0.8;
            font-size: 0.9em;
        }}
        
        .no-results {{
            text-align: center;
            padding: 40px 20px;
            color: #999;
        }}
        
        .info-box {{
            background: rgba(255, 255, 255, 0.95);
            border-left: 4px solid #667eea;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            font-size: 0.9em;
            color: #333;
        }}
        
        .info-box h4 {{
            color: #667eea;
            margin-bottom: 8px;
        }}
        
        code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "Monaco", "Menlo", "Consolas", monospace;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎬 TVBox 接口导航</h1>
            <p>分类汇总 · TVBox配置 · 本地包 · 直播源</p>
        </header>
        
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="搜索配置名称、URL 或本地包...">
        </div>
        
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('tvbox')">TVBox 配置</button>
            <button class="tab-btn" onclick="switchTab('ry')">本地包</button>
            <button class="tab-btn" onclick="switchTab('live')">直播源</button>
            <button class="tab-btn" onclick="switchTab('stats')">统计信息</button>
        </div>
        
        <div id="tvbox" class="section active">
            <div class="info-box">
                <h4>ℹ️ 使用说明</h4>
                <p>以下 TVBox 配置可直接粘贴到 TVBox 客户端。<strong>仅包含包含 sites 字段的合法配置</strong>。</p>
                <p>多仓配置访问：<code>https://raw.githubusercontent.com/thevip001/tvbox-api-backup/feature/api-interface-pages/multiline.txt</code></p>
            </div>
            {tvbox_html}
        </div>
        
        <div id="ry" class="section">
            <div class="info-box">
                <h4>ℹ️ 本地包说明</h4>
                <p>以下为本地包/下载资源配置，<strong>不支持直接作为 TVBox sites 配置使用</strong>。可在 TVBox 中作为"下载资源源"导入。</p>
            </div>
            {ry_html}
        </div>
        
        <div id="live" class="section">
            <div class="info-box">
                <h4>ℹ️ 直播源说明</h4>
                <p>以下为从 TVBox 配置中提取的直播源列表。来源于各个 TVBox 接口的 <code>lives</code> 字段。</p>
            </div>
            {live_html}
        </div>
        
        <div id="stats" class="section">
            <div class="stats-content">
                <h3 style="color: white; margin-bottom: 20px;">📊 统计信息</h3>
                <div class="stats">
                    <p>📅 更新时间: <strong>{self.results['timestamp']}</strong></p>
                    <p>✅ TVBox 配置（有效）: <strong>{len(tvbox_items)}</strong></p>
                    <p>❌ TVBox 配置（无效）: <strong>{len(self.results['tvbox_invalid'])}</strong></p>
                    <p>📦 本地包: <strong>{len(ry_items)}</strong></p>
                    <p>📡 直播源: <strong>{len(live_items)}</strong></p>
                </div>
                
                <h4 style="color: white; margin-top: 30px; margin-bottom: 15px;">⚠️ 无效配置列表</h4>
                {self._render_invalid_section()}
            </div>
        </div>
        
        <footer>
            <p>TVBox 接口导航 | 自动生成于 {self.results['timestamp']}</p>
            <p>GitHub: <a href="https://github.com/thevip001/tvbox-api-backup" style="color: white;">thevip001/tvbox-api-backup</a></p>
        </footer>
    </div>
    
    <script>
        const searchInput = document.getElementById('searchInput');
        
        searchInput.addEventListener('input', function() {{
            const query = this.value.toLowerCase();
            const items = document.querySelectorAll('.item-card');
            
            items.forEach(item => {{
                const text = item.textContent.toLowerCase();
                item.classList.toggle('hidden', !text.includes(query));
            }});
        }});
        
        function switchTab(tabName) {{
            // 隐藏所有 section
            document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            
            // 显示选中 section
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }}
        
        function copyToClipboard(url, btn) {{
            navigator.clipboard.writeText(url).then(() => {{
                const oldText = btn.textContent;
                btn.textContent = '✅ 已复制';
                btn.classList.add('copied');
                setTimeout(() => {{
                    btn.textContent = oldText;
                    btn.classList.remove('copied');
                }}, 2000);
            }});
        }}
        
        function openInNewTab(url) {{
            window.open(url, '_blank');
        }}
    </script>
</body>
</html>
"""

    def _render_tvbox_section(self, items) -> str:
        """渲染 TVBox 配置卡片"""
        if not items:
            return '<div class="no-results">未找到有效的 TVBox 配置</div>'

        html_items = []
        for item in items:
            warnings = []
            if item.get("type3_count", 0) > 0:
                warnings.append(f'⚠️ 包含 {item["type3_count"]} 个 type=3 插件')
            if item.get("jar_count", 0) > 0:
                warnings.append(f'⚠️ 包含 {item["jar_count"]} 个 jar 引用')

            warning_html = ''.join([f'<div class="status-badge status-warning">{w}</div>' for w in warnings])

            html_items.append(f"""
            <div class="item-card" data-name="{item['filename']}">
                <h3>📋 {item['filename'].replace('.json', '')}</h3>
                <div class="item-meta">
                    <div><strong>Sites:</strong> {item.get('sites_count', 0)}</div>
                    <div><strong>文件:</strong> {item['filename']}</div>
                    <div><strong>大小:</strong> {item['size']} 字节</div>
                    <div><strong>更新:</strong> {item['mtime'][:10]}</div>
                </div>
                <div class="status-badge status-valid">✓ 合法配置</div>
                {warning_html}
                <div class="action-buttons">
                    <button class="btn btn-copy" onclick="copyToClipboard('{item['raw_url']}', this)">
                        📋 复制链接
                    </button>
                </div>
            </div>
            """)

        return f'<div class="items-grid">{"".join(html_items)}</div>'

    def _render_ry_section(self, items) -> str:
        """渲染本地包卡片"""
        if not items:
            return '<div class="no-results">未找到本地包</div>'

        html_items = []
        for item in items:
            html_items.append(f"""
            <div class="item-card" data-name="{item['filename']}">
                <h3>📦 {item['filename'].replace('.json', '')}</h3>
                <div class="item-meta">
                    <div><strong>类型:</strong> 本地包（LocalMedia）</div>
                    <div><strong>分类数:</strong> {item.get('categories', 0)}</div>
                    <div><strong>项目数:</strong> {item.get('items', 0)}</div>
                    <div><strong>文件:</strong> {item['filename']}</div>
                    <div><strong>大小:</strong> {item['size']} 字节</div>
                    <div><strong>更新:</strong> {item['mtime'][:10]}</div>
                </div>
                <div class="status-badge status-valid">✓ 合法本地包</div>
                <p style="font-size: 0.85em; color: #999; margin-top: 10px;">
                    💡 此文件作为本地包使用，不纳入 TVBox 多仓配置
                </p>
                <div class="action-buttons">
                    <button class="btn btn-copy" onclick="copyToClipboard('{item['raw_url']}', this)">
                        📋 复制链接
                    </button>
                </div>
            </div>
            """)

        return f'<div class="items-grid">{"".join(html_items)}</div>'

    def _render_live_section(self, items) -> str:
        """渲染直播源卡片"""
        if not items:
            return '<div class="no-results">未找到直播源</div>'

        html_items = []
        for item in items:
            html_items.append(f"""
            <div class="item-card" data-name="{item['name']}">
                <h3>📡 {item['name']}</h3>
                <div class="item-meta">
                    <div><strong>来源:</strong> {item['source']}</div>
                    <div><strong>类型:</strong> {item.get('type', 0)}</div>
                    <div><strong>URL:</strong></div>
                    <div style="font-size: 0.8em; word-break: break-all; background: #f5f5f5; padding: 8px; border-radius: 3px; margin-top: 5px;">
                        {item['url'][:100]}{'...' if len(item['url']) > 100 else ''}
                    </div>
                </div>
                <div class="action-buttons">
                    <button class="btn btn-copy" onclick="copyToClipboard('{item['url'].replace("'", "\\'")}', this)">
                        📋 复制URL
                    </button>
                </div>
            </div>
            """)

        return f'<div class="items-grid">{"".join(html_items)}</div>'

    def _render_invalid_section(self) -> str:
        """渲染无效配置列表"""
        if not self.results["tvbox_invalid"]:
            return '<div class="stats" style="background: rgba(212, 237, 218, 0.2); color: #155724;"><strong>✓ 所有 TVBox 配置均合法</strong></div>'

        html_items = []
        for item in self.results["tvbox_invalid"]:
            html_items.append(f"""
            <div class="stats" style="background: rgba(248, 215, 218, 0.2); color: #721c24; margin-bottom: 10px;">
                <div><strong>❌ {item['filename']}</strong></div>
                <div>原因: {item['reason']}</div>
            </div>
            """)

        return "".join(html_items)

    def generate_summary_json(self, output_path: Path = None):
        """生成检测摘要 JSON"""
        if output_path is None:
            output_path = self.repo_root / "interface_check_summary.json"

        summary = {
            "timestamp": self.results["timestamp"],
            "tvbox": {
                "valid": len(self.results["tvbox_valid"]),
                "invalid": len(self.results["tvbox_invalid"]),
                "items": self.results["tvbox_valid"]
            },
            "ry": {
                "valid": len(self.results["ry_valid"]),
                "items": self.results["ry_valid"]
            },
            "lives": {
                "total": len(self.results["lives"]),
                "items": self.results["lives"]
            }
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        self.log(f"生成摘要: {output_path}")
        return output_path

    def run(self):
        """执行完整检测流程"""
        self.log("=" * 50)
        self.log("TVBox 接口检测 - 开始")
        self.log("=" * 50)

        self.scan_tvbox()
        self.scan_ry()

        self.log("")
        self.log("=" * 50)
        self.log("生成产物")
        self.log("=" * 50)

        multiline_path, count = self.generate_multiline_txt()
        html_path = self.generate_html_page()
        summary_path = self.generate_summary_json()

        self.log("")
        self.log("=" * 50)
        self.log("检测完成")
        self.log("=" * 50)
        self.log(f"TVBox 配置（有效）: {len(self.results['tvbox_valid'])}")
        self.log(f"TVBox 配置（无效）: {len(self.results['tvbox_invalid'])}")
        self.log(f"本地包: {len(self.results['ry_valid'])}")
        self.log(f"直播源: {len(self.results['lives'])}")
        self.log(f"multiline.txt: {count} 条")
        self.log(f"网页: {html_path}")
        self.log(f"摘要: {summary_path}")

        return {
            "success": True,
            "multiline": multiline_path,
            "html": html_path,
            "summary": summary_path,
            "stats": {
                "tvbox_valid": len(self.results["tvbox_valid"]),
                "tvbox_invalid": len(self.results["tvbox_invalid"]),
                "ry_valid": len(self.results["ry_valid"]),
                "lives": len(self.results["lives"])
            }
        }


if __name__ == "__main__":
    debug = "--debug" in sys.argv
    validator = InterfaceValidator(debug=debug)
    result = validator.run()
    sys.exit(0 if result["success"] else 1)
