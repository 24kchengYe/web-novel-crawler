#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基于 so-novel WebUI API 的批量小说下载器

前置条件：so-novel WebUI 已在 localhost:7765 运行
启动方式：cd tools/SoNovel && ./sonovel.exe

用法:
  # 从 discovered_books.json 全量下载
  python -m scraper.sonovel_batch --from-discovered --max 500

  # 按分类优先下载
  python -m scraper.sonovel_batch --from-discovered --categories 灵异,科幻 --max 2000

  # 查看进度
  python -m scraper.sonovel_batch --status
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.parse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISCOVERED_PATH = os.path.join(PROJECT_DIR, "discovered_books.json")
DOWNLOAD_LOG_PATH = os.path.join(PROJECT_DIR, "sonovel_download_log.json")
SONOVEL_API = "http://localhost:7765"
SONOVEL_DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "tools", "SoNovel", "downloads")

os.environ["PYTHONUNBUFFERED"] = "1"
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def api_get(path, timeout=30):
    url = f"{SONOVEL_API}{path}"
    try:
        return json.loads(urllib.request.urlopen(url, timeout=timeout).read().decode("utf-8", errors="replace"))
    except Exception as e:
        return None


def search(keyword):
    kw = urllib.parse.quote(keyword)
    data = api_get(f"/search/aggregated?kw={kw}", timeout=30)
    if data and isinstance(data, dict):
        return data.get("data", [])
    return []


def download(item, fmt="txt"):
    params = urllib.parse.urlencode(item)
    try:
        urllib.request.urlopen(
            f"{SONOVEL_API}/book-fetch?{params}&format={fmt}", timeout=600
        ).read()
        return True
    except Exception:
        return False


def load_download_log():
    if os.path.exists(DOWNLOAD_LOG_PATH):
        with open(DOWNLOAD_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"downloaded": {}, "failed": {}}


def save_download_log(log):
    with open(DOWNLOAD_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="so-novel 批量下载器")
    parser.add_argument("--from-discovered", action="store_true",
                        help="从 discovered_books.json 全量下载")
    parser.add_argument("--categories", type=str, default=None,
                        help="只下载指定分类（逗号分隔）")
    parser.add_argument("--max", type=int, default=None,
                        help="最多下载多少本")
    parser.add_argument("--status", action="store_true",
                        help="查看下载进度")
    args = parser.parse_args()

    if args.status:
        log = load_download_log()
        downloaded = len(log.get("downloaded", {}))
        failed = len(log.get("failed", {}))
        # 统计下载目录
        txt_count = 0
        txt_size = 0
        if os.path.isdir(SONOVEL_DOWNLOAD_DIR):
            for f in os.listdir(SONOVEL_DOWNLOAD_DIR):
                if f.endswith(".txt"):
                    txt_count += 1
                    txt_size += os.path.getsize(os.path.join(SONOVEL_DOWNLOAD_DIR, f))
        print(f"下载进度:")
        print(f"  成功: {downloaded}")
        print(f"  失败: {failed}")
        print(f"  TXT 文件: {txt_count} 个, {txt_size/1e9:.2f} GB")
        return

    # 检查 so-novel
    if api_get("/config", timeout=5) is None:
        print("so-novel WebUI 未运行! 请先启动:")
        print("  cd tools/SoNovel && ./sonovel.exe")
        sys.exit(1)

    if not args.from_discovered:
        parser.print_help()
        return

    # 加载书目
    with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    all_books = data.get("books", [])

    # 分类过滤
    if args.categories:
        cats = set(c.strip() for c in args.categories.split(","))
        all_books = [b for b in all_books if b.get("category", "") in cats]

    # 排除已下载/已失败
    log = load_download_log()
    done_names = set(log.get("downloaded", {}).keys())
    # 也排除 data/ 中已有的
    data_dir = os.path.join(PROJECT_DIR, "data")
    if os.path.isdir(data_dir):
        for d in os.listdir(data_dir):
            done_names.add(d.split("_")[0])
    # 排除 downloads/ 中已有的
    if os.path.isdir(SONOVEL_DOWNLOAD_DIR):
        for f in os.listdir(SONOVEL_DOWNLOAD_DIR):
            name = f.replace(".txt", "")
            if "(" in name:
                name = name.split("(")[0]
            done_names.add(name)

    pending = [b for b in all_books if b["name"] not in done_names]
    if args.max:
        pending = pending[:args.max]

    print(f"{'='*60}")
    print(f"so-novel 批量下载")
    print(f"  书目总量: {len(all_books)}")
    print(f"  已完成: {len(done_names)}")
    print(f"  待下载: {len(pending)}")
    if args.categories:
        print(f"  分类过滤: {args.categories}")
    print(f"{'='*60}")

    start_time = time.time()
    success = 0
    failed = 0

    for i, book in enumerate(pending, 1):
        name = book["name"]
        cat = book.get("category", "")
        print(f"[{i}/{len(pending)}] {name} ({cat})", flush=True)

        # 搜索
        results = search(name)
        if not results:
            print(f"  未找到", flush=True)
            log.setdefault("failed", {})[name] = {"reason": "not_found", "time": time.strftime("%H:%M:%S")}
            failed += 1
            time.sleep(0.3)
            continue

        # 选最佳结果
        best = None
        for r in results:
            if r.get("bookName", "") == name:
                best = r
                break
        if not best:
            best = results[0]

        # 下载
        t0 = time.time()
        ok = download(best)
        elapsed = time.time() - t0

        if ok:
            success += 1
            log.setdefault("downloaded", {})[name] = {
                "source": best.get("sourceName", ""),
                "source_id": best.get("sourceId", ""),
                "source_url": best.get("url", ""),
                "author": best.get("author", ""),
                "book_name": best.get("bookName", ""),
                "latest_chapter": best.get("latestChapter", ""),
                "category_from_source": best.get("category", ""),
                "category_discovered": cat,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "seconds": round(elapsed, 1),
                # 保留完整搜索结果供后续提取权重
                "raw_search_result": {k: v for k, v in best.items()
                                      if isinstance(v, (str, int, float))},
            }
            print(f"  OK ({elapsed:.1f}s) [{best.get('sourceName','')}]", flush=True)
        else:
            failed += 1
            log.setdefault("failed", {})[name] = {"reason": "download_error", "time": time.strftime("%H:%M:%S")}
            print(f"  FAILED", flush=True)

        # 每 10 本保存日志 + 输出进度
        if i % 10 == 0:
            save_download_log(log)
            total_elapsed = time.time() - start_time
            rate = success / total_elapsed * 3600 if total_elapsed > 0 else 0
            print(f"  [PROGRESS] {success} ok / {failed} fail / {i} total | "
                  f"{total_elapsed/60:.1f}min | {rate:.0f} 本/h", flush=True)

        time.sleep(0.2)

    save_download_log(log)
    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"完成!")
    print(f"  成功: {success}")
    print(f"  失败: {failed}")
    print(f"  耗时: {elapsed/60:.1f} 分钟")


if __name__ == "__main__":
    main()
