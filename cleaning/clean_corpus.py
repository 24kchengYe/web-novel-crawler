#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网络小说语料清洗管线

读取 data/ 原始数据，输出清洗后的数据到 data_cleaned/。
原始 data/ 目录不做任何修改。

清洗步骤:
  1. 去除网站水印 / 广告行 / 站点插入文本
  2. 去除乱码、控制字符
  3. 标点与空白归一化
  4. 短章过滤（纯汉字 < 100 字的章节丢弃）
  5. 基于 metadata 的质量分级 (S/A/B/C)
  6. 输出清洗后的 chapters_cleaned.jsonl + 统计报告

用法:
  python -m cleaning.clean_corpus                # 清洗全部
  python -m cleaning.clean_corpus --limit 10     # 只处理前 10 本（调试用）
  python -m cleaning.clean_corpus --stats        # 只输出统计，不清洗
"""

import os
import sys
import json
import re
import time
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

# ============================================================
# 路径
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_DIR = os.path.join(PROJECT_DIR, "data")
CLEAN_DATA_DIR = os.path.join(PROJECT_DIR, "data_cleaned")
REPORT_PATH = os.path.join(CLEAN_DATA_DIR, "cleaning_report.json")

# ============================================================
# 水印 / 广告模式（编译一次，复用）
# ============================================================
# 整行匹配删除的水印文本（精确匹配）
WATERMARK_EXACT = {
    "小主，这个章节后面还有哦，请点击下一页继续阅读，后面更精彩！",
    "这章没有结束，请点击下一页继续阅读！",
}

# 正则匹配的广告模式（匹配到的整行删除）
WATERMARK_PATTERNS = [
    re.compile(p) for p in [
        r".*全本小说网.*更新速度.*",
        r".*www\.qbxsw\.com.*",
        r".*qbxsw\.com.*",
        r".*请大家收藏.*最新章节.*",
        r".*本小?章还?未完.*点击下一页.*",
        r".*最新章节.*全网最快.*",
        r".*手机用户请浏览.*阅读.*",
        r".*一秒记住.*网址.*",
        r".*记住网址.*",
        r".*免费阅读.*全文.*",
        r".*zhenhunxiaoshuo.*",
        r".*ixdzs8?\.com.*",
        r".*本章未完.*点击.*",
        r".*后面还有哦.*点击下一页.*",
        r".*请点击下一页继续阅读.*",
        r".*这章没有结束.*",
        r".*小主.*这个章节.*",
        r".*喜欢.*请大家收藏.*",
        r".*加入书签.*方便.*",
    ]
]

# 控制字符与零宽字符
CTRL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f"
    r"\u200b-\u200f\u2028-\u202f\u2060\ufeff\ufff9-\ufffc]"
)

# CJK 汉字判断
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 多个连续空行 → 最多保留一个
MULTI_BLANK_RE = re.compile(r"\n{3,}")

# 多个连续空格 → 单个空格
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


# ============================================================
# 核心清洗函数
# ============================================================
def clean_chapter_text(text: str) -> str:
    """
    对单个章节的文本执行清洗。
    返回清洗后的文本。
    """
    # 1. 控制字符 / 零宽字符
    text = CTRL_CHAR_RE.sub("", text)

    # 2. 逐行处理：去水印、去广告
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()

        # 精确匹配水印 → 跳过
        if stripped in WATERMARK_EXACT:
            continue

        # 正则匹配广告 → 跳过
        is_ad = False
        for pat in WATERMARK_PATTERNS:
            if pat.match(stripped):
                is_ad = True
                break
        if is_ad:
            continue

        # 纯空行保留（后面统一压缩）
        if not stripped:
            cleaned_lines.append("")
            continue

        cleaned_lines.append(stripped)

    text = "\n".join(cleaned_lines)

    # 3. 标点归一化
    # 半角引号 → 中文引号（小说场景下更常见）
    text = text.replace('"', '\u201c').replace('"', '\u201d')

    # 连续省略号归一化：…… 或 ... 或 。。。 → ……
    text = re.sub(r"\.{3,}", "……", text)
    text = re.sub(r"。{2,}", "……", text)
    text = re.sub(r"…{3,}", "……", text)

    # 4. 空白归一化
    text = MULTI_SPACE_RE.sub(" ", text)
    text = MULTI_BLANK_RE.sub("\n\n", text)
    text = text.strip()

    return text


def count_hanzi(text: str) -> int:
    """统计纯汉字数量"""
    return len(CJK_RE.findall(text))


# ============================================================
# 质量分级
# ============================================================
def classify_quality(metadata: dict) -> str:
    """
    基于起点收藏数对小说进行质量分级:
      S: 收藏 >= 100,000   （头部精品）
      A: 收藏 >= 10,000    （优质）
      B: 收藏 >= 1,000     （普通）
      C: 收藏 < 1,000 或无数据（长尾/无评级）
    """
    collect = metadata.get("qidian_collect", 0)
    if not isinstance(collect, (int, float)):
        try:
            collect = int(collect)
        except (ValueError, TypeError):
            collect = 0

    if collect >= 100_000:
        return "S"
    elif collect >= 10_000:
        return "A"
    elif collect >= 1_000:
        return "B"
    else:
        return "C"


# ============================================================
# 单本书清洗
# ============================================================
def clean_one_book(book_dir_name: str) -> dict:
    """
    清洗一本书。返回统计信息 dict。
    在子进程中执行，不使用全局可变状态。
    """
    raw_dir = os.path.join(RAW_DATA_DIR, book_dir_name)
    jsonl_path = os.path.join(raw_dir, "chapters.jsonl")
    meta_path = os.path.join(raw_dir, "metadata.json")

    result = {
        "book": book_dir_name,
        "status": "ok",
        "raw_chapters": 0,
        "clean_chapters": 0,
        "dropped_chapters": 0,
        "raw_chars": 0,
        "raw_hanzi": 0,
        "clean_chars": 0,
        "clean_hanzi": 0,
        "watermarks_removed": 0,
        "quality": "C",
        "category": "",
    }

    # 读 metadata
    metadata = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            try:
                metadata = json.load(f)
            except json.JSONDecodeError:
                pass

    result["quality"] = classify_quality(metadata)
    result["category"] = metadata.get("qidian_category", "") or metadata.get("category", "")

    # 读原始章节
    if not os.path.exists(jsonl_path):
        result["status"] = "no_jsonl"
        return result

    raw_chapters = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw_chapters.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    result["raw_chapters"] = len(raw_chapters)

    if not raw_chapters:
        result["status"] = "empty_jsonl"
        return result

    # 清洗每一章
    clean_dir = os.path.join(CLEAN_DATA_DIR, book_dir_name)
    os.makedirs(clean_dir, exist_ok=True)

    cleaned_records = []
    total_watermarks = 0

    for ch in raw_chapters:
        raw_content = ch.get("content", "")
        raw_char_count = len(raw_content)
        raw_hanzi_count = count_hanzi(raw_content)
        result["raw_chars"] += raw_char_count
        result["raw_hanzi"] += raw_hanzi_count

        # 清洗
        clean_content = clean_chapter_text(raw_content)
        clean_hanzi_count = count_hanzi(clean_content)

        # 统计去除的水印行数（近似：原始汉字 - 清洗后汉字 的差值中，
        # 很大一部分来自水印行）
        watermarks_this = max(0, raw_hanzi_count - clean_hanzi_count)
        # 更精确：按行差异估算
        raw_line_count = raw_content.count("\n") + 1
        clean_line_count = clean_content.count("\n") + 1
        watermark_lines = max(0, raw_line_count - clean_line_count)
        total_watermarks += watermark_lines

        # 短章过滤：纯汉字 < 100 字的章节丢弃
        if clean_hanzi_count < 100:
            result["dropped_chapters"] += 1
            continue

        result["clean_chars"] += len(clean_content)
        result["clean_hanzi"] += clean_hanzi_count

        cleaned_records.append({
            "index": ch.get("index", 0),
            "title": ch.get("title", ""),
            "hanzi_count": clean_hanzi_count,
            "content": clean_content,
        })

    result["clean_chapters"] = len(cleaned_records)
    result["watermarks_removed"] = total_watermarks

    # 写清洗后的 jsonl
    if cleaned_records:
        cleaned_records.sort(key=lambda x: x["index"])
        out_jsonl = os.path.join(clean_dir, "chapters_cleaned.jsonl")
        with open(out_jsonl, "w", encoding="utf-8") as f:
            for rec in cleaned_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 复制 metadata 并追加清洗信息
        clean_meta = dict(metadata)
        clean_meta["cleaning"] = {
            "raw_chapters": result["raw_chapters"],
            "clean_chapters": result["clean_chapters"],
            "dropped_chapters": result["dropped_chapters"],
            "raw_hanzi": result["raw_hanzi"],
            "clean_hanzi": result["clean_hanzi"],
            "quality_tier": result["quality"],
            "cleaned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(os.path.join(clean_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(clean_meta, f, ensure_ascii=False, indent=2)

    return result


# ============================================================
# 统计报告
# ============================================================
def generate_report(results: list[dict]) -> dict:
    """汇总所有书的清洗结果为报告"""
    report = {
        "total_books": len(results),
        "books_ok": sum(1 for r in results if r["status"] == "ok"),
        "books_no_jsonl": sum(1 for r in results if r["status"] == "no_jsonl"),
        "books_empty": sum(1 for r in results if r["status"] == "empty_jsonl"),
        "total_raw_chapters": sum(r["raw_chapters"] for r in results),
        "total_clean_chapters": sum(r["clean_chapters"] for r in results),
        "total_dropped_chapters": sum(r["dropped_chapters"] for r in results),
        "total_raw_hanzi": sum(r["raw_hanzi"] for r in results),
        "total_clean_hanzi": sum(r["clean_hanzi"] for r in results),
        "total_watermark_lines_removed": sum(r["watermarks_removed"] for r in results),
        "quality_distribution": {},
        "category_distribution": {},
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 质量分布
    for tier in ["S", "A", "B", "C"]:
        tier_books = [r for r in results if r["quality"] == tier and r["status"] == "ok"]
        report["quality_distribution"][tier] = {
            "books": len(tier_books),
            "hanzi": sum(r["clean_hanzi"] for r in tier_books),
        }

    # 分类分布
    cats = {}
    for r in results:
        cat = r.get("category", "") or "未知"
        if cat not in cats:
            cats[cat] = {"books": 0, "hanzi": 0}
        cats[cat]["books"] += 1
        cats[cat]["hanzi"] += r["clean_hanzi"]
    report["category_distribution"] = dict(
        sorted(cats.items(), key=lambda x: -x[1]["hanzi"])
    )

    return report


def print_report(report: dict):
    """打印报告摘要"""
    print(f"\n{'='*60}")
    print("清洗完成 — 统计报告")
    print(f"{'='*60}")
    print(f"  书籍总数:         {report['total_books']}")
    print(f"  有效书籍:         {report['books_ok']}")
    print(f"  原始章节:         {report['total_raw_chapters']:,}")
    print(f"  清洗后章节:       {report['total_clean_chapters']:,}")
    print(f"  丢弃章节:         {report['total_dropped_chapters']:,}")
    print(f"  原始汉字:         {report['total_raw_hanzi']:,} ({report['total_raw_hanzi']/1e8:.2f} 亿)")
    print(f"  清洗后汉字:       {report['total_clean_hanzi']:,} ({report['total_clean_hanzi']/1e8:.2f} 亿)")
    hanzi_diff = report["total_raw_hanzi"] - report["total_clean_hanzi"]
    pct = hanzi_diff / report["total_raw_hanzi"] * 100 if report["total_raw_hanzi"] > 0 else 0
    print(f"  清洗去除:         {hanzi_diff:,} 字 ({pct:.1f}%)")
    print(f"  水印行删除:       {report['total_watermark_lines_removed']:,}")

    print(f"\n  质量分级:")
    for tier in ["S", "A", "B", "C"]:
        info = report["quality_distribution"].get(tier, {})
        n = info.get("books", 0)
        h = info.get("hanzi", 0)
        print(f"    {tier}: {n:4d} 本, {h/1e8:.2f} 亿字")

    print(f"\n  分类分布 (TOP 10):")
    for i, (cat, info) in enumerate(report["category_distribution"].items()):
        if i >= 10:
            break
        print(f"    {cat:12s} {info['books']:4d} 本, {info['hanzi']/1e8:.2f} 亿字")

    print(f"\n  报告: {REPORT_PATH}")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="网络小说语料清洗管线")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 本（调试用）")
    parser.add_argument("--workers", type=int, default=8, help="并行进程数 (默认 8)")
    parser.add_argument("--stats", action="store_true", help="只输出已清洗数据的统计")
    args = parser.parse_args()

    os.makedirs(CLEAN_DATA_DIR, exist_ok=True)

    # 获取所有待处理的书目录
    all_books = sorted(
        d for d in os.listdir(RAW_DATA_DIR)
        if os.path.isdir(os.path.join(RAW_DATA_DIR, d))
    )

    if args.limit:
        all_books = all_books[: args.limit]

    total = len(all_books)
    print(f"数据清洗管线")
    print(f"  原始数据: {RAW_DATA_DIR}")
    print(f"  清洗输出: {CLEAN_DATA_DIR}")
    print(f"  待处理:   {total} 本")
    print(f"  并行度:   {args.workers}")
    print(f"{'='*60}")

    # 并行清洗
    results = []
    start_time = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(clean_one_book, book): book for book in all_books}
        done_count = 0

        for future in as_completed(futures):
            done_count += 1
            book_name = futures[future]
            try:
                result = future.result()
                results.append(result)
                # 进度输出（每 50 本或最后一本）
                if done_count % 50 == 0 or done_count == total:
                    elapsed = time.time() - start_time
                    rate = done_count / elapsed if elapsed > 0 else 0
                    eta = (total - done_count) / rate if rate > 0 else 0
                    clean_hanzi_so_far = sum(r["clean_hanzi"] for r in results)
                    print(
                        f"[{done_count}/{total}] "
                        f"{clean_hanzi_so_far/1e8:.2f}亿字 "
                        f"| {elapsed:.0f}s | ETA {eta:.0f}s "
                        f"| {rate:.1f} 本/s",
                        flush=True,
                    )
            except Exception as e:
                results.append({
                    "book": book_name,
                    "status": f"error: {e}",
                    "raw_chapters": 0, "clean_chapters": 0,
                    "dropped_chapters": 0, "raw_chars": 0,
                    "raw_hanzi": 0, "clean_chars": 0, "clean_hanzi": 0,
                    "watermarks_removed": 0, "quality": "C", "category": "",
                })

    # 生成报告
    report = generate_report(results)
    report["elapsed_seconds"] = round(time.time() - start_time, 1)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 保存逐本详情
    detail_path = os.path.join(CLEAN_DATA_DIR, "cleaning_detail.jsonl")
    with open(detail_path, "w", encoding="utf-8") as f:
        for r in sorted(results, key=lambda x: x["book"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print_report(report)


if __name__ == "__main__":
    main()
