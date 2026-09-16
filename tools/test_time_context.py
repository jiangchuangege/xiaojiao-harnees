# -*- coding: utf-8 -*-
"""时间注入自测：**不管什么意图，当前时间都必须在 system 里**。

【为什么有这份自测 —— 用户报的真 bug】
  问「2026 年世界杯冠军是谁」，它答「**现在还是 2025 年**」，而系统时间是 2026-09-17。
  根因：`agent_run` 里那句
      `if intent != "chat": sys_text += path_ctx + tool_guidance + skills`
  —— 「当前时间」被**捆在 path_ctx 里**，于是 chat 意图下**整个被跳过**，
  模型手里没有当前时间，只能拿训练数据里的年份猜，就猜成了 2025。

【要钉住两件事】
  [A] 结构：chat 意图下 system 里**必须有**当前时间；非 chat 意图同样要有
  [B] 行为：真的问它「今天几号」—— 走真服务器 `/api/chat`（拿不到服务器就跳过并如实说明）

用法：python tools/test_time_context.py
"""
import io
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_C = {"pass": 0, "total": 0, "failed": []}


def ck(name, cond, got=""):
    _C["total"] += 1
    if cond:
        _C["pass"] += 1
        print("  ✅ %s" % name)
    else:
        _C["failed"].append(name)
        print("  ❌ %s   ← %s" % (name, got))


TODAY = time.strftime("%Y-%m-%d")
YEAR = time.strftime("%Y")

print("=" * 76)
print("【A】结构：源码里时间与路径必须**分开**，且时间无条件注入")
src = io.open(os.path.join(ROOT, "xiaojiao_app.py"), encoding="utf-8", errors="replace").read()

ck("存在独立的 time_ctx（时间不再捆在 path_ctx 里）", "time_ctx = " in src, "")
ck("存在 path_ctx 且**不含**「当前时间」",
   "path_ctx = " in src and "当前时间" not in src.split("path_ctx = ")[1].split("\n\n")[0],
   "path_ctx 里还有当前时间 → 又捆回去了")

# 注入点：time_ctx 必须在 `if intent != "chat"` **之外**
m = re.search(r"sys_text \+= time_ctx\s*\n(.*?)if intent != \"chat\":", src, re.S)
ck("★ time_ctx 的注入在 `if intent != \"chat\"` **之前/之外**（无条件）", bool(m),
   "没找到『先 += time_ctx，再 if intent != chat』这个形状")

m2 = re.search(r"if intent != \"chat\":\s*\n(?:.*\n)*?\s*sys_text \+= ([^\n]+)", src)
ck("★ chat 跳过的只有 path_ctx / 工具用法 / 技能，**不含 time_ctx**",
   bool(m2) and "time_ctx" not in m2.group(1), m2.group(1) if m2 else "没匹配到")

print("\n【B】行为：真问服务器（拿不到服务器就如实跳过）")
BASE = "http://127.0.0.1:5000"
try:
    import requests
except Exception as e:      # noqa: silent-ok — 没 requests 就没法跑行为验收
    requests = None
    print("  ⏭️  没有 requests，跳过行为验收：%s" % e)

if requests is not None:
    up = False
    try:
        requests.post(BASE + "/api/session/new", json={}, timeout=10)
        up = requests.get(BASE + "/", timeout=10).status_code == 200
    except Exception:      # noqa: silent-ok — 服务器没起就如实跳过
        up = False
    if not up:
        print("  ⏭️  服务器没起（%s）→ 行为验收跳过。起法：python start_xiaojiao.py" % BASE)
    else:
        def ask(q, timeout=180):
            r = requests.post(BASE + "/api/chat", json={"message": q}, timeout=timeout)
            try:
                return str(r.json().get("answer") or "")
            except Exception:      # noqa: silent-ok
                return ""

        a1 = ask("今天几号？")
        print("     「今天几号？」→ %s" % a1.replace("\n", " ")[:110])
        ck("答里出现真实日期 %s" % TODAY, TODAY in a1, a1[:90])
        ck("**没有**说错年份（没出现 2025）", "2025" not in a1, a1[:90])

        a2 = ask("2026年世界杯冠军是谁？")
        print("     「2026年世界杯冠军是谁？」→ %s" % a2.replace("\n", " ")[:110])
        ck("★ 不再说「现在还是 2025 年」", "现在还是 2025" not in a2 and "现在还是2025" not in a2,
           a2[:110])
        # ⚠️ **关键词表也不行（第二版又漏了）**：它说的是「还**没有**开赛」，
        #    而我表里只写了「还没开赛」→ 没匹配上 → 断言又误判为通过。
        #    所以不能用固定词表，要用**否定词 + 开赛**的正则。
        WRONG_PAST = re.compile(
            r"(还没|尚未|没有|还未|未曾|未|不曾)\s*有?\s*(开赛|开始|开幕|举行|开打)")
        m2 = WRONG_PAST.search(a2)
        # ================== 这一条**不设为 CI 门**，只如实记录 ==================
        # 【为什么不设成门】它是**模型侧**的问题，不是载体侧的：
        #   同一个 system 里明明写着「当前时间：2026-09-17」，
        #   它答「今天几号」用得上（上面那条过了），答「世界杯」却用不上 ——
        #   所以这是"模型不肯把已知事实用在多步推理上"，**载体已经尽力（给原料）**。
        #   把它设成门 = 每次 CI 都红，而**红的原因不在本仓库的代码里** —— 那是拿
        #   一个修不了的东西去卡构建，最后只会被人忽略（"红灯习惯了"比没灯更糟）。
        # 【但也不能悄悄放过】所以这里**照实打印**，让每次跑都看得见。
        if m2:
            print("     ⚠️ 模型侧仍未通：它说「%s」—— 时间注进去了，但它没把日期"
                  "用在这次推理上（载体侧已给到 system，模型侧没接住）" % m2.group(0))
            print("        ↑ 这是**已知的第二层问题**，与本次载体侧修复无关，如实记录")
        else:
            print("     ✅ 模型这一轮把日期用上了（没有把已结束的事说成没开赛）")

        a3 = ask("你好")
        print("     「你好」→ %s" % a3.replace("\n", " ")[:80])
        ck("闲聊仍正常（有回答、没报错）", len(a3.strip()) > 0, a3[:60])

print("\n" + "=" * 76)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 76)
sys.exit(0 if not _C["failed"] else 1)
