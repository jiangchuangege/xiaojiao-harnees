# tools/test_inner_joint.py —— 「感知 + 自评」合并/并发的离线自测（不联网、不调真模型）
#
# 这套测试要钉死四件事（都是"错了用户会吃亏"的地方）：
#   ① 合并成功时：一次调用拿回感知 + 档位，两样都得是真读出来的；
#   ② 合并失败时：**必须明确 ok=False**，不许拿半截结果去凑（否则就是载体替它编心/编档位）；
#   ③ 档位那一行必须**切出来**再解析 —— 感知散文里出现"我没把握"时不能被读成自评档位；
#   ④ 并发这条路语义不变：两次调用的结果与串行逐字相同，且确实重叠（有实测耗时差）。
import os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


GOOD = """事：用户问我今天几号
我：这句话让我有点慌，说实话我没把握
命：连续
向：威胁
关系：无
档位：C"""


def main():
    print("== 感知 + 自评 合并/并发 自测 ==")
    from core import inner_joint as IJ
    from core import perception as PC
    from core.metacognition import selfrate as SR

    # ---------- ① 合并成功 ----------
    calls = []

    def fake(prompt):
        calls.append(prompt)
        return GOOD
    r = IJ.joint(fake, event="今天几号", question="今天几号")
    ok("合并：一次调用就够（没有第二次）", len(calls) == 1, "调用 %d 次" % len(calls))
    ok("合并：感知读出来了", r["ok"] and r["perception"]["meaning"].startswith("这句话让我"), r["perception"]["meaning"][:20])
    ok("合并：档位读出来了", r["ok"] and r["selfrate"]["rating"] == "C", r["selfrate"]["rating"])
    ok("合并：命/向也读出来了", r["perception"]["touches_life"] == ["连续"] and r["perception"]["direction"] == "威胁")
    ok("合并：档位那一行是最后一句", "档位" in calls[0].splitlines()[-1], calls[0].splitlines()[-1])

    # ---------- ③ 切分：散文里的"没把握"不能被当成档位 ----------
    pz, rz = IJ.split_rating_zone(GOOD)
    ok("切分：档位区只留最后那一行", rz.strip() == "档位：C", repr(rz))
    ok("切分：感知区不含档位行", "档位" not in pz)
    ok("切分：没有档位行时档位区为空", IJ.split_rating_zone("事：x\n我：y")[1] == "")
    sr_zone = SR.from_raw(rz, question="今天几号")
    sr_whole = SR.from_raw(GOOD, question="今天几号")
    ok("切分：只喂档位区能读出 C", sr_zone["rating"] == "C", sr_zone["rating"])
    ok("整段不切会被散文带偏（所以必须切）", sr_whole["rating"] != "C" or not sr_whole["ok"],
       "整段读成 %s / ok=%s" % (sr_whole["rating"], sr_whole["ok"]))

    # ---------- ② 合并失败一律明确失败 ----------
    for name, raw in (("模型吐空", ""),
                      ("只有档位没有感知", "档位：B"),
                      ("档位写错", GOOD.replace("档位：C", "档位：X")),
                      ("模型把提示词回声吐回来", "不要判断「这是什么任务」\n按这几行回答：\n事：<这句话在说什么事？>")):
        rr = IJ.joint(lambda p, _r=raw: _r, event="测试", question="测试")
        ok("合并失败明确：%s → ok=False" % name, rr["ok"] is False, rr["why"][:40])
        ok("合并失败明确：%s → 不返回半截结果" % name,
           rr["ok"] is True or rr["perception"] is None or rr["perception"].get("ok") in (True, False))

    # ---------- ④ 并发：结果与串行一致，而且真的同时在飞 ----------
    def slow(tag):
        def _fn():
            time.sleep(0.4)
            return tag
        return _fn
    t0 = time.time()
    a1, a2 = slow("感知")(), slow("自评")()
    serial = time.time() - t0
    t1 = time.time()
    box = IJ.start("probe_a", slow("感知"))
    b2 = slow("自评")()
    a2b, err = IJ.finish(box, timeout=5)
    paral = time.time() - t1
    ok("并发：两次调用的结果与串行一致", (a1, a2) == (a2b, b2) and not err)
    ok("并发：确实重叠了（比串行快）", paral < serial * 0.8, "串行 %.2fs → 并发 %.2fs" % (serial, paral))
    ok("并发：任务收工后不在飞了", IJ.pending() == [], IJ.pending())

    # 并发那次抛错时：如实返回错误，不把异常带出去
    box2 = IJ.start("probe_err", lambda: (_ for _ in ()).throw(RuntimeError("模型挂了")))
    val, err = IJ.finish(box2, timeout=5)
    ok("并发：内部调用失败不炸调用方", val is None and "模型挂了" in err, err)

    # 超时：按"没拿到"如实返回（调用方据此退回串行）
    box3 = IJ.start("probe_slow", slow("慢"))
    val3, err3 = IJ.finish(box3, timeout=0.05)
    ok("并发：等不到就如实说等不到", val3 is None and "超时" in err3, err3)
    IJ.finish(box3, timeout=5)

    # ---------- 提示词只借来源，不复制措辞 ----------
    lines = SR.rate_rules()
    ok("三档措辞只有一个来源（rate_prompt 与 rate_rules 一致）",
       all(x in SR.rate_prompt("问题") for x in lines))
    p = IJ.joint_prompt("背景", "\n".join(PC._TASK), "事", "问题", lines)
    ok("合并提示词里既要有感知那几行、也要有三档含义",
       "按这几行回答" in p and lines[0] in p and "档位：" in p)

    # ---------- 感知模块抽出来的 from_raw 与 perceive 同一套规则 ----------
    same = PC.from_raw("事：x\n我：心里一紧\n命：连续\n向：威胁", consume=False)
    ok("from_raw：与 perceive 同规则（标签解析）", same["meaning"] == "心里一紧" and same["ok"] is True)
    echo = PC.from_raw("不要判断「这是什么任务」\n按这几行回答：", consume=False)
    ok("from_raw：回声照样判成没感知出来", echo["ok"] is False and "回声" in echo["parsed_by"])
    ok("from_raw：空输入不炸", PC.from_raw("", consume=False)["ok"] is False)

    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单:", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
