# -*- coding: utf-8 -*-
"""接入验收 · 最小化真实版（9 条场景，每条真实对话 + 查日志痕迹）

【为什么要有这个测试 —— 它抓到的是一类自测永远抓不到的问题】
    `core/boost/`（模块 10）自测 195/195、`core/metacognition/` 143/143、
    `core/central/` 44/44 —— **全绿**。但 `agent_run` 一次都没调用过它们：
    这三块全是**离线能力**，用户对话时一项都不会被触发。
    教训：**"函数是对的"不等于"接入过"**。本测试证明的是"真的被触发过"。

每条：开新会话 → 发一句 → 读日志/落盘文件 → 找该模块的痕迹。
运行：python tools/test_module_integration.py     （需要小焦在跑）
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

PASS, FAIL = [], []
BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")
BOUNDARY = os.path.join(_ROOT, "logs", "metacognition", "boundary.jsonl")
EVENTS = os.path.join(_ROOT, "logs", "central", "events.jsonl")


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _tail_mark():
    try:
        return os.path.getsize(LOG)
    except Exception:      # noqa: silent-ok — 日志不存在就从 0 开始
        return 0


def _read_since(mark):
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            return f.read()
    except Exception:      # noqa: silent-ok — 读不到就当空，由断言如实报缺
        return ""


def _lines_with(text, keys):
    out = []
    for ln in text.split("\n"):
        if any(k in ln for k in keys):
            out.append(ln.strip()[:160])
    return out


def new_session():
    try:
        return requests.post(BASE + "/api/session/new", json={}, timeout=20).status_code == 200
    except Exception:      # noqa: silent-ok — 建不了新会话就继续用当前会话
        return False


def ask(msg, timeout=300):
    t0 = time.time()
    for _ in range(5):
        r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
        if r.status_code != 429:
            break
        time.sleep(4)
    try:
        d = r.json()
    except Exception:      # noqa: silent-ok — 非 JSON 也要能看状态码
        d = {}
    ans = str(d.get("answer") or "")
    tools = [t.get("tool") for t in (d.get("tool_trace") or []) if isinstance(t, dict)]
    return r.status_code, ans, tools, time.time() - t0


def file_size(p):
    try:
        return os.path.getsize(p)
    except Exception:      # noqa: silent-ok — 文件不存在按 0
        return 0


# 九条场景：(编号, 模块, 说明, 提问, 日志关键词)
SCENES = (
    ("1", "10.1 元推理模板", "概率题",
     "一个箱子有 3 个红球 2 个蓝球，随机摸 2 个，都是红球的概率？",
     ("极限补刀接入", "reasoning:")),
    ("2", "10.2 长链因果", "因果题",
     "A 比 B 高，B 比 C 高，C 比 D 高，谁最矮？",
     ("极限补刀接入", "causal:")),
    ("3", "10.3 跨领域联想", "跨域题",
     "用物理学的思维分析一下公司现金流",
     ("极限补刀接入", "analogy:")),
    ("4", "10.4 模糊意图", "回指（接上文）",
     "我要全部的",     # 配合上一条"有哪些工具"形成回指链
     ("上下文融合", "工具清单类问题")),
    ("5", "10.5 创造性", "创意题",
     "写 3 个完全不同风格的开场白，主题是咖啡",
     ("极限补刀接入", "creative:")),
    ("6", "10.6 深度推理", "深度题",
     "为什么天空是蓝色的？",
     ("极限补刀接入", "deepthink:")),
    ("7", "10.7 超长一致性", "长文",
     "写 3000 字小说，主角叫张三",
     ("极限补刀接入", "consistency:")),
    ("8", "元认知", "未知题",
     "2027 年诺贝尔物理学奖得主是谁？",
     ("元认知",)),
    ("9", "协同网络", "多模块",
     "帮我抓一下 http://example.com 然后总结一下内容",
     # ⚠️ 协同网络的痕迹**不在 xiaojiao.log 里** —— 事件走的是
     #    `logs/central/events.jsonl`（落盘）+ `/api/central`（运行期快照）。
     #    第一版我在主日志里找"boost.used"→ 找不到 → 误判"没接入"（假红）。
     #    教训：**先确认证据到底落在哪**，再去断言。
     ("boost.used", "memory.retrieved", "metacognition.checked")),
)


def main():
    print("=" * 82)
    print("  接入验收 · 最小化真实版（9 条场景，真实对话 + 日志痕迹）")
    print("=" * 82)
    try:
        if requests.get(BASE + "/health", timeout=5).status_code != 200:
            raise RuntimeError("health != 200")
    except Exception as e:
        print("❌ 小焦没在跑（%s）：%s。先 `python start_xiaojiao.py`。" % (BASE, e))
        return 1

    results = []
    for num, mod, desc, msg, keys in SCENES:
        print("\n【%s · %s】%s" % (num, mod, desc))
        new_session()
        # 场景 4 需要上文：先发一句工具询问
        if num == "4":
            _c0, _a0, _t0, _e0 = ask("帮我看看有哪些工具")
            print("    预热（工具询问）：%d 字" % len(_a0))
        b_mark, e_mark = _tail_mark(), file_size(BOUNDARY)
        e_before = file_size(EVENTS)
        print("    发：%s" % msg)
        code, ans, tools, el = ask(msg)
        time.sleep(1.0)                      # 给日志落盘留一点时间
        seg = _read_since(b_mark)
        hits = _lines_with(seg, keys)
        # 场景 9 的痕迹在**事件文件**里（不在主日志）：两条通道合并看
        if num == "9" and file_size(EVENTS) > e_before:
            try:
                with open(EVENTS, "r", encoding="utf-8", errors="replace") as f:
                    ev_lines = [l.strip()[:110] for l in f.readlines()[-4:]]
                hits = hits + [("events.jsonl: " + l) for l in ev_lines]
            except Exception:      # noqa: silent-ok — 读不到就按主日志的结果
                pass
        # 输出侧证据
        out_evidence = ""
        if num == "1":
            out_evidence = ("红" in ans or "概率" in ans)
        elif num == "2":
            out_evidence = ("D" in ans)
        elif num == "4":
            out_evidence = ("工具" in ans)
        elif num == "8":
            out_evidence = any(w in ans for w in ("不确定", "查", "不知道", "无法", "没有"))
        else:
            out_evidence = len(ans) > 30
        print("    HTTP=%s | %.1fs | 工具=%s | %d 字" % (code, el, tools[:3], len(ans)))
        print("    回答开头：%s" % ans[:80].replace("\n", " "))
        ck("[%s] 日志有痕迹" % num, bool(hits), (hits[0] if hits else "无命中"))
        if num == "8":
            grew = file_size(BOUNDARY) > e_mark
            ck("[%s] boundary.jsonl 有写入" % num, grew,
               "%.0f → %.0f 字节" % (e_mark, file_size(BOUNDARY)))
        ck("[%s] 有输出/行为变化" % num, bool(out_evidence) or bool(tools),
           "输出=%s 工具=%s" % (out_evidence, tools[:2]))
        results.append((num, mod, hits, out_evidence or bool(tools)))

    print("\n" + "=" * 82)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    # ---- 场景 9 的**订阅侧**验收：模块 A 发布 → 模块 B 收到 ----
    # 事件文件只证明"有人发布了"；要证明"有人收到并处理了"，
    # 必须读服务器进程自己的中央状态（`/api/central` 里订阅者写进去的那些）。
    print("\n[9·订阅侧] 模块 A 发布 → 模块 B 收到（读服务器自己的中央状态）")
    try:
        r = requests.get(BASE + "/api/central", timeout=20)
        snap = r.json() if r.status_code == 200 else {}
        st = snap.get("state") or {}
        bus = snap.get("bus") or {}
        print("    HTTP=%s | 在线模块 %s/%s | 命名空间=%s"
              % (r.status_code, snap.get("modules_available"),
                 snap.get("modules_total"), sorted(st.keys())))
        print("    总线：published=%s subscribers=%s topics=%s persist=%s"
              % (bus.get("published"), bus.get("subscribers"),
                 bus.get("topics"), bus.get("persist")))
        ck("[9] 中央状态里有**订阅者写入的命名空间**（memory / boost_last）",
           bool(st.get("memory") or st.get("boost_last")), sorted(st.keys()))
        ck("[9] 总线真的被用过（published>0 且 subscribers>0）",
           (bus.get("published") or 0) > 0 and (bus.get("subscribers") or 0) > 0,
           "published=%s subscribers=%s" % (bus.get("published"), bus.get("subscribers")))
        ck("[9] 事件在落盘（persist=True，可事后复盘）", bus.get("persist") is True,
           bus.get("persist"))
        ck("[9] 最近事件里有主题流水（A 发过 B 收过）",
           len(snap.get("recent_events") or []) > 0,
           [e.get("topic") for e in (snap.get("recent_events") or [])[-3:]])
    except Exception as e:
        ck("[9] 订阅侧可读（/api/central）", False, "%s: %s" % (type(e).__name__, e))

    # 事件文件证据
    try:
        with open(EVENTS, "r", encoding="utf-8", errors="replace") as f:
            n_ev = sum(1 for _ in f)
        print("\n  协同网络事件流水：%s（%d 行）" % (EVENTS, n_ev))
    except Exception:      # noqa: silent-ok — 读不到就如实说明
        print("\n  协同网络事件流水：读不到（%s）" % EVENTS)
    print("=" * 82)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
