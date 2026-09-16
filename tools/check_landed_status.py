# -*- coding: utf-8 -*-
"""落地状态核对（not-done 表述 × 已核实落地的能力）—— 基线式回归。

【为什么要有它】这个项目最大的对外风险不是"功能少"，是**文档说错**：
已经落地的东西还写着"未落地/没接/进行中"。这类错已经被抓到 4 批：
  工具无限第 5 步四项、`self_rate()`、睡眠（落在 energy/heartbeat，不在 health 模块）、
  内感受篇那句"硬改三样还没接"。
**光靠人看一定会漏** —— 所以要有一个能反复跑的东西。

做法：
  ① 维护一份「已核实落地」的能力关键词表（每条都到代码里看过）
  ② 扫全仓所有 not-done 句子，命中关键词表的就是候选
  ③ 与 `tools/landed_status_allow.txt` 里的**基线**比对：
     · 在基线上 → 已知且已逐条判过，不报
     · 不在基线上 → **新出现的**，报出来
  ④ 基线里每条都写了"为什么它是对的"

⚠️ **诚实说明**：基线不等于"证明都对"。它是"某年某月某日逐条判过一遍"的记录。
   基线里任何一条**都可能随时间变错** —— 所以定期要重新审一遍基线本身。

用法：
    python tools/check_landed_status.py            # 比对基线
    python tools/check_landed_status.py --rebuild  # 重写基线（审过之后才用）
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOW = os.path.join(ROOT, "tools", "landed_status_allow.txt")
SKIP = {".git", "logs", "node_modules", "__pycache__", ".pytest_cache"}

NOTDONE = re.compile(r"未落地|未接入|尚未|没有接入|还没(有)?(接|做|实现)|未实现|"
                     r"进行中|计划中|规划中|待实现|待落地|设计目标")

# 「已核实落地」的能力 —— 每条都到代码里看过（见文件尾的出处）
LANDED = {
    "睡眠/精力/心跳": re.compile(r"睡眠|精力|心跳|挂起|唤醒"),
    "EYC 进行时自述": re.compile(r"EYC|进行时|自述|第一人称"),
    "路径二四阶段": re.compile(r"内感受|视角状态|perspective|自我模型|self_model|硬改"),
    "工具无限第5步": re.compile(r"第 ?5 步|工具调度|上下文隔离|结果校验|幻觉|archify"),
    "元认知自评": re.compile(r"self_rate|自评|元认知|cross_check|交叉检查"),
    "两处真修": re.compile(r"命=无|偏好|聚类|跨类"),
    "三条补接线": re.compile(r"因果归属|归属|疼|相关记忆优先"),
    "记忆污染五修": re.compile(r"记忆污染|来源标记|修饰词|时间线|清库|工具结果"),
    "上下文四层防护": re.compile(r"上下文无限|_fit_context|摘要"),
}
# 讲"这次改名/更正"的句子不算（否则正确的描述会被当成残留）
RENAME_HINT = ("→", "改名", "改为", "已改", "更正", "原来是", "过期标注", "早先")


def scan():
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            if rel.startswith("CHANGELOG"):
                continue
            for i, ln in enumerate(io.open(p, encoding="utf-8", errors="replace").read().splitlines(), 1):
                if not NOTDONE.search(ln) or any(k in ln for k in RENAME_HINT):
                    continue
                for cap, pat in LANDED.items():
                    if pat.search(ln):
                        out.append((rel, i, cap, ln.strip()))
                        break
    return out


def fingerprint(rel, line):
    return hashlib.sha1(("%s|%s" % (rel, re.sub(r"\s+", "", line)[:80])).encode("utf-8")).hexdigest()[:16]


def load_allow():
    d = {}
    if os.path.exists(ALLOW):
        for ln in io.open(ALLOW, encoding="utf-8", errors="replace"):
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) >= 2:
                d[parts[0]] = parts[1] if len(parts) > 1 else ""
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="重写基线（审过之后再写）")
    args = ap.parse_args()

    items = scan()
    if args.rebuild:
        seen, lines = set(), []
        lines.append("# 落地状态基线：这些 not-done 句子已逐条判过，是【对的】或【工具误报】")
        lines.append("# 格式：<指纹>\\t<文件:行 摘要>")
        lines.append("# ⚠️ 基线≠证明都对；每条都可能随时间变错，需定期重审。")
        for rel, i, cap, text in sorted(items):
            fp = fingerprint(rel, text)
            if fp in seen:
                continue
            seen.add(fp)
            lines.append("%s\t%s:%d [%s] %s" % (fp, rel, i, cap, re.sub(r"\s+", " ", text)[:90]))
        with io.open(ALLOW, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        print("已重写基线：%d 条 → %s" % (len(seen), ALLOW))
        return 0

    allow = load_allow()
    new = [(rel, i, cap, t) for rel, i, cap, t in items if fingerprint(rel, t) not in allow]
    print("扫描：命中「已落地能力 × not-done 表述」%d 处；基线内 %d 处"
          % (len(items), len(items) - len(new)))
    if not new:
        print("✅ 没有**新出现**的过期表述。")
        return 0
    print("❌ 有 %d 处不在基线里（新出现 / 或被改过）—— 逐条确认是不是过期标注：" % len(new))
    for rel, i, cap, t in sorted(new):
        print("  %-46s 行%-5d [%s]" % (rel, i, cap))
        print("      %s" % re.sub(r"\s+", " ", t)[:140])
    return 1


if __name__ == "__main__":
    sys.exit(main())
