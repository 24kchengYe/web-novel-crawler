#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量补充起点统计数据：搜索书名 → 拿 bid → 拿收藏/月票/推荐 → 写回 metadata.json
"""
import os, sys, io, json, re, time, random, urllib.request, urllib.parse, glob

os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
HEADERS = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
# 起点不需要直连，走代理也行
OPENER = urllib.request.build_opener()


def search_qidian_bid(book_name):
    """在起点搜索书名，返回 bid 或 None"""
    url = f'https://m.qidian.com/soushu/{urllib.parse.quote(book_name)}.html'
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = OPENER.open(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except:
        return None

    # 从搜索结果找精确匹配
    # records 格式: {"bName":"xxx","bid":"123",...}
    records = re.findall(r'\{"[^}]*"bName"\s*:\s*"([^"]*)"[^}]*"bid"\s*:\s*"?(\d+)"?[^}]*\}', html)
    if not records:
        # 备选格式
        bids = re.findall(r'"bid"\s*:\s*"?(\d+)"?', html)
        names = re.findall(r'"bName"\s*:\s*"([^"]*)"', html)
        records = list(zip(names, bids))

    for name, bid in records:
        if name == book_name:
            return bid
    # 模糊匹配第一个
    if records:
        return records[0][1]
    return None


def fetch_book_stats(bid):
    """从起点详情页获取统计数据"""
    url = f'https://m.qidian.com/book/{bid}/'
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = OPENER.open(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except:
        return None

    m = re.search(r'"bookInfo"\s*:\s*\{', html)
    if not m:
        return None

    start = m.end() - 1
    depth = 0
    i = start
    while i < len(html):
        if html[i] == '{': depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0: break
        i += 1

    try:
        book = json.loads(html[start:i+1])
    except:
        return None

    labels = [t.get('tag', '') for t in book.get('bookLabels', [])]
    return {
        'qidian_bid': str(bid),
        'qidian_collect': book.get('collect', 0),
        'qidian_month_ticket': book.get('monthTicket', 0),
        'qidian_recom_all': book.get('recomAll', 0),
        'qidian_recom_week': book.get('recomWeek', 0),
        'qidian_words': book.get('wordsCnt', 0),
        'qidian_words_display': book.get('showWordsCnt', ''),
        'qidian_category': book.get('chanName', ''),
        'qidian_sub_category': book.get('subCateName', ''),
        'qidian_status': book.get('actionStatus', ''),
        'qidian_sign_status': book.get('signStatus', ''),
        'qidian_labels': labels,
    }


def main():
    metas = sorted(glob.glob(os.path.join(DATA_DIR, '*/metadata.json')))
    print(f'共 {len(metas)} 本书需要检查')

    already = 0
    success = 0
    failed = 0
    not_found = 0

    for i, mp in enumerate(metas, 1):
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)

        # 已有统计数据就跳过
        if meta.get('qidian_collect'):
            already += 1
            continue

        name = meta.get('name', '')
        if not name:
            continue

        print(f'[{i}/{len(metas)}] {name}', end=' ', flush=True)

        # 搜索 bid
        bid = search_qidian_bid(name)
        if not bid:
            print('-> 未找到', flush=True)
            not_found += 1
            time.sleep(random.uniform(0.5, 1.0))
            continue

        # 拿统计
        stats = fetch_book_stats(bid)
        if stats:
            meta.update(stats)
            with open(mp, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            print(f'-> 收藏:{stats["qidian_collect"]:,} 月票:{stats["qidian_month_ticket"]:,} 推荐:{stats["qidian_recom_all"]:,}', flush=True)
            success += 1
        else:
            print(f'-> bid={bid} 详情获取失败', flush=True)
            failed += 1

        time.sleep(random.uniform(0.8, 1.5))

    print(f'\n{"="*60}')
    print(f'完成！')
    print(f'  已有统计: {already}')
    print(f'  本次成功: {success}')
    print(f'  未找到: {not_found}')
    print(f'  失败: {failed}')


if __name__ == '__main__':
    main()
