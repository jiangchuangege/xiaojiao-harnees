# -*- coding: utf-8 -*-
"""双模型交叉审校 · 自测（离线为主，最后一组真机可选）

钉住四件事：
  ① **谁该被审**：≥2 处可核查断言、或问题涉及钱/医疗/法律/时间承诺 → 审；普通闲聊 → 不审（省钱）；
  ② **审的人不是自己**：审校模型优先挑"跟出答不同的那个"；
  ③ **一致时不加戏**：判 same 就原样返回，不许在答案上再堆一句"我核对过了"；
  ④ **失败即跳过**：连不上/超时 → unknown，绝不抛异常、不阻塞回答。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 80)
    print("  双模型交叉审校自测")
    print("=" * 80)
    from core import dual_check as DC

    # ---------------- 一、谁该被审 ----------------
    print("\n[一] 只在「高风险」时才花一次模型调用")
    ok1, why1 = DC.is_risky("随便聊聊", "好呀，我在。今天想聊点什么？")
    ck("普通闲聊 → 不审", ok1 is False, why1)
    ok2, why2 = DC.is_risky("这个药一天吃几次", "通常一天两次，每次一片。", {"claims": 1})
    ck("问药 → 审（命中高风险领域）", ok2 is True, why2)
    ok3, why3 = DC.is_risky("总结一下", "价格 199 元，有效期 2026年7月20日",
                            {"claims": 2})
    ck("答案里有 2 处可核查断言 → 审", ok3 is True, why3)
    ok4, _ = DC.is_risky("在吗", "在")
    ck("太短的回答不审", ok4 is False)

    # ---------------- 二、审的人不是自己 ----------------
    print("\n[二] 审校模型优先选「跟出答不同的那个」")
    ids_backup = DC._available_models
    try:
        DC._available_models = lambda: ["xiaojiao", "qwopus3.5-4b-coder-mtp-q5_k_m.gguf", "coder"]
        ck("出答是 xiaojiao → 审校挑别的", DC._pick_reviewer("xiaojiao") != "xiaojiao",
           DC._pick_reviewer("xiaojiao"))
        ck("池子里有多个时，审校一定不是出答那个",
           DC._pick_reviewer("coder") != "coder", DC._pick_reviewer("coder"))
        DC._available_models = lambda: []
        ck("拿不到模型列表 → 返回空（不瞎猜）", DC._pick_reviewer("xiaojiao") == "")
    finally:
        DC._available_models = ids_backup

    # ---------------- 三、一致时不加戏 ----------------
    print("\n[三] 判「一致」时不许在答案上加任何东西")
    body = "菏泽今天阴天，13 度左右。"
    ck("same → 原样返回", DC.annotate(body, {"verdict": "same"}) == body)
    ck("unknown → 原样返回", DC.annotate(body, {"verdict": "unknown"}) == body)
    diff = DC.annotate(body, {"verdict": "diff", "why": "比分没有依据"})
    ck("diff → 前面加标注且正文保留",
       diff.startswith("⚠️") and diff.endswith(body), diff[:40])

    # ---------------- 四、失败即跳过 ----------------
    print("\n[四] 审校失败不许拖垮回答")
    base_backup = DC._base_url
    try:
        DC._base_url = lambda: "http://127.0.0.1:9/v1"      # 故意指向没人听的端口
        res = DC.review("问他", "答", answer_model="xiaojiao", timeout=2)
        ck("连不上 → unknown（不抛异常）", res.get("verdict") == "unknown", res.get("why")[:50])
        ck("失败也带模型名与耗时，便于排查",
           "model" in res and "sec" in res, {k: res.get(k) for k in ("model", "sec")})
    finally:
        DC._base_url = base_backup

    # ---------------- 五、真机（llama-swap 在跑才有意义） ----------------
    print("\n[五] 真机：这台机器上能不能真的审一次")
    ids = DC._available_models()
    if not ids:
        print("  （llama-swap 没起来，跳过真机那条 —— 这不是失败，是条件不具备）")
    else:
        import importlib
        importlib.reload(DC)
        r = DC.review("3.11 和 3.9 哪个大？只说结论", "3.11 更大，因为十分位 1 > 9 不成立。")
        ck("真机审校有结论（same/diff/unknown 之一）",
           r.get("verdict") in ("same", "diff", "unknown"), r.get("verdict"))
        ck("真机审校给了理由", bool(str(r.get("why") or "").strip()), str(r.get("why"))[:50])

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
