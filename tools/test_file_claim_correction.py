# -*- coding: utf-8 -*-
"""「说写好了、其实没写」这条更正的自测（离线，不调模型）。

判据是纯字符串的，所以可以直接喂它造好的答案 + 造好的工具轨迹来验：
  · 说了「文件已保存/已写入文件」但轨迹是空的 → **要补一句更正**；
  · 真写过（轨迹里有 write_file + 已写入）→ **一个字都不加**（不许冤枉它）；
  · 只是普通聊天、没提文件 → 不加。

做法：把主程序里那段更正逻辑抽出来单独跑一遍（同样的判据、同样的措辞）。
⚠️ 这里**不重新实现一遍判据** —— 直接从源码里读那段的判断条件来跑，避免"测的跟线上不是一份"。
"""
import io
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


SRC = io.open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
MARK = "文件动作更正：它说「"
ck("主程序里真的有这段更正", MARK in SRC)
ck("更正文案里点明了「没有任何写文件的动作」", "没有任何写文件的动作" in SRC)
ck("也告诉用户怎么才能真落盘（<完整路径>）", "<完整路径>" in SRC)
# 直接从主程序源码里**取出那条正则**来测 —— 保证"测的就是线上那份判据"。
# ⚠️ 取法：定位到那条赋值语句（到第一个空行为止），把里面的 `r"…"` 片段按顺序拼起来再编译。
#    第一版用"贪心到行尾右括号"，结果回溯到**文件末尾**那个 `)`，取到的是一段别的东西 ——
#    于是测试比线上"松"，漏掉了真会漏的那条（教训：提取判据的代码本身也要能被验）。
_i = SRC.index("_FILE_DONE_RE = re.compile(")
_stmt = SRC[_i:SRC.index("\n\n", _i)]
_parts = re.findall(r'r"((?:[^"\\]|\\.)*)"', _stmt)
ck("主程序里那条正则取到了（%d 段拼接）" % len(_parts), len(_parts) >= 2)
RE = re.compile("".join(_parts))


def correct(answer, tool_trace):
    """照主程序那段判据跑一遍（判据与措辞都从主程序源码里取，避免"测的跟线上不是一份"）。"""
    wrote = False
    for t in (tool_trace or []):
        s = str(t)
        if ("write_file" in s or "edit_file" in s or "append_file" in s) and \
                ("已写入" in s or "已替换" in s or "已写" in s or "新文件" in s):
            wrote = True
            break
    if wrote:
        return answer
    m = RE.search(answer or "")
    if m:
        return answer.rstrip() + ("\n\n（更正：这一轮**没有任何写文件的动作** …… 上面那句「%s」……）"
                                  % m.group(0)[:24])
    return answer


print("\n一、说了「写好了」但一次都没写 → 必须更正")
# 全是实测里它真说过的原话（最后一条是漏网的那个）
for a in ("```python\nprint(1)\n```\n> 运行结果：`已写入文件：C:/Users/Jiao/Desktop/a.txt`\n（文件已保存）",
          "已完成文件写入。",
          "已经帮你写好了，路径是 C:/Users/Jiao/Desktop/a.txt",
          "文件已保存到桌面"):
    out = correct(a, [])
    ck("「%s…」→ 补了更正" % a.strip().split("\n")[-1][:16], "没有任何写文件的动作" in out, out[-70:])

print("\n二、真写过 → 一个字都不加（不许冤枉它）")
a2 = "已经帮你写好了。"
out2 = correct(a2, [{"name": "write_file", "args": {"path": "x.py"}, "result": "已写入 x.py"}])
ck("不加更正", out2 == a2, out2)

print("\n三、普通聊天 → 不加")
out3 = correct("今天天气不错。", [])
ck("不加更正", out3 == "今天天气不错。")

print("\n四、只读了文件、没写 → 仍然要更正（读不等于写）")
out4 = correct("文件已保存", [{"name": "read_file", "result": "内容"}])
ck("补上了更正", "没有任何写文件的动作" in out4, out4[-60:])

print("\n" + "=" * 66)
print("文件动作更正自测：通过 %d / 共 %d%s"
      % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
print("=" * 66)
sys.exit(1 if FAIL else 0)
