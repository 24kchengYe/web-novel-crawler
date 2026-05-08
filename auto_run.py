#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自动恢复运行器：被限流就等，恢复了自动重启爬虫
用法: python auto_run.py
"""
import os, sys, io, time, subprocess, urllib.request

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
TEST_URL = 'https://www.qbxsw.com/du_17701/21578934.html'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


def is_accessible():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        req = urllib.request.Request(TEST_URL, headers=HEADERS)
        r = opener.open(req, timeout=10)
        r.read()
        return True
    except:
        return False


def wait_for_recovery():
    print(f"[{time.strftime('%H:%M:%S')}] 被限流，等待恢复...", flush=True)
    while not is_accessible():
        time.sleep(60)
    print(f"[{time.strftime('%H:%M:%S')}] 恢复了！", flush=True)


def run_downloader():
    print(f"\n[{time.strftime('%H:%M:%S')}] 启动爬虫", flush=True)
    proc = subprocess.run(
        [PYTHON, '-u', os.path.join(BASE_DIR, 'parallel_download.py'), '--workers', '2'],
        cwd=BASE_DIR,
        timeout=86400,
    )
    print(f"[{time.strftime('%H:%M:%S')}] 爬虫退出 (code={proc.returncode})", flush=True)


def get_progress():
    import json
    log_path = os.path.join(BASE_DIR, 'data', 'download_log.json')
    with open(log_path, encoding='utf-8') as f:
        return len(json.load(f))


if __name__ == '__main__':
    print("自动恢复运行器 - Ctrl+C 退出", flush=True)
    while True:
        done = get_progress()
        if done >= 1959:
            print(f"全部完成！{done} 本", flush=True)
            break

        if is_accessible():
            run_downloader()
        else:
            wait_for_recovery()

        # 爬虫退出后短暂等待再检查
        time.sleep(10)
