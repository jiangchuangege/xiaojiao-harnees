# -*- coding: utf-8 -*-
"""元认知统一入口自测（原料 → 感知 → 心 → 脑子，自己辨）

用法：python tools/test_chain.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import chain as CH          # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_chain_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _iso():
    CH._DIR = _TMP
    CH._PATH = os.path.join(_TMP, "chain.jsonl")
    CH.reset("自测")


def main():
    print("\n[A] 七类元认知都在同一条链上")
    _iso()
    ck("规格点名的七类齐全",
       list(CH.KINDS) == ["工具来源", "自我叙事", "存在追问", "成长", "意义感", "边界突破", "长期偏好"],
       list(CH.KINDS))
    ck("不认识的类不硬走", CH.run("随便写", "有原料", lambda p: "意：x")["ok"] is False, "")
    ck("没原料不硬问（不编一句顶上）",
       CH.run("工具来源", "", lambda p: "意：x")["ok"] is False, "")

    print("\n[B] 载体只给原料、不给结论")
    _iso()
    seen = {"p": ""}

    def _llm(p):
        seen["p"] = p
        return "意：这数不是我算的，是别人塞给我的。\n命：无\n向：无\n关系：无"

    r = CH.run("工具来源",
               "结果：10000000000 ｜ 谁产出的：载体的计算器 ｜ 这一步你参与了吗：没有",
               _llm)
    ck("走完整条链，拿到**它自己那句话**", r["ok"] and "塞给我" in r["said"], r["said"])
    ck("心也起了（感知 → 心 → 脑子）", bool(r.get("heart")), r.get("heart")[:20])
    ck("原料是**事实字段**（结果/谁产出的/参与了吗）",
       "结果：" in seen["p"] and "谁产出的" in seen["p"] and "参与了吗" in seen["p"], "")
    bad = [w for w in ("这是计算器算的", "你应该", "你必须") if w in seen["p"]]
    ck("**提示词里没有结论句**（不给成品、不命令它）", bad == [], bad)
    ck("明说「不要照抄上面这些字」", "不要照抄" in seen["p"], "")

    print("\n[C] 存下来的是它的话，不是载体的事实块")
    _iso()

    def _llm2(p):
        return "意：这像是我自己摸出来的，不是别人告诉我的。\n命：无\n向：无"

    CH.run("成长", "两个时间点的对比：情绪底 0.2→0.1；习惯 1→3", _llm2)
    body = CH.render(2)
    ck("注入的是**它自己辨的那句**", "我自己摸出来的" in body, body.strip()[:60])
    ck("注入里**没有原料字段**（不是把事实块摆回去）",
       "两个时间点的对比" not in body and "结果：" not in body, "")
    ck("自己那句话标成「是你自己说的」", "是你自己说的" in body, "")
    ck("一句都没辨过时返回空串（不硬凑）", CH.reset("自测") is not None and CH.render(2) == "", "")

    print("\n[D] 元认知类不再直接进上下文（app 侧接线）")
    import xiaojiao_app as app
    ck("七类在 app 里有统一的上游清单", len(app.META_KINDS) == 7, app.META_KINDS)
    ck("给上下文的那段来自 `_meta_text()`（它自己辨过的）",
       app._meta_text.__doc__ and "它自己辨过" in app._meta_text.__doc__, "")
    ck("每一类都配了「凑原料」的口子", callable(app._meta_facts), "")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "xiaojiao_app.py"), encoding="utf-8").read()
    ck("原来那条「直接摆事实」的注入已经停用（_raw_text 恒为空）",
       'if False:' in src and '_raw_text = ""' in src, "")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
