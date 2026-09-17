# -*- coding: utf-8 -*-
"""心带模型走 v2（`adjust_candidates` 走向量）的判据自测 —— 离线，不调大脑。

【钉的是什么】（用户规格里的三条硬性要求 + 一条我自己加的怀疑）
  ① 向量**正常**时：语义重排生效（"服务器被入侵"要压过"用户喜欢猫"）
  ② 向量**挂了**时：静默退回关键词匹配，**不抛异常、不放弃重排**（要求 3）
  ③ 没有心（`_q` 空）但有关键词时：仍走关键词那条路
  ④ 既没心也没关键词：如实返回"方向中性，未重排"，**候选一个字不动**
  ⑤ 候选为空：如实返回"无候选，未重排"
  ⑥ **我怀疑的一处**：候选里只要有一条**空文本**，`embed("")` 返回 None →
     `zip(v, None)` 抛 TypeError → 被外层 except 吃掉 → **整批**静默退回关键词。
     一条坏候选把整批的向量排序废掉 —— 这条要钉出来（是/不是，都用实测说话）。

运行：python tools/test_thinking_loop_vector.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import psyche                    # noqa: E402
import core.thinking_loop as TL            # noqa: E402
from core import embedder as EM            # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:160]) if info else ""))


CANDS = [
    {"text": "用户喜欢猫，养了一只橘猫"},
    {"text": "上次服务器被入侵是弱密码导致的"},
    {"text": "用户喜欢周杰伦的歌"},
    {"text": "防火墙规则需要定期检查"},
    {"text": "用户最近在学游泳"},
]


def _heart():
    psyche.clear()
    psyche.arise({"meaning": "有人闯进了我的房间", "direction": "威胁",
                  "touches_life": ["世界", "关系"]}, event="服务器被入侵")


def main():
    psyche.start()
    print("一、向量正常：语义重排要生效（要求：'服务器被入侵' 排前面）")
    _heart()
    ordered, rec = TL.adjust_candidates([dict(c) for c in CANDS])
    texts = [c["text"] for c in ordered]
    ck("「服务器被入侵」排到第 1 位", texts[0].startswith("上次服务器被入侵"), texts)
    ck("moved 非空", bool(rec.get("moved")), rec.get("moved"))
    ck("无关的（猫/周杰伦/游泳）都被压到后面",
       texts.index("用户喜欢猫，养了一只橘猫") >= 3, texts)

    print("\n二、向量**挂了**：静默退回关键词，不许抛异常、不许不重排（硬性要求 3）")
    _real = EM.embed
    EM.embed = lambda t: (_ for _ in ()).throw(RuntimeError("向量后端炸了"))
    try:
        _heart()
        # 候选里放一条**含关键词**的（心的关键词表里有"危险/风险/失败"这类），
        # 这样关键词那条路有事可做 —— 才能看出"它还在重排"
        kw_cands = [{"text": "用户喜欢猫"}, {"text": "这是一条危险的东西"}, {"text": "用户学游泳"}]
        ordered2, rec2 = None, None
        _raised = ""
        try:
            ordered2, rec2 = TL.adjust_candidates([dict(c) for c in kw_cands])
        except Exception as e:
            _raised = repr(e)
        ck("向量炸了也不抛异常", _raised == "", _raised)
        ck("仍然给出了重排结果（没中途放弃）",
           isinstance(ordered2, list) and len(ordered2) == len(kw_cands), ordered2)
        ck("退回关键词那条路（含「危险」的排到前面）",
           ordered2 and ordered2[0]["text"] == "这是一条危险的东西", ordered2)
    finally:
        EM.embed = _real

    print("\n三、没有心（_q 空）但有关键词：仍走关键词")
    # ⚠️ 第一版这里用 `psyche.clear()` 造"没有心"，**测试写错了** —— 实测 `clear()` 只清
    #    "此刻的感受"（`_LIVE`），**不清心也不清 state**：清完 colors().query 还是原话、
    #    bias().state 还是"紧"。所以那两节实际测的还是向量那条路。这里改成**打桩**（如实标注）。
    _real_colors, _real_bias = TL._psyche.colors, TL._psyche.bias
    TL._psyche.colors = lambda: {"query": "", "heart": "", "direction": "", "state": "平"}
    TL._psyche.bias = lambda state=None: {"state": "紧", "keywords": ["风险", "危险", "失败"],
                                          "note": "打桩：只有关键词、没有心"}
    try:
        ordered3, rec3 = TL.adjust_candidates([{"text": "这是一条危险的东西"}, {"text": "用户喜欢猫"}])
        ck("关键词仍能重排", ordered3[0]["text"] == "这是一条危险的东西", ordered3)
        ck("如实写明状态与关键词", "state" in rec3 and "keywords" in rec3, rec3)

        print("\n四、既没心也没关键词：候选一个字不动")
        TL._psyche.bias = lambda state=None: {"state": "平", "keywords": [], "note": "方向中性"}
        _src = [dict(c) for c in CANDS]
        ordered4, rec4 = TL.adjust_candidates(_src)
        ck("原样返回", [c["text"] for c in ordered4] == [c["text"] for c in CANDS],
           [c["text"] for c in ordered4])
        ck("如实标「方向中性，未重排」", "方向中性" in str(rec4.get("note")), rec4.get("note"))
    finally:
        TL._psyche.colors, TL._psyche.bias = _real_colors, _real_bias

    print("\n五、候选为空")
    _o, rec5 = TL.adjust_candidates([])
    ck("如实标「无候选，未重排」", "无候选" in str(rec5.get("note")), rec5.get("note"))

    print("\n六、我怀疑的那一处：**一条空文本候选会不会把整批向量排序废掉**")
    _heart()
    with_empty = [dict(c) for c in CANDS] + [{"text": ""}]
    ordered6, rec6 = TL.adjust_candidates(with_empty)
    t6 = [c["text"] for c in ordered6]
    still_vec = t6 and t6[0].startswith("上次服务器被入侵")
    print("     实测结果：%s" % ("向量仍然生效（我的怀疑不成立）" if still_vec
                            else "**整批退回了关键词** —— 我的怀疑成立"))
    ck("【如实记录】空文本候选不会废掉整批向量排序 —— 若失败即证明有隐患",
       bool(still_vec), t6[:3])

    psyche.stop()
    print("\n" + "=" * 66)
    print("心带模型走 v2 判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
