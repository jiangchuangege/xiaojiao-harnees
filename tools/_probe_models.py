# -*- coding: utf-8 -*-
"""模型池探测（一次性，跑完可删）：llama-swap 里每个模型真出一次话，量延迟。"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

BASE = "http://127.0.0.1:9292/v1"
MODELS = ["xiaojiao", "coder", "deepseek-v4", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf"]
TESTS = [
    ("闲聊", "用一句话说明你是谁"),
    ("推理", "3.11 和 3.9 哪个大？只回答哪个大和为什么，20 字内"),
    ("代码", "写一个 Python 快速排序函数，只给代码"),
]


def ask(model, prompt, max_tokens=120):
    t0 = time.time()
    r = requests.post(BASE + "/chat/completions", json={
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }, timeout=300)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, "HTTP %s: %s" % (r.status_code, r.text[:120])
    d = r.json()
    txt = (d.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    usage = d.get("usage") or {}
    return txt.strip(), dt, "tokens=%s" % (usage.get("completion_tokens") or "?")


print("=" * 100)
for m in MODELS:
    print("\n### %s" % m)
    for kind, p in TESTS:
        try:
            txt, dt, note = ask(m, p)
        except Exception as e:
            print("  [%s] 异常：%s: %s" % (kind, type(e).__name__, str(e)[:80]))
            continue
        if txt is None:
            print("  [%s] 失败：%s" % (kind, note))
            continue
        one = txt.replace("\n", " ")[:80]
        print("  [%s] %.1fs ｜ %s ｜ %s" % (kind, dt, note, one))
print("\n" + "=" * 100)
