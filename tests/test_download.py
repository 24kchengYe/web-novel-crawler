#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试：下载诡秘之主前3章，验证完整流程"""
import sys, io, os, json
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import novel_scraper as ns

# 获取书籍信息
info = ns.get_book_info('17701')
if not info:
    print('获取失败')
    exit(1)

print(f'书名: {info["name"]}')
print(f'作者: {info["author"]}')
print(f'章节数: {len(info["chapters"])}')
print(f'前5章:')
for url, title in info['chapters'][:5]:
    print(f'  {title}')

# 只下载前3章测试
print('\n===== 下载前3章 =====')
test_dir = os.path.join(os.path.dirname(__file__), 'data', '_test_诡秘之主')
os.makedirs(test_dir, exist_ok=True)

for i, (ch_url, ch_title) in enumerate(info['chapters'][:3], 1):
    print(f'\n[{i}/3] {ch_title}')
    content = ns.download_chapter_content(ch_url)
    if content:
        ch_path = os.path.join(test_dir, f'{i:04d}_{ns.sanitize_filename(ch_title)}.txt')
        with open(ch_path, 'w', encoding='utf-8') as f:
            f.write(f'# {ch_title}\n\n{content}')
        print(f'  字数: {len(content)}')
        print(f'  前200字: {content[:200]}')
    else:
        print('  下载失败')
    ns.polite_sleep()

print(f'\n测试完成，文件保存在: {test_dir}')
