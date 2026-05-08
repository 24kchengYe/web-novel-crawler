#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
并行下载器 —— 将书单分片，启动多个子进程同时下载
每个子进程独立调用 novel_scraper.py --id，共享 download_log.json

用法:
  python parallel_download.py                  # 默认4个worker
  python parallel_download.py --workers 6      # 6个worker
  python parallel_download.py --workers 4 --max 200  # 最多下200本
"""

import os
import sys
import io
import json
import time
import signal
import subprocess
import threading

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BOOKLIST_PATH = os.path.join(BASE_DIR, 'booklist.json')
DATA_DIR = os.path.join(BASE_DIR, 'data')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
DL_LOG_PATH = os.path.join(DATA_DIR, 'download_log.json')
PYTHON_EXE = sys.executable

# 文件锁用于安全写 download_log
_log_lock = threading.Lock()


def load_downloaded():
    """加载已下载ID集合"""
    if os.path.exists(DL_LOG_PATH):
        with open(DL_LOG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def record_download(qb_id, name):
    """线程安全地记录已下载"""
    with _log_lock:
        log = load_downloaded()
        log[qb_id] = {
            'name': name,
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(DL_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)


def get_pending_tasks(max_books=None):
    """获取待下载任务（排除已下载）"""
    with open(BOOKLIST_PATH, 'r', encoding='utf-8') as f:
        booklist = json.load(f)

    downloaded = set(load_downloaded().keys())

    tasks = []
    for book in booklist['books']:
        qb_id = book.get('qbxsw_id', '')
        if not qb_id or qb_id in downloaded:
            continue
        tasks.append({
            'qbxsw_id': qb_id,
            'name': book.get('name', ''),
        })

    if max_books:
        tasks = tasks[:max_books]
    return tasks


def worker(worker_id, task_queue, stats, stop_event=None):
    """
    worker线程：从队列取任务，调用 novel_scraper.py 下载
    连续失败时自动暂停，避免打死目标站点
    stop_event: 被设置时优雅退出
    """
    log_file = os.path.join(LOG_DIR, f'worker_{worker_id}.log')
    consecutive_book_fails = 0

    with open(log_file, 'w', encoding='utf-8') as log:
        while True:
            # 检查停止信号
            if stop_event and stop_event.is_set():
                log.write(f"[W{worker_id}] 收到停止信号，退出\n")
                break

            # 连续多本书失败 → 大概率被限流了，长时间暂停
            if consecutive_book_fails >= 3:
                pause = min(consecutive_book_fails * 60, 300)
                msg = f"[W{worker_id}] 连续{consecutive_book_fails}本失败，暂停{pause}s等限流恢复..."
                print(msg)
                log.write(msg + '\n')
                log.flush()
                # 分段 sleep，每秒检查一次停止信号
                for _ in range(pause):
                    if stop_event and stop_event.is_set():
                        break
                    time.sleep(1)

            # 从队列取任务
            try:
                task = task_queue.pop(0)
            except IndexError:
                break  # 队列空了

            qb_id = task['qbxsw_id']
            name = task['name']

            # 再次检查（其他worker可能已经下载了）
            if qb_id in load_downloaded():
                continue

            remaining = len(task_queue)
            msg = f"[W{worker_id}] {name} (qb={qb_id}) [剩余{remaining}]"
            print(msg)
            log.write(msg + '\n')
            log.flush()

            cmd = [
                PYTHON_EXE, '-u',  # -u: unbuffered，实时输出
                os.path.join(BASE_DIR, 'novel_scraper.py'),
                '--id', qb_id,
            ]

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    cwd=BASE_DIR,
                )
                # 实时读取子进程输出，同时检查停止信号
                for line in proc.stdout:
                    if stop_event and stop_event.is_set():
                        proc.kill()
                        break
                    line = line.rstrip('\n')
                    if line:
                        tagged = f"[W{worker_id}] {line}"
                        print(tagged)
                        log.write(line + '\n')
                proc.wait(timeout=30)

                if proc.returncode == 0:
                    record_download(qb_id, name)
                    stats['ok'] += 1
                    consecutive_book_fails = 0
                    log.write(f"  OK\n")
                elif stop_event and stop_event.is_set():
                    log.write(f"  STOPPED\n")
                    break
                else:
                    stats['fail'] += 1
                    consecutive_book_fails += 1
                    log.write(f"  FAIL (exit {proc.returncode})\n")
            except subprocess.TimeoutExpired:
                proc.kill()
                stats['fail'] += 1
                consecutive_book_fails += 1
                log.write(f"  TIMEOUT\n")
            except Exception as e:
                stats['fail'] += 1
                consecutive_book_fails += 1
                log.write(f"  ERROR: {e}\n")

            log.flush()

    return worker_id


def main():
    import argparse
    parser = argparse.ArgumentParser(description='并行下载器')
    parser.add_argument('--workers', type=int, default=3, help='并行进程数 (默认3)')

    parser.add_argument('--max', type=int, default=None, help='最多下载几本')
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    tasks = get_pending_tasks(args.max)
    if not tasks:
        print("没有待下载的书籍。")
        return

    print(f"{'='*60}")
    print(f"并行下载器")
    print(f"  待下载: {len(tasks)} 本")
    print(f"  线程数: {args.workers}")
    print(f"  数据目录: {DATA_DIR}")
    print(f"{'='*60}\n")

    # 共享任务队列（线程安全：list.pop(0) 在 CPython 下是原子的，加上 GIL）
    task_queue = list(tasks)
    stats = {'ok': 0, 'fail': 0}

    start_time = time.time()
    _stop_event = threading.Event()

    # Ctrl+C 处理：设置停止标志，让 worker 优雅退出
    def _signal_handler(sig, frame):
        print("\n\n[Ctrl+C] 正在停止所有 worker，已下载的数据不会丢失...")
        _stop_event.set()
    signal.signal(signal.SIGINT, _signal_handler)

    # 把 stop_event 注入 worker（通过闭包替换 task_queue.pop）
    original_worker = worker

    def stoppable_worker(worker_id, tq, st):
        original_worker(worker_id, tq, st, _stop_event)

    threads = []
    for w in range(args.workers):
        t = threading.Thread(target=stoppable_worker, args=(w, task_queue, stats), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(3)  # 错开启动

    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=1)
    except KeyboardInterrupt:
        _stop_event.set()
        print("\n等待 worker 退出...")
        for t in threads:
            t.join(timeout=10)

    elapsed = time.time() - start_time
    total_done = len(load_downloaded())

    print(f"\n{'='*60}")
    print(f"全部完成！")
    print(f"  本次成功: {stats['ok']}, 失败: {stats['fail']}")
    print(f"  累计已下载: {total_done} 本")
    print(f"  耗时: {elapsed/60:.1f} 分钟")
    print(f"  日志: {LOG_DIR}/worker_*.log")


if __name__ == '__main__':
    main()
