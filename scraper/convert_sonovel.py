#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
so-novel TXT → 标准格式转换器

将 tools/SoNovel/downloads/ 中的 TXT 文件转换为
data/ 标准结构：书名_作者/metadata.json + chapters.jsonl

同时从 sonovel_download_log.json 和 discovered_books.json
中提取元数据（数据源、分类、标签等）。

用法:
  python -m scraper.convert_sonovel                  # 转换所有新下载
  python -m scraper.convert_sonovel --stats          # 查看统计
  python -m scraper.convert_sonovel --output data    # 输出到 data/ 目录
"""

import os
import sys
import json
import re
import time
import argparse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SONOVEL_DOWNLOAD_DIR = os.path.join(PROJECT_DIR, "tools", "SoNovel", "downloads")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_DIR, "data")
DOWNLOAD_LOG_PATH = os.path.join(PROJECT_DIR, "sonovel_download_log.json")
DISCOVERED_PATH = os.path.join(PROJECT_DIR, "discovered_books.json")

os.environ["PYTHONUNBUFFERED"] = "1"
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 常见的章节标题模式
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


def is_chapter_title(line):
    """判断一行是否是章节标题"""
    line = line.strip()
    if not line or len(line) > 60:
        return False
    for pat in CHAPTER_PATTERNS:
        if pat.match(line):
            return True
    return False


def parse_txt(filepath):
    """
    解析 so-novel 输出的 TXT 文件为章节列表。

    so-novel TXT 格式：
      书名（作者）

      第一章 标题
      正文...

      第二章 标题
      正文...

    返回: (book_name, author, [(title, content), ...])
    """
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")

    # 从文件名提取书名和作者: "书名(作者).txt"
    filename = os.path.basename(filepath).replace(".txt", "")
    book_name = filename
    author = "未知"
    m = re.match(r"^(.+?)\((.+?)\)$", filename)
    if m:
        book_name = m.group(1).strip()
        author = m.group(2).strip()

    # 按章节标题切分
    chapters = []
    current_title = ""
    current_lines = []

    for line in lines:
        if is_chapter_title(line):
            # 保存上一章
            if current_title and current_lines:
                content = "\n".join(current_lines).strip()
                if len(content) > 10:
                    chapters.append((current_title, content))
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    # 最后一章
    if current_title and current_lines:
        content = "\n".join(current_lines).strip()
        if len(content) > 10:
            chapters.append((current_title, content))

    return book_name, author, chapters


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip('. ')[:100]


def convert_one(txt_path, output_dir, metadata_extra=None):
    """转换一个 TXT 文件为标准格式"""
    book_name, author, chapters = parse_txt(txt_path)

    if not chapters:
        return None

    safe_name = sanitize_filename(f"{book_name}_{author}")
    book_dir = os.path.join(output_dir, safe_name)

    # 跳过已存在的
    if os.path.exists(os.path.join(book_dir, "chapters.jsonl")):
        return "exists"

    os.makedirs(book_dir, exist_ok=True)

    # 写 chapters.jsonl
    total_words = 0
    total_hanzi = 0
    jsonl_path = os.path.join(book_dir, "chapters.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for i, (title, content) in enumerate(chapters, 1):
            word_count = len(content)
            hanzi_count = len(CJK_RE.findall(content))
            total_words += word_count
            total_hanzi += hanzi_count
            record = {
                "index": i,
                "title": title,
                "word_count": word_count,
                "content": content,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 写 metadata.json
    meta = {
        "name": book_name,
        "author": author,
        "chapter_count": len(chapters),
        "downloaded_chapters": len(chapters),
        "failed_chapters": 0,
        "total_words": total_words,
        "total_hanzi": total_hanzi,
        "source_site": "sonovel",
        "source_format": "txt",
        "source_file": os.path.basename(txt_path),
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 合并额外元数据
    if metadata_extra:
        meta.update(metadata_extra)

    with open(os.path.join(book_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "name": book_name,
        "author": author,
        "chapters": len(chapters),
        "words": total_words,
        "hanzi": total_hanzi,
        "dir": book_dir,
    }


def load_metadata_lookup():
    """从下载日志和发现清单中构建元数据查找表"""
    lookup = {}  # book_name -> extra metadata

    # 从下载日志
    if os.path.exists(DOWNLOAD_LOG_PATH):
        with open(DOWNLOAD_LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
        for name, info in log.get("downloaded", {}).items():
            lookup[name] = {
                "sonovel_source": info.get("source", ""),
                "sonovel_author": info.get("author", ""),
                "category": info.get("category", ""),
                "download_time": info.get("time", ""),
            }

    # 从发现清单补充
    if os.path.exists(DISCOVERED_PATH):
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for book in data.get("books", []):
            name = book.get("name", "")
            if name and name not in lookup:
                lookup[name] = {
                    "category": book.get("category", ""),
                    "sonovel_source": book.get("source", ""),
                    "discovered_url": book.get("url", ""),
                }
            elif name in lookup and not lookup[name].get("category"):
                lookup[name]["category"] = book.get("category", "")

    return lookup


def main():
    parser = argparse.ArgumentParser(description="so-novel TXT 转换器")
    parser.add_argument("--output", type=str, default=DEFAULT_OUTPUT_DIR,
                        help=f"输出目录 (默认 {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--stats", action="store_true", help="查看统计")
    args = parser.parse_args()

    if not os.path.isdir(SONOVEL_DOWNLOAD_DIR):
        print(f"下载目录不存在: {SONOVEL_DOWNLOAD_DIR}")
        return

    txt_files = [f for f in os.listdir(SONOVEL_DOWNLOAD_DIR) if f.endswith(".txt")]

    if args.stats:
        total_size = sum(
            os.path.getsize(os.path.join(SONOVEL_DOWNLOAD_DIR, f))
            for f in txt_files
        )
        print(f"TXT 文件: {len(txt_files)} 个, {total_size/1e9:.2f} GB")
        return

    if not txt_files:
        print("无 TXT 文件可转换")
        return

    # 加载元数据查找表
    lookup = load_metadata_lookup()

    print(f"{'='*60}")
    print(f"so-novel TXT → 标准格式转换")
    print(f"  输入: {SONOVEL_DOWNLOAD_DIR} ({len(txt_files)} 个 TXT)")
    print(f"  输出: {args.output}")
    print(f"  元数据: {len(lookup)} 条")
    print(f"{'='*60}")

    os.makedirs(args.output, exist_ok=True)

    converted = 0
    skipped = 0
    failed = 0
    total_chapters = 0
    total_hanzi = 0

    for i, txt_file in enumerate(sorted(txt_files), 1):
        txt_path = os.path.join(SONOVEL_DOWNLOAD_DIR, txt_file)
        name = txt_file.replace(".txt", "")
        # 提取书名（去掉作者部分）
        book_name = name
        if "(" in name:
            book_name = name.split("(")[0].strip()

        extra_meta = lookup.get(book_name, {})

        result = convert_one(txt_path, args.output, metadata_extra=extra_meta)
        if result == "exists":
            skipped += 1
        elif result is None:
            failed += 1
        else:
            converted += 1
            total_chapters += result["chapters"]
            total_hanzi += result["hanzi"]

        if i % 100 == 0 or i == len(txt_files):
            print(f"[{i}/{len(txt_files)}] 转换: {converted}, 跳过: {skipped}, "
                  f"失败: {failed}, 章节: {total_chapters:,}, "
                  f"汉字: {total_hanzi/1e8:.2f}亿", flush=True)

    print(f"\n{'='*60}")
    print(f"转换完成!")
    print(f"  转换: {converted}")
    print(f"  跳过(已存在): {skipped}")
    print(f"  失败(无章节): {failed}")
    print(f"  总章节: {total_chapters:,}")
    print(f"  总汉字: {total_hanzi:,} ({total_hanzi/1e8:.2f}亿)")


if __name__ == "__main__":
    main()
