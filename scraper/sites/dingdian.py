#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
顶点小说爬虫

可能的域名（域名经常变更，如当前域名不可用请尝试切换）：
  - https://www.dingdiann.com
  - https://www.dingdiann.net
  - https://www.ddxs.com
  - https://www.23us.com
  - https://www.23us.so
  - https://www.dingdianxs.com

站点特征：
  - 结构类似笔趣阁，为常见的小说站模板
  - 分类页路径形如 /sort/1/、/fenlei/1/（数字对应分类）
  - 书籍详情页形如 /book/12345/ 或 /info/12345/
  - 章节正文通常在 id="content" 的 div 中
"""

import re
import sys
import argparse

from .base import NovelSiteBase


class DingdianScraper(NovelSiteBase):
    """顶点小说爬虫，继承 NovelSiteBase"""

    SITE_NAME = "dingdian"
    # 当前使用的域名，如不可用请切换为上方备用域名
    BASE_URL = "https://www.dingdiann.com"
    ENCODING = "utf-8"  # 顶点小说大多使用 UTF-8，部分镜像站用 GBK

    # 分类映射（数字 → 分类名称，仅供参考，实际以站点为准）
    CATEGORIES = {
        "1": "玄幻小说",
        "2": "修真小说",
        "3": "都市小说",
        "4": "历史小说",
        "5": "网游小说",
        "6": "科幻小说",
        "7": "言情小说",
        "8": "其他小说",
    }

    def get_ad_patterns(self) -> list[str]:
        """返回顶点小说站点常见的广告行正则模式"""
        return [
            r".*顶点小说.*",
            r".*顶点文学.*",
            r".*dingdian.*",
            r".*ddxs.*",
            r".*23us.*",
            r".*请记住.*顶点.*",
            r".*请收藏.*顶点.*",
            r".*本站域名.*",
            r".*手机版阅读.*",
            r".*天才一秒记住.*",
            r".*最新网址.*",
            r".*加入书签.*",
            r".*推荐票.*",
            r".*月票.*",
        ]

    def get_book_list(self, category=None, max_pages=5) -> list[dict]:
        """
        获取书籍列表。

        Args:
            category: 分类编号（字符串），如 "1" 表示玄幻小说。None 则使用默认分类 "1"。
            max_pages: 最多爬取的页数

        Returns:
            书籍信息字典列表:
            [{"book_id": "123", "name": "书名", "author": "作者", "category": "分类"}, ...]
        """
        cat = category or "1"
        cat_name = self.CATEGORIES.get(cat, f"分类{cat}")
        books = []

        for page in range(1, max_pages + 1):
            # 分类页 URL：尝试 /sort/ 和 /fenlei/ 两种路径
            if page == 1:
                url = f"{self.BASE_URL}/sort/{cat}/"
            else:
                url = f"{self.BASE_URL}/sort/{cat}/{page}/"

            html = self.fetch(url)
            if not html:
                # 尝试备用路径 /fenlei/
                if page == 1:
                    url = f"{self.BASE_URL}/fenlei/{cat}/"
                else:
                    url = f"{self.BASE_URL}/fenlei/{cat}/{page}/"
                html = self.fetch(url)

            if not html:
                print(f"  [dingdian] 分类页获取失败，停止翻页")
                break

            # 解析书籍列表
            # 模式1: <a href="/book/12345/">书名</a>（类笔趣阁结构）
            items = re.findall(
                r'<a\s+href="[^"]*?/(?:book|info|html)/(\d+)/?"[^>]*>\s*([^<]+?)\s*</a>',
                html
            )

            if not items:
                # 模式2: 更宽泛的链接匹配
                items = re.findall(
                    r'href="[^"]*?/(\d{3,})/?"[^>]*>\s*([^<]{2,30})\s*</a>',
                    html
                )

            # 提取作者信息
            author_map = {}
            # 常见格式: 书名链接后跟作者，如 <td>作者名</td> 或 /作者名
            author_blocks = re.findall(
                r'/(?:book|info|html)/(\d+)/?"[^>]*>[^<]+</a>.*?(?:作者|author)[：:\s]*([^<\s/]+)',
                html, re.DOTALL
            )
            for bid, author in author_blocks:
                author_map[bid] = author.strip()

            # 备用作者提取：表格行中的作者列
            if not author_map:
                # <tr> 中多个 <td>: 书名 | 最新章节 | 作者 | ...
                rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
                for row in rows:
                    cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
                    if len(cells) >= 3:
                        bid_match = re.search(r'/(\d{3,})/?"', cells[0])
                        if bid_match:
                            author_text = re.sub(r'<[^>]+>', '', cells[2]).strip()
                            if author_text:
                                author_map[bid_match.group(1)] = author_text

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

        print(f"  [dingdian] 分类 {cat_name}: 获取到 {len(books)} 本书")
        return books

    def get_chapters(self, book_id) -> tuple[dict, list[tuple[str, str]]]:
        """
        获取书籍详情及章节列表。

        Args:
            book_id: 书籍 ID（字符串或数字）

        Returns:
            (book_info_dict, [(chapter_url, chapter_title), ...])
        """
        # 尝试多个可能的书籍/目录页 URL
        detail_urls = [
            f"{self.BASE_URL}/book/{book_id}/",
            f"{self.BASE_URL}/info/{book_id}/",
            f"{self.BASE_URL}/html/{book_id}/",
        ]

        html = None
        used_url = None
        for url in detail_urls:
            html = self.fetch(url)
            if html and len(html) > 500:
                used_url = url
                break

        if not html:
            print(f"  [dingdian] 书籍 {book_id} 详情页获取失败")
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
        cat_match = re.search(r'(?:分类|类型|类别)[：:\s]*(?:<a[^>]*>)?\s*([^<\n]+)', html)
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
        chapters = []

        # 章节列表可能在详情页，也可能在单独的目录页
        # 首先尝试在当前页面解析
        # 常见格式: <a href="/book/12345/67890.html">第一章 开始</a>
        # 或: <a href="/html/12345/67890.html">第一章 开始</a>
        chapter_pattern = re.findall(
            r'<a\s+href="([^"]*?/(?:book|html|info)/' + str(book_id) + r'/\d+\.html?)"[^>]*>\s*([^<]+?)\s*</a>',
            html
        )

        if not chapter_pattern:
            # 备用模式：更宽泛的章节链接匹配
            chapter_pattern = re.findall(
                r'<a\s+href="([^"]*?/' + str(book_id) + r'/\d+\.html?)"[^>]*>\s*([^<]+?)\s*</a>',
                html
            )

        if not chapter_pattern:
            # 尝试获取专门的目录页
            toc_urls = [
                f"{self.BASE_URL}/html/{book_id}/",
                f"{self.BASE_URL}/book/{book_id}/",
            ]
            for toc_url in toc_urls:
                if toc_url == used_url:
                    continue
                toc_html = self.fetch(toc_url)
                if toc_html:
                    chapter_pattern = re.findall(
                        r'<a\s+href="([^"]*?/\d+\.html?)"[^>]*>\s*([^<]+?)\s*</a>',
                        toc_html
                    )
                    if chapter_pattern:
                        break

        # 过滤和去重
        seen_urls = set()
        for href, title in chapter_pattern:
            title = title.strip()
            # 过滤明显不是章节的链接
            if len(title) < 2:
                continue
            if title in ("返回", "目录", "首页", "上一页", "下一页", "上一章", "下一章"):
                continue

            # 补全 URL
            if href.startswith("/"):
                full_url = f"{self.BASE_URL}{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"{self.BASE_URL}/{href}"

            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            chapters.append((full_url, title))

        print(f"  [dingdian] {book_name}: 找到 {len(chapters)} 章")
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

        # 尝试多种正文容器匹配
        content = ""

        # 模式1: id="content"（最常见的笔趣阁模板）
        content_match = re.search(
            r'<div\s+id="content"[^>]*>(.*?)</div>',
            html, re.DOTALL
        )

        if not content_match:
            # 模式2: id 包含 content/chapter/booktext
            content_match = re.search(
                r'<div\s+id="(?:chaptercontent|booktxt|BookText|txtContent|chapter_content)"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )

        if not content_match:
            # 模式3: class 包含 content 的 div
            content_match = re.search(
                r'<div\s+class="[^"]*(?:chapter[-_]?content|book[-_]?content|read[-_]?content|txt[-_]?body)[^"]*"[^>]*>(.*?)</div>',
                html, re.DOTALL
            )

        if not content_match:
            # 模式4: 大段 <p> 标签集合（作为最后手段）
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
    parser = argparse.ArgumentParser(description="顶点小说爬虫")
    parser.add_argument("--category", "-c", default="1",
                        help="分类编号（1=玄幻 2=修真 3=都市 4=历史 5=网游 6=科幻 7=言情 8=其他）")
    parser.add_argument("--book-id", "-b", default=None,
                        help="指定书籍 ID 下载单本")
    parser.add_argument("--max-pages", "-p", type=int, default=3,
                        help="分类列表最多爬取页数（默认 3）")
    parser.add_argument("--max-books", "-n", type=int, default=50,
                        help="批量下载最多下载本数（默认 50）")
    parser.add_argument("--output", "-o", default=None,
                        help="输出目录（默认 data_dingdian/）")
    parser.add_argument("--base-url", default=None,
                        help="覆盖默认域名，如 https://www.ddxs.com")
    parser.add_argument("--encoding", default=None,
                        help="覆盖默认编码（utf-8），部分镜像站可能需要 gbk")

    args = parser.parse_args()

    scraper = DingdianScraper(output_base=args.output)
    if args.base_url:
        scraper.BASE_URL = args.base_url.rstrip("/")
        print(f"  [dingdian] 使用自定义域名: {scraper.BASE_URL}")
    if args.encoding:
        scraper.ENCODING = args.encoding
        print(f"  [dingdian] 使用编码: {scraper.ENCODING}")

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
