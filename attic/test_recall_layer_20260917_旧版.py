# -*- coding: utf-8 -*-
"""画像召回层自测（**静态，不需要模型、不需要服务，可进 CI**）

【为什么要有它】
    `xiaojiao_recall.py --selftest` 要真调本地 4B（10 条问句 ≈ 100 次调用），CI 上跑不了。
    但这一层里**最容易悄悄坏掉的不是模型那部分，是死规矩那部分**：
      · 10 路血管被砍成几路（越改越少，没人发现）
      · 权重/门槛被顺手改掉（4 路规则 1.0、6+1 路模型 0.5、纯模型票要 4 票…）
      · system 模板被加了"额外指令"（规格：一个字都不许改）
      · 画像少写 triggers / scope（上一版就是这么把两路血管废掉的）
      · 触发词里混进"看/吃/喝"这类单字动词（万能词，会到处乱命中）
    这些**全部可以离线断言**，所以放 CI 里钉死。

运行：python tools/test_recall_layer.py
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_recall as R  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _fake_recall(votes):
    """用**假血管**跑投票：把"每一路投给谁、是规则票还是模型票"写死，
    验的是**计票与门槛**，不碰模型。

    `votes` 是 10 个 `(真实索引 或 None, 权重)`。
    ⚠️ 别再用"前 3 路算规则票"这种位置假设 —— 第一版就是这么写错的：
    我以为第 9 路是规则票，其实按位置它拿的是 0.5，于是"第二条够不够"那条断言判错了对象。
    """
    real = R.VESSELS
    fake = []
    for i, (idx, w) in enumerate(votes):
        fake.append(("fake%d" % i, (lambda q, order, _i=idx: _i), w))
    R.VESSELS = tuple(fake)
    try:
        return R.recall("测试问句", verbose=False)
    finally:
        R.VESSELS = real


def main():
    print("一、血管数量与权重（规格：10 路 = 规则 + 模型，权重 1.0 / 0.5）")
    names = [v[0] for v in R.VESSELS]
    ck("一共 10 路", len(R.VESSELS) == 10, len(R.VESSELS))
    ck("规则血管 3 路（v1_trigger / v2_type_first / v3_scope）",
       [n for n, f, w in R.VESSELS if w == R.W_RULE] == ["v1_trigger", "v2_type_first", "v3_scope"],
       [n for n, f, w in R.VESSELS if w == R.W_RULE])
    ck("模型血管 7 路（v4~v10，规格里那 7 个问法一个不少）",
       names[3:] == ["v4_direct", "v5_needed", "v6_aspect", "v7_temp", "v8_multi",
                     "v9_archive", "v10_understand"], names[3:])
    ck("规则票权重 = 1.0", R.W_RULE == 1.0, R.W_RULE)
    ck("模型票权重 = 0.5", R.W_MODEL == 0.5, R.W_MODEL)
    ck("v7 用 temperature=0.7", R.V7_TEMPERATURE == 0.7, R.V7_TEMPERATURE)
    ck("模型血管 max_tokens=64", R.MODEL_MAX_TOKENS == 64, R.MODEL_MAX_TOKENS)
    ck("模型血管默认 temperature=0.0", R.MODEL_TEMPERATURE == 0.0, R.MODEL_TEMPERATURE)

    print("二、门槛与取数（规格：2 票 + 1.0 / 纯模型 4 票 / 第二条 0.6 倍 / 最多 2 条）")
    ck("有规则票门槛 votes>=2", R.NEED_RULE_VOTES == 2, R.NEED_RULE_VOTES)
    ck("有规则票门槛 weight>=1.0", R.NEED_RULE_WEIGHT == 1.0, R.NEED_RULE_WEIGHT)
    ck("纯模型票门槛 votes>=4", R.NEED_MODEL_VOTES == 4, R.NEED_MODEL_VOTES)
    ck("第二条比例 0.6", R.SECOND_RATIO == 0.6, R.SECOND_RATIO)
    ck("最多返回 2 条", R.TOP_N == 2, R.TOP_N)

    print("三、计票真的按门槛走（用假血管验，不碰模型）")
    R_, M_ = R.W_RULE, R.W_MODEL
    # 3 路规则全投 0 → w=3.0 v=3，有规则票，过门槛
    got = _fake_recall([(0, R_), (0, R_), (0, R_)] + [(None, R_) for _ in range(7)])
    ck("规则票 3/3 → 召回 1 条", len(got) == 1 and got[0]["_idx"] == 0,
       [(g["_idx"], g["_weight"], g["_votes"]) for g in got])
    ck("它的 weight=3.0 votes=3", got and got[0]["_weight"] == 3.0 and got[0]["_votes"] == 3,
       got and (got[0]["_weight"], got[0]["_votes"]))
    # 只有 1 路规则投 0 → votes=1 < 2 → 不过门槛（"一条规则说了不算"）
    got = _fake_recall([(0, R_)] + [(None, R_) for _ in range(9)])
    ck("只有 1 路规则票 → 不给（votes<2）", got == [], [(g["_idx"], g["_votes"]) for g in got])
    # 1 路规则 + 1 路模型 → votes=2、weight=1.5 → 过门槛
    got = _fake_recall([(0, R_), (0, M_)] + [(None, R_) for _ in range(8)])
    ck("规则 1 票 + 模型 1 票 → 过门槛（v=2, w=1.5）",
       len(got) == 1 and got[0]["_weight"] == 1.5 and got[0]["_votes"] == 2,
       [(g["_idx"], g["_weight"], g["_votes"]) for g in got])
    # 纯模型票只有 3 票 → 不给（防同源模型假多数）
    got = _fake_recall([(None, R_)] * 3 + [(1, M_), (1, M_), (1, M_)] + [(None, M_)] * 4)
    ck("纯模型票 3 票 → 不给（<4）", got == [], [(g["_idx"], g["_votes"]) for g in got])
    # 纯模型票 4 票 → 给
    got = _fake_recall([(None, R_)] * 3 + [(1, M_)] * 4 + [(None, M_)] * 3)
    ck("纯模型票 4 票 → 给 1 条", len(got) == 1 and got[0]["_idx"] == 1,
       [(g["_idx"], g["_weight"], g["_votes"]) for g in got])
    # 第二条 weight 必须 >= 第一条 × 0.6：第一条 3.0，第二条 1.0（2 模型票）→ 1.0 < 1.8 → 只 1 条
    got = _fake_recall([(0, R_), (0, R_), (0, R_), (2, M_), (2, M_)] + [(None, M_)] * 5)
    ck("第二条太弱（1.0 < 3.0×0.6）→ 只返回 1 条", len(got) == 1,
       [(g["_idx"], g["_weight"]) for g in got])
    # 第二条 2.0（1 规则 + 2 模型）>= 1.8 → 返回 2 条
    got = _fake_recall([(0, R_), (0, R_), (0, R_), (2, M_), (2, M_), (2, R_)]
                       + [(None, M_)] * 4)
    ck("第二条够（2.0 >= 1.8）→ 返回 2 条，且第一条在前",
       len(got) == 2 and got[0]["_idx"] == 0 and got[1]["_idx"] == 2,
       [(g["_idx"], g["_weight"]) for g in got])

    print("四、画像四条字段一个都不能少")
    for i, p in enumerate(R.PROFILES):
        miss = [k for k in ("text", "type", "triggers", "scope") if k not in p]
        ck("第 %d 条四字段齐全（%s）" % (i + 1, str(p.get("text"))[:16]), not miss, miss)
    ck("type 都在 状态/偏好/约束/背景 四类里",
       all(p.get("type") in R.TYPES for p in R.PROFILES),
       sorted({p.get("type") for p in R.PROFILES}))
    ck("triggers 都是非空 list", all(isinstance(p.get("triggers"), list) and p["triggers"]
                                 for p in R.PROFILES))
    ck("scope 都非空", all(str(p.get("scope") or "").strip() for p in R.PROFILES))

    print("五、触发词里不许有单字动词（万能词会到处乱命中）")
    bad = [(p["text"][:14], t) for p in R.PROFILES for t in p["triggers"]
           if t in R.STOP_TRIGGERS]
    ck("没有触发词落在 STOP_TRIGGERS 里", not bad, bad)
    ck("STOP_TRIGGERS 就是规格给的那 16 个字",
       R.STOP_TRIGGERS == {"看", "吃", "喝", "玩", "听", "写", "读", "买", "去", "走",
                           "做", "学", "用", "说", "讲"}, sorted(R.STOP_TRIGGERS))

    print("六、命中判据真的会挡单字动词")
    _want = [p["text"] for p in R.PROFILES if "代码" in (p.get("triggers") or [])]
    hit = [p["text"] for p in R.PROFILES
           if R._hits(R.PROFILES.index(p), "帮我看看这段代码") > 0]
    ck("「帮我看看这段代码」只命中含『代码』那条，不会因为『看』乱命中",
       hit == _want, hit)

    print("七、system 模板：一个字都不许改")
    with_one = R.build_system([{"text": "用户对花生严重过敏，绝对不能吃花生"}])
    ck("有印象时模板完全一致",
       with_one == ("你是小焦，用户的本地 AI 伙伴。\n\n"
                    "关于这个人，你手上有的信息：\n"
                    "- 用户对花生严重过敏，绝对不能吃花生\n\n"
                    "自然地跟他聊。"), repr(with_one))
    ck("无印象时模板完全一致",
       R.build_system([]) == "你是小焦，用户的本地 AI 伙伴。自然地聊。",
       repr(R.build_system([])))
    ck("模板里没有额外指令（像认识很久/不要编造/必须避开/约束要排除）",
       not any(k in with_one for k in ("认识很久", "不要编造", "必须避开", "要排除", "朋友")),
       with_one)
    ck("最多只列 2 条", R.build_system([{"text": "a"}, {"text": "b"}, {"text": "c"}])
       .count("- ") == 2)

    print("八、显示顺序每问一次就重新洗（防位置偏见）")
    o1 = R._shuffled_order("晚上想吃点啥", 16)
    o2 = R._shuffled_order("今天心情不好", 16)
    ck("同一个问题可复现（同样的顺序）", o1 == R._shuffled_order("晚上想吃点啥", 16))
    ck("不同问题顺序不同", o1 != o2)
    ck("是 0..15 的一个排列", sorted(o1) == list(range(16)))

    print("九、序号解析要宽容（4B 会答「第 3 条」「3、7」「3. xxx」）")
    order = list(range(16))
    ck("纯数字", R._pick_number("3", order) == 2)
    ck("带前缀", R._pick_number("第 3 条", order) == 2)
    ck("多个序号取第一个", R._pick_number("4,6,15", order) == 3)
    ck("越界不认", R._pick_number("99", order) is None)
    ck("没有数字 → None", R._pick_number("我觉得没有相关的", order) is None)

    print("十、规则血管本事（不调模型，纯规则那两路）")
    # v1 只用触发词/滑窗，不调模型 —— 这几条必须对
    for q, want in (("推荐首歌听听", "周杰伦"),
                    ("帮我看看这段代码", "后端"),
                    ("有什么好看的电影推荐", "悬疑"),
                    ("我女儿最近怎么样", "女儿"),
                    ("今天心情不好", "失恋")):
        idx = R.v1_trigger(q, R._shuffled_order(q, len(R.PROFILES)))
        txt = R.PROFILES[idx]["text"] if idx is not None else ""
        ck("v1 命中「%s」" % want, want in txt, "%s → %s" % (q, txt))

    print("十一、直连 9292（不许走 llm_chat，它会首选云端）")
    src = io.open(os.path.join(_ROOT, "xiaojiao_recall.py"), encoding="utf-8").read()
    ck("本地地址是 127.0.0.1:9292", "127.0.0.1:9292" in src, R.LOCAL_BASE)
    ck("没有 import requests/httpx（规格要求 urllib 直连）",
       "import requests" not in src and "import httpx" not in src)
    ck("没调用 llm_chat", "llm_chat(" not in src.replace("llm_chat()", ""))
    ck("没有 ThreadPoolExecutor **被用起来**（本地 4B 串行；注释里提到它不算）",
       "ThreadPoolExecutor(" not in src and "import concurrent" not in src)

    print("=" * 66)
    print("画像召回层自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
