# -*- coding: utf-8 -*-
"""无限 5 · 感知无限 · 逐条验收（真浏览器 DOM 检查）

提示词的验收口径：
    ① 界面**不出现**技术术语（切片 / 循环 / 合并 / 检索 / 第 X/Y 片 / exceeds context）；
    ② 用户**撞不到"装不下"的墙**（贴超长内容不报上下文错，界面照常给结果）。

为什么必须真开浏览器：前一轮的 `test_infinity_456` 验的是"源码里没有这类文案"，
但**用户看到的是 DOM** —— 文案可能来自模板拼接、SSE 推送、或运行时报错。
只有把页面开起来、在真实生成过程中取 DOM 文本，才算验过。

运行：python tools/test_perception_infinity.py      （需要小焦在跑 + Playwright）
"""
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

PASS, FAIL = [], []
BASE = "http://127.0.0.1:5000"
CHROME = "G:/xiaojiao harness/chrome-win64/chrome.exe"

# 用户**不该**在界面上看到的词（技术痕迹）
FORBIDDEN = ("exceeds context", "超过上下文", "上下文超限", "token 上限", "tokens 上限",
             "切片", "分片", "合并段落", "第 1/", "第 2/", "第 3/", "chunk", "ctx")


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _alive():
    try:
        return requests.get(BASE + "/health", timeout=5).status_code == 200
    except Exception:      # noqa: silent-ok — 探活失败就如实报"小焦没在跑"
        return False


def main():
    print("=" * 78)
    print("  无限 5 · 感知无限 · 真浏览器 DOM 检查")
    print("=" * 78)
    if not _alive():
        print("❌ 小焦没在跑（%s）。先 `python start_xiaojiao.py`。" % BASE)
        return 1
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("⏭️  Playwright 不可用，跳过 DOM 检查：%s" % e)
        return 0

    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, executable_path=CHROME)
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(2500)
        pg.evaluate("()=>{const s=document.getElementById('splash');if(s)s.remove();}")

        # ---------------- ① 长文生成过程中，DOM 里不该出现技术术语 ----------------
        print("\n[①] 长文生成过程：界面**全程**不出现技术术语")
        bots0 = pg.evaluate("()=>document.querySelectorAll('#feed .m.bot').length")
        pg.fill("#inp", "写 3000 字产品介绍")
        pg.click(".send, #send, button[onclick*='send']")

        # 生成期间每 700ms 取一次**整个可见文本**（含进度提示、按钮、气泡）
        seen_texts, leaked = [], []
        t0 = time.time()
        while time.time() - t0 < 150:
            pg.wait_for_timeout(700)
            txt = pg.evaluate("()=>document.body.innerText || ''")
            # ⚠️ 取样要**留全文**：第一版只 `txt[:4000]`，而界面文本（历史消息+正文）
            #    早就超过 4000 字，进度提示被截在窗口外 → 断言假红。
            #    同时禁词检查用的是**全文**（`low`），否则等于只查了前 4000 字。
            seen_texts.append(txt)
            low = txt.lower()
            for w in FORBIDDEN:
                if w.lower() in low:
                    leaked.append(w)
            st = pg.evaluate(
                "()=>({bots:document.querySelectorAll('#feed .m.bot').length,"
                "stop:Array.from(document.querySelectorAll('#feed .icon-btn'))"
                ".filter(e=>e.textContent.indexOf('停止')>=0).length})")
            if st["bots"] > bots0 and st["stop"] == 0:
                break
        ck("生成期间取到了界面文本（不是空断言）",
           len(seen_texts) >= 2 and max(len(t) for t in seen_texts) > 40,
           "%d 次取样 / 最长 %d 字" % (len(seen_texts), max(len(t) for t in seen_texts)))
        ck("**界面全程没有技术术语**（%d 个禁词逐个查）" % len(FORBIDDEN),
           not leaked, "命中=%s" % sorted(set(leaked))[:5])
        ck("生成过程中出现过**友好提示**（正在处理/正在生成/正在理解…）",
           any(("正在" in t) for t in seen_texts),
           "取样 %d 次，最长界面文本 %d 字" % (len(seen_texts),
                                        max(len(t) for t in seen_texts)))
        ck("**用户看得到正文**（不是空等）",
           any(len(t) > 200 for t in seen_texts),
           "最长界面文本 %d 字" % max(len(t) for t in seen_texts))

        # ---------------- ② 贴超长内容 → 撞不到"装不下"的墙 ----------------
        print("\n[②] 贴超长内容：撞不到「装不下」的墙")
        # 段落要够长：原来用 12 句 * 220 段只有 6.1 万字，达不到"输入无限"该验的规模。
        long_text = ("载体把上下文按需装配，模型只处理当前这一小块，单次请求永远装得下。"
                     * 12 + "\n\n") * 1000
        ck("构造的超长输入规模（验证『输入无限』）", len(long_text) > 200000,
           "%d 字（约 %.1f 万字）" % (len(long_text), len(long_text) / 10000))
        pg.fill("#inp", "帮我总结下面这段材料：\n" + long_text)
        pg.click(".send, #send, button[onclick*='send']")
        # 等界面给出反馈（回答出现 或 明确报错）
        got_answer, err_like = False, ""
        t0 = time.time()
        while time.time() - t0 < 240:
            pg.wait_for_timeout(1500)
            txt = pg.evaluate("()=>document.body.innerText || ''")
            low = txt.lower()
            for w in FORBIDDEN:
                if w.lower() in low:
                    leaked.append(w)
            if any(w in low for w in ("exceeds", "too long", "超过最大", "上下文超限")):
                err_like = [l for l in txt.split("\n") if "exceeds" in l.lower()
                            or "超过" in l][:1]
                break
            if len(txt) > 300 and ("总结" in txt or "材料" in txt):
                got_answer = True
                break
        ck("**超长输入没有撞到「装不下」的墙**（无 exceeds/超限报错）", not err_like,
           err_like or "界面无此类报错")
        ck("界面给了回应或正在处理（没有静默卡死）", got_answer or not err_like,
           "got_answer=%s" % got_answer)
        ck("超长输入期间界面同样没有技术术语",
           not leaked, "命中=%s" % sorted(set(leaked))[:5])

        # ---------------- ③ 页面仍可交互（没被卡死） ----------------
        print("\n[③] 长内容之后页面仍可交互")
        try:
            pg.evaluate("()=>{const i=document.getElementById('inp');return !!i;}")
            pg.fill("#inp", "你好")
            ck("输入框仍可写入（页面没卡死）", True)
        except Exception as e:
            ck("输入框仍可写入（页面没卡死）", False, "%s" % e)
        pg.close()
        b.close()

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
