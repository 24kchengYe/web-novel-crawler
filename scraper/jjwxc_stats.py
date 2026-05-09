#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
晋江文学城统计数据采集
从排行榜爬取书目 → 每本书的详情页获取积分/收藏/书评等
输出: jjwxc_books.json (独立的晋江书目数据)
"""
import os, sys, io, json, re, time, random, urllib.request, urllib.parse

os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(BASE_DIR, 'jjwxc_books.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def get(url, enc='gbk', timeout=12):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        return urllib.request.urlopen(req, timeout=timeout).read().decode(enc, errors='replace')
    except:
        return None


def get_topten_books(max_pages=30):
    """从晋江排行榜获取书目 (novelid + 书名)"""
    books = {}  # novelid -> name

    # orderstr: 3=收藏 4=积分 5=评论; t: 0=全站 1=原创 2=同人
    combos = [
        (3, 0), (4, 0), (5, 0),  # 全站
        (3, 1), (4, 1),           # 原创
        (3, 2), (4, 2),           # 同人
    ]

    for order, t in combos:
        label = f"order={order},t={t}"
        for page in range(1, max_pages + 1):
            html = get(f'https://www.jjwxc.net/topten.php?orderstr={order}&t={t}&p={page}')
            if not html:
                break

            # novelid
            nids = re.findall(r'onebook\.php\?novelid=(\d+)', html)
            # 书名在 tooltip class
            titles = re.findall(r'class="tooltip">([^<]+)<', html)

            if not nids:
                break

            for nid in nids:
                if nid not in books:
                    books[nid] = ''  # 占位，后面从详情页拿

            # 尝试匹配 nid-title 对
            if len(titles) == len(set(nids)):
                for nid, title in zip(dict.fromkeys(nids), titles):
                    books[nid] = title.strip()

            time.sleep(random.uniform(0.3, 0.6))

        print(f'  [{label}] 累计 {len(books)} 本', flush=True)

    return books


def get_book_detail(novelid):
    """从晋江详情页获取统计数据"""
    html = get(f'https://www.jjwxc.net/onebook.php?novelid={novelid}')
    if not html:
        return None

    stats = {'jjwxc_novelid': novelid}

    # 书名
    m = re.search(r'<title>《([^》]+)》', html)
    if m:
        stats['name'] = m.group(1).strip()

    # 作者
    m = re.search(r'作者[：:]\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        stats['author'] = m.group(1).strip()

    # 统计字段
    for pat, key in [
        (r'作品积分[：:]\s*(\d+)', 'jjwxc_score'),
        (r'总书评数[：:]\s*(\d+)', 'jjwxc_reviews'),
        (r'当前被收藏数[：:]\s*(\d+)', 'jjwxc_collect'),
        (r'营养液数[：:]\s*(\d+)', 'jjwxc_nutrition'),
    ]:
        m = re.search(pat, html)
        if m:
            stats[key] = int(m.group(1).replace(',', ''))

    # 字数
    m = re.search(r'>(\d[\d,]*)字<', html)
    if m:
        stats['word_count'] = int(m.group(1).replace(',', ''))

    # 类型标签
    m = re.search(r'作品类型[：:]\s*([^<]+)', html)
    if m:
        stats['genre'] = m.group(1).strip()

    # 状态
    if '已完结' in html:
        stats['status'] = '已完结'
    elif '连载中' in html:
        stats['status'] = '连载中'

    # 章节数
    chapters = re.findall(r'onebook\.php\?novelid=\d+&chapterid=\d+', html)
    stats['chapter_count'] = len(chapters)

    return stats


def main():
    print('='*60)
    print('晋江文学城 书目+统计数据采集')
    print('='*60)

    # 阶段1: 爬排行榜获取书目
    print('\n阶段1: 爬取排行榜书目...')
    books = get_topten_books(max_pages=30)
    print(f'\n排行榜共 {len(books)} 本不重复书目')

    # 阶段2: 逐本获取统计数据
    print(f'\n阶段2: 获取每本书的统计数据...')

    # 加载已有结果（断点续传）
    results = {}
    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding='utf-8') as f:
            old = json.load(f)
        for book in old.get('books', []):
            results[book['jjwxc_novelid']] = book

    success = 0
    skipped = 0
    failed = 0
    total = len(books)

    for i, (nid, name) in enumerate(books.items(), 1):
        if nid in results and results[nid].get('jjwxc_score'):
            skipped += 1
            continue

        print(f'[{i}/{total}] novelid={nid}', end=' ', flush=True)
        stats = get_book_detail(nid)
        if stats and (stats.get('jjwxc_score') or stats.get('jjwxc_collect')):
            stats['platforms'] = ['jjwxc']
            results[nid] = stats
            success += 1
            print(f"-> {stats.get('name','?')} 积分:{stats.get('jjwxc_score',0)} 收藏:{stats.get('jjwxc_collect',0)}", flush=True)
        else:
            failed += 1
            print('-> 失败', flush=True)

        # 定期保存
        if i % 50 == 0:
            _save(results)

        time.sleep(random.uniform(0.5, 1.0))

    _save(results)

    print(f'\n{"="*60}')
    print(f'完成！')
    print(f'  成功: {success}')
    print(f'  跳过(已有): {skipped}')
    print(f'  失败: {failed}')
    print(f'  总书目: {len(results)}')
    print(f'  输出: {OUTPUT_PATH}')


def _save(results):
    books_list = sorted(results.values(), key=lambda x: x.get('jjwxc_score', 0), reverse=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({
            'total': len(books_list),
            'source': '晋江文学城 jjwxc.net 排行榜',
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'books': books_list,
        }, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
