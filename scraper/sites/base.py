#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多站点小说爬虫 - 基类

所有站点爬虫继承此类，实现统一接口。
输出格式与 novel_scraper.py 一致:
  data_{site}/书名_作者/
    metadata.json
    chapters.jsonl
"""

import os
import re
import json
import time
import random
import urllib.request
import urllib.parse
import threading
from concurrent.futures import ThreadPoolExecutor


class NovelSiteBase:
    """小说站点爬虫基类"""

    SITE_NAME = "base"          # 子类覆盖
    BASE_URL = ""               # 子类覆盖
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    MIN_DELAY = 0.1
    MAX_DELAY = 0.3
    MAX_RETRIES = 3
    MAX_WORKERS = 3
    ENCODING = "utf-8"

    def __init__(self, output_base=None):
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if output_base is None:
            output_base = os.path.join(project_dir, f"data_{self.SITE_NAME}")
        self.output_base = output_base
        os.makedirs(self.output_base, exist_ok=True)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._consecutive_fails = 0

    def fetch(self, url, retries=None):
        """带重试和冷却的 HTTP GET"""
        if retries is None:
            retries = self.MAX_RETRIES

        if self._consecutive_fails >= 5:
            cooldown = min(2 ** (self._consecutive_fails - 3), 120)
            print(f"  [冷却] 连续{self._consecutive_fails}次失败，等待{cooldown}s...", flush=True)
            time.sleep(cooldown)

        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, headers=self.HEADERS)
                resp = self._opener.open(req, timeout=15)
                data = resp.read().decode(self.ENCODING, errors="replace")
                self._consecutive_fails = 0
                return data
            except Exception as e:
                if attempt < retries - 1:
                    wait = (attempt + 1) * 2 + random.random()
                    time.sleep(wait)
                else:
                    self._consecutive_fails += 1
                    return None

    def polite_sleep(self):
        time.sleep(random.uniform(self.MIN_DELAY, self.MAX_DELAY))

    @staticmethod
    def sanitize_filename(name):
        name = re.sub(r'[<>:"/\\|?*]', '_', name)
        name = name.strip('. ')
        return name[:100]

    @staticmethod
    def clean_html(html_content):
        """通用 HTML → 纯文本"""
        text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</p>', '\n', text)
        text = re.sub(r'<p[^>]*>', '', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&amp;', '&').replace('&quot;', '"')
        return text

    # ---- 子类必须实现的接口 ----

    def get_book_list(self, category=None, max_pages=5) -> list[dict]:
        """
        获取书籍列表。返回:
        [{"book_id": "123", "name": "书名", "author": "作者", "category": "分类"}, ...]
        """
        raise NotImplementedError

    def get_chapters(self, book_id) -> tuple[dict, list[tuple[str, str]]]:
        """
        获取书籍信息和章节列表。返回:
        (book_info_dict, [(chapter_url, chapter_title), ...])
        """
        raise NotImplementedError

    def get_chapter_content(self, chapter_url) -> str:
        """获取单个章节的纯文本内容"""
        raise NotImplementedError

    def get_ad_patterns(self) -> list[str]:
        """返回本站特有的广告行正则模式列表"""
        return []

    # ---- 通用下载逻辑 ----

    def filter_ads(self, text):
        """过滤广告行"""
        patterns = self.get_ad_patterns()
        if not patterns:
            return text
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                cleaned.append(line)
                continue
            is_ad = False
            for pat in patterns:
                if re.match(pat, line_stripped):
                    is_ad = True
                    break
            if not is_ad:
                cleaned.append(line)
        return '\n'.join(cleaned)

    def download_book(self, book_id, extra_meta=None, skip_existing=True):
        """
        下载一本完整小说。返回输出目录路径或 None。
        """
        info, chapters = self.get_chapters(book_id)
        if not info or not chapters:
            return None

        book_name = info.get("name", f"book_{book_id}")
        author = info.get("author", "未知")
        print(f"\n  [{self.SITE_NAME}] {book_name} / {author} ({len(chapters)}章)")

        safe_name = self.sanitize_filename(f"{book_name}_{author}")
        book_dir = os.path.join(self.output_base, safe_name)
        os.makedirs(book_dir, exist_ok=True)

        # 断点续传
        jsonl_path = os.path.join(book_dir, "chapters.jsonl")
        existing = set()
        records = []
        if skip_existing and os.path.exists(jsonl_path):
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        existing.add(obj.get("index", -1))
                        records.append(obj)
                    except json.JSONDecodeError:
                        pass

        if len(existing) >= len(chapters):
            print(f"    已下载完成，跳过")
            return book_dir

        pending = [(i, url, title) for i, (url, title)
                   in enumerate(chapters, 1) if i not in existing]

        downloaded = 0
        failed = 0
        _lock = threading.Lock()
        jsonl_file = open(jsonl_path, "a", encoding="utf-8")

        def _download_one(task):
            nonlocal downloaded, failed
            idx, ch_url, ch_title = task
            content = self.get_chapter_content(ch_url)

            with _lock:
                if content and len(content) > 10:
                    content = self.filter_ads(content)
                    word_count = len(content)
                    record = {
                        "index": idx,
                        "title": ch_title,
                        "word_count": word_count,
                        "content": content,
                    }
                    jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    jsonl_file.flush()
                    records.append(record)
                    downloaded += 1
                    if downloaded % 50 == 0:
                        print(f"    [{idx}/{len(chapters)}] {downloaded} 章已下载...", flush=True)
                else:
                    failed += 1

        try:
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as pool:
                pool.map(_download_one, pending)
        finally:
            jsonl_file.close()

        # 排序 jsonl
        records.sort(key=lambda x: x.get("index", 0))
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 写 metadata
        total_words = sum(r.get("word_count", 0) for r in records)
        meta = {
            "name": book_name,
            "author": author,
            "category": info.get("category", ""),
            "status": info.get("status", ""),
            "chapter_count": len(chapters),
            "downloaded_chapters": len(records),
            "failed_chapters": failed,
            "total_words": total_words,
            "source_url": f"{self.BASE_URL}",
            "source_site": self.SITE_NAME,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if extra_meta:
            meta.update(extra_meta)

        with open(os.path.join(book_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f"    完成: {downloaded} 下载, {len(existing)} 跳过, {failed} 失败, {total_words:,} 字")
        return book_dir

    def batch_download(self, category=None, max_books=100, max_pages=5):
        """批量下载某个分类的书籍"""
        books = self.get_book_list(category=category, max_pages=max_pages)
        if not books:
            print(f"  [{self.SITE_NAME}] 未找到书籍")
            return

        # 去重（排除已下载）
        existing_dirs = set(os.listdir(self.output_base)) if os.path.isdir(self.output_base) else set()
        pending = []
        for book in books:
            safe = self.sanitize_filename(f"{book['name']}_{book.get('author', '未知')}")
            if safe not in existing_dirs:
                pending.append(book)

        pending = pending[:max_books]
        print(f"  [{self.SITE_NAME}] 分类={category or '全部'}, "
              f"找到 {len(books)} 本, 待下载 {len(pending)} 本")

        success = 0
        for i, book in enumerate(pending, 1):
            print(f"\n  [{i}/{len(pending)}] {book['name']}")
            result = self.download_book(
                book["book_id"],
                extra_meta={"category": book.get("category", "")},
            )
            if result:
                success += 1
            self.polite_sleep()

        print(f"\n  [{self.SITE_NAME}] 完成: {success}/{len(pending)}")
