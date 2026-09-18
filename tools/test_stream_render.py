# -*- coding: utf-8 -*-
"""回归测试：流式渲染不能吃内容（"标题结构全在，内容全空"）

【用户实测的 bug】
    问"3 红 2 蓝摸 2 个都是红球的概率"，回答里标题结构都在，但**标题下面全空**，
    只有最后那段引用有内容。

【根因（已用隔离实验定位，见下）】
    前端 `renderBlocks()` 处理标题时写的是
        const hm = b.match(/^(#{1,3})\\s+(.+)/);  if (hm) { …标题…; return; }
    `.+` **不跨行**，所以只匹配标题那一行；可 `b` 是**整块**（空行之间的一切）——
    `return` 把整块交出去，于是"标题 + 紧随其后的正文"里，**正文全被丢掉**。
    模型写 Markdown 时经常不空行（"### 第一步\\n从 5 个球中任取 2 个："），
    所以这个 bug 在真实回答里高频出现。

【本测试怎么钉】
    真浏览器 + 真模型回答（可选），把回答喂给页面自己的 `renderMd`，
    断言"渲染出的可见文本没有丢内容"。**用页面自己的渲染器**是关键 ——
    用 Python 重写一遍渲染器等于测我自己的解释器，测不出前端的 bug。

运行：python tools/test_stream_render.py        （需要小焦在跑 + Playwright）
"""
import sys
import time

_ROOT = __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

BASE = "http://127.0.0.1:5000"
# 【2026-09-19 去掉写死的 `G:/xiaojiao harness/chrome-win64/chrome.exe`】换台机器那个路径必然不存在，
#   于是这个自测会"失败"，而失败原因跟被测功能没关系。现在统一走 `core.paths.find_chrome()`
#   （环境变量 XIAOJIAO_CHROME > PATH > 常见安装位置）；找不到就**如实跳过**，不假装跑过。
from core import paths as _PATHS  # noqa: E402
CHROME = _PATHS.find_chrome()[0]

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# 固定的渲染用例（不依赖模型，直接钉住渲染器行为）
FIXED = (
    ("标题+列表（无空行）", "## 已知条件\n- 红球：3 个\n- 蓝球：2 个", ("红球", "蓝球")),
    ("标题+正文（无空行）", "## 已知条件\n红球一共有 3 个", ("红球一共有 3 个",)),
    ("多级标题连着写", "# 一级\n## 二级\n### 三级\n正文在这里", ("正文在这里",)),
    ("标题+正文+列表混合", "### 第一步\n先算总数：\n- 总数 10\n- 有利 3\n### 第二步\n相除",
     ("先算总数", "总数 10", "有利 3", "相除")),
    ("标题后紧跟表格", "## 数据\n| 项 | 值 |\n|---|---|\n| a | 1 |", ("项", "值")),
    ("空行分隔（原本就正常）", "## 标题\n\n正文内容", ("正文内容",)),
    ("无标题的普通段落", "就是一段普通的话，没有标题。", ("普通的话",)),
)

# 5 个不同类型的复杂问题（多标题 + 多段落）—— 用真模型回答
REAL_QUESTIONS = (
    "一个箱子有 3 个红球 2 个蓝球，随机摸 2 个，都是红球的概率？",
    "请分步骤讲清楚 TCP 三次握手的每一步，并给出为什么需要三次。",
    "写一份 5 条的产品上线检查清单，每条要说明为什么。",
    "对比 Redis 和 MySQL 的适用场景，分场景说明并给结论。",
    "用一个生活中的比喻解释什么是递归，再给一个代码例子。",
)


