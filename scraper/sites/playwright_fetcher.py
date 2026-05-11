#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Playwright 无头浏览器内容获取器

为需要 JS 渲染的站点提供正文获取能力。
使用浏览器池复用实例，避免频繁启停。

用法:
  fetcher = PlaywrightFetcher(max_browsers=2)
  text = fetcher.get_page_text(url, wait_ms=5000)
  fetcher.close()
"""

import re
import time
import threading
from queue import Queue


class PlaywrightFetcher:
    """Playwright 无头浏览器内容获取器"""

    def __init__(self, max_browsers=2, headless=True):
        self._headless = headless
        self._max_browsers = max_browsers
        self._pw = None
        self._browser = None
        self._page_pool = Queue()
        self._lock = threading.Lock()
        self._started = False

    def _ensure_started(self):
        """懒启动 Playwright"""
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            from playwright.sync_api import sync_playwright
            self._pw_context = sync_playwright()
            self._pw = self._pw_context.start()
            self._browser = self._pw.chromium.launch(headless=self._headless)
            # 创建页面池
            for _ in range(self._max_browsers):
                ctx = self._browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36",
                )
                page = ctx.new_page()
                self._page_pool.put(page)
            self._started = True

    def get_page_text(self, url, wait_ms=5000, timeout_ms=20000) -> str:
        """
        获取页面渲染后的纯文本内容。

        Args:
            url: 页面 URL
            wait_ms: JS 渲染等待时间（毫秒）
            timeout_ms: 页面加载超时（毫秒）

        Returns:
            页面 body 的纯文本，获取失败返回空字符串
        """
        self._ensure_started()
        page = self._page_pool.get()
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            text = page.inner_text("body")
            return text
        except Exception as e:
            print(f"  [Playwright] 获取失败: {url} -> {e}")
            return ""
        finally:
            self._page_pool.put(page)

    def get_page_html(self, url, wait_ms=5000, timeout_ms=20000) -> str:
        """获取渲染后的完整 HTML"""
        self._ensure_started()
        page = self._page_pool.get()
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            return page.content()
        except Exception as e:
            print(f"  [Playwright] 获取失败: {url} -> {e}")
            return ""
        finally:
            self._page_pool.put(page)

    def close(self):
        """关闭浏览器"""
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw_context.__exit__(None, None, None)
        self._started = False


# 全局单例（进程内共享）
_global_fetcher = None
_global_lock = threading.Lock()


def get_fetcher(max_browsers=2) -> PlaywrightFetcher:
    """获取全局 PlaywrightFetcher 单例"""
    global _global_fetcher
    if _global_fetcher is None:
        with _global_lock:
            if _global_fetcher is None:
                _global_fetcher = PlaywrightFetcher(max_browsers=max_browsers)
    return _global_fetcher
