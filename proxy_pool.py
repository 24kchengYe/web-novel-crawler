#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
代理池：读取 NekoBox 的 vmess 节点配置，启动多个本地 SOCKS5 代理端口
每个端口走不同的出口 IP，爬虫轮换使用

用法:
  python proxy_pool.py start          # 启动代理池（默认10个节点）
  python proxy_pool.py start -n 20    # 启动20个节点
  python proxy_pool.py stop           # 停止代理池
  python proxy_pool.py test           # 测试代理池可用性
  python proxy_pool.py list           # 列出可用节点
"""

import os
import sys
import io
import json
import time
import random
import subprocess
import threading
import urllib.request
import argparse

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEKO_DIR = r"D:\BaiduNetdiskDownload\v2rayN-Core(1)\nekoray-4.0.1-2024-12-12-windows64 (1)\nekoray"
NEKO_CORE = os.path.join(NEKO_DIR, "nekobox_core.exe")
PROFILES_DIR = os.path.join(NEKO_DIR, "config", "profiles")
POOL_DIR = os.path.join(BASE_DIR, "proxy_pool_configs")
POOL_STATE_FILE = os.path.join(BASE_DIR, "proxy_pool_state.json")

# 代理池本地端口起始
BASE_PORT = 3000


def load_profiles(max_nodes=None):
    """从 NekoBox profiles 目录读取 trojan/vmess 节点（优先 trojan）"""
    trojan_nodes = []
    vmess_nodes = []

    for fname in sorted(os.listdir(PROFILES_DIR), key=lambda x: int(x.replace('.json', ''))):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(PROFILES_DIR, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
            except:
                continue

        node_type = data.get('type', '')
        bean = data.get('bean', {})
        name = bean.get('name', '')
        stream = bean.get('stream', {})

        if node_type == 'trojan':
            trojan_nodes.append({
                'id': data.get('id', 0),
                'type': 'trojan',
                'name': name,
                'addr': bean.get('addr', ''),
                'port': bean.get('port', 0),
                'password': bean.get('pass', ''),
                'sni': stream.get('sni', ''),
                'insecure': stream.get('insecure', False),
            })
        elif node_type == 'vmess':
            vmess_nodes.append({
                'id': data.get('id', 0),
                'type': 'vmess',
                'name': name,
                'addr': bean.get('addr', ''),
                'port': bean.get('port', 0),
                'uuid': bean.get('id', ''),
                'aid': bean.get('aid', 0),
                'security': bean.get('sec', 'auto'),
                'net': stream.get('net', 'tcp'),
            })

    # 优先 trojan（更稳定），不够再补 vmess
    nodes = trojan_nodes + vmess_nodes
    if max_nodes:
        return nodes[:max_nodes]
    return nodes


def generate_singbox_config(node, local_port):
    """为单个节点生成 sing-box 配置（支持 trojan 和 vmess）"""
    if node['type'] == 'trojan':
        outbound = {
            "type": "trojan",
            "tag": "proxy",
            "server": node['addr'],
            "server_port": node['port'],
            "password": node['password'],
            "tls": {
                "enabled": True,
                "server_name": node.get('sni', ''),
                "insecure": node.get('insecure', False),
            },
        }
    else:  # vmess
        outbound = {
            "type": "vmess",
            "tag": "proxy",
            "server": node['addr'],
            "server_port": node['port'],
            "uuid": node['uuid'],
            "alter_id": node.get('aid', 0),
            "security": node.get('security', 'auto'),
        }

    config = {
        "log": {"level": "error"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": local_port,
            }
        ],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
    }
    return config


def start_pool(num_nodes=10):
    """启动代理池"""
    nodes = load_profiles(max_nodes=num_nodes)
    if not nodes:
        print("未找到可用的 vmess 节点")
        return

    print(f"找到 {len(nodes)} 个节点，启动代理池...")

    os.makedirs(POOL_DIR, exist_ok=True)

    pool_state = {'proxies': [], 'pids': []}
    processes = []

    for i, node in enumerate(nodes):
        local_port = BASE_PORT + i
        config = generate_singbox_config(node, local_port)

        config_path = os.path.join(POOL_DIR, f"node_{i}.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        # 启动 sing-box 实例
        cmd = [NEKO_CORE, "run", "-c", config_path]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            processes.append(proc)
            pool_state['proxies'].append({
                'port': local_port,
                'url': f'http://127.0.0.1:{local_port}',
                'node_name': node['name'],
                'pid': proc.pid,
            })
            pool_state['pids'].append(proc.pid)
            print(f"  [{i+1}/{len(nodes)}] :{local_port} -> {node['name']} (PID {proc.pid})")
        except Exception as e:
            print(f"  [{i+1}/{len(nodes)}] 启动失败: {e}")

    # 保存状态
    with open(POOL_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(pool_state, f, ensure_ascii=False, indent=2)

    print(f"\n代理池启动完成: {len(pool_state['proxies'])} 个代理")
    print(f"  端口范围: {BASE_PORT}-{BASE_PORT + len(pool_state['proxies']) - 1}")
    print(f"  状态文件: {POOL_STATE_FILE}")

    # 等一下让进程初始化
    time.sleep(2)

    # 快速测试
    test_pool(quick=True)


def stop_pool():
    """停止代理池"""
    if not os.path.exists(POOL_STATE_FILE):
        print("代理池未启动")
        return

    with open(POOL_STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)

    for pid in state.get('pids', []):
        try:
            subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                           capture_output=True, timeout=5)
        except:
            pass

    os.remove(POOL_STATE_FILE)
    print(f"代理池已停止，杀掉 {len(state.get('pids', []))} 个进程")


def get_proxy_list():
    """获取当前可用的代理列表"""
    if not os.path.exists(POOL_STATE_FILE):
        return []
    with open(POOL_STATE_FILE, 'r', encoding='utf-8') as f:
        state = json.load(f)
    return [p['url'] for p in state.get('proxies', [])]


def test_pool(quick=False):
    """测试代理池可用性"""
    proxies = get_proxy_list()
    if not proxies:
        print("代理池未启动或无可用代理")
        return

    test_url = 'https://www.qbxsw.com/du_17701/21578934.html'
    print(f"\n测试 {len(proxies)} 个代理 (目标: qbxsw.com)...")

    ok = 0
    fail = 0
    for i, proxy_url in enumerate(proxies):
        if quick and i >= 3:
            break
        try:
            handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
            opener = urllib.request.build_opener(handler)
            req = urllib.request.Request(test_url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            t0 = time.time()
            resp = opener.open(req, timeout=10)
            data = resp.read()
            elapsed = time.time() - t0
            print(f"  :{proxy_url.split(':')[-1]} OK ({elapsed:.1f}s, {len(data)}b)")
            ok += 1
        except Exception as e:
            print(f"  :{proxy_url.split(':')[-1]} FAIL: {str(e)[:60]}")
            fail += 1

    print(f"\n结果: {ok} 成功, {fail} 失败")


def list_nodes():
    """列出所有可用节点"""
    nodes = load_profiles()
    print(f"共 {len(nodes)} 个 vmess 节点:")
    for i, n in enumerate(nodes):
        print(f"  {i:3d}. {n['name']} ({n['addr']}:{n['port']})")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='NekoBox 代理池')
    parser.add_argument('action', choices=['start', 'stop', 'test', 'list'],
                        help='start=启动, stop=停止, test=测试, list=列出节点')
    parser.add_argument('-n', type=int, default=10, help='启动几个节点 (默认10)')
    args = parser.parse_args()

    if args.action == 'start':
        start_pool(args.n)
    elif args.action == 'stop':
        stop_pool()
    elif args.action == 'test':
        test_pool()
    elif args.action == 'list':
        list_nodes()
