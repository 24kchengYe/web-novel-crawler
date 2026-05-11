#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Playwright 无头浏览器内容获取器

为需要 JS 渲染的站点提供正文获取能力。
每次请求创建新页面，失败后自动重启浏览器。

用法:
  fetcher = PlaywrightFetcher()
  text = fetcher.get_page_text(url, wait_ms=5000)
  fetcher.close()
"""

import time
import threading


class PlaywrightFetcher:
    """Playwright 无头浏览器内容获取器（自动重启）"""

    def __init__(self, headless=True):
        self._headless = headless
        self._pw_context_mgr = None
        self._pw = None
        self._browser = None
        self._lock = threading.Lock()
        self._consecutive_fails = 0

    def _start_browser(self):
        """启动或重启浏览器"""
        self._close_browser()
        from playwright.sync_api import sync_playwright
        self._pw_context_mgr = sync_playwright()
        self._pw = self._pw_context_mgr.start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._consecutive_fails = 0

    def _close_browser(self):
        """安全关闭浏览器"""
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw_context_mgr:
                self._pw_context_mgr.__exit__(None, None, None)
        except Exception:
            pass
        self._browser = None
        self._pw = None
        self._pw_context_mgr = None

    def _ensure_browser(self):
        """确保浏览器可用，必要时重启"""
        if self._browser is None or not self._browser.is_connected():
            self._start_browser()

    def get_page_text(self, url, wait_ms=5000, timeout_ms=20000) -> str:
        """
        获取页面渲染后的纯文本内容。
        每次用新页面，失败自动重启浏览器。
        """
        with self._lock:
            try:
                self._ensure_browser()
                page = self._browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36",
                )
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(wait_ms)
                    text = page.inner_text("body")
                    self._consecutive_fails = 0
                    return text
                finally:
                    page.close()
            except Exception as e:
                self._consecutive_fails += 1
                err_msg = str(e)[:80]
                # 超时或线程死亡 → 重启浏览器
                if self._consecutive_fails >= 2 or "thread" in err_msg.lower() or "closed" in err_msg.lower():
                    print(f"  [Playwright] 重启浏览器 (连续{self._consecutive_fails}次失败)", flush=True)
                    try:
                        self._start_browser()
                    except Exception as restart_err:
                        print(f"  [Playwright] 重启失败: {restart_err}", flush=True)
                else:
                    print(f"  [Playwright] 获取失败: {err_msg}", flush=True)
                return ""

    def get_page_html(self, url, wait_ms=5000, timeout_ms=20000) -> str:
        """获取渲染后的完整 HTML"""
        with self._lock:
            try:
                self._ensure_browser()
                page = self._browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36",
                )
                try:
                    page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                    page.wait_for_timeout(wait_ms)
                    return page.content()
                finally:
                    page.close()
            except Exception as e:
                self._consecutive_fails += 1
                if self._consecutive_fails >= 2:
                    try:
                        self._start_browser()
                    except Exception:
                        pass
                return ""

    def close(self):
        """关闭浏览器"""
        self._close_browser()


# 全局单例
_global_fetcher = None
_global_lock = threading.Lock()


def get_fetcher() -> PlaywrightFetcher:
    """获取全局 PlaywrightFetcher 单例"""
    global _global_fetcher
    if _global_fetcher is None:
        with _global_lock:
            if _global_fetcher is None:
                _global_fetcher = PlaywrightFetcher()
    return _global_fetcher
