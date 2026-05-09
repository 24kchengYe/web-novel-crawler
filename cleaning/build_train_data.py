#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
训练数据构造器

从 data_cleaned/ 读取清洗后的章节，构造三类训练数据：
  A. 续写任务 (~60%): 前文 → 续写
  B. 大纲展开 (~25%): 章节标题+首段摘要 → 章节正文
  C. 风格控制 (~15%): 分类+标签+场景提示 → 段落

输出 Alpaca JSON 格式，可直接用于 LLaMA-Factory 微调。

用法:
  python -m cleaning.build_train_data                     # 全量构造
  python -m cleaning.build_train_data --tier S            # 只用 S 级
  python -m cleaning.build_train_data --tier S,A          # S+A 级
  python -m cleaning.build_train_data --limit 10          # 只处理 10 本（调试）
  python -m cleaning.build_train_data --max-samples 100000  # 最多 10 万条
"""

import os
import sys
import json
import re
import time
import random
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

# ============================================================
# 路径
# ============================================================
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_DATA_DIR = os.path.join(PROJECT_DIR, "data_cleaned")
TRAIN_DATA_DIR = os.path.join(PROJECT_DIR, "data_train")

# ============================================================
# 构造参数
# ============================================================
# 续写任务
CONTEXT_MIN = 800     # 前文最少字数
CONTEXT_MAX = 2000    # 前文最多字数
TARGET_MIN = 400      # 续写最少字数
TARGET_MAX = 1200     # 续写最多字数
SLIDE_STEP = 1500     # 滑动窗口步长（汉字）

# 大纲展开
OUTLINE_MAX_CHARS = 200   # 伪大纲最多取多少字
CHAPTER_MIN_FOR_OUTLINE = 1500  # 章节至少多长才生成大纲任务

# 风格控制
STYLE_SNIPPET_MIN = 300
STYLE_SNIPPET_MAX = 800

# CJK 正则
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def count_hanzi(text: str) -> int:
    return len(CJK_RE.findall(text))


# ============================================================
# 任务 A: 续写
# ============================================================
def build_continuation_samples(chapters: list[dict], book_meta: dict) -> list[dict]:
    """
    滑动窗口切出续写对。
    跨章节边界：将相邻章节文本拼接，模拟连续阅读。
    """
    samples = []

    # 拼接全部章节为连续文本（用换行分隔章节）
    full_text = "\n\n".join(ch["content"] for ch in chapters)
    text_len = len(full_text)

    if text_len < CONTEXT_MIN + TARGET_MIN:
        return samples

    pos = 0
    while pos + CONTEXT_MIN + TARGET_MIN <= text_len:
        # 随机化 context 和 target 长度（增加多样性）
        ctx_len = random.randint(CONTEXT_MIN, min(CONTEXT_MAX, text_len - TARGET_MIN - pos))
        tgt_len = random.randint(TARGET_MIN, min(TARGET_MAX, text_len - pos - ctx_len))

        context = full_text[pos : pos + ctx_len]
        target = full_text[pos + ctx_len : pos + ctx_len + tgt_len]

        # 确保 context 和 target 都有足够的汉字
        if count_hanzi(context) < CONTEXT_MIN // 2 or count_hanzi(target) < TARGET_MIN // 2:
            pos += SLIDE_STEP
            continue

        # 尽量在句号/问号/感叹号处截断，而不是截在半句话中间
        context = _snap_to_sentence_end(context)
        target = _snap_to_sentence_end(target)

        if count_hanzi(context) < 200 or count_hanzi(target) < 100:
            pos += SLIDE_STEP
            continue

        samples.append({
            "instruction": "请续写以下小说片段，保持文风和情节连贯：",
            "input": context,
            "output": target,
        })

        pos += SLIDE_STEP

    return samples


def _snap_to_sentence_end(text: str) -> str:
    """将文本截断到最后一个句末标点处"""
    # 从末尾往前找句号/问号/感叹号/省略号
    for i in range(len(text) - 1, max(len(text) - 200, 0), -1):
        if text[i] in '。！？…」』\u201d】\n':
            return text[: i + 1]
    return text


# ============================================================
# 任务 B: 大纲展开
# ============================================================
def build_outline_samples(chapters: list[dict], book_meta: dict) -> list[dict]:
    """
    伪大纲展开：用章节标题 + 首段作为 input，整个章节作为 output。
    """
    samples = []
    book_name = book_meta.get("name", "")
    category = book_meta.get("qidian_category", "") or book_meta.get("category", "")

    for ch in chapters:
        content = ch["content"]
        hanzi = ch.get("hanzi_count", count_hanzi(content))

        if hanzi < CHAPTER_MIN_FOR_OUTLINE:
            continue

        title = ch.get("title", "")

        # 提取首段作为"伪大纲"（前 OUTLINE_MAX_CHARS 字符，截到句号）
        outline_raw = content[:OUTLINE_MAX_CHARS]
        outline = _snap_to_sentence_end(outline_raw)
        if count_hanzi(outline) < 50:
            outline = outline_raw

        # 构造 input
        input_parts = []
        if category:
            input_parts.append(f"类型：{category}")
        if book_name:
            input_parts.append(f"作品：《{book_name}》")
        input_parts.append(f"章节标题：{title}")
        input_parts.append(f"章节概要：{outline}")

        samples.append({
            "instruction": "根据以下信息，写出完整的章节正文：",
            "input": "\n".join(input_parts),
            "output": content,
        })

    return samples


# ============================================================
# 任务 C: 风格控制
# ============================================================
STYLE_PROMPTS = [
    "写一段{category}小说的{scene}场景，风格{style}，约{length}字：",
    "以{style}的风格，续写一段{category}小说中的{scene}：",
    "请用{style}的笔触，描写一个{scene}的片段，类型为{category}：",
]

SCENE_KEYWORDS = {
    "战斗": ["战斗", "厮杀", "对决", "交手", "出手", "攻击", "剑气", "拳风"],
    "修炼": ["修炼", "突破", "境界", "丹田", "灵气", "功法", "闭关"],
    "感情": ["目光", "心中", "温柔", "眼眸", "微笑", "心跳", "拥抱"],
    "日常": ["吃饭", "走路", "聊天", "笑道", "说道", "回到"],
    "商战": ["公司", "股份", "合同", "投资", "会议", "谈判"],
}

STYLE_WORDS = ["热血激昂", "轻松幽默", "紧张悬疑", "细腻温情", "大气磅礴", "冷酷凌厉"]


def build_style_samples(chapters: list[dict], book_meta: dict) -> list[dict]:
    """
    从章节中随机抽取片段，配上风格标签作为训练对。
    """
    samples = []
    category = book_meta.get("qidian_category", "") or book_meta.get("category", "") or "小说"
    labels = book_meta.get("qidian_labels", [])

    for ch in chapters:
        content = ch["content"]
        hanzi = ch.get("hanzi_count", count_hanzi(content))

        if hanzi < STYLE_SNIPPET_MIN * 2:
            continue

        # 每章最多抽 1 个风格片段（控制总量）
        # 随机选一个起始点
        max_start = len(content) - STYLE_SNIPPET_MIN
        if max_start <= 0:
            continue

        start = random.randint(0, max_start)
        snippet_len = random.randint(STYLE_SNIPPET_MIN, min(STYLE_SNIPPET_MAX, len(content) - start))
        snippet = content[start : start + snippet_len]
        snippet = _snap_to_sentence_end(snippet)

        if count_hanzi(snippet) < 200:
            continue

        # 检测场景类型
        scene = "日常"
        for scene_name, keywords in SCENE_KEYWORDS.items():
            if any(kw in snippet for kw in keywords):
                scene = scene_name
                break

        style = random.choice(STYLE_WORDS)
        length = f"{count_hanzi(snippet) // 100 * 100}"

        prompt_template = random.choice(STYLE_PROMPTS)
        instruction = prompt_template.format(
            category=category, scene=scene, style=style, length=length
        )

        samples.append({
            "instruction": instruction,
            "input": "",
            "output": snippet,
        })

    return samples


# ============================================================
# 单本书处理
# ============================================================
def process_one_book(book_dir_name: str, tiers: set[str] | None) -> dict:
    """处理一本书，返回 {book, samples, stats}"""
    clean_dir = os.path.join(CLEAN_DATA_DIR, book_dir_name)
    meta_path = os.path.join(clean_dir, "metadata.json")
    jsonl_path = os.path.join(clean_dir, "chapters_cleaned.jsonl")

    result = {
        "book": book_dir_name,
        "tier": "C",
        "samples_cont": 0,
        "samples_outline": 0,
        "samples_style": 0,
        "total": 0,
    }

    if not os.path.exists(jsonl_path):
        return {**result, "samples": []}

    # 读 metadata
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            try:
                meta = json.load(f)
            except json.JSONDecodeError:
                pass

    # 质量分级
    cleaning_info = meta.get("cleaning", {})
    tier = cleaning_info.get("quality_tier", "C")
    result["tier"] = tier

    # 过滤：只保留指定质量等级
    if tiers and tier not in tiers:
        return {**result, "samples": []}

    # 读章节
    chapters = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                chapters.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not chapters:
        return {**result, "samples": []}

    # 按 index 排序
    chapters.sort(key=lambda x: x.get("index", 0))

    # 构造三类样本
    all_samples = []

    cont_samples = build_continuation_samples(chapters, meta)
    all_samples.extend(cont_samples)
    result["samples_cont"] = len(cont_samples)

    outline_samples = build_outline_samples(chapters, meta)
    all_samples.extend(outline_samples)
    result["samples_outline"] = len(outline_samples)

    style_samples = build_style_samples(chapters, meta)
    all_samples.extend(style_samples)
    result["samples_style"] = len(style_samples)

    result["total"] = len(all_samples)

    return {**result, "samples": all_samples}


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="训练数据构造器")
    parser.add_argument("--tier", type=str, default="S,A",
                        help="质量等级过滤，逗号分隔 (默认 S,A)")
    parser.add_argument("--limit", type=int, default=None,
                        help="只处理前 N 本书（调试用）")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="最多输出多少条样本")
    parser.add_argument("--workers", type=int, default=8,
                        help="并行进程数 (默认 8)")
    parser.add_argument("--seed", type=int, default=42,
                        help="随机种子 (默认 42)")
    args = parser.parse_args()

    random.seed(args.seed)
    os.makedirs(TRAIN_DATA_DIR, exist_ok=True)

    # 解析质量等级
    tiers = set(t.strip().upper() for t in args.tier.split(",")) if args.tier else None
    tier_label = "+".join(sorted(tiers)) if tiers else "ALL"

    # 获取所有待处理书目录
    if not os.path.isdir(CLEAN_DATA_DIR):
        print(f"清洗数据目录不存在: {CLEAN_DATA_DIR}")
        print(f"请先运行: python -m cleaning.clean_corpus")
        sys.exit(1)

    all_books = sorted(
        d for d in os.listdir(CLEAN_DATA_DIR)
        if os.path.isdir(os.path.join(CLEAN_DATA_DIR, d))
    )

    if args.limit:
        all_books = all_books[: args.limit]

    total_books = len(all_books)
    print(f"训练数据构造器")
    print(f"  清洗数据: {CLEAN_DATA_DIR}")
    print(f"  输出目录: {TRAIN_DATA_DIR}")
    print(f"  质量等级: {tier_label}")
    print(f"  待处理:   {total_books} 本")
    print(f"  并行度:   {args.workers}")
    print(f"  随机种子: {args.seed}")
    print(f"{'='*60}")

    # 并行处理
    all_samples = []
    stats = {"cont": 0, "outline": 0, "style": 0, "books_used": 0}
    start_time = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(process_one_book, book, tiers): book
            for book in all_books
        }
        done_count = 0

        for future in as_completed(futures):
            done_count += 1
            try:
                result = future.result()
                book_samples = result.pop("samples", [])

                if book_samples:
                    all_samples.extend(book_samples)
                    stats["cont"] += result["samples_cont"]
                    stats["outline"] += result["samples_outline"]
                    stats["style"] += result["samples_style"]
                    stats["books_used"] += 1

                if done_count % 100 == 0 or done_count == total_books:
                    elapsed = time.time() - start_time
                    print(
                        f"[{done_count}/{total_books}] "
                        f"样本: {len(all_samples):,} | "
                        f"用书: {stats['books_used']} | "
                        f"{elapsed:.0f}s",
                        flush=True,
                    )
            except Exception as e:
                print(f"  ERROR: {futures[future]}: {e}", flush=True)

    # 限制样本数
    if args.max_samples and len(all_samples) > args.max_samples:
        random.shuffle(all_samples)
        all_samples = all_samples[: args.max_samples]
        print(f"\n采样限制: {args.max_samples:,} 条")

    # 打乱
    random.shuffle(all_samples)

    # 切分 train / val (95% / 5%)
    val_size = max(1, len(all_samples) // 20)
    train_samples = all_samples[val_size:]
    val_samples = all_samples[:val_size]

    # 写入文件
    train_path = os.path.join(TRAIN_DATA_DIR, f"train_{tier_label}.json")
    val_path = os.path.join(TRAIN_DATA_DIR, f"val_{tier_label}.json")
    meta_path = os.path.join(TRAIN_DATA_DIR, f"dataset_info_{tier_label}.json")

    with open(train_path, "w", encoding="utf-8") as f:
        json.dump(train_samples, f, ensure_ascii=False)

    with open(val_path, "w", encoding="utf-8") as f:
        json.dump(val_samples, f, ensure_ascii=False)

    # 数据集信息（LLaMA-Factory 格式）
    dataset_info = {
        f"novel_{tier_label.lower()}_train": {
            "file_name": os.path.basename(train_path),
            "formatting": "alpaca",
        },
        f"novel_{tier_label.lower()}_val": {
            "file_name": os.path.basename(val_path),
            "formatting": "alpaca",
        },
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(dataset_info, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time

    # 统计报告
    report = {
        "tier_filter": tier_label,
        "books_processed": total_books,
        "books_used": stats["books_used"],
        "total_samples": len(all_samples),
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
        "by_type": {
            "continuation": stats["cont"],
            "outline": stats["outline"],
            "style": stats["style"],
        },
        "train_path": train_path,
        "val_path": val_path,
        "elapsed_seconds": round(elapsed, 1),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    report_path = os.path.join(TRAIN_DATA_DIR, f"build_report_{tier_label}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"训练数据构造完成")
    print(f"{'='*60}")
    print(f"  质量等级:   {tier_label}")
    print(f"  使用书籍:   {stats['books_used']} / {total_books}")
    print(f"  总样本数:   {len(all_samples):,}")
    print(f"    续写:     {stats['cont']:,} ({stats['cont']*100//max(len(all_samples),1)}%)")
    print(f"    大纲展开: {stats['outline']:,} ({stats['outline']*100//max(len(all_samples),1)}%)")
    print(f"    风格控制: {stats['style']:,} ({stats['style']*100//max(len(all_samples),1)}%)")
    print(f"  训练集:     {len(train_samples):,}")
    print(f"  验证集:     {len(val_samples):,}")
    print(f"  耗时:       {elapsed:.1f}s")
    print(f"\n  输出文件:")
    print(f"    {train_path}")
    print(f"    {val_path}")
    print(f"    {meta_path}")


if __name__ == "__main__":
    main()
