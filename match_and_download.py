#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
书单匹配 & 批量下载器
读取 booklist.json，在 qbxsw.com 上匹配书名，下载全文
"""

import os
import sys
import io
import re
import json
import time
import random
import urllib.request
import urllib.parse

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKLIST_PATH = os.path.join(BASE_DIR, 'booklist.json')
MATCH_CACHE_PATH = os.path.join(BASE_DIR, 'match_cache.json')
DATA_DIR = os.path.join(BASE_DIR, 'data')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
QBXSW_BASE = "https://www.qbxsw.com"


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            if attempt < retries - 1:
                time.sleep((attempt + 1) * 2 + random.random())
            else:
                return None


def load_match_cache():
    if os.path.exists(MATCH_CACHE_PATH):
        with open(MATCH_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_match_cache(cache):
    with open(MATCH_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def search_qbxsw(book_name, author=''):
    """
    在 qbxsw 上搜索书名，返回匹配的 book_id 或 None
    策略：
    1. POST 搜索
    2. 从搜索结果中匹配书名
    3. 如果有作者名，优先匹配书名+作者
    """
    # 方法1: POST 搜索
    search_url = QBXSW_BASE + "/search.html"
    data = urllib.parse.urlencode({'searchkey': book_name}).encode('utf-8')
    try:
        req = urllib.request.Request(search_url, data=data, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except:
        html = ''

    if html and '/du_' in html:
        # 提取搜索结果
        pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)

        # 精确匹配书名
        for qb_id, name in matches:
            if name.strip() == book_name:
                return qb_id

        # 模糊匹配
        for qb_id, name in matches:
            if book_name in name.strip() or name.strip() in book_name:
                return qb_id

    # 方法2: 从 shu_ 页面（书籍介绍页）搜索
    shu_url = QBXSW_BASE + f"/search.html?searchkey={urllib.parse.quote(book_name)}"
    html = fetch(shu_url)
    if html and '/du_' in html:
        pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)
        for qb_id, name in matches:
            if name.strip() == book_name:
                return qb_id
        for qb_id, name in matches:
            if book_name in name.strip() or name.strip() in book_name:
                return qb_id

    # 方法3: 尝试直接从分类页找
    # 暂时跳过，后面补充

    return None


def match_all_books():
    """
    批量匹配 booklist.json 中的书 → qbxsw book_id
    """
    with open(BOOKLIST_PATH, 'r', encoding='utf-8') as f:
        booklist = json.load(f)

    books = booklist['books']
    cache = load_match_cache()

    print(f"书单共 {len(books)} 本，已匹配 {len(cache)} 本")
    print(f"{'='*60}")

    matched = 0
    failed = 0
    skipped = 0

    for i, book in enumerate(books, 1):
        name = book['name']
        author = book.get('author', '')

        # 如果 booklist 里已经有 qbxsw_id（从 qbxsw 补充的书）
        if book.get('qbxsw_id'):
            cache[name] = {
                'qbxsw_id': book['qbxsw_id'],
                'author': author,
                'source': 'qbxsw_direct',
            }
            matched += 1
            continue

        # 检查缓存
        if name in cache:
            skipped += 1
            continue

        print(f"  [{i}/{len(books)}] 匹配: {name} / {author} ...", end=' ', flush=True)
        qb_id = search_qbxsw(name, author)

        if qb_id:
            cache[name] = {
                'qbxsw_id': qb_id,
                'author': author,
                'source': 'search',
            }
            matched += 1
            print(f"-> qb_{qb_id}")
        else:
            cache[name] = {
                'qbxsw_id': None,
                'author': author,
                'source': 'not_found',
            }
            failed += 1
            print("-> 未找到")

        save_match_cache(cache)
        time.sleep(random.uniform(0.5, 1.0))

    save_match_cache(cache)

    # 统计
    total_matched = sum(1 for v in cache.values() if v.get('qbxsw_id'))
    total_failed = sum(1 for v in cache.values() if not v.get('qbxsw_id'))

    print(f"\n{'='*60}")
    print(f"匹配完成:")
    print(f"  成功: {total_matched}")
    print(f"  未找到: {total_failed}")
    print(f"  缓存: {MATCH_CACHE_PATH}")

    return cache


def batch_download_from_booklist(max_books=None, skip_categories=None):
    """
    从 booklist + match_cache 批量下载
    """
    import novel_scraper as ns

    with open(BOOKLIST_PATH, 'r', encoding='utf-8') as f:
        booklist = json.load(f)

    cache = load_match_cache()

    # 构建下载任务
    tasks = []
    for book in booklist['books']:
        name = book['name']
        cat = book.get('category', '')

        if skip_categories and cat in skip_categories:
            continue

        # 获取 qbxsw_id
        qb_id = None
        if book.get('qbxsw_id'):
            qb_id = book['qbxsw_id']
        elif name in cache and cache[name].get('qbxsw_id'):
            qb_id = cache[name]['qbxsw_id']

        if qb_id:
            tasks.append({
                'qbxsw_id': qb_id,
                'name': name,
                'qidian_meta': book,
            })

    print(f"可下载任务: {len(tasks)} 本")
    if max_books:
        tasks = tasks[:max_books]
        print(f"限制为: {max_books} 本")

    # 检查已下载
    log_path = os.path.join(DATA_DIR, 'download_log.json')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            download_log = json.load(f)
    else:
        download_log = {}

    os.makedirs(DATA_DIR, exist_ok=True)

    downloaded = 0
    for i, task in enumerate(tasks, 1):
        qb_id = task['qbxsw_id']
        name = task['name']

        if qb_id in download_log:
            print(f"  [{i}/{len(tasks)}] 已下载: {name}, 跳过")
            continue

        print(f"\n  [{i}/{len(tasks)}] 下载: {name} (qb_id={qb_id})")
        result = ns.download_book(qb_id, output_base=DATA_DIR, qidian_meta=task.get('qidian_meta'))

        if result:
            download_log[qb_id] = {
                'name': name,
                'dir': result,
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            with open(log_path, 'w', encoding='utf-8') as f:
                json.dump(download_log, f, ensure_ascii=False, indent=2)
            downloaded += 1

    print(f"\n{'='*60}")
    print(f"批量下载完成: 本次下载 {downloaded} 本")
    print(f"累计已下载: {len(download_log)} 本")
    print(f"数据目录: {DATA_DIR}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='书单匹配 & 批量下载')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--match', action='store_true', help='匹配书单中的书 → qbxsw ID')
    group.add_argument('--download', action='store_true', help='批量下载已匹配的书')
    group.add_argument('--all', action='store_true', help='匹配 + 下载 一步到位')
    group.add_argument('--stats', action='store_true', help='查看当前书单和匹配状态')

    parser.add_argument('--max', type=int, default=None, help='最多下载几本')

    args = parser.parse_args()

    if args.match:
        match_all_books()
    elif args.download:
        batch_download_from_booklist(max_books=args.max)
    elif args.all:
        match_all_books()
        batch_download_from_booklist(max_books=args.max)
    elif args.stats:
        with open(BOOKLIST_PATH, 'r', encoding='utf-8') as f:
            bl = json.load(f)
        cache = load_match_cache()
        matched = sum(1 for v in cache.values() if v.get('qbxsw_id'))
        print(f"书单: {bl['total']} 本")
        print(f"已匹配: {matched} 本")

        log_path = os.path.join(DATA_DIR, 'download_log.json')
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                dl = json.load(f)
            print(f"已下载: {len(dl)} 本")
