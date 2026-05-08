#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多平台统计数据采集器
按书名搜索，从 起点/晋江/纵横/豆瓣 采集权重数据
汇总写入每本书的 metadata.json

用法:
  python multi_platform_stats.py           # 跑所有缺统计的书
  python multi_platform_stats.py --stats   # 查看当前覆盖率
"""
import os, sys, io, json, re, time, random, urllib.request, urllib.parse, glob, argparse

os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HEADERS_MOBILE = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15'}


def _get(url, headers=HEADERS, timeout=12, encoding='utf-8'):
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.read().decode(encoding, errors='replace')
    except:
        return None


# ============================================================
# 起点
# ============================================================
def fetch_qidian(book_name):
    """起点移动端：搜索 → 详情页"""
    html = _get(f'https://m.qidian.com/soushu/{urllib.parse.quote(book_name)}.html', HEADERS_MOBILE)
    if not html:
        return None

    # 搜索结果里找 bid
    records = re.findall(r'"bName"\s*:\s*"([^"]*)"[^}]*?"bid"\s*:\s*"?(\d+)"?', html)
    if not records:
        bids = re.findall(r'"bid"\s*:\s*"?(\d+)"?', html)
        names = re.findall(r'"bName"\s*:\s*"([^"]*)"', html)
        records = list(zip(names, bids))

    bid = None
    for name, b in records:
        if name == book_name:
            bid = b
            break
    if not bid and records:
        bid = records[0][1]
    if not bid:
        return None

    # 详情页
    html2 = _get(f'https://m.qidian.com/book/{bid}/', HEADERS_MOBILE)
    if not html2 or 'bookInfo' not in html2:
        return None

    m = re.search(r'"bookInfo"\s*:\s*\{', html2)
    if not m:
        return None
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(html2):
        if html2[i] == '{': depth += 1
        elif html2[i] == '}':
            depth -= 1
            if depth == 0: break
        i += 1
    try:
        book = json.loads(html2[start:i+1])
    except:
        return None

    labels = [t.get('tag', '') for t in book.get('bookLabels', [])]
    return {
        'platform': 'qidian',
        'qidian_bid': str(bid),
        'qidian_collect': book.get('collect', 0),
        'qidian_month_ticket': book.get('monthTicket', 0),
        'qidian_recom_all': book.get('recomAll', 0),
        'qidian_recom_week': book.get('recomWeek', 0),
        'qidian_words': book.get('wordsCnt', 0),
        'qidian_category': book.get('chanName', ''),
        'qidian_sub_category': book.get('subCateName', ''),
        'qidian_status': book.get('actionStatus', ''),
        'qidian_labels': labels,
    }


# ============================================================
# 晋江文学城
# ============================================================
def fetch_jjwxc(book_name):
    """晋江：搜索 → 详情页"""
    # GBK 编码搜索
    kw_gbk = book_name.encode('gbk', errors='replace')
    kw_quoted = urllib.parse.quote(kw_gbk)
    html = _get(f'https://www.jjwxc.net/search.php?kw={kw_quoted}&t=1', encoding='gbk')
    if not html:
        return None

    # 找 novelid
    nids = re.findall(r'novelid=(\d+)', html)
    if not nids:
        return None

    # 取第一个结果的详情
    nid = nids[0]
    detail = _get(f'https://www.jjwxc.net/onebook.php?novelid={nid}', encoding='gbk')
    if not detail:
        return None

    stats = {'platform': 'jjwxc', 'jjwxc_novelid': nid}

    # 提取统计
    for pat, key in [
        (r'作品积分[：:]\s*(\d+)', 'jjwxc_score'),
        (r'总书评数[：:]\s*(\d+)', 'jjwxc_reviews'),
        (r'当前被收藏数[：:]\s*(\d+)', 'jjwxc_collect'),
        (r'营养液数[：:]\s*(\d+)', 'jjwxc_nutrition'),
    ]:
        m = re.search(pat, detail)
        if m:
            stats[key] = int(m.group(1).replace(',', ''))

    # 如果连积分都没拿到，说明匹配有误
    if 'jjwxc_score' not in stats and 'jjwxc_collect' not in stats:
        return None

    return stats


# ============================================================
# 纵横中文网
# ============================================================
def fetch_zongheng(book_name):
    """纵横：搜索页 HTML 解析"""
    kw = urllib.parse.quote(book_name)
    html = _get(f'https://search.zongheng.com/s?keyword={kw}')
    if not html:
        return None

    # 从搜索结果找书籍ID和统计
    # 搜索结果 HTML 中含 bookId
    bids = re.findall(r'/book/(\d+)\.html', html)
    if not bids:
        return None

    bid = bids[0]
    # 访问详情页
    detail = _get(f'https://book.zongheng.com/book/{bid}.html')
    if not detail:
        return None

    stats = {'platform': 'zongheng', 'zongheng_bookid': bid}

    for pat, key in [
        (r'总点击[：:]\s*([\d,]+)', 'zongheng_clicks'),
        (r'总推荐[：:]\s*([\d,]+)', 'zongheng_recom'),
        (r'月票[：:]\s*([\d,]+)', 'zongheng_month_ticket'),
        (r'收藏[：:]\s*([\d,]+)', 'zongheng_collect'),
        (r'字数[：:]\s*([\d,]+)', 'zongheng_words'),
    ]:
        m = re.search(pat, detail)
        if m:
            stats[key] = int(m.group(1).replace(',', ''))

    # 也试 data 属性
    for pat, key in [
        (r'"totalClick"\s*:\s*(\d+)', 'zongheng_clicks'),
        (r'"totalRecommend"\s*:\s*(\d+)', 'zongheng_recom'),
        (r'"collectNum"\s*:\s*(\d+)', 'zongheng_collect'),
    ]:
        m = re.search(pat, detail)
        if m and key not in stats:
            stats[key] = int(m.group(1))

    if len(stats) <= 2:  # 只有 platform 和 bookid，没拿到任何统计
        return None

    return stats


# ============================================================
# 豆瓣读书
# ============================================================
def fetch_douban(book_name):
    """豆瓣：suggest API → 详情页评分"""
    kw = urllib.parse.quote(book_name)
    resp = _get(f'https://book.douban.com/j/subject_suggest?q={kw}')
    if not resp:
        return None

    try:
        items = json.loads(resp)
    except:
        return None

    if not items:
        return None

    # 取第一个结果
    subject_url = items[0].get('url', '')
    subject_id = re.search(r'subject/(\d+)', subject_url)
    if not subject_id:
        return None

    sid = subject_id.group(1)
    detail = _get(subject_url)
    if not detail:
        return None

    stats = {'platform': 'douban', 'douban_subject_id': sid}

    m = re.search(r'property="v:average"[^>]*>([^<]+)<', detail)
    if m:
        try:
            stats['douban_rating'] = float(m.group(1).strip())
        except:
            pass

    m = re.search(r'property="v:votes"[^>]*>([^<]+)<', detail)
    if m:
        try:
            stats['douban_votes'] = int(m.group(1).strip())
        except:
            pass

    if 'douban_rating' not in stats:
        return None

    return stats


# ============================================================
# 主逻辑
# ============================================================
PLATFORMS = [
    ('qidian', fetch_qidian),
    ('jjwxc', fetch_jjwxc),
    ('zongheng', fetch_zongheng),
    ('douban', fetch_douban),
]


def process_all():
    metas = sorted(glob.glob(os.path.join(DATA_DIR, '*/metadata.json')))
    print(f'共 {len(metas)} 本书')

    stats_count = {p: 0 for p, _ in PLATFORMS}
    skipped = 0
    processed = 0

    for i, mp in enumerate(metas, 1):
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)

        name = meta.get('name', '')
        if not name:
            continue

        # 检查已有哪些平台数据
        existing = set()
        if meta.get('qidian_collect'): existing.add('qidian')
        if meta.get('jjwxc_score') or meta.get('jjwxc_collect'): existing.add('jjwxc')
        if meta.get('zongheng_clicks') or meta.get('zongheng_collect'): existing.add('zongheng')
        if meta.get('douban_rating'): existing.add('douban')

        # 全部都有就跳过
        if len(existing) == len(PLATFORMS):
            skipped += 1
            continue

        print(f'[{i}/{len(metas)}] {name} (已有: {",".join(existing) or "无"})', end='', flush=True)

        updated = False
        platforms_found = list(existing)

        for pname, pfunc in PLATFORMS:
            if pname in existing:
                stats_count[pname] += 1
                continue

            result = pfunc(name)
            if result:
                # 去掉 platform 键，合并到 meta
                result.pop('platform', None)
                meta.update(result)
                updated = True
                stats_count[pname] += 1
                platforms_found.append(pname)
                print(f' +{pname}', end='', flush=True)

            time.sleep(random.uniform(0.5, 1.0))

        # 更新 platforms 列表
        meta['platforms'] = sorted(set(platforms_found))

        if updated:
            with open(mp, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        processed += 1
        print(flush=True)

    # 最终统计
    print(f'\n{"="*60}')
    print(f'完成！处理 {processed} 本，跳过 {skipped} 本')
    print(f'\n平台覆盖:')
    for pname, count in stats_count.items():
        pct = count * 100 // len(metas) if metas else 0
        bar = '█' * (pct // 2)
        print(f'  {pname:12s} {count:5d} ({pct}%) {bar}')


def show_stats():
    metas = sorted(glob.glob(os.path.join(DATA_DIR, '*/metadata.json')))
    print(f'共 {len(metas)} 本书')

    platform_counts = {}
    combo_counts = {}
    no_stats = 0

    for mp in metas:
        with open(mp, encoding='utf-8') as f:
            meta = json.load(f)

        platforms = []
        if meta.get('qidian_collect'): platforms.append('qidian')
        if meta.get('jjwxc_score') or meta.get('jjwxc_collect'): platforms.append('jjwxc')
        if meta.get('zongheng_clicks') or meta.get('zongheng_collect'): platforms.append('zongheng')
        if meta.get('douban_rating'): platforms.append('douban')

        if not platforms:
            no_stats += 1
        for p in platforms:
            platform_counts[p] = platform_counts.get(p, 0) + 1
        combo = '+'.join(platforms) if platforms else '无'
        combo_counts[combo] = combo_counts.get(combo, 0) + 1

    print(f'\n平台覆盖:')
    for p in ['qidian', 'jjwxc', 'zongheng', 'douban']:
        c = platform_counts.get(p, 0)
        pct = c * 100 // len(metas) if metas else 0
        print(f'  {p:12s} {c:5d} ({pct}%)')

    print(f'\n无任何统计: {no_stats} ({no_stats*100//len(metas)}%)')
    print(f'\n组合分布 (top 10):')
    for combo, count in sorted(combo_counts.items(), key=lambda x: -x[1])[:10]:
        print(f'  {combo:30s} {count:5d}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='多平台统计数据采集')
    parser.add_argument('--stats', action='store_true', help='查看当前覆盖率')
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        process_all()
