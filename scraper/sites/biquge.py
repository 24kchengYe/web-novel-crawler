#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
笔趣阁(xbiquge)爬虫 - 继承 NovelSiteBase

站点: 新笔趣阁 www.xbiquge.com.cn (镜像: www.xbiquge.la 等)
特点: 中文盗版小说站，书目极多，章节页通常可直接访问
结构:
  - 分类页: /xuanhuanxiaoshuo/ 等
  - 排行榜: /top/allvisit/ 等
  - 书籍详情: /book/{id}/
  - 章节正文: /book/{id}/{chap_id}.html, 正文在 div#content
"""

import os
import sys
import re
import argparse

# 保证父包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scraper.sites.base import NovelSiteBase


class BiqugeScraper(NovelSiteBase):
    """新笔趣阁爬虫"""

    SITE_NAME = "biquge"
    BASE_URL = "https://www.xbiquge.com.cn"
    ENCODING = "utf-8"

    # 分类映射: 中文名 -> URL 路径
    # xbiquge.com.cn 实际使用 /list{N}/ 格式
    CATEGORY_MAP = {
        "玄幻": "/list1/",
        "修真": "/list2/",
        "都市": "/list3/",
        "历史": "/list4/",
        "网游": "/list5/",
        "科幻": "/list6/",
        "言情": "/list7/",
        "其他": "/list8/",
    }

    # 排行榜和其他列表
    RANK_MAP = {
        "排行榜": "/top/",
        "全本": "/full/",
        "最新发布": "/lastpost/",
        "最近更新": "/lastupdate/",
    }

    # ---- 接口实现 ----

    def get_book_list(self, category=None, max_pages=5) -> list[dict]:
        """
        从分类页 + 排行榜获取书籍列表。

        Args:
            category: 分类名(中文)，None 表示从排行榜获取
            max_pages: 分类页最多翻几页

        Returns:
            [{"book_id": "123", "name": "书名", "author": "作者", "category": "分类"}, ...]
        """
        books = []
        seen_ids = set()

        if category and category in self.CATEGORY_MAP:
            # 从分类页获取
            cat_path = self.CATEGORY_MAP[category]
            for page in range(1, max_pages + 1):
                if page == 1:
                    url = self.BASE_URL + cat_path
                else:
                    url = self.BASE_URL + cat_path + f"{page}/"
                print(f"  [{self.SITE_NAME}] 获取 {category} 第{page}页 ...", flush=True)
                html = self.fetch(url)
                if not html:
                    break

                page_books = self._parse_book_list_page(html, category)
                if not page_books:
                    break

                for b in page_books:
                    if b["book_id"] not in seen_ids:
                        seen_ids.add(b["book_id"])
                        books.append(b)

                self.polite_sleep()
        else:
            # 无分类或分类不在映射中，从排行榜获取
            for rank_name, rank_path in self.RANK_MAP.items():
                url = self.BASE_URL + rank_path
                print(f"  [{self.SITE_NAME}] 获取排行榜: {rank_name} ...", flush=True)
                html = self.fetch(url)
                if not html:
                    continue

                rank_books = self._parse_rank_page(html)
                for b in rank_books:
                    if b["book_id"] not in seen_ids:
                        seen_ids.add(b["book_id"])
                        b["category"] = category or rank_name
                        books.append(b)

                self.polite_sleep()
                # 排行榜通常每个榜一页，取两个榜就够了
                if len(books) >= 100:
                    break

        return books

    def get_chapters(self, book_id) -> tuple[dict, list[tuple[str, str]]]:
        """
        获取书籍信息和章节列表。

        Args:
            book_id: 书籍ID (纯数字字符串)

        Returns:
            (book_info_dict, [(chapter_url, chapter_title), ...])
        """
        url = f"{self.BASE_URL}/book/{book_id}/"
        html = self.fetch(url)
        if not html:
            return {}, []

        info = {"book_id": book_id}

        # 从 meta 标签提取信息
        meta_map = {
            "og:novel:book_name": "name",
            "og:novel:author": "author",
            "og:novel:category": "category",
            "og:novel:status": "status",
            "og:novel:description": "description",
        }
        for og_key, info_key in meta_map.items():
            m = re.search(
                rf'property="{re.escape(og_key)}"\s+content="([^"]*)"', html
            )
            if m:
                info[info_key] = m.group(1).strip()

        # 备选: 从页面 HTML 元素提取
        if "name" not in info:
            m = re.search(r'<h1>([^<]+)</h1>', html)
            if m:
                info["name"] = m.group(1).strip()

        if "author" not in info:
            m = re.search(r'<span>作\s*者[：:]([^<]+)</span>', html)
            if m:
                info["author"] = m.group(1).strip()

        if "description" not in info:
            m = re.search(r'id="intro"[^>]*>(.*?)</div>', html, re.DOTALL)
            if m:
                desc = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                info["description"] = desc

        # 补充默认值
        info.setdefault("name", f"book_{book_id}")
        info.setdefault("author", "未知")
        info.setdefault("category", "")
        info.setdefault("status", "")
        info.setdefault("description", "")

        # 解析章节列表
        # 笔趣阁页面通常有"最新章节"(倒序)和"正文卷"(正序)两段
        # 优先取"正文卷"之后的部分，避免重复
        chapters = []
        chapter_section = html

        # 定位正文章节区域: 找 id="list" 的 div
        list_match = re.search(r'<div\s+id="list"[^>]*>(.*)', html, re.DOTALL)
        if list_match:
            chapter_section = list_match.group(1)

        # 解析 <dd><a href="/book/{id}/{chap}.html">章节名</a></dd>
        # book_id 格式: "0/411"，需要转义斜杠
        pattern = (
            r'<dd>\s*<a\s+href="(/book/'
            + re.escape(book_id)
            + r'/(\d+)\.html)"[^>]*>([^<]+)</a>\s*</dd>'
        )
        matches = re.findall(pattern, chapter_section)

        seen_chap = set()
        for path, chap_id, title in matches:
            if chap_id not in seen_chap:
                seen_chap.add(chap_id)
                full_url = self.BASE_URL + path
                chapters.append((full_url, title.strip()))

        return info, chapters

    def get_chapter_content(self, chapter_url) -> str:
        """
        获取单个章节的纯文本内容。

        Args:
            chapter_url: 章节完整 URL

        Returns:
            纯文本字符串，获取失败返回空字符串
        """
        html = self.fetch(chapter_url)
        if not html:
            return ""

        # 提取 div#content 中的内容
        m = re.search(r'id="content"[^>]*>(.*?)</div>', html, re.DOTALL)
        if not m:
            # 备选: 尝试 class="showtxt" 等常见容器
            m = re.search(r'class="showtxt"[^>]*>(.*?)</div>', html, re.DOTALL)
        if not m:
            return ""

        content_html = m.group(1)
        text = self.clean_html(content_html)

        # 清理空行和多余空白
        lines = []
        for line in text.split('\n'):
            line = line.strip()
            if line:
                lines.append(line)
        text = '\n'.join(lines)

        self.polite_sleep()
        return text

    def get_ad_patterns(self) -> list[str]:
        """返回笔趣阁特有的广告行正则模式列表"""
        return [
            r'.*笔趣阁.*',
            r'.*biquge.*',
            r'.*xbiquge.*',
            r'.*bi[qQ]u[gG]e.*',
            r'.*www\.xbiquge\.\w+.*',
            r'.*请大家收藏.*',
            r'.*一秒记住.*',
            r'.*最快更新.*',
            r'.*手机用户请浏览.*阅读.*',
            r'.*手机版阅读网址.*',
            r'.*最新章节.*全网.*',
            r'.*天才一秒记住.*',
            r'.*本站.*最快更新.*',
            r'.*请记住本书首发域名.*',
            r'.*喜欢.*请大家收藏.*',
            r'.*百度搜索.*笔趣阁.*',
            r'.*加入书签.*方便.*阅读.*',
            r'.*本章未完.*点击下一页.*',
            r'.*新笔趣阁.*',
        ]

    # ---- 内部解析方法 ----

    def _parse_book_list_page(self, html, category="") -> list[dict]:
        """
        解析分类页的书籍列表。

        笔趣阁分类页常见结构:
          <li>
            <span class="s2"><a href="/book/12345/">书名</a></span>
            ...最新章节...
            <span class="s5"><a href="/book/12345/">作者</a></span>
          </li>
        或:
          <div class="bookname">
            <a href="/book/12345/">书名</a>
          </div>
        """
        books = []

        # 模式1: 表格式列表 (常见于分类页)
        # <span class="s2"><a href="/book/{id}/">书名</a></span>
        # <span class="s5">作者</span>
        rows = re.findall(
            r'<span\s+class="s2">\s*<a\s+href="/book/(\d+/\d+)/"[^>]*>([^<]+)</a>\s*</span>'
            r'.*?'
            r'<span\s+class="s5">\s*([^<]*?)\s*</span>',
            html,
            re.DOTALL,
        )
        for book_id, name, author in rows:
            books.append({
                "book_id": book_id,
                "name": name.strip(),
                "author": author.strip() or "未知",
                "category": category,
            })

        if books:
            return books

        # 模式2: 通用 <a href="/book/{id}/">书名</a> 提取
        pattern = r'<a\s+href="/book/(\d+/\d+)/"[^>]*>([^<]+)</a>'
        matches = re.findall(pattern, html)
        seen = set()
        for book_id, name in matches:
            name = name.strip()
            # 排除导航链接等无意义短文本
            if book_id not in seen and len(name) > 1:
                seen.add(book_id)
                books.append({
                    "book_id": book_id,
                    "name": name,
                    "author": "未知",
                    "category": category,
                })

        return books

    def _parse_rank_page(self, html) -> list[dict]:
        """
        解析排行榜页面。

        排行榜结构与分类页类似，优先尝试表格式，再回退到通用模式。
        """
        return self._parse_book_list_page(html, category="排行榜")


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="笔趣阁(xbiquge)小说爬虫 - 学术研究用语料采集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 批量下载玄幻类，最多20本
  python biquge.py --batch --category 玄幻 --max 20

  # 从排行榜批量下载
  python biquge.py --batch --max 10

  # 按ID下载指定小说
  python biquge.py --id 12345

  # 列出可用分类
  python biquge.py --list-categories

  # 列出某分类的书籍
  python biquge.py --list --category 都市
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", action="store_true", help="批量下载")
    group.add_argument("--id", type=str, help="按ID下载指定小说")
    group.add_argument("--list", action="store_true", help="列出书籍（需配合 --category）")
    group.add_argument("--list-categories", action="store_true", help="列出所有可用分类")

    parser.add_argument(
        "--category", type=str, default=None,
        help="分类名(中文)，如: 玄幻, 修真, 都市, 历史, 网游, 科幻, 言情, 其他",
    )
    parser.add_argument("--max", type=int, default=10, help="最多下载/列出几本 (默认: 10)")
    parser.add_argument("--pages", type=int, default=5, help="分类页最多翻几页 (默认: 5)")
    parser.add_argument("--output", type=str, default=None, help="输出目录 (默认: data_biquge)")

    args = parser.parse_args()

    scraper = BiqugeScraper(output_base=args.output)

    if args.list_categories:
        print(f"\n[{scraper.SITE_NAME}] 可用分类:")
        for name, path in scraper.CATEGORY_MAP.items():
            print(f"  {name:6s} -> {scraper.BASE_URL}{path}")
        print(f"\n[{scraper.SITE_NAME}] 可用排行榜:")
        for name, path in scraper.RANK_MAP.items():
            print(f"  {name:10s} -> {scraper.BASE_URL}{path}")

    elif args.list:
        books = scraper.get_book_list(category=args.category, max_pages=args.pages)
        books = books[: args.max]
        print(f"\n[{scraper.SITE_NAME}] 分类={args.category or '排行榜'}, 共 {len(books)} 本:")
        for i, b in enumerate(books, 1):
            print(f"  {i:3d}. [{b['book_id']}] {b['name']} / {b['author']}")

    elif args.id:
        scraper.download_book(args.id)

    elif args.batch:
        scraper.batch_download(
            category=args.category,
            max_books=args.max,
            max_pages=args.pages,
        )


if __name__ == "__main__":
    main()
