#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一格式转换器

将所有数据源转换为统一的 books/ 目录结构：
  books/分类/书名_作者/
    book.json        # 结构化元数据
    chapters.jsonl   # 每行一章 {index, title, word_count, hanzi_count, content}

支持的输入源：
  1. data/ — qbxsw 原始爬取数据（metadata.json + chapters.jsonl）
  2. tools/SoNovel/downloads/ — so-novel 下载的 TXT 文件
  3. (后续) Pixiv、开源数据集等

同时生成 library_index.json 全局索引。

用法:
  python -m scraper.convert_to_unified                       # 转换全部
  python -m scraper.convert_to_unified --source qbxsw        # 只转 qbxsw
  python -m scraper.convert_to_unified --source sonovel      # 只转 so-novel TXT
  python -m scraper.convert_to_unified --index-only          # 只重建索引
  python -m scraper.convert_to_unified --stats               # 查看统计
"""

import os
import sys
import json
import re
import time
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QBXSW_DATA_DIR = os.path.join(PROJECT_DIR, "data")
SONOVEL_DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "tools", "SoNovel", "downloads")
SONOVEL_LOG_PATH = os.path.join(PROJECT_DIR, "sonovel_download_log.json")
DISCOVERED_PATH = os.path.join(PROJECT_DIR, "discovered_books.json")
BOOKS_DIR = os.path.join(PROJECT_DIR, "books")
INDEX_PATH = os.path.join(PROJECT_DIR, "library_index.json")

os.environ["PYTHONUNBUFFERED"] = "1"
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 章节标题正则
CHAPTER_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千万零\d]+[章节回卷集篇]"),
    re.compile(r"^Chapter\s*\d+", re.IGNORECASE),
    re.compile(r"^[【\[]?第?\d+[章节回]\s"),
    re.compile(r"^卷[一二三四五六七八九十\d]"),
    re.compile(r"^序[章篇言]"),
    re.compile(r"^楔子"),
    re.compile(r"^尾声"),
    re.compile(r"^番外"),
]


def count_hanzi(text):
    return len(CJK_RE.findall(text))


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip('. ')[:100]


def is_chapter_title(line):
    line = line.strip()
    if not line or len(line) > 60:
        return False
    for pat in CHAPTER_PATTERNS:
        if pat.match(line):
            return True
    return False


def classify_quality(meta):
    """基于收藏数分级"""
    collect = 0
    for key in ["qidian_collect", "collect"]:
        val = meta.get(key, 0)
        if val and isinstance(val, (int, float)):
            collect = max(collect, int(val))
    if collect >= 100_000:
        return "S"
    elif collect >= 10_000:
        return "A"
    elif collect >= 1_000:
        return "B"
    return "C"


def make_book_json(title, author, description="", category="未分类",
                   sub_category="", tags=None, gender="", status="",
                   chapter_count=0, word_count=0, hanzi_count=0,
                   quality_data=None, sources=None, book_id=""):
    """构造标准 book.json"""
    return {
        "book_id": book_id,
        "title": title,
        "author": author,
        "description": description,
        "classification": {
            "category": category,
            "sub_category": sub_category,
            "tags": tags or [],
            "gender": gender,
        },
        "stats": {
            "chapter_count": chapter_count,
            "word_count": word_count,
            "hanzi_count": hanzi_count,
            "status": status,
        },
        "quality": quality_data or {
            "tier": "C",
            "qidian_collect": None,
            "qidian_recom": None,
            "douban_rating": None,
            "jjwxc_score": None,
        },
        "sources": sources or [],
    }


# ============================================================
# Source 1: qbxsw data/
# ============================================================
def convert_qbxsw_book(book_dir_name):
    """转换一本 qbxsw 数据"""
    src_dir = os.path.join(QBXSW_DATA_DIR, book_dir_name)
    meta_path = os.path.join(src_dir, "metadata.json")
    jsonl_path = os.path.join(src_dir, "chapters.jsonl")

    if not os.path.exists(jsonl_path):
        return None

    # 读 metadata
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            try:
                meta = json.load(f)
            except json.JSONDecodeError:
                pass

    title = meta.get("name", book_dir_name.split("_")[0])
    author = meta.get("author", "未知")
    category = meta.get("qidian_category", "") or meta.get("category", "") or "未分类"

    # 读章节并添加 hanzi_count
    chapters = []
    total_words = 0
    total_hanzi = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ch = json.loads(line)
                hz = count_hanzi(ch.get("content", ""))
                ch["hanzi_count"] = hz
                total_words += ch.get("word_count", 0)
                total_hanzi += hz
                chapters.append(ch)
            except json.JSONDecodeError:
                continue

    if not chapters:
        return None

    # 确定输出目录
    safe_cat = sanitize_filename(category) if category else "未分类"
    safe_name = sanitize_filename(f"{title}_{author}")
    out_dir = os.path.join(BOOKS_DIR, safe_cat, safe_name)
    os.makedirs(out_dir, exist_ok=True)

    # 写 chapters.jsonl
    chapters.sort(key=lambda x: x.get("index", 0))
    with open(os.path.join(out_dir, "chapters.jsonl"), "w", encoding="utf-8") as f:
        for ch in chapters:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    # 构造 book.json
    quality = {
        "tier": classify_quality(meta),
        "qidian_collect": meta.get("qidian_collect"),
        "qidian_recom": meta.get("qidian_recom_all"),
        "qidian_month_ticket": meta.get("qidian_month_ticket"),
        "douban_rating": meta.get("douban_rating"),
        "jjwxc_score": meta.get("jjwxc_score"),
    }

    book = make_book_json(
        title=title, author=author,
        description=meta.get("description", ""),
        category=category,
        sub_category=meta.get("qidian_sub_category", ""),
        tags=meta.get("qidian_labels", []),
        gender=meta.get("gender", ""),
        status=meta.get("qidian_status", "") or meta.get("status", ""),
        chapter_count=len(chapters),
        word_count=total_words,
        hanzi_count=total_hanzi,
        quality_data=quality,
        sources=[{
            "site": meta.get("source_site", "qbxsw.com"),
            "url": meta.get("source_url", ""),
            "scraped_at": meta.get("scraped_at", ""),
        }],
        book_id=f"qbxsw_{meta.get('id', '')}",
    )

    with open(os.path.join(out_dir, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)

    return book


# ============================================================
# Source 2: so-novel TXT
# ============================================================
def _load_sonovel_metadata():
    """加载 so-novel 下载日志和发现清单"""
    lookup = {}
    if os.path.exists(SONOVEL_LOG_PATH):
        with open(SONOVEL_LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
        for name, info in log.get("downloaded", {}).items():
            lookup[name] = info
    if os.path.exists(DISCOVERED_PATH):
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for b in data.get("books", []):
            name = b.get("name", "")
            if name and name not in lookup:
                lookup[name] = {"category_discovered": b.get("category", ""),
                                "sonovel_source": b.get("source", "")}
    return lookup


def convert_sonovel_txt(txt_filename, sonovel_meta_lookup):
    """转换一个 so-novel TXT"""
    txt_path = os.path.join(SONOVEL_DOWNLOAD_DIR, txt_filename)

    # 从文件名提取书名和作者
    filename = txt_filename.replace(".txt", "")
    title = filename
    author = "未知"
    m = re.match(r"^(.+?)\((.+?)\)$", filename)
    if m:
        title = m.group(1).strip()
        author = m.group(2).strip()

    # 读取 TXT 并切分章节
    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    chapters = []
    current_title = ""
    current_lines = []

    for line in lines:
        if is_chapter_title(line):
            if current_title and current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) > 10:
                    chapters.append((current_title, content))
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title and current_lines:
        content = "\n".join(current_lines).strip()
        if len(content) > 10:
            chapters.append((current_title, content))

    if not chapters:
        return None

    # 查找元数据
    extra = sonovel_meta_lookup.get(title, {})
    category = extra.get("category_discovered", "") or extra.get("category", "") or "未分类"

    # 输出目录
    safe_cat = sanitize_filename(category) if category else "未分类"
    safe_name = sanitize_filename(f"{title}_{author}")
    out_dir = os.path.join(BOOKS_DIR, safe_cat, safe_name)
    os.makedirs(out_dir, exist_ok=True)

    # 写 chapters.jsonl
    total_words = 0
    total_hanzi = 0
    with open(os.path.join(out_dir, "chapters.jsonl"), "w", encoding="utf-8") as f:
        for i, (ch_title, content) in enumerate(chapters, 1):
            wc = len(content)
            hz = count_hanzi(content)
            total_words += wc
            total_hanzi += hz
            record = {
                "index": i,
                "title": ch_title,
                "word_count": wc,
                "hanzi_count": hz,
                "content": content,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 构造 book.json
    source_info = {
        "site": f"sonovel/{extra.get('sonovel_source', extra.get('source', 'unknown'))}",
        "url": extra.get("source_url", extra.get("discovered_url", "")),
        "scraped_at": extra.get("time", time.strftime("%Y-%m-%d")),
    }

    book = make_book_json(
        title=title, author=author,
        category=category,
        sub_category=extra.get("category_from_source", ""),
        chapter_count=len(chapters),
        word_count=total_words,
        hanzi_count=total_hanzi,
        sources=[source_info],
        book_id=f"sonovel_{sanitize_filename(title)}",
    )

    with open(os.path.join(out_dir, "book.json"), "w", encoding="utf-8") as f:
        json.dump(book, f, ensure_ascii=False, indent=2)

    return book


# ============================================================
# 全局索引
# ============================================================
def build_index():
    """遍历 books/ 目录生成 library_index.json"""
    books = []
    total_chapters = 0
    total_hanzi = 0

    for cat_dir in sorted(os.listdir(BOOKS_DIR)):
        cat_path = os.path.join(BOOKS_DIR, cat_dir)
        if not os.path.isdir(cat_path):
            continue
        for book_dir in sorted(os.listdir(cat_path)):
            book_path = os.path.join(cat_path, book_dir)
            book_json_path = os.path.join(book_path, "book.json")
            if not os.path.exists(book_json_path):
                continue
            with open(book_json_path, "r", encoding="utf-8") as f:
                book = json.load(f)
            book["file_path"] = f"books/{cat_dir}/{book_dir}/chapters.jsonl"
            books.append(book)
            total_chapters += book.get("stats", {}).get("chapter_count", 0)
            total_hanzi += book.get("stats", {}).get("hanzi_count", 0)

    index = {
        "version": "1.0",
        "total_books": len(books),
        "total_chapters": total_chapters,
        "total_hanzi": total_hanzi,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "books": books,
    }

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    return index


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="统一格式转换器")
    parser.add_argument("--source", choices=["qbxsw", "sonovel", "all"], default="all",
                        help="转换哪个数据源")
    parser.add_argument("--index-only", action="store_true", help="只重建索引")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    parser.add_argument("--workers", type=int, default=8, help="并行度")
    args = parser.parse_args()

    os.makedirs(BOOKS_DIR, exist_ok=True)

    if args.stats or args.index_only:
        index = build_index()
        cats = {}
        tiers = {}
        for b in index["books"]:
            cat = b.get("classification", {}).get("category", "未分类")
            tier = b.get("quality", {}).get("tier", "C")
            cats[cat] = cats.get(cat, 0) + 1
            tiers[tier] = tiers.get(tier, 0) + 1

        print(f"图书馆统计:")
        print(f"  总书目:    {index['total_books']:,}")
        print(f"  总章节:    {index['total_chapters']:,}")
        print(f"  总汉字:    {index['total_hanzi']:,} ({index['total_hanzi']/1e8:.2f}亿)")
        print(f"\n  质量分级:")
        for t in ["S", "A", "B", "C"]:
            print(f"    {t}: {tiers.get(t, 0)}")
        print(f"\n  分类分布:")
        for cat, cnt in sorted(cats.items(), key=lambda x: -x[1])[:15]:
            print(f"    {cat:12s} {cnt:>5}")
        return

    start_time = time.time()

    # === 转换 qbxsw ===
    if args.source in ("qbxsw", "all") and os.path.isdir(QBXSW_DATA_DIR):
        qbxsw_books = [d for d in os.listdir(QBXSW_DATA_DIR)
                       if os.path.isdir(os.path.join(QBXSW_DATA_DIR, d))]
        print(f"\n转换 qbxsw: {len(qbxsw_books)} 本", flush=True)

        converted = 0
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(convert_qbxsw_book, d): d for d in qbxsw_books}
            done = 0
            for future in as_completed(futures):
                done += 1
                result = future.result()
                if result:
                    converted += 1
                if done % 200 == 0 or done == len(qbxsw_books):
                    print(f"  [{done}/{len(qbxsw_books)}] 转换: {converted}", flush=True)
        print(f"  qbxsw 完成: {converted} 本", flush=True)

    # === 转换 so-novel TXT ===
    if args.source in ("sonovel", "all") and os.path.isdir(SONOVEL_DOWNLOAD_DIR):
        txt_files = [f for f in os.listdir(SONOVEL_DOWNLOAD_DIR) if f.endswith(".txt")]
        print(f"\n转换 so-novel: {len(txt_files)} 个 TXT", flush=True)

        sonovel_meta = _load_sonovel_metadata()
        converted = 0
        for i, txt_file in enumerate(sorted(txt_files), 1):
            result = convert_sonovel_txt(txt_file, sonovel_meta)
            if result:
                converted += 1
            if i % 100 == 0 or i == len(txt_files):
                print(f"  [{i}/{len(txt_files)}] 转换: {converted}", flush=True)
        print(f"  so-novel 完成: {converted} 本", flush=True)

    # === 生成全局索引 ===
    print(f"\n生成 library_index.json ...", flush=True)
    index = build_index()
    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"统一格式转换完成!")
    print(f"  总书目: {index['total_books']:,}")
    print(f"  总章节: {index['total_chapters']:,}")
    print(f"  总汉字: {index['total_hanzi']:,} ({index['total_hanzi']/1e8:.2f}亿)")
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  输出: {BOOKS_DIR}")
    print(f"  索引: {INDEX_PATH}")


if __name__ == "__main__":
    main()
