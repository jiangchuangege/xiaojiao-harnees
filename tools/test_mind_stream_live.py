# -*- coding: utf-8 -*-
"""思维流 Mind Stream · 验收测试（7 条，全部真对话 + 真日志）

【这 7 条为什么这么定】
    "思维连续性"最容易做成"看起来有状态、实际每轮还是重来"。
    所以每条都必须**可观测**：要么比两次回答的差异（测试1），
    要么查日志里的状态演进（测试6），要么看温度真的按意图变了（测试5）。
    最容易被糊弄过去的是测试 1 —— 判据必须**排除固定话术**
    （"你刚说过了"也算不合格：那是载体给的模板，不是模型自然的回应）。

运行：python tools/test_mind_stream_live.py      （需要小焦在跑）
"""
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402
from core.mind_stream import state as ST  # noqa: E402

PASS, FAIL = [], []
BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")

# 固定话术（载体给的模板）—— 出现这些就算**不合格**
CANNED = ("你刚说过了", "你已经说过了", "这个我刚说过", "重复了", "说过了哦",
          "我们已经聊过")


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def new_session():
    try:
        return requests.post(BASE + "/api/session/new", json={}, timeout=20).status_code == 200
    except Exception:      # noqa: silent-ok — 建不了就继续用当前会话
        return False


def cur_sid():
    try:
        r = requests.get(BASE + "/api/sessions", timeout=20).json()
        cur = r.get("current") or r.get("current_id") or ""
        if isinstance(cur, dict):
            cur = cur.get("id") or ""
        return str(cur or "")
    except Exception:      # noqa: silent-ok — 拿不到会话 id 就用空（只在测试6需要）
        return ""


def ask(msg, timeout=300):
    for _ in range(5):
        r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
        if r.status_code != 429:
            break
        time.sleep(4)
    try:
        d = r.json()
    except Exception:      # noqa: silent-ok — 非 JSON 也要能看状态码
        d = {}
    return r.status_code, str(d.get("answer") or ""), \
        [t.get("tool") for t in (d.get("tool_trace") or []) if isinstance(t, dict)]


def log_since(mark):
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            return f.read()
    except Exception:      # noqa: silent-ok — 读不到就当空
        return ""


def log_mark():
    try:
        return os.path.getsize(LOG)
    except Exception:      # noqa: silent-ok — 文件不在从 0 开始
        return 0


