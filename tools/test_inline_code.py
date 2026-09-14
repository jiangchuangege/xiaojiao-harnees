# -*- coding: utf-8 -*-
"""行内代码渲染 · 真实浏览器取证（一次跑完：渲染链路 + 真实回答 + 截图）。

测两件事，一件事一次：
  ① **渲染链路**（确定性）：把用户截图里那句原话**真的渲染进消息气泡**，读 `<code>` 的
     计算样式，逐项对照标准（灰底 / 等宽 / 小 padding / 小圆角 / 无边框）。
     为什么不靠模型：模型每次答什么不稳定，而被测对象是**样式**，用固定样本才能前后对比。
  ② **真实回答**（端到端）：发一句会让小焦写出行内代码的话，等它答完，数一数页面上
     真的渲染出了几个 `<code>`，再截图。

用法：
    python tools/test_inline_code.py
    python tools/test_inline_code.py --base http://127.0.0.1:5000
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME_CANDIDATES = [
    os.path.join(REPO_ROOT, "chrome-win64", "chrome.exe"),
    os.path.expanduser(r"~\chrome-win64\chrome.exe"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SAMPLE = "方案一：使用 `image_recognition` 插件（推荐）\n\n方案二：用 `archify` 画流程图，再 `copy` 到剪贴板。"
ASK = "推荐一下 image_recognition 插件，一句话，插件名用反引号包起来。"

PASS = {"n": 0, "ok": 0}
FAILS = []


def check(name, cond, extra=""):
    PASS["n"] += 1
    if cond:
        PASS["ok"] += 1
    else:
        FAILS.append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← %s" % extra) if extra else ""))


PROBE_JS = r"""
(sample) => {
  const before = document.querySelectorAll('#feed .m.bot').length;
  add('bot', sample);                       // 走真实链路：add → renderMd → renderBlocks → inline
  const nodes = document.querySelectorAll('#feed .m.bot');
  const last = nodes[nodes.length - 1];
  const cs = [...last.querySelectorAll('.b code')];
  if (!cs.length) return {found: false};
  const s = getComputedStyle(cs[0]);
  const pick = k => s[k];
  return {
    found: true, n: cs.length,
    html: last.querySelector('.b').innerHTML.slice(0, 240),
    bubbleBg: getComputedStyle(last.querySelector('.b')).backgroundColor,
    code: {background: pick('backgroundColor'), border: pick('border'),
           borderWidth: pick('borderWidth'), borderStyle: pick('borderStyle'),
           borderRadius: pick('borderRadius'), padding: pick('padding'),
           fontFamily: pick('fontFamily'), fontSize: pick('fontSize'),
           display: pick('display'), verticalAlign: pick('verticalAlign'),
           boxShadow: pick('boxShadow'), textShadow: pick('textShadow')},
    bodyFont: getComputedStyle(last.querySelector('.b')).fontSize,
    rect: last.getBoundingClientRect().toJSON()
  };
}
"""

# 代码块不能被这次的改动带花：读 pre.code code 的计算样式
BLOCK_JS = r"""
() => {
  add('bot', '示例：\n\n```python\nprint("hi")\n```\n');
  const nodes = document.querySelectorAll('#feed .m.bot');
  const last = nodes[nodes.length - 1];
  const c = last.querySelector('pre.code code');
  if (!c) return {found: false};
  const s = getComputedStyle(c);
  return {found: true,
          background: s.backgroundColor, border: s.borderWidth,
          padding: s.padding, margin: s.margin, fontSize: s.fontSize,
          radius: s.borderRadius, color: s.color, whiteSpace: s.whiteSpace};
}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="行内代码渲染取证")
    ap.add_argument("--base", default="http://127.0.0.1:5000")
    ap.add_argument("--out", default=os.path.join("logs", "e2e_shots", "inline_code.png"))
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 未安装 playwright")
        return 1

    out_path = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print("=" * 78)
    print("  行内代码渲染 · 真实浏览器取证")
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
        page = browser.new_page(viewport={"width": 1100, "height": 860},
                                device_scale_factor=2)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(args.base, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        print("\n[1] 渲染链路（固定样本，不依赖模型）")
        print("      样本：%s" % SAMPLE.replace("\n", " ⏎ "))
        info = page.evaluate(PROBE_JS, SAMPLE)
        if not info.get("found"):
            print("  ❌ 渲染后找不到 .b code —— 行内代码根本没生成（渲染逻辑问题，不是 CSS）")
            page.screenshot(path=out_path, full_page=True)
            browser.close()
            return 1
        print("      HTML：%s" % info["html"])
        for k, v in info["code"].items():
            print("      %-14s %s" % (k, v))
        c = info["code"]
        bg = re.findall(r"[\d.]+", c["background"])
        check("底色是**半透明灰**（不是不透明实心块）",
              c["background"].startswith("rgba") and len(bg) == 4 and float(bg[3]) < 0.6,
              c["background"])
        check("**无边框**（border-width 0）", c["borderWidth"] == "0px", c["borderWidth"])
        check("圆角 6px（GitHub 取值）", c["borderRadius"] == "6px", c["borderRadius"])
        check("等宽字体", "Consolas" in c["fontFamily"] or "monospace" in c["fontFamily"],
              c["fontFamily"].split(",")[0])
        check("字号跟着正文走（.85em，不是写死 px）",
              abs(float(c["fontSize"].rstrip("px")) / float(info["bodyFont"].rstrip("px")) - 0.85) < 0.02,
              "%s / 正文 %s" % (c["fontSize"], info["bodyFont"]))
        pad = re.findall(r"[\d.]+", c["padding"])
        check("上下内边距 ≥ 2px（灰底比字形大一圈，不是贴着字）",
              len(pad) >= 2 and float(pad[0]) >= 2, c["padding"])
        check("无阴影（box-shadow / text-shadow 都是 none）",
              c["boxShadow"] == "none" and c["textShadow"] == "none",
              "%s / %s" % (c["boxShadow"], c["textShadow"]))
        check("基线对齐（vertical-align: baseline）",
              c["verticalAlign"] == "baseline", c["verticalAlign"])

        print("\n[2] 代码块没有被带花（回归）")
        blk = page.evaluate(BLOCK_JS)
        if blk.get("found"):
            for k, v in blk.items():
                if k != "found":
                    print("      %-14s %s" % (k, v))
            check("代码块背景仍被清空（不是灰色）", blk["background"] in ("rgba(0, 0, 0, 0)", "transparent"),
                  blk["background"])
            check("代码块无内边距 / 无圆角", blk["padding"] == "0px" and blk["radius"] == "0px",
                  "%s / %s" % (blk["padding"], blk["radius"]))
            check("代码块字号仍是 13px（不跟行内一起变成 .85em）",
                  blk["fontSize"] == "13px", blk["fontSize"])
        else:
            check("代码块节点存在", False, "没找到 pre.code code")

        print("\n[3] 真实回答（发一条会让小焦写行内代码的话）")
        sel = None
        for cand in ("#inp", "textarea#inp", "textarea", "input[type=text]"):
            if page.query_selector(cand):
                sel = cand
                break
        if sel:
            page.fill(sel, ASK)
            page.keyboard.press("Enter")
            print("      已发送：%s" % ASK)
            deadline = time.time() + 120
            n_code = 0
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                n_code = page.evaluate("()=>document.querySelectorAll('#feed .m.bot .b code').length")
                if n_code > 0:
                    break
            txt = page.inner_text("body")
            print("      页面上渲染出的行内 code 个数：%d" % n_code)
            check("真实回答里出现了行内代码 <code>", n_code > 0, "%d 个" % n_code)
            check("回答正文不再出现裸反引号（` 没被原样显示）", "`" not in txt[-600:],
                  "尾部文本里有反引号" if "`" in txt[-600:] else "")
        else:
            check("找到输入框", False, "页面上没有输入框")

        print("\n      控制台错误：%d 条 %s" % (len(errors), errors[:2]))
        page.screenshot(path=out_path, full_page=True)
        # 再单独截一张"只有这条回答"的，样式细节看得清
        box = info["rect"]
        page.screenshot(path=out_path.replace(".png", "_zoom.png"),
                        clip={"x": max(0, box["x"] - 10), "y": max(0, box["y"] - 10),
                              "width": min(1080, box["width"] + 20),
                              "height": max(80, box["height"] + 20)})
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
