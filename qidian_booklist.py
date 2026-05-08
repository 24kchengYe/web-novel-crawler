#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
起点中文网榜单爬虫 —— 只抓书单，不抓正文
从起点移动端SSR数据中提取各分类×各榜单的热门书籍
输出去重后的 booklist.json 供后续下载使用
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

# ============================================================
# 配置
# ============================================================
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 起点分类 ID 映射
CATEGORIES = {
    "全部":  0,
    "玄幻": 21,
    "仙侠": 22,
    "都市":  4,
    "历史":  5,
    "科幻": 30,
    "悬疑":  6,
    "游戏":  7,
    "体育":  8,
    "武侠":  2,
    "军事": 31,
    "轻小说": 32,
}

# 女生频道分类
CATEGORIES_FEMALE = {
    "古代言情": 80,
    "现代言情": 81,
    "幻想言情": 82,
    "青春校园": 83,
    "仙侠奇缘": 84,
    "科幻空间": 85,
}

# 榜单类型 → URL路径
RANK_TYPES = {
    "月票榜": "yuepiao",
    "畅销榜": "hotsales",
    "阅读指数": "readIndex",
    "推荐榜": "recom",
    "收藏榜": "collect",
    "完本榜": "finish",
}

# 时间维度: 月票榜/推荐榜有周/月，其他通常只有一种
# dateType: 不加参数=默认（月或总）


def fetch(url, retries=3):
    """带重试的 HTTP GET"""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=15)
            return resp.read().decode('utf-8', errors='replace')
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 2 + random.random()
                print(f"  [重试 {attempt+1}] {url} -> {e}")
                time.sleep(wait)
            else:
                print(f"  [失败] {url} -> {e}")
                return None


def parse_rank_page(html):
    """
    从起点移动端HTML中提取SSR嵌入的排行榜数据
    返回: [{"bName", "bAuth", "cat", "subCat", "bid", "cnt", "rankCnt", "rankNum", "desc"}, ...]
    """
    # 找 pageContext JSON
    m = re.search(r'"pageData"\s*:\s*\{', html)
    if not m:
        return []

    # 从这里开始往后找 records 数组
    start = m.start()
    # 找 records 数组
    rec_m = re.search(r'"records"\s*:\s*\[', html[start:])
    if not rec_m:
        return []

    arr_start = start + rec_m.start() + rec_m.end() - rec_m.start()
    # 找匹配的 ]
    # 简单方法：从 [ 开始计数括号
    bracket_start = start + rec_m.end() - 1  # 指向 [
    depth = 0
    i = bracket_start
    while i < len(html):
        if html[i] == '[':
            depth += 1
        elif html[i] == ']':
            depth -= 1
            if depth == 0:
                break
        i += 1

    records_json = html[bracket_start:i+1]
    try:
        records = json.loads(records_json)
        return records
    except json.JSONDecodeError as e:
        print(f"  JSON解析失败: {e}")
        return []


def fetch_rank(rank_type="月票榜", cat_id=0, gender="male", page=1):
    """
    获取起点某个榜单的一页数据
    gender: "male" 或 "female"
    """
    rank_path = RANK_TYPES.get(rank_type, "yuepiao")

    if cat_id > 0:
        cat_part = f"catid{cat_id}/"
    else:
        cat_part = ""

    if gender == "female":
        base = "https://m.qidian.com/mm/rank"
    else:
        base = "https://m.qidian.com/rank"

    url = f"{base}/{rank_path}/{cat_part}"
    if page > 1:
        # 起点移动端分页通常在 URL 参数中
        url += f"?page={page}"

    html = fetch(url)
    if not html:
        return []

    records = parse_rank_page(html)
    return records


