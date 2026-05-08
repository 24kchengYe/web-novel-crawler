#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网络小说爬虫 - 基于全本小说网(qbxsw.com)
用途：学术研究用语料采集
支持：玄幻、言情（古言/现言/幻言）、悬疑 三大类
输出：一本书一个文件夹，含 metadata.json + 按章节分文件的 txt
"""

import os
import sys
import io
import re
import json
import time
import random
import argparse
import urllib.request
import urllib.parse
from html.parser import HTMLParser
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Windows UTF-8 输出 + 强制无缓冲
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# ============================================================
# 配置
# ============================================================
BASE_URL = "https://www.qbxsw.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# 请求间隔（秒）
MIN_DELAY = 0.1
MAX_DELAY = 0.25
# 并发线程数（单本书内章节并行下载）
# 自适应：短书并发快下，长书低并发防封
MAX_WORKERS_SHORT = 4   # <800章的书用4线程
MAX_WORKERS_LONG = 3    # >=800章的书用3线程
CHAPTER_THRESHOLD = 800  # 章节数阈值
# 重试次数
MAX_RETRIES = 3

# 分类映射：用户友好名 -> URL路径
CATEGORY_MAP = {
    "玄幻": "/XuanHuan/",
    "奇幻": "/QiHuan/",
    "武侠": "/WuXia/",
    "都市": "/DuShi/",
    "历史": "/LiShi/",
    "军事": "/JunShi/",
    "悬疑": "/XuanYi/",
    "游戏": "/YouXi/",
    "科幻": "/KeHuan/",
    "古言": "/GuYan/",
    "现言": "/XianYan/",
    "幻言": "/HuanYan/",
    "仙侠": "/XianXia/",
    "言情": None,  # 特殊处理：合并古言+现言+幻言
}

# 排行榜 URL
RANK_URLS = {
    "热门榜": "/top/allvisit/",
    "推荐榜": "/top/allvote/",
    "收藏榜": "/top/goodnum/",
}


# 起点移动端配置（用于拉取统计数据）
QIDIAN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
    "Accept": "text/html",
}


# ============================================================
# 起点统计数据采集
# ============================================================
def fetch_qidian_stats(book_name, qidian_bid=None):
    """
    从起点移动端书籍详情页获取统计数据（收藏、月票、推荐等）
    优先用 qidian_bid，否则不调用（无法通过书名直接查）
    返回: dict 或 None
    """
    if not qidian_bid:
        return None

    url = f"https://m.qidian.com/book/{qidian_bid}/"
    try:
        req = urllib.request.Request(url, headers=QIDIAN_HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  [起点统计] 获取失败: {e}")
        return None

    if 'bookInfo' not in html:
        return None

    # 解析 bookInfo JSON
    m = re.search(r'"bookInfo"\s*:\s*\{', html)
    if not m:
        return None

    start = m.end() - 1
    depth = 0
    i = start
    while i < len(html):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                break
        i += 1

    try:
        book_data = json.loads(html[start:i+1])
    except json.JSONDecodeError:
        return None

    # 提取关键统计字段
    labels = [tag.get('tag', '') for tag in book_data.get('bookLabels', [])]
    stats = {
        'qidian_bid': str(qidian_bid),
        'qidian_collect': book_data.get('collect', 0),         # 收藏数
        'qidian_month_ticket': book_data.get('monthTicket', 0), # 月票
        'qidian_recom_all': book_data.get('recomAll', 0),       # 总推荐票
        'qidian_recom_week': book_data.get('recomWeek', 0),     # 周推荐
        'qidian_words': book_data.get('wordsCnt', 0),           # 精确字数
        'qidian_words_display': book_data.get('showWordsCnt', ''),  # 显示字数
        'qidian_category': book_data.get('chanName', ''),       # 分类
        'qidian_sub_category': book_data.get('subCateName', ''), # 子分类
        'qidian_status': book_data.get('actionStatus', ''),     # 状态
        'qidian_sign_status': book_data.get('signStatus', ''),  # 签约状态
        'qidian_labels': labels,                                 # 标签
        'qidian_author_id': book_data.get('authorId', 0),
        'qidian_update_time': book_data.get('updTime', ''),
    }
    return stats


# ============================================================
# 工具函数
# ============================================================
# 直连模式（不走任何代理）
_direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_consecutive_fails = 0


def fetch(url, retries=MAX_RETRIES):
    """带重试和自适应冷却的HTTP GET（强制直连）"""
    global _consecutive_fails

    if _consecutive_fails >= 5:
        cooldown = min(2 ** (_consecutive_fails - 3), 120)
        print(f"  [冷却] 连续{_consecutive_fails}次失败，等待{cooldown}s...", flush=True)
        time.sleep(cooldown)

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = _direct_opener.open(req, timeout=15)
            data = resp.read().decode('utf-8', errors='replace')
            _consecutive_fails = 0
            return data
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 2 + random.random()
                print(f"  [重试 {attempt+1}/{retries}] {url} -> {e}, 等待 {wait:.1f}s", flush=True)
                time.sleep(wait)
            else:
                _consecutive_fails += 1
                print(f"  [失败] {url} -> {e}", flush=True)
                return None


def clean_text(html_content):
    """从HTML中提取纯文本，去除标签和广告"""
    # 去除 script/style
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    # <p> 和 <br> 转换行
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<p[^>]*>', '', text)
    # 去除其他标签
    text = re.sub(r'<[^>]+>', '', text)
    # HTML实体
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&amp;', '&').replace('&quot;', '"')
    # 去除广告行
    ad_patterns = [
        r'.*全本小说网.*更新速度.*',
        r'.*www\.qbxsw\.com.*',
        r'.*请大家收藏.*',
        r'.*本小章还未完.*点击下一页.*',
        r'.*喜欢.*请大家收藏.*',
        r'.*最新章节.*全网最快.*',
        r'.*手机用户请浏览.*阅读.*',
        r'.*一秒记住.*',
    ]
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        is_ad = False
        for pat in ad_patterns:
            if re.match(pat, line):
                is_ad = True
                break
        if not is_ad:
            cleaned.append(line)
    return '\n'.join(cleaned)


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name[:100]  # 限制长度


def polite_sleep():
    """礼貌延迟"""
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


# ============================================================
# 排行榜 / 分类页解析
# ============================================================
def get_rank_books(rank_type="热门榜", category=None, max_books=100):
    """
    获取排行榜中指定分类的书籍列表
    返回: [(book_id, book_name, author), ...]
    """
    url = BASE_URL + RANK_URLS.get(rank_type, RANK_URLS["热门榜"])
    print(f"\n📊 正在获取 {rank_type} ...")
    html = fetch(url)
    if not html:
        print("  获取排行榜失败")
        return []

    # 解析所有书籍链接：<a href="/du_XXXXX/">书名</a>
    books = []
    # 排行榜页面结构：<li><a href="/du_17701/">诡秘之主</a> / 爱潜水的乌贼</li>
    pattern = r'<li[^>]*>.*?<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>\s*/?\s*([^<]*?)(?:</li>|<)'
    matches = re.findall(pattern, html, re.DOTALL)
    for book_id, name, author in matches:
        author = author.strip().strip('/')
        books.append((book_id, name.strip(), author.strip()))

    print(f"  排行榜共找到 {len(books)} 本书")
    return books[:max_books]


def get_category_books(category_name, max_pages=5, max_books=100):
    """
    获取分类页面的书籍列表
    返回: [(book_id, book_name, author), ...]
    """
    if category_name == "言情":
        # 合并古言+现言+幻言
        all_books = []
        for sub in ["古言", "现言", "幻言"]:
            sub_books = get_category_books(sub, max_pages=2, max_books=40)
            all_books.extend(sub_books)
        # 去重
        seen = set()
        unique = []
        for b in all_books:
            if b[0] not in seen:
                seen.add(b[0])
                unique.append(b)
        return unique[:max_books]

    path = CATEGORY_MAP.get(category_name)
    if not path:
        print(f"  未知分类: {category_name}")
        return []

    books = []
    for page in range(1, max_pages + 1):
        if page == 1:
            url = BASE_URL + path
        else:
            url = BASE_URL + path + f"{page}.html"

        print(f"  正在获取 {category_name} 第{page}页 ...")
        html = fetch(url)
        if not html:
            break

        # 解析书籍列表
        pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)
        page_books = set()
        for book_id, name in matches:
            if book_id not in page_books:
                page_books.add(book_id)
                books.append((book_id, name.strip(), ""))

        if len(books) >= max_books:
            break
        polite_sleep()

    # 去重
    seen = set()
    unique = []
    for b in books:
        if b[0] not in seen:
            seen.add(b[0])
            unique.append(b)
    return unique[:max_books]


def search_books(keyword):
    """
    搜索小说（POST方式）
    返回: [(book_id, book_name, author), ...]
    """
    print(f"\n搜索: {keyword}")

    # 尝试 POST 搜索
    search_url = BASE_URL + "/search.html"
    data = urllib.parse.urlencode({'searchkey': keyword}).encode('utf-8')
    try:
        req = urllib.request.Request(search_url, data=data, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f"  搜索失败: {e}")
        # 备选：Google site search
        return _search_fallback(keyword)

    books = []
    # 搜索结果页: <a href="/du_XXXXX/">书名</a>
    pattern = r'<a\s+href="/du_(\d+)/"[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)
    seen = set()
    for book_id, name in matches:
        if book_id not in seen and keyword.lower() in name.lower():
            seen.add(book_id)
            books.append((book_id, name.strip(), ""))

    if not books:
        # 宽松匹配
        for book_id, name in matches:
            if book_id not in seen:
                seen.add(book_id)
                books.append((book_id, name.strip(), ""))

    if not books:
        return _search_fallback(keyword)

    return books


def _search_fallback(keyword):
    """
    搜索备选方案：从 shu_XXX 页面搜索
    如果搜索不到，提示用户使用 --id 或 --list-rank
    """
    print(f"  提示: 站内搜索不可用，请使用 --list-rank 查看排行榜获取书籍ID")
    print(f"        或使用 --id <book_id> 直接下载")
    return []


# ============================================================
# 书籍详情 & 章节列表
# ============================================================
def get_book_info(book_id):
    """
    获取书籍详情和章节列表
    返回: {
        'id': str,
        'name': str,
        'author': str,
        'category': str,
        'status': str,
        'description': str,
        'chapters': [(chapter_url, chapter_title), ...]
    }
    """
    url = f"{BASE_URL}/du_{book_id}/"
    html = fetch(url)
    if not html:
        return None

    info = {'id': book_id, 'chapters': []}

    # 从 og:meta 提取元信息
    og_map = {
        'og:novel:book_name': 'name',
        'og:novel:author': 'author',
        'og:novel:category': 'category',
        'og:novel:status': 'status',
    }
    for og_key, info_key in og_map.items():
        m = re.search(rf'property="{og_key}"\s+content="([^"]*)"', html)
        if m:
            info[info_key] = m.group(1).strip()

    # 简介
    m = re.search(r'<div[^>]*class="intro"[^>]*>(.*?)</div>', html, re.DOTALL)
    if m:
        desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        info['description'] = desc
    else:
        info['description'] = ''

    # 补充默认值
    info.setdefault('name', f'book_{book_id}')
    info.setdefault('author', '未知')
    info.setdefault('category', '未知')
    info.setdefault('status', '未知')

    # 章节列表
    # 页面有两段章节：第一段是最新章节（倒序），第二段是正文（正序）
    # 我们只取"正文"之后的章节
    zhengwen_idx = html.find('正文')
    if zhengwen_idx > 0:
        chapter_html = html[zhengwen_idx:]
    else:
        chapter_html = html

    pattern = r'<dd><a\s+href="(/du_' + book_id + r'/\d+\.html)"[^>]*>([^<]+)</a></dd>'
    chapters = re.findall(pattern, chapter_html)
    info['chapters'] = [(BASE_URL + path, title.strip()) for path, title in chapters]

    return info


# ============================================================
# 章节内容下载
# ============================================================
def download_chapter_content(chapter_url):
    """
    下载单个章节的完整内容（处理分页）
    返回: str (纯文本)
    """
    all_text = []
    current_url = chapter_url
    page_num = 0
    max_pages = 20  # 防止无限循环

    while current_url and page_num < max_pages:
        page_num += 1
        html = fetch(current_url)
        if not html:
            break

        # 提取 content div
        m = re.search(r'id="content"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            content_html = m.group(1)
            text = clean_text(content_html)
            if text:
                all_text.append(text)

        # 检查是否有下一页（分页章节: xxx_2.html, xxx_3.html）
        next_page = re.search(
            r'<a[^>]*href="([^"]*)"[^>]*class="next"[^>]*>下一页</a>',
            html
        )
        if next_page:
            next_href = next_page.group(1)
            if next_href.startswith('/'):
                current_url = BASE_URL + next_href
            elif next_href.startswith('http'):
                current_url = next_href
            else:
                # 相对路径
                base = chapter_url.rsplit('/', 1)[0]
                current_url = base + '/' + next_href
            polite_sleep()
        else:
            break

    return '\n'.join(all_text)


def download_book(book_id, output_base=OUTPUT_DIR, skip_existing=True, qidian_meta=None):
    """
    下载一本完整的小说
    输出:
      书名_作者/
        metadata.json       丰富的元信息
        chapters.jsonl      每行一个JSON {index, title, word_count, content}
        full_text.txt       纯文本合并版
        chapters/           逐章txt（方便人工阅读）
          0001_xxx.txt
    qidian_meta: 可选，从起点书单带过来的额外元信息 dict
    返回: 输出目录路径
    """
    print(f"\n{'='*60}")
    print(f"开始获取书籍信息: {book_id}")

    info = get_book_info(book_id)
    if not info:
        print(f"  获取书籍信息失败: {book_id}")
        return None

    book_name = info['name']
    author = info['author']
    chapter_count = len(info['chapters'])
    print(f"  书名: {book_name}")
    print(f"  作者: {author}")
    print(f"  分类: {info.get('category', '未知')}")
    print(f"  状态: {info.get('status', '未知')}")
    print(f"  章节数: {chapter_count}")

    if chapter_count == 0:
        print("  未找到章节，跳过")
        return None

    # 创建输出目录
    safe_name = sanitize_filename(f"{book_name}_{author}")
    book_dir = os.path.join(output_base, safe_name)
    os.makedirs(book_dir, exist_ok=True)
    chapters_dir = os.path.join(book_dir, 'chapters')
    os.makedirs(chapters_dir, exist_ok=True)

    # 检查是否已有完整的 chapters.jsonl（断点续传）
    jsonl_path = os.path.join(book_dir, 'chapters.jsonl')
    existing_indices = set()
    if skip_existing and os.path.exists(jsonl_path):
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    existing_indices.add(obj.get('index', -1))
                except:
                    pass

    # 下载章节（多线程并发）
    downloaded = 0
    skipped = 0
    failed = 0
    total_words = 0
    chapter_records = []  # 收集所有章节数据用于最终合并
    _write_lock = threading.Lock()

    # 先加载已有的 jsonl 记录
    if existing_indices:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    chapter_records.append(json.loads(line))
                except:
                    pass

    skipped = len(existing_indices)

    # 构建待下载任务
    pending = [(i, ch_url, ch_title) for i, (ch_url, ch_title)
               in enumerate(info['chapters'], 1) if i not in existing_indices]

    # 自适应并发：短书快下，长书防封
    actual_workers = MAX_WORKERS_SHORT if chapter_count < CHAPTER_THRESHOLD else MAX_WORKERS_LONG

    if not pending:
        print(f"  所有 {chapter_count} 章已下载，跳过")
    else:
        print(f"  待下载: {len(pending)} 章 (跳过已有 {skipped} 章), 并发: {actual_workers}")

    # 以追加模式打开 jsonl
    jsonl_file = open(jsonl_path, 'a', encoding='utf-8')

    def _download_one(task):
        nonlocal downloaded, failed, total_words
        idx, ch_url, ch_title = task
        content = download_chapter_content(ch_url)

        with _write_lock:
            if content and len(content) > 10:
                word_count = len(content)
                total_words += word_count
                record = {
                    'index': idx,
                    'title': ch_title,
                    'word_count': word_count,
                    'content': content,
                }
                jsonl_file.write(json.dumps(record, ensure_ascii=False) + '\n')
                jsonl_file.flush()
                chapter_records.append(record)

                safe_ch = sanitize_filename(f"{idx:04d}_{ch_title}")
                ch_path = os.path.join(chapters_dir, f"{safe_ch}.txt")
                with open(ch_path, 'w', encoding='utf-8') as f:
                    f.write(f"# {ch_title}\n\n{content}")

                downloaded += 1
                print(f"  [{idx}/{chapter_count}] {ch_title} ok ({word_count}字)")
            else:
                failed += 1
                print(f"  [{idx}/{chapter_count}] {ch_title} FAIL")

    try:
        with ThreadPoolExecutor(max_workers=actual_workers) as pool:
            pool.map(_download_one, pending)
    finally:
        jsonl_file.close()

    # 统计已有记录的字数
    for rec in chapter_records:
        if rec.get('index', -1) in existing_indices:
            total_words += rec.get('word_count', 0)

    # 尝试从起点获取统计数据（收藏、月票、推荐等）
    qidian_bid = None
    if qidian_meta:
        qidian_bid = qidian_meta.get('qidian_id', '')
    qidian_stats = None
    if qidian_bid:
        print(f"  正在从起点获取统计数据 (bid={qidian_bid}) ...")
        qidian_stats = fetch_qidian_stats(book_name, qidian_bid)
        if qidian_stats:
            print(f"    收藏: {qidian_stats.get('qidian_collect', 0):,}")
            print(f"    月票: {qidian_stats.get('qidian_month_ticket', 0):,}")
            print(f"    总推荐: {qidian_stats.get('qidian_recom_all', 0):,}")
            print(f"    标签: {qidian_stats.get('qidian_labels', [])}")
        else:
            print(f"    未获取到（可能被限流）")

    # 保存丰富的 metadata.json
    meta = {
        'id': book_id,
        'name': book_name,
        'author': author,
        'category': info.get('category', ''),
        'status': info.get('status', ''),
        'description': info.get('description', ''),
        'chapter_count': chapter_count,
        'downloaded_chapters': downloaded + skipped,
        'failed_chapters': failed,
        'total_words': total_words,
        'source_url': f"{BASE_URL}/du_{book_id}/",
        'source_site': 'qbxsw.com',
        'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }
    # 合并起点元信息（来自书单）
    if qidian_meta:
        meta['qidian_id'] = qidian_meta.get('qidian_id', '')
        meta['qidian_category'] = qidian_meta.get('category', '')
        meta['qidian_sub_category'] = qidian_meta.get('sub_category', '')
        meta['qidian_word_count'] = qidian_meta.get('word_count', '')
        meta['qidian_rank_info'] = qidian_meta.get('rank_info', '')
        meta['gender'] = qidian_meta.get('gender', '')
    # 合并起点实时统计数据
    if qidian_stats:
        meta.update(qidian_stats)

    meta_path = os.path.join(book_dir, 'metadata.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 按 index 排序所有记录
    chapter_records.sort(key=lambda x: x.get('index', 0))

    # 重写 chapters.jsonl（排序后覆盖，保证顺序正确）
    print(f"\n  正在整理 chapters.jsonl（按章节排序）...")
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for rec in chapter_records:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # 合并为完整纯文本
    print(f"  正在合并 full_text.txt ...")
    full_path = os.path.join(book_dir, 'full_text.txt')
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(f"书名：{book_name}\n作者：{author}\n\n{'='*40}\n\n")
        for rec in chapter_records:
            f.write(f"## {rec['title']}\n\n{rec['content']}\n\n{'─'*40}\n\n")

    print(f"\n  完成: {book_name}")
    print(f"     下载: {downloaded}, 跳过(已有): {skipped}, 失败: {failed}")
    print(f"     总字数: {total_words}")
    print(f"     目录: {book_dir}")
    return book_dir


# ============================================================
# 批量下载
# ============================================================
def batch_download(categories=None, rank_type="热门榜", max_per_category=10, output_base=OUTPUT_DIR):
    """
    按分类批量下载排行榜热门小说
    """
    if categories is None:
        categories = ["玄幻", "言情", "悬疑"]

    print("=" * 60)
    print("网络小说批量爬取工具")
    print(f"   分类: {', '.join(categories)}")
    print(f"   排行榜: {rank_type}")
    print(f"   每类最多: {max_per_category} 本")
    print(f"   输出目录: {output_base}")
    print("=" * 60)

    os.makedirs(output_base, exist_ok=True)

    # 记录已下载
    log_path = os.path.join(output_base, 'download_log.json')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            download_log = json.load(f)
    else:
        download_log = {}

    for cat in categories:
        print(f"\n\n{'#'*60}")
        print(f"# 分类: {cat}")
        print(f"{'#'*60}")

        # 先从分类页获取书籍
        books = get_category_books(cat, max_pages=3, max_books=max_per_category * 2)

        if len(books) < max_per_category:
            # 补充从排行榜获取
            rank_books = get_rank_books(rank_type)
            existing_ids = {b[0] for b in books}
            for b in rank_books:
                if b[0] not in existing_ids:
                    books.append(b)
                    existing_ids.add(b[0])

        # 筛选并下载
        count = 0
        for book_id, book_name, author in books:
            if count >= max_per_category:
                break

            if book_id in download_log:
                print(f"\n  ⏭️ 已下载过: {book_name} (id={book_id}), 跳过")
                count += 1
                continue

            result = download_book(book_id, output_base)
            if result:
                download_log[book_id] = {
                    'name': book_name,
                    'author': author,
                    'category': cat,
                    'dir': result,
                    'time': time.strftime('%Y-%m-%d %H:%M:%S'),
                }
                # 实时保存日志
                with open(log_path, 'w', encoding='utf-8') as f:
                    json.dump(download_log, f, ensure_ascii=False, indent=2)
                count += 1

    print(f"\n\n{'='*60}")
    print(f"🎉 全部完成！共下载 {len(download_log)} 本小说")
    print(f"   输出目录: {OUTPUT_DIR}")


# ============================================================
# 单本下载（按书名搜索）
# ============================================================
def download_by_name(name, output_base=OUTPUT_DIR):
    """按书名搜索并下载第一个匹配结果"""
    books = search_books(name)
    if not books:
        print(f"未找到: {name}")
        return None

    book_id, book_name, author = books[0]
    print(f"找到: {book_name} (id={book_id})")
    return download_book(book_id, output_base=output_base)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description='网络小说爬虫 - 学术研究用语料采集',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 批量下载玄幻、言情、悬疑各10本热门小说
  python novel_scraper.py --batch

  # 批量下载，每类5本
  python novel_scraper.py --batch --max 5

  # 只下载玄幻类
  python novel_scraper.py --batch --categories 玄幻

  # 按书名搜索并下载
  python novel_scraper.py --search "诡秘之主"

  # 按ID下载指定小说
  python novel_scraper.py --id 17701

  # 列出排行榜
  python novel_scraper.py --list-rank
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--batch', action='store_true', help='批量下载热门小说')
    group.add_argument('--search', type=str, help='按书名搜索并下载')
    group.add_argument('--id', type=str, help='按ID下载指定小说')
    group.add_argument('--list-rank', action='store_true', help='列出排行榜')
    group.add_argument('--list-category', type=str, help='列出某分类的小说')

    parser.add_argument('--categories', nargs='+', default=['玄幻', '言情', '悬疑'],
                        help='要爬取的分类 (默认: 玄幻 言情 悬疑)')
    parser.add_argument('--max', type=int, default=10,
                        help='每个分类最多下载几本 (默认: 10)')
    parser.add_argument('--rank', type=str, default='热门榜',
                        choices=['热门榜', '推荐榜', '收藏榜'],
                        help='排行榜类型 (默认: 热门榜)')
    parser.add_argument('--output', type=str, default=OUTPUT_DIR,
                        help=f'输出目录 (默认: {OUTPUT_DIR})')

    args = parser.parse_args()

    output_dir = args.output

    if args.batch:
        batch_download(
            categories=args.categories,
            rank_type=args.rank,
            max_per_category=args.max,
            output_base=output_dir,
        )
    elif args.search:
        download_by_name(args.search, output_base=output_dir)
    elif args.id:
        download_book(args.id, output_base=output_dir)
    elif args.list_rank:
        for rank_name in RANK_URLS:
            books = get_rank_books(rank_name, max_books=20)
            print(f"\n{'─'*40}")
            for i, (bid, name, author) in enumerate(books, 1):
                print(f"  {i:3d}. [{bid}] {name} / {author}")
    elif args.list_category:
        books = get_category_books(args.list_category, max_pages=3, max_books=50)
        for i, (bid, name, author) in enumerate(books, 1):
            print(f"  {i:3d}. [{bid}] {name}")


if __name__ == '__main__':
    main()
