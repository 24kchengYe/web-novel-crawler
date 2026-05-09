#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试：获取书籍信息并下载第1章"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 避免重复包装
import novel_scraper as ns

info = ns.get_book_info('17701')
if info:
    print(f'书名: {info["name"]}')
    print(f'作者: {info["author"]}')
    print(f'分类: {info["category"]}')
    print(f'章节数: {len(info["chapters"])}')
    print(f'\n前5章:')
    for url, title in info['chapters'][:5]:
        print(f'  {title} -> {url}')

    print(f'\n===== 下载第1章 =====')
    content = ns.download_chapter_content(info['chapters'][0][0])
    print(f'字数: {len(content)}')
    print(f'\n前500字:')
    print(content[:500])
else:
    print('获取书籍信息失败')
