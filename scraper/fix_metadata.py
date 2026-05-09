#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
扫描所有 chapters.jsonl，为缺失 metadata.json 的书补生成 metadata
然后批量从起点补充统计数据（收藏/月票/推荐）
"""
import os, sys, io, json, re, time, random, urllib.request, urllib.parse

os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
HEADERS_QIDIAN = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}
OPENER = urllib.request.build_opener()


def search_qidian_bid(book_name):
    url = f'https://m.qidian.com/soushu/{urllib.parse.quote(book_name)}.html'
    try:
        req = urllib.request.Request(url, headers=HEADERS_QIDIAN)
        resp = OPENER.open(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except:
        return None
    records = re.findall(r'"bName"\s*:\s*"([^"]*)"[^}]*?"bid"\s*:\s*"?(\d+)"?', html)
    if not records:
        bids = re.findall(r'"bid"\s*:\s*"?(\d+)"?', html)
        names = re.findall(r'"bName"\s*:\s*"([^"]*)"', html)
        records = list(zip(names, bids))
    for name, bid in records:
        if name == book_name:
            return bid
    if records:
        return records[0][1]
    return None


def fetch_book_stats(bid):
    url = f'https://m.qidian.com/book/{bid}/'
    try:
        req = urllib.request.Request(url, headers=HEADERS_QIDIAN)
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
    # ============ 阶段1: 补生成缺失的 metadata.json ============
    print("=" * 60)
    print("阶段1: 扫描 chapters.jsonl，补生成缺失的 metadata.json")
    print("=" * 60)

    generated = 0
    for d in sorted(os.listdir(DATA_DIR)):
        dp = os.path.join(DATA_DIR, d)
        if not os.path.isdir(dp):
            continue
        jp = os.path.join(dp, 'chapters.jsonl')
        mp = os.path.join(dp, 'metadata.json')

        if not os.path.exists(jp):
            continue
        if os.path.exists(mp):
            continue

        # 从目录名解析书名和作者（格式: 书名_作者）
        parts = d.rsplit('_', 1)
        book_name = parts[0] if parts else d
        author = parts[1] if len(parts) > 1 else '未知'

        # 统计章节数和字数
        chapter_count = 0
        total_words = 0
        with open(jp, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    chapter_count += 1
                    total_words += rec.get('word_count', 0)
                except:
                    pass

        meta = {
            'name': book_name,
            'author': author,
            'chapter_count': chapter_count,
            'downloaded_chapters': chapter_count,
            'failed_chapters': 0,
            'total_words': total_words,
            'source_site': 'qbxsw.com',
            'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            '_generated': True,  # 标记为自动生成
        }

        with open(mp, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        generated += 1
        print(f'  生成: {book_name} ({chapter_count}章, {total_words}字)', flush=True)

    print(f'\n阶段1完成: 补生成 {generated} 个 metadata.json')

    # ============ 阶段2: 批量补充起点统计数据 ============
    print(f'\n{"=" * 60}')
    print("阶段2: 从起点补充统计数据（收藏/月票/推荐）")
    print("=" * 60)

    metas = []
    for d in sorted(os.listdir(DATA_DIR)):
        mp = os.path.join(DATA_DIR, d, 'metadata.json')
        if os.path.exists(mp):
            metas.append(mp)

    success = 0
    skipped = 0
    not_found = 0
    failed = 0

    for i, mp in enumerate(metas, 1):
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)

        if meta.get('qidian_collect'):
            skipped += 1
            continue

        name = meta.get('name', '')
        if not name:
            continue

        print(f'[{i}/{len(metas)}] {name}', end=' ', flush=True)

        bid = search_qidian_bid(name)
        if not bid:
            print('-> 未找到', flush=True)
            not_found += 1
            time.sleep(random.uniform(0.3, 0.8))
            continue

        stats = fetch_book_stats(bid)
        if stats:
            meta.update(stats)
            with open(mp, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            print(f'-> 收藏:{stats["qidian_collect"]:,} 月票:{stats["qidian_month_ticket"]:,}', flush=True)
            success += 1
        else:
            print(f'-> 详情获取失败', flush=True)
            failed += 1

        time.sleep(random.uniform(0.8, 1.5))

    # ============ 最终统计 ============
    print(f'\n{"=" * 60}')
    print(f'全部完成！')
    print(f'  阶段1 补生成 metadata: {generated}')
    print(f'  阶段2 已有统计(跳过): {skipped}')
    print(f'  阶段2 新增统计: {success}')
    print(f'  阶段2 起点未收录: {not_found}')
    print(f'  阶段2 获取失败: {failed}')

    # 最终覆盖率
    total = 0
    with_stats = 0
    for d in os.listdir(DATA_DIR):
        mp = os.path.join(DATA_DIR, d, 'metadata.json')
        if os.path.exists(mp):
            total += 1
            with open(mp, encoding='utf-8') as f:
                m = json.load(f)
            if m.get('qidian_collect'):
                with_stats += 1
    print(f'\n  最终: {with_stats}/{total} 本有统计数据 ({with_stats*100//total}%)')


if __name__ == '__main__':
    main()
