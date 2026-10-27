# -*- coding: utf-8 -*-
"""通用答案闸门 · 自测（离线、确定性）

钉住三件事：
  ① 挑得出"可核查的断言"（数值+单位 / 比分 / 日期 / 网址 / 路径），且不滥抓；
  ② 有依据就不标注、没依据才标注（成本不对称：误报只是多看一眼，漏报会让用户当真）；
  ③ **绝不改写正文**（只在前头加标注）。
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
    print("  通用答案闸门自测")
    print("=" * 80)
    from core import answer_gate as AG

    # ---------------- 一、挑断言 ----------------
    print("\n[一] 挑得出「可核查的断言」")
    c = AG.extract_claims("菏泽 +13°C，湿度 60%，预计 2026年7月20日 有雨")
    kinds = sorted({x["kind"] for x in c})
    ck("数值+单位被挑出来", any(x["kind"] == "数值" for x in c), [x["raw"] for x in c])
    ck("日期被挑出来", "日期" in kinds, kinds)
    ck("普通句子不会滥抓", AG.extract_claims("今天心情不错，随便聊聊") == [])
    ck("网址/路径都认",
       {x["kind"] for x in AG.extract_claims("见 https://a.com/x 与 G:\\\\dzs\\\\a.pdf")}
       >= {"网址", "路径"},
       [x["kind"] for x in AG.extract_claims("见 https://a.com/x 与 G:\\\\dzs\\\\a.pdf")])
    ck("比分认得出", any(x["kind"] == "比分" for x in AG.extract_claims("西班牙 1-0 阿根廷")))

    # ---------------- 二、有依据 / 没依据 ----------------
    print("\n[二] 有依据就不标注，没依据才标注")
    r = AG.audit("菏泽天气：阴天 +13°C", "菏泽 Overcast +13°C 湿度 60%", "菏泽天气")
    ck("材料里有 → 不标注", r["note"] == "", r)
    r2 = AG.audit("西班牙 1-0 阿根廷，2026年7月20日，第106分钟", "某站：足球新闻列表",
                  "2026世界杯谁是冠军")
    ck("材料里没有 → 强标注（≥3 处细节）",
       ("无法在本轮材料里核实" in r2["note"]) or ("没找到依据" in r2["note"]), r2["note"][:50])
    r3 = AG.audit("文件存到 G:\\\\dzs\\\\a.pdf", "", "下载")
    ck("一点材料都没有 → 明说没有可核查来源",
       "没有可核查的来源" in r3["note"], r3["note"][:40])
    ck("用户自己给的数字不算模型编的",
       AG.audit("17 乘以 23 等于 391 元", "随便什么材料", "17 乘以 23 等于 391 元")["note"] == "")
    ck("纯计算（无单位）不抓", AG.audit("17*23=391", "", "算一下")["note"] == "")

    # ---------------- 三、正文不许动 ----------------
    print("\n[三] 只在前面加标注，正文一个字不改")
    body = "西班牙 1-0 阿根廷，2026年7月20日"
    out, res = AG.apply(body, "", "谁赢了")
    ck("原文完整保留在末尾", out.endswith(body), out[-30:])
    ck("标注在前头", out.startswith("⚠️"), out[:12])
    out2, res2 = AG.apply(body, "西班牙 1-0 阿根廷 2026年7月20日", "谁赢了")
    ck("有依据时原样返回（不自我加戏）", out2 == body, out2[:30])
    ck("审计结果带比例，便于观察", isinstance(res.get("ratio"), float), res.get("ratio"))

    print("\n" + "=" * 80)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 80)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
