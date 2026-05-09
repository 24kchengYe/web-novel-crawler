import os, urllib.request
# 强制清除代理环境变量
for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy']:
    os.environ.pop(k, None)
# 强制不走代理
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    r = opener.open('https://www.qbxsw.com/', timeout=10)
    print(f'Direct OK: {r.status}, len={len(r.read())}')
except Exception as e:
    print(f'Direct FAIL: {e}')
