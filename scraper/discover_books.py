#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
书目发现器 —— 从各站点分类页收集全量书目 URL

遍历各站点的所有分类 × 所有分页，提取书籍 URL 列表。
不下载正文，只收集书目。下载交给 so-novel。

输出: discovered_books.json（去重后的全量书目清单）

用法:
  python -m scraper.discover_books                    # 扫描所有可用站点
  python -m scraper.discover_books --site 22biqu      # 只扫一个站
  python -m scraper.discover_books --max-pages 20     # 每分类最多翻20页
"""

import os
import sys
import json
import re
import time
import random
import argparse
import urllib.request

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(PROJECT_DIR, "discovered_books.json")

os.environ["PYTHONUNBUFFERED"] = "1"
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def fetch(url, encoding="utf-8", timeout=15):
    try:
        req = urllib.request.Request(url, headers=_headers)
        return _opener.open(req, timeout=timeout).read().decode(encoding, errors="replace")
    except Exception:
        return None


# ============================================================
# 站点配置
# 每个站点定义：分类URL模式、书籍链接正则、分页模式
# ============================================================
SITES = {
    "22biqu": {
        "name": "笔趣阁22",
        "base": "https://www.22biqu.com",
        "categories": {
            "玄幻": "/fenlei/1_{page}.html",
            "武侠": "/fenlei/2_{page}.html",
            "都市": "/fenlei/3_{page}.html",
            "历史": "/fenlei/4_{page}.html",
            "网游": "/fenlei/5_{page}.html",
            "科幻": "/fenlei/6_{page}.html",
            "灵异": "/fenlei/7_{page}.html",
            "言情": "/fenlei/8_{page}.html",
        },
        # 通用模式：路径含数字，文字是中文书名
        "book_pattern": r'href="(/[^"]*\d+[^"]*)"[^>]*>([^<]{2,30})',
        "book_filter": True,  # 需要后处理过滤非书名链接
    },
    "wxsy": {
        "name": "顶点小说",
        "base": "https://www.wxsy.net",
        "categories": {
            "玄幻": "/sort/1/{page}.html",
            "穿越重生": "/sort/2/{page}.html",
            "都市": "/sort/3/{page}.html",
            "军史": "/sort/4/{page}.html",
            "网游竞技": "/sort/5/{page}.html",
            "科幻": "/sort/6/{page}.html",
            "灵异": "/sort/7/{page}.html",
            "言情": "/sort/8/{page}.html",
            "其他": "/sort/9/{page}.html",
        },
        "book_pattern": r'href="(/[^"]*\d+[^"]*)"[^>]*>([^<]{2,30})',
        "book_filter": True,
    },
    "shu009": {
        "name": "书林文学",
        "base": "http://www.shu009.com",
        "categories": {
            "玄幻": "/sort/1/{page}/",
            "仙侠": "/sort/2/{page}/",
            "都市": "/sort/3/{page}/",
            "历史": "/sort/4/{page}/",
            "网游": "/sort/5/{page}/",
            "科幻": "/sort/6/{page}/",
            "言情": "/sort/7/{page}/",
            "其他": "/sort/8/{page}/",
        },
        "book_pattern": r'href="(/book/\d+/)"[^>]*>([^<]{2,30})',
    },
    "biquge365": {
        "name": "笔趣阁365",
        "base": "https://www.biquge365.net",
        "categories": {
            "玄幻": "/sort/1_{page}/",
            "仙侠": "/sort/2_{page}/",
            "都市": "/sort/3_{page}/",
            "网游": "/sort/4_{page}/",
            "科幻": "/sort/5_{page}/",
            "言情": "/sort/6_{page}/",
            "其他": "/sort/7_{page}/",
        },
        "book_pattern": r'href="(/book/\d+/)"[^>]*>([^<]{2,30})',
    },
    "ranwen8": {
        "name": "燃文小说网",
        "base": "https://www.ranwen8.cc",
        "categories": {
            "玄幻": "/fenlei/1_{page}/",
            "仙侠": "/fenlei/2_{page}/",
            "都市": "/fenlei/3_{page}/",
            "历史": "/fenlei/4_{page}/",
            "网游": "/fenlei/5_{page}/",
            "科幻": "/fenlei/6_{page}/",
            "灵异": "/fenlei/7_{page}/",
            "言情": "/fenlei/8_{page}/",
            "军事": "/fenlei/9_{page}/",
        },
        "book_pattern": r'href="(/book/\d+/)"[^>]*>([^<]{2,30})',
    },
}


# 用于过滤非书名的导航文字
_NAV_KEYWORDS = re.compile(
    r"^(登录|注册|首页|排行|分类|设置|客服|下载|更多|玄幻|仙侠|都市|历史|科幻|言情|武侠|网游|军事|灵异|其他|完本|全部|最新|最热|用户|会员|反馈|搜索|关于|加入|收藏|帮助|联系|版权|声明|返回|上一页|下一页)$"
)


def _is_book_name(href, name):
    """判断一个链接是否是书籍（而不是导航/功能链接）"""
    name = name.strip()
    # 必须含至少2个汉字
    if len(re.findall(r"[\u4e00-\u9fff]", name)) < 2:
        return False
    # 排除纯导航词
    if _NAV_KEYWORDS.match(name):
        return False
    # 排除纯数字路径 (分页链接)
    if re.match(r"^/\d+/?$", href):
        return False
    # href 中应该有数字（书ID）
    if not re.search(r"\d", href):
        return False
    # 排除 css/js/img 等资源链接
    if re.search(r"\.(css|js|jpg|png|ico|xml)", href):
        return False
    return True


def discover_site(site_key, max_pages=30):
    """扫描一个站点的所有分类页，返回书目列表"""
    site = SITES[site_key]
    base = site["base"]
    book_pat = site["book_pattern"]
    need_filter = site.get("book_filter", False)
    all_books = {}  # url -> {name, category, source}

    for cat_name, path_template in site["categories"].items():
        print(f"  [{site['name']}] {cat_name}", end="", flush=True)
        cat_count = 0

        for page in range(1, max_pages + 1):
            path = path_template.format(page=page)
            url = base + path
            html = fetch(url)
            if not html:
                break

            matches = re.findall(book_pat, html)
            page_new = 0
            for href, name in matches:
                name = re.sub(r"<[^>]+>", "", name).strip()
                if not name or len(name) < 2:
                    continue
                # 智能过滤
                if need_filter and not _is_book_name(href, name):
                    continue
                full_url = base + href
                if full_url not in all_books:
                    all_books[full_url] = {
                        "name": name,
                        "url": full_url,
                        "category": cat_name,
                        "source": site["name"],
                        "source_key": site_key,
                    }
                    page_new += 1
                    cat_count += 1

            if page_new == 0:
                break

            time.sleep(random.uniform(0.2, 0.5))

        print(f" -> {cat_count} 本", flush=True)

    return list(all_books.values())


def main():
    parser = argparse.ArgumentParser(description="书目发现器")
    parser.add_argument("--site", type=str, default=None,
                        choices=list(SITES.keys()),
                        help="只扫描指定站点")
    parser.add_argument("--max-pages", type=int, default=30,
                        help="每分类最多翻几页 (默认 30)")
    parser.add_argument("--list-sites", action="store_true",
                        help="列出可用站点")
    args = parser.parse_args()

    if args.list_sites:
        for key, site in SITES.items():
            cats = ", ".join(site["categories"].keys())
            print(f"  {key:12s} {site['name']:10s} {site['base']}")
            print(f"               分类: {cats}")
        return

    sites_to_scan = [args.site] if args.site else list(SITES.keys())

    # 加载已有结果（增量扫描）
    existing = {}
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        for b in old_data.get("books", []):
            existing[b["url"]] = b

    print(f"{'='*60}")
    print(f"书目发现器")
    print(f"  站点: {', '.join(sites_to_scan)}")
    print(f"  每分类最多: {args.max_pages} 页")
    print(f"  已有书目: {len(existing)}")
    print(f"{'='*60}")

    start_time = time.time()
    new_count = 0

    for site_key in sites_to_scan:
        print(f"\n扫描: {SITES[site_key]['name']} ({SITES[site_key]['base']})", flush=True)
        books = discover_site(site_key, max_pages=args.max_pages)
        for b in books:
            if b["url"] not in existing:
                existing[b["url"]] = b
                new_count += 1
        print(f"  小计: {len(books)} 本 (新增 {new_count})", flush=True)

    # 按书名去重（不同站点可能有同一本书）
    by_name = {}
    for b in existing.values():
        name = b["name"]
        if name not in by_name:
            by_name[name] = b

    # 也排除已在 data/ 目录的书
    data_dir = os.path.join(PROJECT_DIR, "data")
    existing_names = set()
    if os.path.isdir(data_dir):
        for d in os.listdir(data_dir):
            existing_names.add(d.split("_")[0])

    new_books = {n: b for n, b in by_name.items() if n not in existing_names}

    # 统计
    cat_stats = {}
    source_stats = {}
    for b in by_name.values():
        cat = b.get("category", "未知")
        src = b.get("source", "未知")
        cat_stats[cat] = cat_stats.get(cat, 0) + 1
        source_stats[src] = source_stats.get(src, 0) + 1

    elapsed = time.time() - start_time

    # 保存
    output = {
        "total_unique_by_name": len(by_name),
        "total_unique_by_url": len(existing),
        "new_vs_existing_data": len(new_books),
        "already_in_data": len(existing_names),
        "by_category": dict(sorted(cat_stats.items(), key=lambda x: -x[1])),
        "by_source": dict(sorted(source_stats.items(), key=lambda x: -x[1])),
        "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed, 1),
        "books": sorted(existing.values(), key=lambda x: x["name"]),
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"扫描完成!")
    print(f"  总书目(按URL): {len(existing):,}")
    print(f"  总书目(按书名去重): {len(by_name):,}")
    print(f"  可新增(不在data/): {len(new_books):,}")
    print(f"  耗时: {elapsed:.1f}s")
    print(f"\n  分类分布:")
    for cat, cnt in sorted(cat_stats.items(), key=lambda x: -x[1]):
        print(f"    {cat:8s} {cnt:5d}")
    print(f"\n  站点分布:")
    for src, cnt in sorted(source_stats.items(), key=lambda x: -x[1]):
        print(f"    {src:12s} {cnt:5d}")
    print(f"\n  输出: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
