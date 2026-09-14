# -*- coding: utf-8 -*-
"""把 xiaojiao_app.py 里的前端 HTML/JS 抽出来，交给 node --check 做语法检查。

为什么要有这一步：前端代码是**字符串常量**，Python 语法检查（ast.parse / py_compile）
对它一个字都不看 —— 少个括号、多个逗号都能"编译通过"，直到用户打开页面白屏才发现。
这个脚本把 <script> 块抽成真 .js 文件，用 node 的解析器过一遍。
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "xiaojiao_app.py")
OUT_DIR = os.path.join(ROOT, "logs")
MARK = 'HTML = r"""'


def main():
    src = open(SRC, encoding="utf-8").read()
    i = src.index(MARK) + len(MARK)
    j = src.index('"""', i)
    html = src[i:j]
    os.makedirs(OUT_DIR, exist_ok=True)
    hp = os.path.join(OUT_DIR, "_ui_extract.html")
    with open(hp, "w", encoding="utf-8") as f:
        f.write(html)
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    js = "\n;\n".join(blocks)
    jp = os.path.join(OUT_DIR, "_ui_script.js")
    with open(jp, "w", encoding="utf-8") as f:
        f.write(js)
    print("HTML %d 字 / <script> 块 %d 个 / JS %d 字" % (len(html), len(blocks), len(js)))
    print("已写出：%s" % jp)
    r = subprocess.run(["node", "--check", jp], capture_output=True, text=True)
    if r.returncode == 0:
        print("✅ node --check 通过（前端 JS 语法正确）")
    else:
        print("❌ node --check 失败：")
        print((r.stderr or r.stdout)[:3000])
    # 顺带做几条"结构性"检查 —— 语法对了但引用错名字照样白屏
    checks = [
        ("GEN 全局状态已定义", "const GEN={" in js),
        ("stopGeneration 已定义", "async function stopGeneration(){" in js),
        ("切会话会先停旧流", "async function openSession(id){\n  await stopGeneration();" in js),
        ("新建会话会先停旧流", "async function newChat(){await stopGeneration();" in js),
        ("send 用 AbortController", "signal:(GEN.ctrl?GEN.ctrl.signal:undefined)" in js),
        ("收到 [DONE] 立刻收尾", "'[DONE]'" in js and "ended=true;break;" in js),
        ("cleanup 一定被 finally 调用", "finally{\n   cleanup();" in js),
        ("占位符不再无条件转圈", "GEN.active?'<span class=\"spin\"></span> 正在回答…'" in js),
        # ---- 问题 2：切会话必须等后端确认这一轮结束（不能再跟注销时机赛跑）----
        ("切会话会等后端确认生成结束", "if(!d.generating)return;" in js),
        ("3 秒没结束就强制清标志", "if(Date.now()-t0>3000)" in js and "/api/chat/abandon" in js),
        ("流一开始就记下会话 id", "else if(d.type==='session')" in js),
        ("收尾不把占位符当内容渲染", "txt.indexOf('__pending__')<0" in js),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print("  %s %s" % ("✅" if ok else "❌", n))
    print("\n结构检查：通过 %d / 共 %d" % (len(checks) - len(bad), len(checks)))
    return 1 if (r.returncode != 0 or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
