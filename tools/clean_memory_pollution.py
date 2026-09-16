# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
"""记忆库污染清理（一次性维护工具 · 先备份再删 · 默认只干跑）

【为什么需要它 —— 实测症状】
  对话记忆里混进了**工具侧的产出**与**坏回复**，最直接的后果是：
  用户问「你还记得上一次吗」，它答「我记不起上一次我们聊了什么 —— 不过我记得一些
  **你曾经提到过的内容**：…哔哩哔哩…」。那句"你曾经提到过"里的东西**根本不是用户说的**，
  是抓取结果的残留。**把"它说的/工具给的"说成"用户说的"，是比检索不准更严重的问题。**

  被污染的还有一类更隐蔽的：**系统提示词泄漏进回答**后整条存进记忆
  （`【系统指令】角色：小焦…工具：list_files…`），以及模型的 `<think>` 未闭合残留。

【判据分三类 + 一条"不清"的边界】
  ① 工具侧产出：抓取结果头（`URL · HTTP 200`）、`🌐 **URL**` 渲染头、
     载体的抓取守卫提示（`⚠️ 抓取失败` / `⚠️ **可能幻觉**` / `✅ 抓取成功`）、
     `📋 **页面结构速览**`、NVD 的"未收录产品配置"标注。
  ② 坏回复：`<think>` 残留、`【系统指令】` 泄漏、整条就是 `⏳ 正在调用工具…` 占位符、
     `（已回答）` 占位符、有问无答（空回答）、`你曾经提到过` 这类把来源说错的回复。
  ③ 极短（< 8 字）——**但必须排除真实事实**：实测命中的 5 条是
     「我住在济南」「我喜欢吃辣的」这类**完整事实**（中文短 ≠ 垃圾）。
     所以这条只在 `kind != fact` 且**不像一句完整的话**时才作数。

【为什么不一律用正则狠删 —— 实测误报】
  最初用了裸的 `HTTP\\s*\\d{3}`，结果把一条**正常回答**当成工具返回删掉：
  那条回答在**解释**"HTTP 200 表示请求成功，服务器正常响应"。
  删它就是删用户的知识。现在只认**工具渲染出来的那个形状**（`🌐 **URL**` / `带 URL 的抓取头`）。

【只列不清的两类】
  · 带 `⏳` 前缀但正文有真内容（占位符被粘在真回答前面）—— 污染，但删了会丢真内容；
  · **完全重复的正文**（实测 196 组 735 行）—— 去重是无损的，但本工具**不自动做**，
    只统计并打印，交给人来决定。

用法：
    python tools/clean_memory_pollution.py            # 只列（默认，不改任何文件）
    python tools/clean_memory_pollution.py --apply    # 备份 + 真删
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让工具挂掉
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(ROOT, "logs", "xiaojiao_memory_vec.jsonl")
BACKUP_DIR = os.path.join(ROOT, "logs", "backup_before_pollution_clean")

# ── 该清的：工具侧产出 ───────────────────────────────────────────────
TOOL_PATTERNS = [
    (r"https?://\S+\s*[·｜|]\s*HTTP\s*\d{3}", "抓取结果头（URL · HTTP 200）"),
    # ⚠️ 不要用裸的 `HTTP\s*\d{3}` —— 实测误报：一条正常回答在**解释**
    #    "HTTP 200 表示请求成功"，把它当工具返回删掉就是删用户的知识。
    #    只认**工具渲染出来的那个形状**。
    (r"🌐\s*\*\*https?://", "工具渲染头（🌐 **URL**）"),
    (r"⚠️\s*\*\*可能幻觉\*\*", "载体抓取守卫提示（可能幻觉）"),
    (r"⚠️\s*抓取失败", "载体抓取失败提示"),
    (r"✅\s*抓取成功", "载体抓取成功提示"),
    (r"📋\s*\*\*页面结构速览\*\*", "抓取结果的结构速览表"),
    (r"未收录产品配置|NVD 未收录", "工具返回的 NVD 标注"),
]
# ── 该清的：坏回复 ──────────────────────────────────────────────────
BAD_REPLY_PATTERNS = [
    (r"</?think>", "未闭合/残留 think 标签"),
    (r"【系统指令】", "系统提示词泄漏进回答"),
    (r"角色：\s*小焦.*工具：\s*list_files", "系统提示词片段泄漏"),
    (r"^用户：[^\n]*\n小焦：\s*⏳\s*正在调用工具[^\n]*$", "整条回复就是工具占位符"),
    (r"^用户：[^\n]*\n小焦：\s*（已回答）\s*$", "占位符「（已回答）」"),
    (r"^用户：[^\n]*\n小焦：\s*$", "有问无答（空回答）"),
    (r"^用户：[^\n]*\n小焦：\s*⏳\s*__pending__", "占位符 ⏳__pending__"),
    (r"你曾经提到过", "把「它说的」说成「你提到过」的坏回复"),
]
# ── 只列不清：疑点 ──────────────────────────────────────────────────
WATCH_PATTERNS = [
    (r"⏳", "带占位符前缀（正文可能有真内容 → 只列不清）"),
    (r"系统显示失败|系统显示", "回答里带系统自述"),
]
# 极短判据的豁免：像一句完整的话就留着
_SENTENCE_OK = re.compile(r"^[我你他她它这那](是|在|有|爱|喜欢|不|最|住|叫|会|想|要)")


def load():
    """读原始行（保留原文，便于原子写回时不改动未命中的行）。"""
    rows = []
    with io.open(P, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            s = line.strip()
            if s:
                rows.append((i, s))
    return rows


def classify(rows):
    plan = {"清": [], "看": []}
    for ln, raw in rows:
        try:
            r = json.loads(raw)
        except Exception:
            plan["清"].append((ln, "清", "这一行 JSON 解析不了（坏行）", raw[:80]))
            continue
        text = str(r.get("text") or "")
        kind = str(r.get("kind") or "")
        why = None
        for pat, w in TOOL_PATTERNS:
            if re.search(pat, text, re.M):
                why = "工具侧产出：" + w
                break
        if not why:
            for pat, w in BAD_REPLY_PATTERNS:
                if re.search(pat, text, re.M):
                    why = "坏回复：" + w
                    break
        if not why and len(text.strip()) < 8:
            body = text.strip().split("\n")[-1].replace("小焦：", "").strip()
            if kind != "fact" and not _SENTENCE_OK.match(body):
                why = "极短且不像完整的话（%d 字）" % len(text.strip())
        if why:
            plan["清"].append((ln, why, text, r.get("ts")))
            continue
        for pat, w in WATCH_PATTERNS:
            if re.search(pat, text, re.M):
                plan["看"].append((ln, w, text, r.get("ts")))
                break
    return plan


def main():
    ap = argparse.ArgumentParser(description="记忆库污染清理（默认只干跑）")
    ap.add_argument("--apply", action="store_true", help="备份后真删（不加就只列）")
    args = ap.parse_args()

    if not os.path.exists(P):
        print("记忆库不存在：%s（没什么可清的）" % P)
        return 0

    rows = load()
    plan = classify(rows)
    kill = {ln for ln, *_ in plan["清"]}

    print("库文件：%s" % P)
    print("总条数：%d" % len(rows))
    print("拟清除：%d 条    只列不清（待判断）：%d 条" % (len(kill), len(plan["看"])))

    print("\n===== 拟清除清单（逐条，全部）=====")
    by = {}
    for ln, why, text, ts in plan["清"]:
        by.setdefault(why, []).append((ln, text, ts))
    for why in sorted(by, key=lambda k: -len(by[k])):
        print("\n【%s】%d 条" % (why, len(by[why])))
        for ln, text, ts in by[why]:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "无时间"
            print("   行%-5d %s  %s" % (ln, when, str(text).replace("\n", " ⏎ ")[:88]))

    print("\n===== 只列不清（新类型 / 待判断）=====")
    by2 = {}
    for ln, w, text, ts in plan["看"]:
        by2.setdefault(w, []).append((ln, text, ts))
    for w in sorted(by2, key=lambda k: -len(by2[k])):
        print("\n【%s】%d 条" % (w, len(by2[w])))
        for ln, text, ts in by2[w][:5]:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "无时间"
            print("   行%-5d %s  %s" % (ln, when, str(text).replace("\n", " ⏎ ")[:88]))

    # 完全重复（新发现的污染类型：只列不清）
    seen = {}
    for ln, raw in rows:
        if ln in kill:
            continue
        try:
            t = str(json.loads(raw).get("text") or "")
        except Exception:
            continue
        seen.setdefault(t, []).append(ln)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    print("\n===== 新发现的污染类型：完全重复的正文 =====")
    print("  重复组 %d 组，涉及 %d 行（其中可去重掉 %d 行）"
          % (len(dups), sum(len(v) for v in dups.values()),
             sum(len(v) - 1 for v in dups.values())))
    for k, v in sorted(dups.items(), key=lambda z: -len(z[1]))[:6]:
        print("   ×%-4d %s" % (len(v), k.replace("\n", " ⏎ ")[:92]))

    if not args.apply:
        print("\n（干跑结束，没有改动任何文件。加 --apply 才真删。）")
        return 0

    bdir = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(bdir, exist_ok=True)
    bpath = os.path.join(bdir, os.path.basename(P))
    shutil.copy2(P, bpath)
    rep = os.path.join(bdir, "removed_list.txt")
    with io.open(rep, "w", encoding="utf-8") as f:
        f.write("记忆库污染清除清单\n库文件：%s\n备份：%s\n原条数：%d\n清除：%d\n剩余：%d\n\n"
                % (P, bpath, len(rows), len(kill), len(rows) - len(kill)))
        for why in sorted(by, key=lambda k: -len(by[k])):
            f.write("=" * 70 + "\n【%s】%d 条\n" % (why, len(by[why])))
            for ln, text, ts in by[why]:
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "无时间"
                f.write("\n[行%d] %s\n%s\n" % (ln, when, str(text)))
    kept = [raw for ln, raw in rows if ln not in kill]
    tmp = P + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        for raw in kept:
            f.write(raw + "\n")
    os.replace(tmp, P)          # 原子替换：写到一半崩了也不会留半个库
    print("\n备份：%s" % bpath)
    print("清除清单：%s" % rep)
    print("清除：%d 条；剩余：%d 条（原 %d 条）" % (len(kill), len(kept), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
