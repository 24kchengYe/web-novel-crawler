#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
补充书单：从 qbxsw.com 各分类排行榜补充书目
合并到现有 booklist.json 中
"""

import os
import sys
import io
import re
import json
import time
import random
import urllib.request

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKLIST_PATH = os.path.join(BASE_DIR, 'booklist.json')
QBXSW_BASE = "https://www.qbxsw.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


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
                print(f"  [失败] {url} -> {e}")
                return None


def get_qbxsw_category_books(category_path, max_pages=3):
    """从 qbxsw 分类页面获取书籍列表"""
    books = []
    seen = set()

    for page in range(1, max_pages + 1):
        if page == 1:
            url = QBXSW_BASE + category_path
        else:
            url = QBXSW_BASE + category_path + f"{page}.html"

        html = fetch(url)
        if not html:
            break

        # 提取书籍和作者
        # 格式通常: <a href="/du_XXXXX/">书名</a> / 作者
        pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)

        for qb_id, name in matches:
            name = name.strip()
            if qb_id not in seen and name and len(name) > 1:
                seen.add(qb_id)
                books.append((qb_id, name))

        time.sleep(random.uniform(0.3, 0.6))

    return books


def get_qbxsw_rank_books(rank_path):
    """从 qbxsw 排行榜获取书籍"""
    url = QBXSW_BASE + rank_path
    html = fetch(url)
    if not html:
        return []

    books = []
    seen = set()
    pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)
    for qb_id, name in matches:
        name = name.strip()
        if qb_id not in seen and name and len(name) > 1:
            seen.add(qb_id)
            books.append((qb_id, name))
    return books


def main():
    # 加载现有 booklist
    existing_books = {}
    if os.path.exists(BOOKLIST_PATH):
        with open(BOOKLIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for b in data.get('books', []):
            key = b.get('name', '')
            if key:
                existing_books[key] = b
        print(f"已有书单: {len(existing_books)} 本")
    else:
        print("未找到已有书单，从头开始")

    # qbxsw 分类和排行榜来源
    sources = {
        # 分类页（多页）
        "玄幻": ("/XuanHuan/", "male", 3),
        "奇幻": ("/QiHuan/", "male", 2),
        "武侠": ("/WuXia/", "male", 2),
        "仙侠": ("/XianXia/", "male", 2),
        "都市": ("/DuShi/", "male", 3),
        "历史": ("/LiShi/", "male", 2),
        "军事": ("/JunShi/", "male", 2),
        "悬疑": ("/XuanYi/", "male", 3),
        "科幻": ("/KeHuan/", "male", 2),
        "游戏": ("/YouXi/", "male", 2),
        "古言": ("/GuYan/", "female", 3),
        "现言": ("/XianYan/", "female", 3),
        "幻言": ("/HuanYan/", "female", 3),
        "青春": ("/QinɡChun/", "female", 2),
        "穿越": ("/ChuanYue/", "female", 2),
    }

    print(f"\n{'='*60}")
    print("从 qbxsw.com 补充各分类书目")
    print(f"{'='*60}")

    new_count = 0
    for cat_name, (path, gender, pages) in sources.items():
        print(f"\n  {cat_name} ({path}) ...", end=' ', flush=True)
        books = get_qbxsw_category_books(path, max_pages=pages)
        cat_new = 0
        for qb_id, name in books:
            if name not in existing_books:
                existing_books[name] = {
                    'qidian_id': '',
                    'qbxsw_id': qb_id,
                    'name': name,
                    'author': '',
                    'category': cat_name,
                    'sub_category': '',
                    'word_count': '',
                    'rank_info': f"qbxsw分类·{cat_name}",
                    'rank_value': '',
                    'description': '',
                    'gender': gender,
                }
                cat_new += 1
                new_count += 1
        print(f"获取 {len(books)}, 新增 {cat_new} (总 {len(existing_books)})")

    # 排行榜
    print(f"\n{'─'*60}")
    print("排行榜补充")
    ranks = {
        "热门榜": "/top/allvisit/",
        "推荐榜": "/top/allvote/",
        "收藏榜": "/top/goodnum/",
        "完结榜": "/wanben/",
    }
    for rank_name, rank_path in ranks.items():
        print(f"\n  {rank_name} ...", end=' ', flush=True)
        books = get_qbxsw_rank_books(rank_path)
        rank_new = 0
        for qb_id, name in books:
            if name not in existing_books:
                existing_books[name] = {
                    'qidian_id': '',
                    'qbxsw_id': qb_id,
                    'name': name,
                    'author': '',
                    'category': '',
                    'sub_category': '',
                    'word_count': '',
                    'rank_info': f"qbxsw·{rank_name}",
                    'rank_value': '',
                    'description': '',
                    'gender': '',
                }
                rank_new += 1
                new_count += 1
        print(f"获取 {len(books)}, 新增 {rank_new} (总 {len(existing_books)})")
        time.sleep(random.uniform(0.3, 0.6))

    # 保存
    booklist = sorted(existing_books.values(), key=lambda x: x['name'])
    with open(BOOKLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            'total': len(booklist),
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'source': '起点中文网 + qbxsw.com 排行榜/分类页',
            'books': booklist,
        }, f, ensure_ascii=False, indent=2)

    # 统计
    cats = {}
    genders = {}
    for b in booklist:
        c = b.get('category', '未分类') or '未分类'
        g = b.get('gender', '?') or '?'
        cats[c] = cats.get(c, 0) + 1
        genders[g] = genders.get(g, 0) + 1

    has_qbid = sum(1 for b in booklist if b.get('qbxsw_id'))

    print(f"\n\n{'='*60}")
    print(f"书单更新完成！")
    print(f"  总计: {len(booklist)} 本 (本次新增 {new_count} 本)")
    print(f"  已有 qbxsw ID: {has_qbid} 本 (可直接下载)")
    print(f"  输出: {BOOKLIST_PATH}")
    print(f"\n  分类统计:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count}")
    print(f"\n  频道统计:")
    for g, count in sorted(genders.items(), key=lambda x: -x[1]):
        label = {'male': '男频', 'female': '女频', '?': '未知'}.get(g, g)
        print(f"    {label}: {count}")


if __name__ == '__main__':
    main()