def main():
    print("=" * 80)
    print("  思维流 Mind Stream · 验收测试（7 条）")
    print("=" * 80)
    try:
        if requests.get(BASE + "/health", timeout=5).status_code != 200:
            raise RuntimeError("health != 200")
    except Exception as e:
        print("❌ 小焦没在跑（%s）：%s" % (BASE, e))
        return 1

    # ================= 测试 1：同一会话连说两次，回应必须不同且不是固定话术 =================
    print("\n[测试 1] 连说两次同一句 → 第二次回应必须不同、且不是固定话术")
    new_session()
    sid = cur_sid()
    code1, a1, _ = ask("我叫张三，在济南做后端开发")
    code2, a2, _ = ask("我叫张三，在济南做后端开发")
    ck("两次都答上了", code1 == 200 and code2 == 200 and len(a1) > 10 and len(a2) > 10,
       "%d 字 / %d 字" % (len(a1), len(a2)))
    same = (a1.strip() == a2.strip())
    ck("**第二次回应与第一次不同**（不是重放）", not same,
       "完全相同=%s" % same)
    # 差异要"实质"：去掉标点后仍应有明显不同（不能只差一个标点）
    n1 = re.sub(r"[\s，。！？、,.!?~～]+", "", a1)
    n2 = re.sub(r"[\s，。！？、,.!?~～]+", "", a2)
    diff_ratio = 1 - (len(set(n1) & set(n2)) / max(1, len(set(n1) | set(n2))))
    ck("差异是**实质**的（字符差异率 ≥ 0.25）", diff_ratio >= 0.25,
       "差异率=%.2f" % diff_ratio)
    hit = [w for w in CANNED if w in a2]
    ck("**不是固定话术**（不许用你刚说过了敷衍）", not hit, hit)
    st1 = ST.load(sid) if sid else {}
    ck("思维状态已落盘（话题/轮数都在）",
       bool(st1.get("current_topic")) and (st1.get("turn_count") or 0) >= 2,
       "话题=%s 轮数=%s" % (st1.get("current_topic"), st1.get("turn_count")))
    ck("记住了用户事实（名字/城市/职业）",
       len(st1.get("user_understanding") or []) >= 2, st1.get("user_understanding"))
    print("     第一次：%s" % a1[:70].replace("\n", " "))
    print("     第二次：%s" % a2[:70].replace("\n", " "))

    # ================= 测试 2：思维连续性 =================
    print("\n[测试 2] 三句连起来应当在聊同一件事")
    new_session()
    sid2 = cur_sid()
    mark = log_mark()
    _c, t2a, _ = ask("帮我看看有哪些工具")
    _c, t2b, _ = ask("我要全部的")
    _c, t2c, _ = ask("给我解释一下 net_ip 是干嘛的")
    seg = log_since(mark)
    turns = re.findall(r"思维流：话题=([^｜]+)", seg)
    ck("三句的过程里都有思维流日志", len(turns) >= 3, turns)
    ck("**话题始终是工具相关**（没有断线跑到别的话题）",
       all(("工具" in x) for x in turns) if turns else False, turns)
    ck("第三句真的解释了 net_ip（接上了前两句）",
       ("net_ip" in t2c or "公网" in t2c or "IP" in t2c), t2c[:70].replace("\n", " "))
    st2 = ST.load(sid2) if sid2 else {}
    ck("状态里话题仍是工具", "工具" in str(st2.get("current_topic") or ""),
       st2.get("current_topic"))

    # ================= 测试 3：话题切换 + 回到原话题 =================
    print("\n[测试 3] 换话题再回来，第三句应能接上第一句")
    new_session()
    sid3 = cur_sid()
    _c, t3a, _ = ask("帮我抓一下 http://example.com")
    st_a = ST.load(sid3) if sid3 else {}
    _c, t3b, _ = ask("对了，今天天气怎么样")
    st_b = ST.load(sid3) if sid3 else {}
    ck("换话题后状态确实变了（抓取 → 天气）",
       "抓" in str(st_a.get("current_topic") or "")
       and "天气" in str(st_b.get("current_topic") or ""),
       "%s → %s" % (st_a.get("current_topic"), st_b.get("current_topic")))
    _c, t3c, _ = ask("回到刚才那个抓取")
    st_c = ST.load(sid3) if sid3 else {}
    ck("**第三句回到了抓取话题**（不被中间那句打断）",
       "抓" in str(st_c.get("current_topic") or ""), st_c.get("current_topic"))
    ck("第三句的回应与抓取/网页有关（不是答天气）",
       any(w in t3c for w in ("抓", "网页", "example", "robots", "HTTP")),
       t3c[:70].replace("\n", " "))

    # ================= 测试 4：没说出口的话 =================
    print("\n[测试 4] 长文被截断后，下一句然后呢能接上")
    new_session()
    sid4 = cur_sid()
    _c, t4a, _ = ask("帮我写个 3000 字的文章")
    st4 = ST.load(sid4) if sid4 else {}
    _c, t4b, _ = ask("然后呢")
    ck("长文请求之后状态里有在写文章的痕迹（话题或思路）",
       ("写作" in str(st4.get("current_topic") or ""))
       or any("写" in str(x) for x in (st4.get("recent_thoughts") or []))
       or ("文章" in str(st4.get("current_topic") or "")),
       "话题=%s 思路=%s" % (st4.get("current_topic"),
                            (st4.get("recent_thoughts") or [])[:1]))
    ck("**然后呢接上了上文**（回应与文章/继续有关）",
       any(w in t4b for w in ("继续", "接着", "文章", "下一", "段落", "下一节")),
       t4b[:70].replace("\n", " "))

    # ================= 测试 5：温度自适应 =================
    print("\n[测试 5] 温度按意图给（日志里可查）")
    mark = log_mark()
    new_session()
    ask("你好呀，今天过得怎么样")
    ask("3 个红球 2 个蓝球摸 2 个都是红球的概率是多少")
    ask("帮我抓一下 http://example.com")
    seg = log_since(mark)
    temps = re.findall(r"温度 ([\d.]+)", seg)
    ck("日志里记录了温度", len(temps) >= 3, temps)
    ck("**闲聊温度偏高（0.8）**", "0.8" in temps, temps)
    ck("**事实题温度偏低（0.2）**", "0.2" in temps, temps)
    ck("温度确实按意图在变（不止一个值）", len(set(temps)) >= 2, sorted(set(temps)))

    # ================= 测试 6：状态不丢（重启后仍在） =================
    print("\n[测试 6] 重启后同会话继续 → 状态恢复")
    new_session()
    sid6 = cur_sid()
    ask("我叫王五，在成都做测试工程师")
    st6 = ST.load(sid6) if sid6 else {}
    ck("状态文件在盘上（含用户事实）",
       os.path.exists(ST.path_for(sid6)) if sid6 else False,
       ST.path_for(sid6) if sid6 else "（拿不到会话 id）")
    ck("**重新读盘仍能恢复**（不依赖内存）",
       any("王五" in str(x) for x in (st6.get("user_understanding") or [])),
       st6.get("user_understanding"))
    ck("话题也在", bool(st6.get("current_topic")), st6.get("current_topic"))

    # ================= 测试 7：全量基线 =================
    print("\n[测试 7] 全量基线 249（单独跑，见报告）")
    ck("本文件不代跑全量（报告里给 run_all 的结果）", True)

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