def main():
    print("=" * 80)
    print("  回归 · 流式渲染不能吃内容（标题下的正文必须显示）")
    print("=" * 80)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("⏭️  Playwright 不可用，跳过：%s" % e)
        return 0
    if not CHROME:
        print("⏭️  没找到浏览器，跳过（自己指定：set XIAOJIAO_CHROME=完整路径）")
        return 0
    try:
        if requests.get(BASE + "/health", timeout=5).status_code != 200:
            raise RuntimeError("health != 200")
    except Exception as e:
        print("❌ 小焦没在跑（%s）：%s" % (BASE, e))
        return 1

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(2500)

        def render(text):
            """用**页面自己的** renderMd 渲染，返回可见文本。"""
            return pg.evaluate(
                """(t)=>{
                  const d=document.createElement('div');
                  d.style.cssText='width:705px';
                  document.body.appendChild(d);
                  d.innerHTML=renderMd(t);
                  const out=(d.innerText||'');
                  d.remove();
                  return out;
                }""", text)

        # ---------------- 一、固定用例（钉住渲染器行为，不依赖模型） ----------------
        print("\n[一] 固定用例：标题后面的内容一个都不能丢")
        for label, src, must in FIXED:
            vis = render(src)
            missing = [m for m in must if m not in vis]
            ck("%s → 内容都在" % label, not missing,
               "缺=%s / 可见=%r" % (missing, vis[:60]))

        # ---------------- 二、真实回答（5 个复杂问题） ----------------
        print("\n[二] 真模型回答（5 个多标题多段落问题）：渲染后不得丢正文")
        for i, q in enumerate(REAL_QUESTIONS, 1):
            try:
                requests.post(BASE + "/api/session/new", json={}, timeout=20)
                t0 = time.time()
                r = requests.post(BASE + "/api/chat", json={"message": q}, timeout=300)
                if r.status_code == 429:
                    time.sleep(4)
                    r = requests.post(BASE + "/api/chat", json={"message": q}, timeout=300)
                ans = str((r.json() if r.status_code == 200 else {}).get("answer") or "")
            except Exception as e:
                ck("[%d] 提问「%s」成功" % (i, q[:14]), False, "%s: %s" % (type(e).__name__, e))
                continue
            ck("[%d] 提问「%s」拿到回答" % (i, q[:16]), len(ans) > 50,
               "%d 字 / %.1fs" % (len(ans), time.time() - t0))
            vis = render(ans)
            # 判据：去掉 Markdown 标记后，正文应当基本都在可见文本里。
            # 允许丢失的只有标记符号本身（#、*、-、| 等），不允许丢**文字**。
            import re as _re
            body = _re.sub(r"[#*`>\|=\-\s]", "", ans)
            vis_body = _re.sub(r"[#*`>\|=\-\s]", "", vis)
            keep = (len(vis_body) / len(body)) if body else 1.0
            ck("[%d] 渲染保留正文比例 ≥ 0.85（实测 %.2f）" % (i, keep), keep >= 0.85,
               "源 %d 字 / 可见 %d 字" % (len(body), len(vis_body)))
            # 单独盯"标题吃内容"这个具体形态，但要**先把 Markdown 归一化**再比对。
            # ⚠️ 三次假红换来的教训：逐标题做子串比对总会误报，因为渲染会**规范化**文本：
            #     `**加粗**` → 文本去掉星号、`---` → `<hr>`、表格 → 单元格里带制表符。
            #     第一版/第二版分别栽在这些形态上，而"保留比例 1.00~1.03"早就证明内容没丢。
            #     所以这里两边都做同样程度的归一化（去掉所有标记符号与空白）再判断。
            import re as _re

            def _norm(s):
                return _re.sub(r"[#*`>|=\-\s\u200b·]+", "", s or "")

            # 代码围栏（```lang）不是"正文内容"，它会被渲染成代码块 —— 排除掉再判断
            # （第 4 次假红就是它：`### 💻 代码例子\n```python` 被当成"标题后没有正文"）。
            heads = _re.findall(r"^#{1,6}[ \t]*([^\n]+)\n+([^\n#\s][^\n]*)", ans, _re.M)
            bad = [(h.strip(), n.strip()) for h, n in heads
                   if n.strip() and not n.strip().startswith("```")
                   and _norm(n)[:10] and _norm(n)[:10] not in _norm(vis)]
            ck("[%d] **每个 Markdown 标题后面的正文都可见**（检查 %d 处标题）" % (i, len(heads)),
               not bad, "被吃掉=%s" % bad[:2])

        b.close()

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
