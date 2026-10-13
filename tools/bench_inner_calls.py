# tools/bench_inner_calls.py —— 「感知 + 自评」串行 / 并发 / 合并 三种走法的实测(要大脑在跑)
#
# 为什么要单独量：用户体感「回复好慢」，我提出"并发 + 合并"能省时间 ——
#   那就得拿真模型量出来，而不是拿"设计上应该更快"当结论。
# 用法：python tools/bench_inner_calls.py [重复次数，默认3]
# 前提：llama-swap 在跑（大脑空闲，别和视频生成抢显卡）
import os, sys, json, time, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "video_service"))

import xiaojiao_app as X            # noqa: E402  —— 复用它真实的提示词与调用路径
from core import inner_joint as IJ  # noqa: E402
from core import perception as PC   # noqa: E402
from core.metacognition import selfrate as SR   # noqa: E402

QUESTION = "帮我算一下 1234 乘 5678 等于多少，再说说这个数字有什么特别的地方"


def _one_mode(mode):
    """只跑一种走法（三种走法要能**轮流先跑** —— 固定顺序会把"先跑的那次吃亏/占便宜"算进结论）。"""
    doing = "空闲"
    p_in, _ = X._perceive_inputs(QUESTION)
    bg = PC.self_background(doing)
    p_task = "\n".join(PC._TASK)
    rate_lines = SR.rate_rules()
    out = {}
    if mode == "串行":
        t0 = time.time()
        per = X._perceive_event(QUESTION)
        sr = X._selfrate_now(QUESTION)
        out["秒"] = time.time() - t0
        out["感知ok"] = bool(per.get("ok"))
        out["档位"] = sr.get("rating")
    elif mode == "并发":
        t1 = time.time()
        box = IJ.start("bench_selfrate", lambda: X._selfrate_now(QUESTION))
        per = X._perceive_event(QUESTION)
        val, err = IJ.finish(box, timeout=120)
        out["秒"] = time.time() - t1
        out["感知ok"] = bool(per.get("ok"))
        out["档位"] = (val or {}).get("rating") if val else ("失败:" + err)
    else:
        t2 = time.time()
        jr = IJ.joint(X._perceive_llm, background=bg, perception_task=p_task,
                      event=p_in, question=QUESTION, rate_lines=rate_lines,
                      rate_context=X._eyc_now(), doing=doing)
        out["秒"] = time.time() - t2
        out["ok"] = bool(jr.get("ok"))
        out["原因"] = jr.get("why")
        out["档位"] = (jr.get("selfrate") or {}).get("rating")
        out["感知"] = (jr.get("perception") or {}).get("meaning", "")[:24]
    return out


MODES = ("串行", "并发", "合并")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print("=" * 78)
    print("一轮问答里「感知 + 自评」的三种走法实测 ｜ 重复 %d 次（每次换一种先跑，去掉先后偏差）" % n)
    print("问题：%s" % QUESTION)
    print("=" * 78)
    rows = []
    for i in range(n):
        order = MODES[i % len(MODES):] + MODES[:i % len(MODES)]      # 轮流先跑
        r = {}
        for mode in order:
            r[mode] = _one_mode(mode)
        rows.append(r)
        print("\n第 %d 次（先跑「%s」）：" % (i + 1, order[0]))
        for mode in MODES:
            d = r[mode]
            extra = ""
            if mode == "合并":
                extra = " 成功=%s 感知=%s" % (d.get("ok"), d.get("感知"))
                if not d.get("ok"):
                    extra += " (%s)" % str(d.get("原因"))[:40]
            print("  %s %.2f 秒   感知ok=%s 档位=%s%s" % (mode, d["秒"], d.get("感知ok"), d.get("档位"), extra))
    print("\n" + "=" * 78)
    for mode in MODES:
        vals = [x[mode]["秒"] for x in rows]
        print("  %s：中位 %.2f 秒 ｜ 平均 %.2f 秒 ｜ 各次 %s"
              % (mode, statistics.median(vals), statistics.mean(vals),
                 " ".join("%.2f" % v for v in vals)))
    if rows:
        print("  串行 → 并发：中位省 %.2f 秒" % (statistics.median([x["串行"]["秒"] for x in rows])
                                              - statistics.median([x["并发"]["秒"] for x in rows])))
        print("  串行 → 合并：中位省 %.2f 秒" % (statistics.median([x["串行"]["秒"] for x in rows])
                                              - statistics.median([x["合并"]["秒"] for x in rows])))
    okn = sum(1 for x in rows if x["合并"].get("ok"))
    print("  合并成功率：%d/%d" % (okn, len(rows)))
    print("  档位一致情况（串行 / 并发 / 合并）：%s"
          % "、".join("%s/%s/%s" % (x["串行"].get("档位"), x["并发"].get("档位"), x["合并"].get("档位")) for x in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