def build_booklist():
    """
    遍历所有分类×榜单，构建完整书单
    """
    all_books = {}  # bid -> book_info，用bid去重

    # ========== 男频 ==========
    print("=" * 60)
    print("起点中文网 · 榜单书目采集")
    print("=" * 60)

    # 主要榜单 × 主要分类
    target_ranks = ["月票榜", "畅销榜", "阅读指数", "推荐榜", "收藏榜"]
    target_cats = {
        "全部": 0,
        "玄幻": 21,
        "仙侠": 22,
        "都市": 4,
        "悬疑": 6,
        "科幻": 30,
        "历史": 5,
        "武侠": 2,
        "游戏": 7,
        "军事": 31,
    }

    for rank_name in target_ranks:
        for cat_name, cat_id in target_cats.items():
            print(f"\n[男频] {rank_name} · {cat_name} ...", end=' ', flush=True)
            records = fetch_rank(rank_name, cat_id, "male")
            new_count = 0
            for r in records:
                bid = str(r.get('bid', ''))
                if bid and bid not in all_books:
                    all_books[bid] = {
                        'qidian_id': bid,
                        'name': r.get('bName', ''),
                        'author': r.get('bAuth', ''),
                        'category': r.get('cat', ''),
                        'sub_category': r.get('subCat', ''),
                        'word_count': r.get('cnt', ''),
                        'rank_info': f"{rank_name}·{cat_name}: #{r.get('rankNum', '?')}",
                        'rank_value': r.get('rankCnt', ''),
                        'description': r.get('desc', ''),
                        'gender': 'male',
                    }
                    new_count += 1
            print(f"获取 {len(records)} 本, 新增 {new_count} 本 (累计 {len(all_books)})")
            time.sleep(random.uniform(0.5, 1.0))

    # 完本榜（不分分类，只取全部）
    print(f"\n[男频] 完本榜 · 全部 ...", end=' ', flush=True)
    records = fetch_rank("完本榜", 0, "male")
    new_count = 0
    for r in records:
        bid = str(r.get('bid', ''))
        if bid and bid not in all_books:
            all_books[bid] = {
                'qidian_id': bid,
                'name': r.get('bName', ''),
                'author': r.get('bAuth', ''),
                'category': r.get('cat', ''),
                'sub_category': r.get('subCat', ''),
                'word_count': r.get('cnt', ''),
                'rank_info': f"完本榜: #{r.get('rankNum', '?')}",
                'rank_value': r.get('rankCnt', ''),
                'description': r.get('desc', ''),
                'gender': 'male',
            }
            new_count += 1
    print(f"获取 {len(records)} 本, 新增 {new_count} 本 (累计 {len(all_books)})")
    time.sleep(random.uniform(0.5, 1.0))

    # ========== 补充：从 qbxsw 获取女频和悬疑等分类 ==========
    print(f"\n{'─'*60}")
    print("从 qbxsw.com 补充女频/悬疑/科幻榜单")
    print(f"{'─'*60}")

    qbxsw_cats = {
        "古言": "https://www.qbxsw.com/top/allvisit/c80/",
        "现言": "https://www.qbxsw.com/top/allvisit/c81/",
        "幻言": "https://www.qbxsw.com/top/allvisit/c82/",
        "悬疑": "https://www.qbxsw.com/top/allvisit/c6/",
        "科幻": "https://www.qbxsw.com/top/allvisit/c30/",
    }

    for cat_name, qb_url in qbxsw_cats.items():
        print(f"\n[qbxsw] {cat_name} ...", end=' ', flush=True)
        html = fetch(qb_url)
        if not html:
            # 也试通用排行页
            qb_url2 = f"https://www.qbxsw.com/{cat_name.replace('言','Yan').replace('古','Gu').replace('现','Xian').replace('幻','Huan')}/"
            html = fetch(qb_url2)
        if not html:
            print("失败")
            continue

        # 提取书籍: <a href="/du_XXXXX/">书名</a>
        import re as _re
        pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
        matches = _re.findall(pattern, html)
        new_count = 0
        seen_here = set()
        for qb_id, name in matches:
            name = name.strip()
            if qb_id in seen_here or not name:
                continue
            seen_here.add(qb_id)
            # 用 qbxsw ID 作 key（前缀 qb_ 避免和起点 bid 冲突）
            key = f"qb_{qb_id}"
            if key not in all_books:
                all_books[key] = {
                    'qidian_id': '',
                    'qbxsw_id': qb_id,
                    'name': name,
                    'author': '',
                    'category': cat_name,
                    'sub_category': '',
                    'word_count': '',
                    'rank_info': f"qbxsw热门·{cat_name}",
                    'rank_value': '',
                    'description': '',
                    'gender': 'female' if cat_name in ('古言', '现言', '幻言') else 'male',
                }
                new_count += 1
        print(f"获取 {len(seen_here)} 本, 新增 {new_count} 本 (累计 {len(all_books)})")
        time.sleep(random.uniform(0.5, 1.0))

    # ========== 输出 ==========
    booklist = sorted(all_books.values(), key=lambda x: x['name'])

    output_path = os.path.join(OUTPUT_DIR, 'booklist.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            'total': len(booklist),
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'source': '起点中文网 m.qidian.com 排行榜',
            'books': booklist,
        }, f, ensure_ascii=False, indent=2)

    # 统计
    cats = {}
    for b in booklist:
        c = b.get('category', '未知')
        cats[c] = cats.get(c, 0) + 1

    print(f"\n\n{'='*60}")
    print(f"书单生成完毕！")
    print(f"  总计: {len(booklist)} 本不重复书籍")
    print(f"  输出: {output_path}")
    print(f"\n  分类统计:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {count} 本")

    return output_path


if __name__ == '__main__':
    build_booklist()
