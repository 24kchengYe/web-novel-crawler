#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全量爬取驱动器 —— 遍历指定站点的所有分类，批量下载

用法:
  python -m scraper.crawl_all --site quanben --max-per-cat 200 --pages 10
  python -m scraper.crawl_all --site biquge --max-per-cat 100 --pages 5
  python -m scraper.crawl_all --site quanben --categories 玄幻,悬疑
"""

import os
import sys
import json
import time
import argparse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Windows UTF-8
os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def get_scraper(site_name, output=None):
    """根据站点名返回爬虫实例和分类映射"""
    if site_name == "quanben":
        from scraper.sites.quanben import QuanbenScraper, CATEGORY_MAP
        return QuanbenScraper(output_base=output), CATEGORY_MAP
    elif site_name == "biquge":
        from scraper.sites.biquge import BiqugeScraper
        return BiqugeScraper(output_base=output), BiqugeScraper.CATEGORY_MAP
    elif site_name == "69shu":
        from scraper.sites.shu69 import Shu69Scraper
        return Shu69Scraper(output_base=output), getattr(Shu69Scraper, 'CATEGORY_MAP', {})
    elif site_name == "dingdian":
        from scraper.sites.dingdian import DingdianScraper
        return DingdianScraper(output_base=output), getattr(DingdianScraper, 'CATEGORY_MAP', {})
    else:
        print(f"未知站点: {site_name}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="全量爬取驱动器")
    parser.add_argument("--site", required=True, choices=["quanben", "biquge", "69shu", "dingdian"])
    parser.add_argument("--max-per-cat", type=int, default=200, help="每个分类最多下载多少本")
    parser.add_argument("--pages", type=int, default=10, help="每个分类最多翻几页书单")
    parser.add_argument("--categories", type=str, default=None, help="逗号分隔的分类名，不指定则全部")
    parser.add_argument("--output", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    scraper, category_map = get_scraper(args.site, args.output)
    all_categories = list(category_map.keys())

    if args.categories:
        categories = [c.strip() for c in args.categories.split(",")]
    else:
        categories = all_categories

    print(f"{'='*60}", flush=True)
    print(f"全量爬取: {args.site}", flush=True)
    print(f"  站点: {scraper.BASE_URL}", flush=True)
    print(f"  分类: {', '.join(categories)}", flush=True)
    print(f"  每类最多: {args.max_per_cat} 本", flush=True)
    print(f"  书单页数: {args.pages}", flush=True)
    print(f"  输出: {scraper.output_base}", flush=True)
    print(f"{'='*60}", flush=True)

    start_time = time.time()
    total_books = 0
    total_downloaded = 0
    cat_stats = {}

    for cat in categories:
        print(f"\n{'#'*60}", flush=True)
        print(f"# 分类: {cat}", flush=True)
        print(f"{'#'*60}", flush=True)

        # 1. 获取书单
        books = scraper.get_book_list(category=cat, max_pages=args.pages)
        total_books += len(books)

        if not books:
            print(f"  [{args.site}] {cat}: 无书籍", flush=True)
            cat_stats[cat] = {"found": 0, "downloaded": 0}
            continue

        # 2. 去除已下载的
        existing_dirs = set()
        if os.path.isdir(scraper.output_base):
            existing_dirs = set(os.listdir(scraper.output_base))

        pending = []
        for book in books:
            safe = scraper.sanitize_filename(f"{book['name']}_{book.get('author', '未知')}")
            if safe not in existing_dirs:
                pending.append(book)

        pending = pending[:args.max_per_cat]
        print(f"  [{args.site}] {cat}: 找到 {len(books)} 本, 待下载 {len(pending)} 本", flush=True)

        # 3. 逐本下载
        cat_downloaded = 0
        for i, book in enumerate(pending, 1):
            print(f"\n  [{cat} {i}/{len(pending)}] {book['name']}", flush=True)
            try:
                result = scraper.download_book(
                    book["book_id"],
                    extra_meta={"category": cat},
                )
                if result:
                    cat_downloaded += 1
                    total_downloaded += 1
            except Exception as e:
                print(f"    ERROR: {e}", flush=True)

            # 定期输出进度
            if i % 10 == 0:
                elapsed = time.time() - start_time
                print(f"  [PROGRESS] {args.site} | {cat} {i}/{len(pending)} | "
                      f"总下载 {total_downloaded} | {elapsed/60:.1f}min", flush=True)

        cat_stats[cat] = {"found": len(books), "downloaded": cat_downloaded}
        print(f"\n  [{args.site}] {cat} 完成: {cat_downloaded}/{len(pending)}", flush=True)

    # 最终汇总
    elapsed = time.time() - start_time
    print(f"\n{'='*60}", flush=True)
    print(f"全量爬取完成: {args.site}", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"  总发现: {total_books} 本", flush=True)
    print(f"  总下载: {total_downloaded} 本", flush=True)
    print(f"  耗时: {elapsed/60:.1f} 分钟", flush=True)
    print(f"\n  分类统计:", flush=True)
    for cat, st in cat_stats.items():
        print(f"    {cat:10s}  发现 {st['found']:4d}, 下载 {st['downloaded']:4d}", flush=True)

    # 保存报告
    report_path = os.path.join(scraper.output_base, "crawl_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "site": args.site,
            "base_url": scraper.BASE_URL,
            "total_found": total_books,
            "total_downloaded": total_downloaded,
            "elapsed_minutes": round(elapsed / 60, 1),
            "categories": cat_stats,
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
