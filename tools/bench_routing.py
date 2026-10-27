# -*- coding: utf-8 -*-
"""难度路由实测：同一批题，逐个模型量「准确率 + 延迟」（2026-10-17）

【这个脚本回答什么】"换更大/更专的模型到底值不值"。做法很直白：
  同一批**可自动判分**的题，分别打给模型池里的每个模型，记两件事 —— 答对没、用了多久。

为什么不用 app 的 /api/chat 来测：那条路包含感知、记忆、工具、元认知等十几处内部调用，
测出来的延迟是"整条链"，看不清"模型本身"的差别。这里直接打 llama-swap，差别才干净。

判分口径（每题自带"答案里必须出现什么"）：
  · 数学/事实题 → 必须出现正确数字或词；
  · 代码题 → 必须出现 `def` / `[::-1]` 这类真代码标志（不接受"我不会"）；
  · 开放题（自我介绍）→ 非空且不超长。

用法：
    python tools/bench_routing.py                 # 全量（4 模型 × 8 题）
    python tools/bench_routing.py --save          # 另外写 docs/routing-bench.json
"""
import argparse
import io
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import requests      # noqa: E402

BASE = "http://127.0.0.1:9292/v1"
MODELS = ["xiaojiao", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder", "deepseek-v4"]

# (题, 分类, 判分函数)　分类就是难度路由里的档位含义
CASES = [
    ("用一句话说明你是谁", "闲聊", lambda a: 5 <= len(a.strip()) <= 120),
    ("你好呀", "闲聊", lambda a: len(a.strip()) >= 2),
    ("3.11 和 3.9 哪个大？只说结论", "简单事实", lambda a: "3.11" in a),
    ("17 乘以 23 等于多少？只给数字", "简单事实", lambda a: "391" in a.replace(",", "")),
    ("把 hello world 转成大写，只给结果", "简单事实", lambda a: "HELLO WORLD" in a.upper()),
    ("写一个 Python 函数把字符串反转，只给代码", "代码", lambda a: ("def " in a) and ("[::-1]" in a or "reversed" in a)),
    ("用 Python 写快速排序，只给代码", "代码", lambda a: "def " in a and ("pivot" in a.lower() or "sorted" in a)),
    ("为什么微服务要把数据库按服务拆开？用三句话说明", "重推理",
     lambda a: len(a.strip()) >= 40 and any(k in a for k in ("耦合", "边界", "事务", "数据", "扩展"))),
]


def ask(model, prompt, max_tokens=300, timeout=180):
    t0 = time.time()
    try:
        r = requests.post(BASE + "/chat/completions", json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": 0.2,
        }, timeout=timeout)
        dt = time.time() - t0
        if r.status_code != 200:
            return "", dt, "HTTP %s" % r.status_code
        d = r.json()
        txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return txt.strip(), dt, ""
    except Exception as e:
        return "", time.time() - t0, "%s: %s" % (type(e).__name__, str(e)[:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--models", default="")
    a = ap.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()] or MODELS

    print("=" * 104)
    print("  难度路由实测：%d 个模型 × %d 道题（判分自动，延迟直测）" % (len(models), len(CASES)))
    print("=" * 104)
    rows = []
    for m in models:
        for q, kind, judge in CASES:
            ans, dt, err = ask(m, q)
            ok = bool(judge(ans)) if ans else False
            rows.append({"model": m, "q": q, "kind": kind, "sec": round(dt, 1),
                         "ok": ok, "err": err, "len": len(ans),
                         "head": ans.replace("\n", " ")[:70]})
            print("  %-38s %-8s %5.1fs  %s" % (m[:38], kind, dt, "✅" if ok else "❌"),
                  ("  " + ans.replace("\n", " ")[:50]) if not ok else "")

    print("\n" + "=" * 104)
    print("  按「模型 × 分类」汇总（准确率 / 平均延迟）")
    print("=" * 104)
    kinds = []
    for _q, k, _j in CASES:
        if k not in kinds:
            kinds.append(k)
    print("  %-38s %s" % ("模型", "  ".join("%-14s" % k for k in kinds)))
    summary = {}
    for m in models:
        cells = []
        for k in kinds:
            sel = [r for r in rows if r["model"] == m and r["kind"] == k]
            if not sel:
                cells.append("%-14s" % "-")
                continue
            acc = 100.0 * sum(1 for r in sel if r["ok"]) / len(sel)
            avg = sum(r["sec"] for r in sel) / len(sel)
            summary.setdefault(m, {})[k] = {"acc": round(acc, 1), "avg_s": round(avg, 1)}
            cells.append("%-14s" % ("%.0f%% / %.1fs" % (acc, avg)))
        print("  %-38s %s" % (m[:38], "  ".join(cells)))

    # 档位视角：路由会怎么选，以及那样选值不值
    print("\n" + "=" * 104)
    print("  路由视角：每个档的首选模型，在「它负责的那类题」上表现如何")
    print("=" * 104)
    route_map = {"fast": ("xiaojiao", ["闲聊", "简单事实"]),
                 "code": ("qwopus3.5-4b-coder-mtp-q5_k_m.gguf", ["代码"]),
                 "strong": ("deepseek-v4", ["重推理"])}
    verdict = {}
    for tier, (model, kk) in route_map.items():
        sel = [r for r in rows if r["model"] == model and r["kind"] in kk]
        if not sel:
            print("  %-7s %-38s 没有数据" % (tier, model))
            continue
        acc = 100.0 * sum(1 for r in sel if r["ok"]) / len(sel)
        avg = sum(r["sec"] for r in sel) / len(sel)
        # 对照：同一个档的题，用别的模型（尤其"更强的" deepseek-v4）表现如何
        alts = []
        for other in models:
            if other == model:
                continue
            s2 = [r for r in rows if r["model"] == other and r["kind"] in kk]
            if s2:
                alts.append((other, 100.0 * sum(1 for r in s2 if r["ok"]) / len(s2),
                             sum(r["sec"] for r in s2) / len(s2)))
        best_alt = max(alts, key=lambda x: x[1]) if alts else None
        verdict[tier] = {"model": model, "acc": round(acc, 1), "avg_s": round(avg, 1),
                         "alts": [{"model": o, "acc": round(a2, 1), "avg_s": round(s3, 1)}
                                  for o, a2, s3 in alts]}
        print("  %-7s %-38s 准确率 %.0f%% / 平均 %.1fs" % (tier, model[:38], acc, avg))
        if best_alt:
            print("          对照 %-34s 准确率 %.0f%% / 平均 %.1fs  → %s"
                  % (str(best_alt[0])[:34], best_alt[1], best_alt[2],
                     "本档选择更划算" if (acc >= best_alt[1] and avg <= best_alt[2]) else
                     "值得复看"))

    if a.save:
        out = os.path.join(_ROOT, "docs", "routing-bench.json")
        io.open(out, "w", encoding="utf-8").write(json.dumps(
            {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": BASE,
             "rows": rows, "summary": summary, "verdict": verdict},
            ensure_ascii=False, indent=1))
        print("\n  已写：%s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
