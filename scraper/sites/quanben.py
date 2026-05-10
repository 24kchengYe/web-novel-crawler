#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全本小说网系列站点爬虫

支持域名：
  - quanben-xiaoshuo.com（主站）
  - quanben.io
  - quanben.net
  - quanben5.com

页面结构与 qbxsw.com 类似，静态 HTML 纯文本小说站。
用途：学术研究用语料采集。
"""

import os
import re
import argparse

from scraper.sites.base import NovelSiteBase


# 分类映射：中文名 -> URL 路径
CATEGORY_MAP = {
    "玄幻": "/XuanHuan/",
    "奇幻": "/QiHuan/",
    "武侠": "/WuXia/",
    "仙侠": "/XianXia/",
    "都市": "/DuShi/",
    "历史": "/LiShi/",
    "军事": "/JunShi/",
    "悬疑": "/XuanYi/",
    "游戏": "/YouXi/",
    "科幻": "/KeHuan/",
    "古言": "/GuYan/",
    "现言": "/XianYan/",
    "幻言": "/HuanYan/",
}

# 可用域名列表（按优先级排列）
AVAILABLE_DOMAINS = [
    "quanben-xiaoshuo.com",
    "quanben.io",
    "quanben.net",
    "quanben5.com",
]


class QuanbenScraper(NovelSiteBase):
    """全本小说网爬虫

    继承 NovelSiteBase，实现全本小说网系列站点的采集逻辑。
    支持多域名切换，页面结构与 qbxsw.com 高度相似。
    """

    SITE_NAME = "quanben"
    BASE_URL = "https://www.quanben-xiaoshuo.com"
    ENCODING = "utf-8"

    def __init__(self, output_base=None, domain=None):
        """初始化全本小说网爬虫。

        Args:
            output_base: 输出目录，默认为项目目录下的 data_quanben/。
            domain: 使用的域名，默认 quanben-xiaoshuo.com。
                    可选值见 AVAILABLE_DOMAINS。
        """
        if domain:
            if domain not in AVAILABLE_DOMAINS:
                print(f"  [警告] 未知域名 {domain}，已知域名: {', '.join(AVAILABLE_DOMAINS)}")
            self.BASE_URL = f"https://www.{domain}"
        super().__init__(output_base)

    # ----------------------------------------------------------------
    # 接口实现
    # ----------------------------------------------------------------

    def get_book_list(self, category=None, max_pages=5) -> list[dict]:
        """从分类页获取书籍列表。

        Args:
            category: 分类名（中文），如 "玄幻"、"都市"。
                      为 None 时默认使用 "玄幻"。
            max_pages: 最多翻几页分类列表，默认 5。

        Returns:
            书籍字典列表，每项包含 book_id, name, author, category。
        """
        if category is None:
            category = "玄幻"

        path = CATEGORY_MAP.get(category)
        if not path:
            print(f"  [{self.SITE_NAME}] 未知分类: {category}")
            print(f"  可用分类: {', '.join(CATEGORY_MAP.keys())}")
            return []

        books = []
        seen_ids = set()

        for page in range(1, max_pages + 1):
            if page == 1:
                url = self.BASE_URL + path
            else:
                url = self.BASE_URL + path + f"{page}.html"

            print(f"  [{self.SITE_NAME}] 获取 {category} 第{page}页 ...", flush=True)
            html = self.fetch(url)
            if not html:
                break

            # 解析书籍列表
            # 详情页链接格式: /n/书名拼音/ 或 /n/书名拼音/list.html
            # 分类页中的书籍链接: <a href="/n/xxxxx/">书名</a>
            pattern = r'<a\s+href="(/n/([^/"]+)/)"[^>]*>([^<]+)</a>'
            matches = re.findall(pattern, html)

            page_count = 0
            for href, book_id, name in matches:
                if book_id not in seen_ids:
                    seen_ids.add(book_id)
                    books.append({
                        "book_id": book_id,
                        "name": name.strip(),
                        "author": "",
                        "category": category,
                    })
                    page_count += 1

            if page_count == 0:
                # 没有新书了，停止翻页
                break

            self.polite_sleep()

        # 尝试补全作者信息（从列表页 HTML 中提取）
        # 某些分类页会在书名旁边显示作者，格式不定，这里做一次尝试
        self._fill_authors_from_list(books)

        print(f"  [{self.SITE_NAME}] {category} 共找到 {len(books)} 本", flush=True)
        return books

    def _fill_authors_from_list(self, books):
        """尝试从书籍详情页补全作者信息（仅对缺少作者的书籍）。

        只对前几本做请求，避免大量额外请求。
        """
        for book in books:
            if book.get("author"):
                continue
            # 从详情页获取作者
            detail_url = self.BASE_URL + f"/n/{book['book_id']}/"
            html = self.fetch(detail_url)
            if html:
                # 尝试从 meta 标签提取
                m = re.search(
                    r'property="og:novel:author"\s+content="([^"]*)"', html
                )
                if m:
                    book["author"] = m.group(1).strip()
                else:
                    # 备选：页面中 "作者：XXX" 的文本
                    m = re.search(r'作者[：:]\s*([^<\s]+)', html)
                    if m:
                        book["author"] = m.group(1).strip()
            self.polite_sleep()

    def get_chapters(self, book_id) -> tuple[dict, list[tuple[str, str]]]:
        """获取书籍信息和章节列表。

        Args:
            book_id: 书籍标识（拼音路径名），如 "guimizhuzhizhuren"。

        Returns:
            (book_info, chapters) 元组。
            book_info 包含 name, author, category, status 等。
            chapters 为 [(chapter_url, chapter_title), ...] 列表。
        """
        # 章节列表页: /n/书名拼音/list.html 或 /n/书名拼音/
        list_url = self.BASE_URL + f"/n/{book_id}/list.html"
        html = self.fetch(list_url)

        if not html:
            # 回退到目录主页
            list_url = self.BASE_URL + f"/n/{book_id}/"
            html = self.fetch(list_url)

        if not html:
            print(f"  [{self.SITE_NAME}] 获取章节列表失败: {book_id}")
            return {}, []

        # 提取书籍元信息
        info = {"book_id": book_id}

        og_map = {
            "og:novel:book_name": "name",
            "og:novel:author": "author",
            "og:novel:category": "category",
            "og:novel:status": "status",
        }
        for og_key, info_key in og_map.items():
            m = re.search(rf'property="{og_key}"\s+content="([^"]*)"', html)
            if m:
                info[info_key] = m.group(1).strip()

        # 备选方式提取书名和作者
        if "name" not in info:
            m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
            if m:
                info["name"] = m.group(1).strip()
            else:
                info["name"] = book_id

        if "author" not in info:
            m = re.search(r'作者[：:]\s*([^<\s]+)', html)
            if m:
                info["author"] = m.group(1).strip()
            else:
                info["author"] = "未知"

        info.setdefault("category", "")
        info.setdefault("status", "")

        # 简介
        m = re.search(r'<div[^>]*class="intro"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            info["description"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        else:
            info["description"] = ""

        # 提取章节列表
        # 格式: <dd><a href="/n/书名拼音/123.html">章节名</a></dd>
        # 页面可能包含"最新章节"区（倒序）和"正文"区（正序），优先取正文区
        zhengwen_idx = html.find("正文")
        if zhengwen_idx > 0:
            chapter_html = html[zhengwen_idx:]
        else:
            chapter_html = html

        pattern = (
            r'<dd>\s*<a\s+href="(/n/'
            + re.escape(book_id)
            + r'/(\d+)\.html)"[^>]*>([^<]+)</a>\s*</dd>'
        )
        matches = re.findall(pattern, chapter_html)

        chapters = []
        seen = set()
        for href, ch_num, title in matches:
            if ch_num not in seen:
                seen.add(ch_num)
                full_url = self.BASE_URL + href
                chapters.append((full_url, title.strip()))

        print(
            f"  [{self.SITE_NAME}] {info.get('name', book_id)} / "
            f"{info.get('author', '未知')} - {len(chapters)} 章",
            flush=True,
        )
        return info, chapters

    def get_chapter_content(self, chapter_url) -> str:
        """获取单个章节的纯文本内容，自动处理分页。

        Args:
            chapter_url: 章节页面的完整 URL。

        Returns:
            章节纯文本内容。获取失败时返回空字符串。
        """
        all_text = []
        current_url = chapter_url
        max_sub_pages = 20  # 防止无限循环

        for _ in range(max_sub_pages):
            html = self.fetch(current_url)
            if not html:
                break

            # 提取 id="content" 的 div 中的正文
            m = re.search(r'id="content"[^>]*>(.*?)</div>', html, re.DOTALL)
            if m:
                content_html = m.group(1)
                text = self.clean_html(content_html)
                if text:
                    all_text.append(text)

            # 检查分页：下一页链接
            # 常见格式: <a href="xxx_2.html" class="next">下一页</a>
            # 或: <a class="next" href="xxx_2.html">下一页</a>
            next_match = re.search(
                r'<a[^>]*href="([^"]*)"[^>]*>\s*下一页\s*</a>', html
            )
            if not next_match:
                # 另一种顺序
                next_match = re.search(
                    r'<a[^>]*class="next"[^>]*href="([^"]*)"[^>]*>', html
                )

            if next_match:
                next_href = next_match.group(1)
                # 判断是否为章节内分页（同一章的子页），而非下一章
                # 分页通常是 xxx_2.html, xxx_3.html 格式
                if re.search(r'_\d+\.html$', next_href):
                    if next_href.startswith("/"):
                        current_url = self.BASE_URL + next_href
                    elif next_href.startswith("http"):
                        current_url = next_href
                    else:
                        base_path = chapter_url.rsplit("/", 1)[0]
                        current_url = base_path + "/" + next_href
                    self.polite_sleep()
                else:
                    # 链接指向的是下一章，停止
                    break
            else:
                break

        return "\n".join(all_text)

    def get_ad_patterns(self) -> list[str]:
        """返回全本小说网常见的广告行正则模式。

        Returns:
            正则模式字符串列表。
        """
        return [
            r'.*全本小说网.*',
            r'.*quanben.*\.com.*',
            r'.*quanben-xiaoshuo.*',
            r'.*www\.quanben.*',
            r'.*请大家收藏.*',
            r'.*本小章还未完.*点击下一页.*',
            r'.*喜欢.*请大家收藏.*',
            r'.*最新章节.*全网最快.*',
            r'.*手机用户请浏览.*阅读.*',
            r'.*一秒记住.*',
            r'.*更新速度最快.*',
            r'.*天才一秒记住.*',
            r'.*最快更新.*',
            r'.*百度搜索.*全本小说.*',
            r'.*记住本站.*',
        ]

    # ----------------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------------

    @staticmethod
    def list_categories() -> dict[str, str]:
        """列出所有支持的分类及其 URL 路径。

        Returns:
            {分类中文名: URL路径} 字典。
        """
        return dict(CATEGORY_MAP)

    @staticmethod
    def list_domains() -> list[str]:
        """列出所有可用域名。

        Returns:
            域名字符串列表。
        """
        return list(AVAILABLE_DOMAINS)


# ================================================================
# CLI 入口
# ================================================================
def main():
    """命令行入口，支持分类浏览和批量下载。"""
    parser = argparse.ArgumentParser(
        description="全本小说网爬虫 - 学术研究用语料采集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 列出所有分类
  python -m scraper.sites.quanben --list-categories

  # 下载玄幻分类前10本
  python -m scraper.sites.quanben --category 玄幻 --max 10

  # 使用备用域名
  python -m scraper.sites.quanben --category 都市 --max 5 --domain quanben.io

  # 按书籍ID下载
  python -m scraper.sites.quanben --book-id guimizhuzhizhuren
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--category", type=str, help="下载指定分类的书籍")
    group.add_argument("--list-categories", action="store_true", help="列出所有分类")
    group.add_argument("--book-id", type=str, help="按书籍拼音ID下载指定小说")

    parser.add_argument(
        "--max", type=int, default=10, help="最多下载几本 (默认: 10)"
    )
    parser.add_argument(
        "--max-pages", type=int, default=5, help="分类列表最多翻几页 (默认: 5)"
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help=f"使用的域名 (默认: quanben-xiaoshuo.com, 可选: {', '.join(AVAILABLE_DOMAINS)})",
    )
    parser.add_argument("--output", type=str, default=None, help="输出目录")

    args = parser.parse_args()

    if args.list_categories:
        print("全本小说网 - 可用分类:")
        print("-" * 30)
        for name, path in CATEGORY_MAP.items():
            print(f"  {name:<6s}  {path}")
        print(f"\n可用域名: {', '.join(AVAILABLE_DOMAINS)}")
        return

    scraper = QuanbenScraper(output_base=args.output, domain=args.domain)

    if args.book_id:
        print(f"下载书籍: {args.book_id}")
        result = scraper.download_book(args.book_id)
        if result:
            print(f"\n完成，输出目录: {result}")
        else:
            print("\n下载失败")
    elif args.category:
        print(f"批量下载: {args.category} (最多 {args.max} 本)")
        scraper.batch_download(
            category=args.category,
            max_books=args.max,
            max_pages=args.max_pages,
        )


if __name__ == "__main__":
    main()
