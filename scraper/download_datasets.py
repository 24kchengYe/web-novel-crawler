#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
开源小说数据集下载器

从 HuggingFace / 清华云盘下载公开小说语料数据集，
统一转换为项目标准格式存入 data_opensource/ 目录。

每个数据集一个子目录，包含：
  - source_info.json   数据源描述
  - chapters.jsonl     统一格式 {index, title, content, hanzi_count, source}
  - 或 raw/            原始下载文件

数据集清单:
  1. webnovel_cn (50K subset, HuggingFace)
  2. chinese-novel-dataset (3.8K, HuggingFace)
  3. LongData-Corpus 小说部分 (清华云盘)
  4. Chinese-Pixiv-Novel (145K, HuggingFace, 12.9GB)
  5. GuoFeng-Webnovel (GitHub)

用法:
  python -m scraper.download_datasets --all           # 下载全部
  python -m scraper.download_datasets --dataset webnovel_cn
  python -m scraper.download_datasets --list          # 列出可用数据集
"""

import os
import sys
import json
import time
import re
import argparse
import subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPENSOURCE_DIR = os.path.join(PROJECT_DIR, "data_opensource")
PYTHON = sys.executable

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def count_hanzi(text: str) -> int:
    return len(CJK_RE.findall(text))


# ============================================================
# Dataset: webnovel_cn (50K subset)
# ============================================================
def download_webnovel_cn():
    """下载 webnovel_cn 50K 子集 (603MB, Alpaca 格式)"""
    name = "webnovel_cn"
    out_dir = os.path.join(OPENSOURCE_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "source_info.json")
    if os.path.exists(info_path):
        print(f"  [{name}] 已存在，跳过下载")
        return

    print(f"  [{name}] 下载 HuggingFace 数据集...")
    try:
        from datasets import load_dataset
        ds = load_dataset("zxbsmk/webnovel_cn", split="train")
        print(f"  [{name}] 加载完成: {len(ds)} 条")

        # 转为标准 jsonl
        jsonl_path = os.path.join(out_dir, "data.jsonl")
        total_hanzi = 0
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for i, item in enumerate(ds):
                output = item.get("output", "")
                hz = count_hanzi(output)
                total_hanzi += hz
                record = {
                    "index": i + 1,
                    "instruction": item.get("instruction", ""),
                    "input": item.get("input", ""),
                    "output": output,
                    "hanzi_count": hz,
                    "source": name,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        with open(info_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": name,
                "source_url": "https://huggingface.co/datasets/zxbsmk/webnovel_cn",
                "description": "中文网文续写 instruction 数据集 (50K 子集，完整版 21.7M 条)",
                "format": "alpaca (instruction/input/output)",
                "total_samples": len(ds),
                "total_hanzi": total_hanzi,
                "license": "MIT",
                "category": "混合(12,560本网文)",
                "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)

        print(f"  [{name}] 完成: {len(ds)} 条, {total_hanzi/1e4:.0f} 万汉字")
    except Exception as e:
        print(f"  [{name}] 下载失败: {e}")
        print(f"  [{name}] 请先安装: pip install datasets")


# ============================================================
# Dataset: chinese-novel-dataset (3.8K)
# ============================================================
def download_chinese_novel():
    """下载 kkcmbx/chinese-novel-dataset (10.8MB)"""
    name = "chinese-novel-dataset"
    out_dir = os.path.join(OPENSOURCE_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "source_info.json")
    if os.path.exists(info_path):
        print(f"  [{name}] 已存在，跳过下载")
        return

    print(f"  [{name}] 下载 HuggingFace 数据集...")
    try:
        from datasets import load_dataset
        ds = load_dataset("kkcmbx/chinese-novel-dataset", split="train")
        print(f"  [{name}] 加载完成: {len(ds)} 条")

        jsonl_path = os.path.join(out_dir, "data.jsonl")
        total_hanzi = 0
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for i, item in enumerate(ds):
                output = item.get("output", "")
                hz = count_hanzi(output)
                total_hanzi += hz
                record = {
                    "index": i + 1,
                    "instruction": item.get("instruction", ""),
                    "input": item.get("input", ""),
                    "output": output,
                    "hanzi_count": hz,
                    "source": name,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        with open(info_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": name,
                "source_url": "https://huggingface.co/datasets/kkcmbx/chinese-novel-dataset",
                "description": "中文小说续写数据集",
                "format": "alpaca (instruction/input/output)",
                "total_samples": len(ds),
                "total_hanzi": total_hanzi,
                "license": "未指定",
                "category": "混合",
                "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)

        print(f"  [{name}] 完成: {len(ds)} 条, {total_hanzi/1e4:.0f} 万汉字")
    except Exception as e:
        print(f"  [{name}] 下载失败: {e}")


# ============================================================
# Dataset: Chinese-Pixiv-Novel (145K, 12.9GB)
# ============================================================
def download_pixiv_novel():
    """下载 Chinese-Pixiv-Novel (大文件，流式处理)"""
    name = "Chinese-Pixiv-Novel"
    out_dir = os.path.join(OPENSOURCE_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "source_info.json")
    if os.path.exists(info_path):
        print(f"  [{name}] 已存在，跳过下载")
        return

    print(f"  [{name}] 下载 HuggingFace 数据集 (12.9GB, 流式)...")
    try:
        from datasets import load_dataset
        ds = load_dataset("wuliangfo/Chinese-Pixiv-Novel", split="train", streaming=True)

        jsonl_path = os.path.join(out_dir, "data.jsonl")
        total_hanzi = 0
        count = 0
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for item in ds:
                text = item.get("text", "")
                if not text or count_hanzi(text) < 100:
                    continue
                hz = count_hanzi(text)
                total_hanzi += hz
                count += 1
                record = {
                    "index": count,
                    "title": item.get("title", ""),
                    "content": text,
                    "hanzi_count": hz,
                    "tags": item.get("tags", ""),
                    "source": name,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                if count % 10000 == 0:
                    print(f"    [{name}] {count} 条, {total_hanzi/1e8:.2f} 亿汉字...", flush=True)

        with open(info_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": name,
                "source_url": "https://huggingface.co/datasets/wuliangfo/Chinese-Pixiv-Novel",
                "description": "Pixiv 中文小说 (同人/二创, R-18 含量高)",
                "format": "text + metadata",
                "total_samples": count,
                "total_hanzi": total_hanzi,
                "license": "OpenRAIL",
                "category": "同人/二次创作",
                "note": "数据未经清洗，可能含低质量内容",
                "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)

        print(f"  [{name}] 完成: {count} 条, {total_hanzi/1e4:.0f} 万汉字")
    except Exception as e:
        print(f"  [{name}] 下载失败: {e}")


# ============================================================
# Dataset: LongData-Corpus 小说部分 (清华云盘)
# ============================================================
def download_longdata_novel():
    """提示用户手动下载 LongData-Corpus 小说部分 (清华云盘)"""
    name = "LongData-Corpus-Novel"
    out_dir = os.path.join(OPENSOURCE_DIR, name)
    os.makedirs(out_dir, exist_ok=True)

    info_path = os.path.join(out_dir, "source_info.json")
    if os.path.exists(info_path):
        print(f"  [{name}] 已存在，跳过")
        return

    print(f"  [{name}] 此数据集需要手动下载：")
    print(f"    中文小说: https://cloud.tsinghua.edu.cn/d/0670fcb14d294c97b5cf/")
    print(f"    下载后放入: {out_dir}/raw/")
    print(f"    然后重新运行此脚本处理")

    with open(info_path, "w", encoding="utf-8") as f:
        json.dump({
            "name": name,
            "source_url": "https://huggingface.co/datasets/yuyijiong/LongData-Corpus",
            "download_url": "https://cloud.tsinghua.edu.cn/d/0670fcb14d294c97b5cf/",
            "description": "长文本语料库 - 中文小说部分 (>16K 字)",
            "format": "JSON",
            "license": "CC-BY-NC-4.0",
            "category": "长篇小说",
            "status": "pending_manual_download",
            "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, ensure_ascii=False, indent=2)


# ============================================================
# Dataset: GuoFeng-Webnovel (GitHub)
# ============================================================
def download_guofeng():
    """克隆 GuoFeng-Webnovel 仓库"""
    name = "GuoFeng-Webnovel"
    out_dir = os.path.join(OPENSOURCE_DIR, name)

    info_path = os.path.join(out_dir, "source_info.json")
    if os.path.exists(info_path):
        print(f"  [{name}] 已存在，跳过")
        return

    print(f"  [{name}] 克隆 GitHub 仓库...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1",
             "https://github.com/longyuewangdcu/GuoFeng-Webnovel.git",
             out_dir],
            check=True, timeout=120,
        )
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump({
                "name": name,
                "source_url": "https://github.com/longyuewangdcu/GuoFeng-Webnovel",
                "description": "多语言网文语料库 (中英对照, 学术用)",
                "format": "mixed",
                "license": "学术研究",
                "category": "多语言网文",
                "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }, f, ensure_ascii=False, indent=2)
        print(f"  [{name}] 完成")
    except Exception as e:
        print(f"  [{name}] 克隆失败: {e}")


# ============================================================
# 主入口
# ============================================================
DATASETS = {
    "webnovel_cn": ("webnovel_cn (50K instruction 数据)", download_webnovel_cn),
    "chinese-novel": ("chinese-novel-dataset (3.8K)", download_chinese_novel),
    "pixiv-novel": ("Chinese-Pixiv-Novel (145K, 12.9GB)", download_pixiv_novel),
    "longdata-novel": ("LongData-Corpus 小说部分 (手动下载)", download_longdata_novel),
    "guofeng": ("GuoFeng-Webnovel (GitHub)", download_guofeng),
}


def main():
    parser = argparse.ArgumentParser(description="开源小说数据集下载器")
    parser.add_argument("--all", action="store_true", help="下载全部数据集")
    parser.add_argument("--dataset", type=str, help="指定下载某个数据集")
    parser.add_argument("--list", action="store_true", help="列出可用数据集")
    args = parser.parse_args()

    os.makedirs(OPENSOURCE_DIR, exist_ok=True)

    if args.list:
        print("可用数据集:")
        for key, (desc, _) in DATASETS.items():
            print(f"  {key:20s}  {desc}")
        return

    if args.dataset:
        if args.dataset not in DATASETS:
            print(f"未知数据集: {args.dataset}")
            print(f"可用: {', '.join(DATASETS.keys())}")
            return
        desc, func = DATASETS[args.dataset]
        print(f"\n下载: {desc}")
        func()
        return

    if args.all:
        print(f"{'='*60}")
        print(f"开源小说数据集批量下载")
        print(f"输出目录: {OPENSOURCE_DIR}")
        print(f"{'='*60}")
        for key, (desc, func) in DATASETS.items():
            print(f"\n[{key}] {desc}")
            func()
        print(f"\n{'='*60}")
        print(f"全部完成!")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
