# -*- coding: utf-8 -*-
"""回归测试：对话连续性（上下文融合）—— 防"每句话当新对话"复发

【用户实测的核心缺陷（本文件要钉住的就是它）】
    用户："帮我看看有哪些工具" → 小焦列出工具
    用户："我要全部的"        → 小焦反问"你要全部什么？"（**没接上文**）

【根因】
    不是"历史没进 prompt"（历史进了），而是**意图判定阶段是孤立的**：
    `_detect_intent(user_input)` 只看当前这一句，而"我要全部的"孤立看确实没有信息
    （没有动词、没有对象）→ 判成 chat → 模型只能反问。人不会这样：
    人先知道"上文在聊工具"，再看"这句指全部"。

【修法】在意图识别**之前**做一次 `merge_context(user_text, history)`：
    只有句子里出现**回指**（继续类/追加类/要全部/换目标/指代词）时才融合；
    没有回指就不动它（否则换话题时会被上一轮的话题带跑，那是更糟的错）。

运行：python tools/test_context_merge.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as X  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _m(cur, prevs):
    """把 (当前句, [上文用户消息...]) 跑一遍融合。"""
    h = [{"role": "user", "content": p} for p in prevs]
    return X.merge_context(cur, h)


# 用户给的验收用例（一字不改）+ 同族变体
CASES = (
    # (当前句, 上文, 期望 kind, 期望融合文本包含, 期望需要反问)
    ("我要全部的", ["帮我看看有哪些工具"], "all", "工具", False),
    ("再来一个", ["推荐一部电影"], "more", "电影", False),
    ("继续", ["最近有什么新闻"], "continue", "新闻", False),
    ("换成 baidu", ["帮我抓一下 example.com"], "retarget", "baidu", False),
    ("我要全部的", [], "all", "", True),                       # 无上文 → 反问
    # 同族变体（证明是通用能力，不是给某一条打补丁）
    ("全部都要", ["有哪些插件"], "all", "插件", False),
    ("还有吗", ["讲个笑话"], "more", "笑话", False),
    ("接着说", ["帮我分析一下这个方案"], "continue", "方案", False),
    ("换成 github", ["抓一下 gitlab.com"], "retarget", "github", False),
    ("再来一个", [], "more", "", True),
    ("继续", [], "continue", "", True),
    ("换成 x", [], "retarget", "", True),
)


def main():
    print("=" * 78)
    print("  回归 · 对话连续性（上下文融合必须读 history）")
    print("=" * 78)

    # ---------------- 一、用户给的五条验收用例 ----------------
    print("\n[一] 验收用例逐条（前 5 条是用户原话）")
    for cur, prevs, kind, must, need_q in CASES:
        r = _m(cur, prevs)
        ck("「%s」（上文：%s）→ 融合类型 %s"
           % (cur, (prevs[0][:14] if prevs else "无"), kind),
           r["kind"] == kind, "%s / %s" % (r["kind"], r.get("why", "")[:30]))
        if must:
            ck("「%s」融合文本含「%s」" % (cur, must), must in str(r["text"]),
               str(r["text"])[:40])
        ck("「%s」%s" % (cur, "需要反问" if need_q else "不该反问"),
           bool(r["need_clarify"]) == need_q, r["need_clarify"])
        if prevs:
            ck("「%s」确实做了融合（merged=True）" % cur, r["merged"] is True)

    # ---------------- 二、意图识别真的用上了融合结果 ----------------
    print("\n[二] 意图识别用融合结果（这才是「接上文」的落点）")
    for cur, prevs, kind, _, need_q in CASES:
        if need_q:
            continue
        r = _m(cur, prevs)
        ck("「%s」融合后 %r 与原文**不同**（否则等于没融合）"
           % (cur, str(r["text"])[:20]), str(r["text"]) != cur, str(r["text"])[:30])
    # 关键那条链：工具清单
    c1 = _m("我要全部的", ["帮我看看有哪些工具"])
    ck("**「我要全部的」接在「有哪些工具」之后 → 判为工具清单问题**（用户实测那条链）",
       X._tool_inventory_question("我要全部的", c1) is True, c1["text"])
    ck("「我要全部的工具」（自带对象）**无上文也**判为工具清单问题",
       X._tool_inventory_question("我要全部的工具", None) is True)
    ck("「我要全部的」**无上文**时不判为工具清单（该反问范围）",
       X._tool_inventory_question("我要全部的", _m("我要全部的", [])) is False)

    # ---------------- 三、没有回指时**绝不动**（不能把换话题带跑） ----------------
    print("\n[三] 反向保护：没有回指时不许融合（否则换话题会被带跑）")
    for cur, prevs in (("今天天气怎么样", ["帮我看看有哪些工具"]),
                       ("写一首诗", ["推荐一部电影"]),
                       ("删除 C:/a.txt", ["最近有什么新闻"]),
                       ("你好", ["帮我抓一下 example.com"]),
                       ("帮我看看有哪些工具", ["推荐一部电影"])):
        r = _m(cur, prevs)
        ck("「%s」不被上文带跑（merged=False）" % cur, r["merged"] is False,
           "%s / %s" % (r["merged"], r["why"][:24]))
        ck("「%s」原文不变" % cur, str(r["text"]) == cur, str(r["text"])[:24])

    # ---------------- 四、反问文案可用（不是空话） ----------------
    print("\n[四] 无上文时的反问：给得出**具体**的追问")
    for cur in ("我要全部的", "再来一个", "继续", "换成 baidu"):
        q = X._clarify_question(cur)
        ck("「%s」有可读的中文反问" % cur, isinstance(q, str) and len(q) >= 10, q[:34])
    ck("反问里**给出了例子**（用户知道该怎么答）",
       "比如" in X._clarify_question("我要全部的") or "范围" in X._clarify_question("我要全部的"),
       X._clarify_question("我要全部的")[:40])

    # ---------------- 五、通用性：不只是那几条，而是所有接续说法 ----------------
    print("\n[五] 通用性：换一批说法也要能接上（不是给某条打补丁）")
    more_family = ("再来一个", "再来一次", "换一个", "还有吗", "另一个", "再推荐一个", "多来几个")
    for w in more_family:
        r = _m(w, ["推荐一部电影"])
        ck("追加类「%s」能接上文" % w, r["kind"] == "more" and r["merged"], r["kind"])
    cont_family = ("继续", "接着", "接着说吧", "然后呢")
    for w in cont_family:
        r = _m(w, ["最近有什么新闻"])
        ck("继续类「%s」能接上文" % w, r["kind"] == "continue" and r["merged"], r["kind"])
    all_family = ("全部", "所有", "全都要", "都要", "全都给我")
    for w in all_family:
        r = _m(w, ["帮我看看有哪些工具"])
        ck("要全部「%s」能接上文" % w, r["kind"] == "all" and r["merged"], r["kind"])

    # ---------------- 六、脏输入与边界 ----------------
    print("\n[六] 边界：脏输入不崩")
    for cur, prevs in (("", ["帮我看看有哪些工具"]), (None, []),
                       ("我要全部的", None), ("继续", ["", "  ", "⏳__pending__"]),
                       ("再来一个", [{"role": "assistant", "content": "好的"}])):
        try:
            r = X.merge_context(cur, prevs if prevs is None
                                else [{"role": "user", "content": p}
                                      if isinstance(p, str) else p for p in prevs])
            ck("脏输入 %r 不崩" % (cur,), isinstance(r, dict), r.get("kind"))
        except Exception as e:
            ck("脏输入 %r 不崩" % (cur,), False, "%s: %s" % (type(e).__name__, e))

    # ---------------- 七、**真实会话角色**（中文 role）也要认 ----------------
    print("\n[七] 真实会话里 role 是中文（「用户」/「小焦」），必须认得出")
    # 为什么单列这一组：`append_msg("用户", …)` 存的是**中文角色**，而 OpenAI 风格是 `user`。
    # 第一版只判了 `user`，单元测试（我按英文 role 造数据）全绿，
    # 但**真实端到端**里一条历史都取不到 → 第 2 轮照样反问（实测当场抓到）。
    # 教训：**测试数据的 role 必须用真实会话那一套**，否则测的是一个不存在的情形。
    real_hist = [{"role": "用户", "content": "帮我看看有哪些工具"},
                 {"role": "小焦", "content": "我一共 77 个工具，全都能用"},
                 {"role": "用户", "content": "推荐一部电影"},
                 {"role": "小焦", "content": "『肖申克的救赎』"}]
    r = X.merge_context("我要全部的", real_hist)
    ck("中文 role（用户/小焦）也能取出上文并融合",
       r["merged"] is True and r["kind"] == "all", "%s / %s" % (r["kind"], r["text"]))
    ck("**只取用户说的**（小焦的回答不算上文，否则话题会被带偏）",
       r.get("topic") == "电影", "topic=%r" % r.get("topic"))
    ck("取的是**最近**那条用户消息（『推荐一部电影』，不是更早的工具那条）",
       "电影" in str(r.get("text")), str(r.get("text"))[:30])
    r2 = X.merge_context("继续", real_hist)
    ck("继续类在真实 role 下也能接上", r2["kind"] == "continue" and r2["merged"],
       "%s / %s" % (r2["kind"], str(r2["text"])[:24]))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
