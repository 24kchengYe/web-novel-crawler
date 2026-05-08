#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
晋江书目爬虫：从盗版站(zhenhunxiaoshuo.com/ixdzs8.com)爬正文 + 从晋江爬统计
输出格式与 qbxsw 爬虫一致: data/书名_作者/metadata.json + chapters.jsonl + full_text.txt
"""
import os, sys, io, json, re, time, random, urllib.request, urllib.parse, threading
from concurrent.futures import ThreadPoolExecutor

os.environ['PYTHONUNBUFFERED'] = '1'
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
JJWXC_BOOKLIST = os.path.join(BASE_DIR, 'jjwxc_books.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url, enc='utf-8', timeout=12):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        return _opener.open(req, timeout=timeout).read().decode(enc, errors='replace')
    except:
        return None


# ============================================================
# zhenhunxiaoshuo.com 爬虫
# ============================================================
def zhenhu_get_book_list():
    """从晋江排行榜获取书目，用拼音构造 zhenhunxiaoshuo URL"""
    from pypinyin import pinyin, Style

    books = []
    # 从晋江排行榜获取书名
    jj_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for order in [3, 4, 5]:  # 收藏/积分/评论
        for t in [0, 1, 2]:  # 全站/原创/同人
            for page in range(1, 25):
                html = _get(f'https://www.jjwxc.net/topten.php?orderstr={order}&t={t}&p={page}', enc='gbk')
                if not html:
                    break
                titles = re.findall(r'class="tooltip">([^<]+)<', html)
                nids = re.findall(r'onebook\.php\?novelid=(\d+)', html)
                if not titles and not nids:
                    break
                for title in titles:
                    title = title.strip()
                    if len(title) > 1 and len(title) < 50:
                        # 转拼音构造URL
                        py = ''.join([p[0] for p in pinyin(title, style=Style.NORMAL)])
                        py = re.sub(r'[^a-z]', '', py)  # 去非字母
                        book_url = f'https://www.zhenhunxiaoshuo.com/{py}/'
                        books.append({'name': title, 'url': book_url, 'source': 'zhenhunxiaoshuo', 'pinyin': py})
                time.sleep(random.uniform(0.3, 0.5))

    # 去重
    seen = set()
    unique = []
    for b in books:
        if b['name'] not in seen:
            seen.add(b['name'])
            unique.append(b)
    return unique


def zhenhu_get_chapters(book_url):
    """获取一本书的章节列表"""
    html = _get(book_url)
    if not html:
        return [], '', ''

    # 书名
    m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    name = m.group(1).strip() if m else ''

    # 作者
    m = re.search(r'作者[：:]\s*([^<\s]+)', html)
    author = m.group(1).strip() if m else '未知'

    # 章节链接
    chapters = re.findall(r'href=\"(https://www\.zhenhunxiaoshuo\.com/\d+\.html)\"[^>]*>([^<]+)</a>', html)
    return chapters, name, author


def zhenhu_get_content(chapter_url):
    """获取章节正文"""
    html = _get(chapter_url)
    if not html:
        return ''
    # 正文在 <p> 标签里
    ps = re.findall(r'<p[^>]*>([^<]+)</p>', html)
    # 过滤广告
    text_parts = []
    for p in ps:
        p = p.strip()
        if len(p) < 3:
            continue
        if any(ad in p for ad in ['zhenhunxiaoshuo', '更新', '收藏', '书签', '免费阅读']):
            continue
        text_parts.append(p)
    return '\n'.join(text_parts)


# ============================================================
# ixdzs8.com 搜索 (备选)
# ============================================================
def ixdzs_search(book_name):
    """在 ixdzs8 搜索书名，返回书页URL或None"""
    url = f'https://ixdzs8.com/bsearch?q={urllib.parse.quote(book_name)}'
    html = _get(url)
    if not html:
        return None
    links = re.findall(r'href=\"(/read/\d+/)\"', html)
    titles = re.findall(r'<a[^>]*/read/(\d+)/[^>]*>([^<]+)</a>', html)
    for bid, title in titles:
        if book_name in title or title in book_name:
            return f'https://ixdzs8.com/read/{bid}/'
    return links[0] if links else None


# ============================================================
# 下载一本书
# ============================================================
def download_book(book_info):
    """下载一本晋江书"""
    name = book_info['name']
    book_url = book_info.get('url', '')

    print(f'\n{"="*50}')
    print(f'下载: {name}')

    # 获取章节列表
    chapters, real_name, author = zhenhu_get_chapters(book_url)
    if not chapters:
        print(f'  章节列表为空，跳过')
        return None

    if real_name:
        name = real_name

    print(f'  作者: {author}')
    print(f'  章节: {len(chapters)}')

    # 创建目录
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', f'{name}_{author}')[:100]
    book_dir = os.path.join(DATA_DIR, safe_name)
    os.makedirs(book_dir, exist_ok=True)
    chapters_dir = os.path.join(book_dir, 'chapters')
    os.makedirs(chapters_dir, exist_ok=True)

    # 下载章节
    jsonl_path = os.path.join(book_dir, 'chapters.jsonl')
    # 断点续传
    existing = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    existing.add(json.loads(line).get('index', -1))
                except:
                    pass

    records = []
    if existing:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    records.append(json.loads(line))
                except:
                    pass

    jsonl_file = open(jsonl_path, 'a', encoding='utf-8')
    downloaded = 0
    failed = 0
    total_words = 0

    for i, (ch_url, ch_title) in enumerate(chapters, 1):
        if i in existing:
            continue

        content = zhenhu_get_content(ch_url)
        if content and len(content) > 10:
            word_count = len(content)
            total_words += word_count
            record = {'index': i, 'title': ch_title.strip(), 'word_count': word_count, 'content': content}
            jsonl_file.write(json.dumps(record, ensure_ascii=False) + '\n')
            jsonl_file.flush()
            records.append(record)

            safe_ch = re.sub(r'[<>:"/\\|?*]', '_', f'{i:04d}_{ch_title.strip()}')[:100]
            with open(os.path.join(chapters_dir, f'{safe_ch}.txt'), 'w', encoding='utf-8') as f:
                f.write(f'# {ch_title.strip()}\n\n{content}')

            downloaded += 1
            print(f'  [{i}/{len(chapters)}] {ch_title.strip()} ok ({word_count}字)', flush=True)
        else:
            failed += 1

        time.sleep(random.uniform(0.3, 0.6))

    jsonl_file.close()

    # 排序 jsonl
    records.sort(key=lambda x: x.get('index', 0))
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # 合并 full_text.txt
    with open(os.path.join(book_dir, 'full_text.txt'), 'w', encoding='utf-8') as f:
        f.write(f'书名：{name}\n作者：{author}\n\n{"="*40}\n\n')
        for rec in records:
            f.write(f'## {rec["title"]}\n\n{rec["content"]}\n\n{"─"*40}\n\n')

    # 写 metadata
    for rec in records:
        total_words += rec.get('word_count', 0) if rec.get('index', -1) in existing else 0

    meta = {
        'name': name,
        'author': author,
        'chapter_count': len(chapters),
        'downloaded_chapters': len(records),
        'failed_chapters': failed,
        'total_words': sum(r.get('word_count', 0) for r in records),
        'source_url': book_url,
        'source_site': 'zhenhunxiaoshuo.com',
        'platforms': ['jjwxc_pirate'],
        'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }

    # 从晋江补统计
    jj_stats = _get_jjwxc_stats(name)
    if jj_stats:
        meta.update(jj_stats)
        if 'jjwxc' not in meta['platforms']:
            meta['platforms'].append('jjwxc')

    with open(os.path.join(book_dir, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f'  完成: {downloaded} 下载, {len(existing)} 跳过, {failed} 失败')
    return book_dir


def _get_jjwxc_stats(book_name):
    """从晋江详情页获取统计"""
    kw = book_name.encode('gbk', errors='replace')
    html = _get(f'https://www.jjwxc.net/search.php?kw={urllib.parse.quote(kw)}&t=1', enc='gbk')
    if not html:
        return None
    nids = re.findall(r'novelid=(\d+)', html)
    if not nids:
        return None
    detail = _get(f'https://www.jjwxc.net/onebook.php?novelid={nids[0]}', enc='gbk')
    if not detail:
        return None
    stats = {'jjwxc_novelid': nids[0]}
    for pat, key in [
        (r'作品积分[：:]\s*(\d+)', 'jjwxc_score'),
        (r'总书评数[：:]\s*(\d+)', 'jjwxc_reviews'),
        (r'当前被收藏数[：:]\s*(\d+)', 'jjwxc_collect'),
    ]:
        m = re.search(pat, detail)
        if m:
            stats[key] = int(m.group(1))
    return stats if len(stats) > 1 else None


def main():
    print('='*60)
    print('晋江书目爬虫 (盗版正文 + 晋江统计)')
    print('='*60)

    # 获取 zhenhunxiaoshuo 书目
    print('\n获取 zhenhunxiaoshuo.com 书目...')
    books = zhenhu_get_book_list()
    print(f'共 {len(books)} 本')

    # 排除已有的
    existing_names = set()
    for d in os.listdir(DATA_DIR):
        mp = os.path.join(DATA_DIR, d, 'metadata.json')
        if os.path.exists(mp):
            with open(mp, encoding='utf-8') as f:
                m = json.load(f)
            if m.get('name'):
                existing_names.add(m['name'])

    pending = [b for b in books if b['name'] not in existing_names]
    print(f'已有: {len(books) - len(pending)}, 待下载: {len(pending)}')

    # 下载
    success = 0
    for i, book in enumerate(pending, 1):
        print(f'\n[{i}/{len(pending)}]', flush=True)
        result = download_book(book)
        if result:
            success += 1

    print(f'\n{"="*60}')
    print(f'完成! 成功: {success}/{len(pending)}')


if __name__ == '__main__':
    main()
