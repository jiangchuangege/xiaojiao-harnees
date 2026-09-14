# -*- coding: utf-8 -*-
"""数学公式渲染 · 真实浏览器取证（KaTeX）

一次跑完三件事（用户要求的三条）：
  ① 块级公式 `$$...$$`  → 必须渲染成数学排版
  ② 行内公式 `$...$`    → 必须渲染成数学排版
  ③ 行内代码 + 公式混排 → 两者都渲染、且**互不干扰**（代码块里的 `$` 不许被当公式）

判据取"页面上真的出现了 KaTeX 的 DOM"（`.katex` / `.katex-display`），
不是"脚本加载成功"——脚本加载成功但没扫描到公式，用户看到的仍然是源码。

用法：
    python tools/test_math_render.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_CANDIDATES = [
    os.path.join(REPO_ROOT, "chrome-win64", "chrome.exe"),
    os.path.expanduser(r"~\chrome-win64\chrome.exe"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# 三组被测样本（就是用户报的那三种）
CASES = [
    ("块级公式 $$...$$",
     "瑞利散射公式：\n\n$$I \\propto \\frac{1}{\\lambda^4}$$\n\n所以蓝光散射更强。",
     ".katex-display", 1, ["\\frac", "1}{\\lambda"]),
    ("行内公式 $...$",
     "当 $x^2 + y^2 = r^2$ 时，点在圆上；这里 $\\alpha$ 是角度。",
     ".katex", 2, ["x^2", "\\alpha"]),
    ("公式 + 行内代码混排",
     "方案一：使用 `image_recognition` 插件处理 $\\beta$ 参数。\n\n"
     "```bash\necho $PATH\n```",
     ".katex", 1, ["\\beta"]),
]

PROBE_JS = r"""
({text}) => {
  const before = document.querySelectorAll('#feed .m.bot').length;
  add('bot', text);
  const nodes = document.querySelectorAll('#feed .m.bot');
  const last = nodes[nodes.length - 1];
  const b = last.querySelector('.b');
  return {
    html: b.innerHTML.slice(0, 400),
    katex: b.querySelectorAll('.katex').length,
    katexDisplay: b.querySelectorAll('.katex-display').length,
    inlineCode: b.querySelectorAll('code').length,
    text: b.textContent.slice(0, 200),
    rect: last.getBoundingClientRect().toJSON()
  };
}
"""

PASS = {"n": 0, "ok": 0}
FAILS = []


def check(name, cond, extra=""):
    PASS["n"] += 1
    if cond:
        PASS["ok"] += 1
    else:
        FAILS.append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← %s" % extra) if extra else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="数学公式渲染取证")
    ap.add_argument("--base", default="http://127.0.0.1:5000")
    ap.add_argument("--out", default=os.path.join("logs", "e2e_shots", "math_render.png"))
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 未安装 playwright")
        return 1

    out_path = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print("=" * 78)
    print("  数学公式渲染 · 真实浏览器取证（KaTeX）")
    print("=" * 78)

    with sync_playwright() as p:
        launch_kw = {"headless": True}
        chrome = next((c for c in CHROME_CANDIDATES if os.path.exists(c)), "")
        if chrome:
            launch_kw["executable_path"] = chrome
        try:
            browser = p.chromium.launch(**launch_kw)
        except Exception:
            browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1100, "height": 900},
                                device_scale_factor=2)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base, timeout=60000, wait_until="domcontentloaded")

        # 等 KaTeX 到位（CDN 首次拉取要一会儿）。拿不到就如实报，不假装通过。
        ready = False
        for _ in range(30):
            page.wait_for_timeout(1000)
            if page.evaluate("()=>!!window.renderMathInElement"):
                ready = True
                break
        check("KaTeX auto-render 已在页面上可用（CDN 拉到了）", ready,
              "window.renderMathInElement 就绪" if ready else "30 秒内没就绪")
        if not ready:
            page.screenshot(path=out_path, full_page=True)
            browser.close()
            return 1

        boxes = []
        for i, (name, sample, sel, want_n, forbid) in enumerate(CASES, 1):
            print("\n[%d] %s" % (i, name))
            print("      样本：%s" % sample.replace("\n", " ⏎ ")[:110])
            info = page.evaluate(PROBE_JS, {"text": sample})
            page.wait_for_timeout(400)
            info = page.evaluate(
                "()=>{const n=document.querySelectorAll('#feed .m.bot');"
                "const b=n[n.length-1].querySelector('.b');"
                # 【为什么要把 .katex-mathml 摘掉再看文本 —— 这条判据第一版判错了】
                #   KaTeX 每个公式会输出**两份**：给眼睛看的 HTML（.katex-html）
                #   和给读屏软件/复制用的 MathML（.katex-mathml），后者里面有一句
                #   `<annotation encoding="application/x-tex">I \\propto \\frac{1}{\\lambda^4}</annotation>`
                #   —— **原文 LaTeX 就在那儿**。直接读 textContent 会读到它，
                #   于是"源码还在页面上"这个断言在公式**已经渲染成功**时照样报红。
                #   MathML 那份是不可见的（CSS clip 掉了），所以必须**只看可见文本**。
                "const c=b.cloneNode(true);"
                "c.querySelectorAll('.katex-mathml').forEach(x=>x.remove());"
                "return {katex:b.querySelectorAll('.katex').length,"
                "katexDisplay:b.querySelectorAll('.katex-display').length,"
                "code:b.querySelectorAll('code').length,"
                "text:c.textContent.slice(0,160),"
                "rect:n[n.length-1].getBoundingClientRect().toJSON()};}")
            boxes.append(info["rect"])
            print("      .katex=%d ｜ .katex-display=%d ｜ <code>=%d"
                  % (info["katex"], info["katexDisplay"], info["code"]))
            print("      渲染后可见文本：%s" % info["text"].replace("\n", " ")[:100])
            if sel == ".katex-display":
                check("%s：块级公式渲染成了独立公式块" % name, info["katexDisplay"] >= want_n,
                      ".katex-display=%d" % info["katexDisplay"])
            else:
                check("%s：行内公式渲染成了 KaTeX" % name, info["katex"] >= want_n,
                      ".katex=%d" % info["katex"])
            check("%s：公式**源码不再原样显示**（可见文本里看不到 \\frac / \\alpha 这类写法）"
                  % name,
                  not any(f in info["text"] for f in forbid),
                  "仍能看到 " + ",".join(f for f in forbid if f in info["text"])
                  if any(f in info["text"] for f in forbid) else "源码已被排版替换")

        print("\n[4] 代码块里的 `$` 不许被公式化（回归）")
        last = page.evaluate(
            "()=>{const n=document.querySelectorAll('#feed .m.bot');"
            "const b=n[n.length-1].querySelector('.b');"
            "const c=b.querySelector('pre.code code');"
            "return {code:c?c.textContent:'', katexInPre:b.querySelectorAll('pre.code .katex').length};}")
        check("```bash 里的 `echo $PATH` 原样保留",
              "$PATH" in last["code"], repr(last["code"][:40]))
        check("代码块里没有生成 KaTeX 节点", last["katexInPre"] == 0,
              "%d 个" % last["katexInPre"])

        print("\n      控制台错误：%d 条 %s" % (len(errors), errors[:2]))
        page.screenshot(path=out_path, full_page=True)
        if boxes:
            top = min(b["y"] for b in boxes)
            bot = max(b["y"] + b["height"] for b in boxes)
            page.screenshot(path=out_path.replace(".png", "_zoom.png"),
                            clip={"x": 0, "y": max(0, top - 10), "width": 1100,
                                  "height": min(880, bot - top + 20)})
        browser.close()

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (PASS["ok"], PASS["n"],
                                  ("　失败：" + "；".join(FAILS)) if FAILS else ""))
    print("  截图：%s" % out_path)
    print("        %s" % out_path.replace(".png", "_zoom.png"))
    print("=" * 78)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
