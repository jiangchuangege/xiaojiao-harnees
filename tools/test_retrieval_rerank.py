# -*- coding: utf-8 -*-
"""载体二次判断（检索精排）· 回归测试

【守的是什么】
  小脑是**字级**模型，精细语义弱：实测"我非常喜欢这个方案" vs "我非常讨厌这个方案"
  余弦 **0.904**（近义对才 0.814），而 `THRESHOLD = 0.6` 挡不住这种反义。
  反义记忆一旦注进 system，模型会拿"A 的反面"去回答"A 的问题" —— 比"没记住"更糟。

【本文件的判据两类】
  ① 正常路径：判官挑出相关的那几条，反义/无关被剔掉。
  ② **失败路径**：判官不可用 / 抛异常 / 判成"全不相关" —— 一律**放行全部候选**。
     这一类比第一类重要：精排是加分项，它挂掉时绝不能顺手把用户的记忆也一起丢了
     （"它突然什么都不记得了"比"多注入一条无关记忆"严重得多）。

不依赖模型、不依赖网络：判官用假函数注入。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core import retriever as R  # noqa: E402

PASS = {"n": 0, "ok": 0}
FAILS = []


def ck(name, cond, extra=""):
    PASS["n"] += 1
    if cond:
        PASS["ok"] += 1
    else:
        FAILS.append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← %s" % extra) if extra else ""))


def hits(*pairs):
    return [{"id": str(i + 1), "text": t, "score": s, "ts": 1.0}
            for i, (t, s) in enumerate(pairs)]


H3 = hits(("我喜欢蓝色", 0.90), ("我讨厌蓝色", 0.88), ("今天天气不错", 0.70))
H5 = hits(("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6), ("e", 0.5), ("f", 0.4))


def main():
    print("=" * 78)
    print("  载体二次判断（检索精排）· 回归测试")
    print("=" * 78)

    print("\n[一] 正常路径：判官说了算")
    keep, note = R.rerank("我喜欢什么颜色", H3, judge=lambda p: "1")
    ck("只保留判官点名的那条（反义 2、无关 3 被剔掉）",
       [h["id"] for h in keep] == ["1"], [h["id"] for h in keep])
    ck("说明里带了保留数量", "1/3" in note, note)

    keep, note = R.rerank("我喜欢什么颜色", H3, judge=lambda p: "1,3")
    ck("判官点两条就留两条", [h["id"] for h in keep] == ["1", "3"], [h["id"] for h in keep])

    keep, note = R.rerank("问我喜欢什么", H3, judge=lambda p: "答案：1。因为…")
    ck("判官夹带解释也能解析出编号", [h["id"] for h in keep] == ["1"], [h["id"] for h in keep])

    print("\n[二] 失败路径：一律放行（**这类比上面重要**）")
    keep, note = R.rerank("q", H3, judge=lambda p: None)
    ck("判官不可用 → 全部放行", len(keep) == 3, "%d 条 · %s" % (len(keep), note))

    def boom(p):
        raise RuntimeError("judge down")

    keep, note = R.rerank("q", H3, judge=boom)
    ck("判官抛异常 → 全部放行", len(keep) == 3, "%d 条 · %s" % (len(keep), note))

    keep, note = R.rerank("q", H3, judge=lambda p: "无")
    ck("判官判「全不相关」→ **保守保留**（不轻易清空记忆）",
       len(keep) == 3, "%d 条 · %s" % (len(keep), note))

    keep, note = R.rerank("q", H3, judge=lambda p: "99, 100")
    ck("判官给越界编号 → 放行", len(keep) == 3, "%d 条 · %s" % (len(keep), note))

    print("\n[三] 闸门：不该调判官的时候就不调")
    called = []
    R.rerank("q", H3[:1], judge=lambda p: called.append(1) or "1")
    ck("只有 1 条候选 → 不调判官（省一次模型往返）", not called)

    called2 = []
    R.RERANK = False
    try:
        keep, note = R.rerank("q", H3, judge=lambda p: called2.append(1) or "1")
    finally:
        R.RERANK = True
    ck("总开关关掉 → 不调判官、全部放行",
       (not called2) and len(keep) == 3, note)

    print("\n[四] 候选上限：只把前 RERANK_MAX 条给判官看")
    seen = {}

    def spy(p):
        seen["prompt"] = p
        return "1"

    keep, note = R.rerank("q", H5, judge=spy)
    listed = seen["prompt"].count("\n1. ") + seen["prompt"].count("\n2. ") \
        + seen["prompt"].count("\n3. ") + seen["prompt"].count("\n4. ") \
        + seen["prompt"].count("\n5. ") + seen["prompt"].count("\n6. ")
    ck("prompt 里只列了前 %d 条" % R.RERANK_MAX, listed == R.RERANK_MAX, "列了 %d 条" % listed)
    ck("没让判官看的尾部候选仍然保留（不能被吞掉）",
       len(keep) == 6 - R.RERANK_MAX + 1, "%d 条 · %s" % (len(keep), note))

    print("\n[五] 参数与提示词口径")
    ck("默认开启", R.RERANK is True)
    ck("至少 2 条候选才精排", R.RERANK_MIN_HITS == 2, R.RERANK_MIN_HITS)
    ck("提示词明确要求判「意思相反」不算相关", "相反" in R._RERANK_PROMPT)
    ck("提示词要求只输出编号（不让模型自由发挥）", "只输出" in R._RERANK_PROMPT)

    print("\n[六] 真接上大脑的调用协议（**防「静默失效」**）")
    # 这一节是实测补的：`xiaojiao_app.llm_chat(messages)` 不接受 max_tokens，
    # 第一版直接带参调用 → 每次都 TypeError 被吞 → 精排**永远走降级路、一次都没生效**，
    # 而且页面/日志上一点报错都没有。所以必须钉住"两条签名分支都能通"。
    import sys as _s

    class _Fake:
        def __init__(self, strict):
            self.strict = strict
            self.calls = 0

        def llm_chat(self, msgs, **kw):
            self.calls += 1
            if self.strict and kw:
                raise TypeError("llm_chat() got an unexpected keyword argument")
            return "1"

    old = _s.modules.get("xiaojiao_app")
    try:
        for strict, tag in ((True, "只接受 messages（真实签名）"), (False, "接受 max_tokens")):
            f = _Fake(strict)
            _s.modules["xiaojiao_app"] = f
            got = R._ask_brain("测试")
            ck("接大脑可用：%s" % tag, got == "1", "返回 %r，调用 %d 次" % (got, f.calls))
        _s.modules.pop("xiaojiao_app", None)
        ck("没有 app 时如实返回 None（不抛异常）", R._ask_brain("测试") is None)
    finally:
        if old is not None:
            _s.modules["xiaojiao_app"] = old

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (PASS["ok"], PASS["n"],
                                  ("　失败：" + "；".join(FAILS)) if FAILS else ""))
    print("=" * 78)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
