#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
69书吧爬虫

可能的域名（域名经常变更，如当前域名不可用请尝试切换）：
  - https://www.69shuba.com
  - https://www.69shu.com
  - https://www.69shu.pro
  - https://www.69shuba.cx
  - https://www.69shu.top

站点特征：
  - 中文小说站，页面以静态 HTML 为主
  - 分类页路径形如 /sort/1/、/sort/2/（数字对应分类）
  - 书籍页路径形如 /book/12345.htm 或 /txt/12345.htm
  - 章节列表和正文均从 HTML 解析
"""

import re
import sys
import argparse

from .base import NovelSiteBase


class Shu69Scraper(NovelSiteBase):
    """69书吧爬虫，继承 NovelSiteBase"""

    SITE_NAME = "69shu"
    # 当前使用的域名，如不可用请切换为上方备用域名
    BASE_URL = "https://www.69shuba.com"
    ENCODING = "gbk"  # 69书吧大多使用 GBK 编码

    # 分类映射（数字 → 分类名称，仅供参考，实际以站点为准）
    CATEGORIES = {
        "1": "玄幻奇幻",
        "2": "武侠仙侠",
        "3": "都市言情",
        "4": "历史军事",
        "5": "科幻灵异",
        "6": "网游竞技",
        "7": "女生频道",
    }

    def get_ad_patterns(self) -> list[str]:
        """返回 69书吧 站点常见的广告行正则模式"""
        return [
            r".*69shu.*",
            r".*69shuba.*",
            r".*六九书吧.*",
            r".*书吧.*最新章节.*",
            r".*书吧.*免费阅读.*",
            r".*请记住.*书吧.*",
            r".*请收藏.*69.*",
            r".*本站域名.*",
            r".*手机版阅读.*",
            r".*加入书签.*",
            r".*推荐票.*",
            r".*月票.*",
        ]

    def get_book_list(self, category=None, max_pages=5) -> list[dict]:
        """
        获取书籍列表。

        Args:
            category: 分类编号（字符串），如 "1" 表示玄幻奇幻。None 则使用默认分类 "1"。
            max_pages: 最多爬取的页数

        Returns:
            书籍信息字典列表:
            [{"book_id": "123", "name": "书名", "author": "作者", "category": "分类"}, ...]
        """
        cat = category or "1"
        cat_name = self.CATEGORIES.get(cat, f"分类{cat}")
        books = []

        for page in range(1, max_pages + 1):
            # 分类页 URL 格式：/sort/分类号/页码/ 或 /sort/分类号/
            if page == 1:
                url = f"{self.BASE_URL}/sort/{cat}/"
            else:
                url = f"{self.BASE_URL}/sort/{cat}/{page}/"

            html = self.fetch(url)
            if not html:
                print(f"  [69shu] 分类页 {url} 获取失败，停止翻页")
                break

            # 尝试多种列表解析模式
            # 模式1: <a href="...book/12345.htm">书名</a> + 作者信息
            # 模式2: <a href="...txt/12345/">书名</a>
            # 模式3: 书籍列表中的链接
            items = re.findall(
                r'<a\s+href="[^"]*?/(?:book|txt)/(\d+)(?:\.htm|/)"[^>]*>\s*([^<]+?)\s*</a>',
                html
            )

            if not items:
                # 备用模式：更宽泛的匹配
                items = re.findall(
                    r'href="[^"]*?/(\d{3,})[/.](?:htm|html)?"[^>]*>\s*([^<]{2,30})\s*</a>',
                    html
                )

            # 提取作者（通常在书名链接附近）
            # 作者模式举例：<span>作者：张三</span> 或纯文本 "/ 张三"
            author_map = {}
            author_blocks = re.findall(
                r'/(?:book|txt)/(\d+)[^"]*"[^>]*>[^<]+</a>.*?(?:作者|author)[：:\s]*([^<\s/]+)',
                html, re.DOTALL
            )
            for bid, author in author_blocks:
                author_map[bid] = author.strip()

            seen_ids = {b["book_id"] for b in books}
            for book_id, name in items:
                if book_id in seen_ids:
                    continue
                seen_ids.add(book_id)
                books.append({
                    "book_id": book_id,
                    "name": name.strip(),
                    "author": author_map.get(book_id, "未知"),
                    "category": cat_name,
                })

            if not items:
                break

            self.polite_sleep()

        print(f"  [69shu] 分类 {cat_name}: 获取到 {len(books)} 本书")
        return books

    def get_chapters(self, book_id) -> tuple[dict, list[tuple[str, str]]]:
        """
        获取书籍详情及章节列表。

        Args:
            book_id: 书籍 ID（字符串或数字）

        Returns:
            (book_info_dict, [(chapter_url, chapter_title), ...])
        """
        # 尝试多个可能的书籍详情/章节列表页 URL
        detail_urls = [
            f"{self.BASE_URL}/book/{book_id}.htm",
            f"{self.BASE_URL}/txt/{book_id}/",
            f"{self.BASE_URL}/book/{book_id}/",
        ]

        html = None
        used_url = None
        for url in detail_urls:
            html = self.fetch(url)
            if html and len(html) > 500:
                used_url = url
                break

        if not html:
            print(f"  [69shu] 书籍 {book_id} 详情页获取失败")
            return {}, []

        # 解析书名
        name_match = re.search(r'<h1[^>]*>\s*([^<]+?)\s*</h1>', html)
        book_name = name_match.group(1).strip() if name_match else f"book_{book_id}"

        # 解析作者
        author_match = re.search(
            r'(?:作\s*者|author)[：:\s]*<?\s*(?:<a[^>]*>)?\s*([^<\n]+?)\s*(?:</a>)?\s*[<\n]',
            html, re.IGNORECASE
        )
        author = author_match.group(1).strip() if author_match else "未知"

        # 解析分类
        cat_match = re.search(r'(?:分类|类型|类别)[：:\s]*([^<\n]+)', html)
        category = cat_match.group(1).strip() if cat_match else ""

        # 解析状态
        status_match = re.search(r'(?:状态|status)[：:\s]*([^<\n]+)', html)
        status = status_match.group(1).strip() if status_match else ""

        book_info = {
            "name": book_name,
            "author": author,
            "category": category,
            "status": status,
        }

        # 解析章节列表
        # 69书吧章节列表可能在同一页面，也可能需要单独的目录页
        chapters = []

        # 尝试在当前页面解析章节链接
        # 常见格式: <a href="/txt/12345/67890">第一章 开始</a>
        # 或: <a href="/book/12345/67890.html">第一章 开始</a>
        chapter_pattern = re.findall(
            r'<a\s+href="([^"]*?/(?:txt|book)/' + str(book_id) + r'/[^"]+)"[^>]*>\s*([^<]+?)\s*</a>',
            html
        )

        if not chapter_pattern:
            # 备用模式：更宽泛匹配
            chapter_pattern = re.findall(
                r'<a\s+href="(/[^"]*?/\d+/\d+(?:\.html?)?)"[^>]*>\s*(第[^<]+?)\s*</a>',
                html
            )

        if not chapter_pattern:
            # 尝试在目录页获取章节列表
            toc_urls = [
                f"{self.BASE_URL}/txt/{book_id}/",
                f"{self.BASE_URL}/book/{book_id}/",
            ]
            for toc_url in toc_urls:
                if toc_url == used_url:
                    continue
                toc_html = self.fetch(toc_url)
                if toc_html:
                    chapter_pattern = re.findall(
                        r'<a\s+href="([^"]*?/\d+(?:\.html?)?)"[^>]*>\s*([^<]+?)\s*</a>',
                        toc_html
                    )
                    if chapter_pattern:
                        break

        for href, title in chapter_pattern:
            title = title.strip()
            # 过滤明显不是章节的链接
            if len(title) < 2 or title in ("返回", "目录", "首页", "上一页", "下一页"):
                continue
            # 补全 URL
            if href.startswith("/"):
                full_url = f"{self.BASE_URL}{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"{self.BASE_URL}/{href}"
            chapters.append((full_url, title))

        print(f"  [69shu] {book_name}: 找到 {len(chapters)} 章")
        return book_info, chapters

    def get_chapter_content(self, chapter_url) -> str:
        """
        获取单个章节的纯文本内容。

        Args:
            chapter_url: 章节页面完整 URL

        Returns:
            章节纯文本内容，获取失败返回空字符串
        """
        html = self.fetch(chapter_url)
        if not html:
            return ""

        # 尝试多种正文容器选择器
        content = ""

        # 模式1: id="content" 或 id="chaptercontent" 或 id="txtContent"
        content_match = re.search(
            r'<div\s+id="(?:content|chaptercontent|txtContent|booktxt)"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )

        if not content_match:
            # 模式2: class 包含 content 的 div
            content_match = re.search(
                r'<div\s+class="[^"]*(?:content|chapter|txt_body|txtnav)[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )

        if not content_match:
            # 模式3: 尝试匹配 <p> 段落集合
            paragraphs = re.findall(r'<p[^>]*>(.+?)</p>', html, re.DOTALL)
            if len(paragraphs) > 3:
                content = "\n".join(paragraphs)

        if content_match:
            content = content_match.group(1)

        if not content:
            return ""

        # 清理 HTML 标签 → 纯文本
        text = self.clean_html(content)

        # 去除多余空行
        lines = [line.strip() for line in text.split('\n')]
        lines = [line for line in lines if line]
        text = '\n'.join(lines)

        self.polite_sleep()
        return text


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="69书吧小说爬虫")
    parser.add_argument("--category", "-c", default="1",
                        help="分类编号（1=玄幻 2=武侠 3=都市 4=历史 5=科幻 6=网游 7=女生）")
    parser.add_argument("--book-id", "-b", default=None,
                        help="指定书籍 ID 下载单本")
    parser.add_argument("--max-pages", "-p", type=int, default=3,
                        help="分类列表最多爬取页数（默认 3）")
    parser.add_argument("--max-books", "-n", type=int, default=50,
                        help="批量下载最多下载本数（默认 50）")
    parser.add_argument("--output", "-o", default=None,
                        help="输出目录（默认 data_69shu/）")
    parser.add_argument("--base-url", default=None,
                        help="覆盖默认域名，如 https://www.69shu.com")

    args = parser.parse_args()

    scraper = Shu69Scraper(output_base=args.output)
    if args.base_url:
        scraper.BASE_URL = args.base_url.rstrip("/")
        print(f"  [69shu] 使用自定义域名: {scraper.BASE_URL}")

    if args.book_id:
        # 下载单本
        result = scraper.download_book(args.book_id)
        if result:
            print(f"\n  输出目录: {result}")
        else:
            print("\n  下载失败")
            sys.exit(1)
    else:
        # 批量下载
        scraper.batch_download(
            category=args.category,
            max_books=args.max_books,
            max_pages=args.max_pages,
        )


if __name__ == "__main__":
    main()
