# -*- coding: utf-8 -*-
"""模块 9 · 人格层 · 自测（确定性，不依赖模型、不依赖网络）。

为什么必须有它：人格的失败**不会报错**——
它只会"说话像机器人"，或者在用户明确要列表时硬写成散文。
这两种都看不出来是 bug，只能靠**把判据钉成断言**来防回归：
  · 十条 AI 味必须识别（并且删得掉）；
  · 十条人味必须真的进了提示词（不是写在文档里）；
  · **用户要什么给什么**：要列表给列表、要表格给表格，闲聊不列点；
  · 后处理**绝不删内容**（只删空壳套话，删完不能变空、不能断句）。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import persona as P   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 70)
    print("  模块 9 · 人格层（去 AI 味 / 长人味 / 表达形式矩阵）")
    print("=" * 70)

    # ---------------- 一、十条 AI 味：必须命中 ----------------
    print("\n[一] 十条 AI 味：逐条检查能被识别")
    trope_cases = [
        ("self_expose", "作为一个 AI 语言模型，我不能有情绪。"),
        ("self_expose", "作为一个AI助手，我来回答你。"),
        ("template_open", "当然可以！下面是具体做法。"),
        ("template_open", "很荣幸为您解答这个问题。"),
        ("template_open", "以下是详细介绍：正文在此。"),
        ("over_apology", "非常抱歉，我刚才没有理解你的意思。"),
        ("over_polite", "希望以上回答对你有帮助。"),
        ("over_polite", "如果还有其它问题，随时问我。"),
        ("over_explain", "让我来为你详细解释一下：这个概念是这样的。"),
        ("over_explain", "总而言之，事情就是这样。"),
        ("fake_humble", "我只是一个程序，没有真正的感情。"),
        ("no_stance", "这个问题因人而异，没有标准答案。"),
        ("over_hedge", "以上仅供参考。"),
    ]
    for kind, text in trope_cases:
        out, hits = P.strip_flavor(text)
        ck("识别并删除「%s」: %s" % (kind, text[:16]), any(h.startswith(kind) for h in hits),
           "命中=%s → %r" % (hits, out[:24]))

    # ---------------- 二、删完不留残句、不删内容 ----------------
    print("\n[二] 后处理边界：只删空壳，绝不删内容、不留残句")
    keep = "载体优先的意思是：把智力放在系统里，模型只做当前这一小块。"
    out, hits = P.strip_flavor(keep)
    ck("**没有套话的正常句子一个字不动**", out == keep and not hits, (out[:20], hits))
    out2, _ = P.strip_flavor("当然可以！第一步先备份，第二步再改配置。")
    ck("删掉开场后**正文完整保留**", "第一步先备份" in out2 and "第二步再改配置" in out2,
       out2)
    ck("删除后不留行首孤立标点", not out2.startswith("，") and not out2.startswith("。"), out2)
    out3, _ = P.strip_flavor("因此，")
    ck("全删空 → 不留悬空连词", out3.strip() == "", repr(out3))
    only_trope = P.polish("希望以上回答对你有帮助。", "你好")
    ck("**整段都是套话时退回原文**（宁可少删也不给空回答）",
       bool(only_trope["text"].strip()), repr(only_trope["text"]))

    # ---------------- 三、表达形式矩阵：用户要什么给什么 ----------------
    print("\n[三] 表达形式矩阵：用户要什么给什么（硬要求优先于人格）")
    form_cases = [
        ("给我列 5 条建议", "list"),
        ("有哪些工具", "list"),
        ("做成表格对比一下", "table"),
        ("这个怎么做，给我步骤", "steps"),
        ("写个 python 函数", "code"),
        ("今天好累啊", "chat"),
        ("在吗", "chat"),
        ("帮我看看这个报错", "code"),
    ]
    for text, want in form_cases:
        got = P.pick_form(text)
        ck("「%s」→ %s" % (text, P._FORM_CN[want]), got == want, P._FORM_CN.get(got, got))
    ck("判成 chat 时给的是**禁止分点**的要求",
       "不要" in P.form_hint("chat") and "列点" in P.form_hint("chat"), P.form_hint("chat"))
    ck("判成 list 时给的是**必须给条目**的要求",
       "列表" in P.form_hint("list"), P.form_hint("list"))

    # ---------------- 四、audit：AI 味可测 ----------------
    print("\n[四] audit：AI 味是个可测的数字（能回归）")
    ai_text = ("当然可以！以下是我的建议：\n1. 多休息\n2. 多喝水\n"
               "希望以上回答对你有帮助。")
    a = P.audit(ai_text, "今天好累")
    ck("闲聊+分点+套话 → 分数明显偏高", a["score"] >= 0.4, a["score"])
    ck("问题清单里有具体原因", len(a["issues"]) >= 2, a["issues"])
    ck("form_ok=False（闲聊里分点了）", a["form_ok"] is False, a["form_ok"])
    good = "累就先歇会儿，别硬撑。我上次也是这样，睡一觉好多了。"
    b = P.audit(good, "今天好累")
    ck("口语搭话 → 分数很低", b["score"] <= 0.2, b["score"])
    ck("human = 1 - ai_ness", abs(b["human"] + b["ai_ness"] - 1.0) < 1e-9,
       (b["human"], b["ai_ness"]))
    # 反向 AI 味：用户要列表却给了散文
    c = P.audit("这件事呢，我觉得可以先做备份，然后再改配置，最后验证一下。", "给我列 3 条")
    ck("**用户要列表却没给条目 → 也算 AI 味**", c["score"] >= 0.2 and not c["form_ok"],
       (c["score"], c["issues"]))
    d = P.audit("1. 先备份\n2. 改配置\n3. 验证", "给我列 3 条")
    ck("给了条目 → form_ok", d["form_ok"] is True, d["issues"])
    e = P.audit("| 项 | 值 |\n|---|---|\n| a | 1 |", "做成表格")
    ck("给了表格 → form_ok", e["form_ok"] is True, e["issues"])

    # ---------------- 五、十条人味：必须真的进提示词 ----------------
    print("\n[五] 十条人味：必须真的拼进提示词（不是写在文档里）")
    block = P.persona_block()
    need = ["有立场", "有情绪", "会反问", "有记忆", "会主动", "允许犯错",
            "有自己的语气", "不讨好", "允许不完美", "有边界感"]
    for w in need:
        ck("人味规则含「%s」" % w, w in block)
    ck("规则里明确禁止自我暴露", "作为一个 AI" in block)
    ck("规则里明确禁止套话收尾", "希望以上" in block)
    ck("规则里明确禁止「为像人而把列表写成散文」", "列表" in block and "一大段话" in block)
    ck("可以追加自定义（不破坏既有规则）",
       "自定义补充" in P.persona_block("自定义补充"), P.persona_block("自定义补充")[-6:])

    # ---------------- 六、polish 主入口 ----------------
    print("\n[六] polish：主入口把「判形式 + 删套话」串起来")
    r = P.polish("当然可以！以下是步骤：\n1. 备份\n2. 改配置\n希望以上对你有帮助。",
                 "给我步骤")
    ck("形式判对（steps）", r["form"] == "steps", r["form"])
    ck("套话被删掉", "当然可以" not in r["text"] and "希望以上" not in r["text"], r["text"])
    ck("**正文条目一个不少**", "1. 备份" in r["text"] and "2. 改配置" in r["text"], r["text"])
    ck("报告的删前删后字数真实",
       r["after"] == len(r["text"]) and r["before"] > r["after"], (r["before"], r["after"]))
    ck("带上了给模型的形式硬要求", bool(r["form_hint"]), r["form_hint"][:24])

    # ---------------- 七、静态概览 ----------------
    print("\n[七] 概览如实（这一层不落盘就说不落盘）")
    s = P.stats()
    ck("套话种类数 = 8（8 大类，覆盖十条 AI 味）", s["tropes"] == 8, s["tropes"])
    ck("如实声明不落盘", s["persistent"] is False, s["persistent"])
    ck("六种表达形式齐全", len(s["forms"]) == 6, s["forms"])

    print("\n" + "=" * 70)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
