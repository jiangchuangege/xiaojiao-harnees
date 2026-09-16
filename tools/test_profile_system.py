# -*- coding: utf-8 -*-
"""画像系统自测（**静态，不需要模型、不需要服务，可进 CI**）

【为什么要有它】
    `xiaojiao_profile.py --selftest` 要真调本地 4B（写入 5 条 + 召回 5 条 ≈ 80 次调用），CI 跑不了。
    这一层里最容易**悄悄坏掉**的恰恰是能离线断言的那些：

      · 10 路血管被砍少（或 7 路模型血管退化成同一个问题 —— 规格明令禁止）
      · 权重/门槛被顺手改掉（规则 1.0 / 模型 0.5 / 规则票 2 票 + 1.0 / 纯模型 4 票 / 第二条 0.6）
      · system 模板被加"额外指令"（规格：一个字都不许改，且点名了三个不许改的词）
      · **解析退化成严格 JSON**（规格明令：必须宽松正则；严格解析会让画像一条都存不下来）
      · 画像少 triggers / scope；触发词里混进单字动词
      · 判据方向反了（"不要记"被当成"要记"、"不值得记"被当成"值得记"）

运行：python tools/test_profile_system.py
"""
import io
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_profile as P  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _fake_recall(votes):
    """用假血管验**计票与门槛**（不碰模型）。`votes` 是 10 个 (索引 或 None, 权重)。"""
    real = P.VESSELS
    P.VESSELS = tuple(("fake%d" % i, (lambda q, order, _i=idx: _i), w)
                      for i, (idx, w) in enumerate(votes))
    try:
        return P.recall("测试问句", profiles=[{"text": "t%d" % i, "type": "背景",
                                             "triggers": [], "scope": "s"}
                                            for i in range(16)])
    finally:
        P.VESSELS = real


def main():
    print("一、10 路血管：3 规则 + 7 模型，7 个问题互不相同")
    ck("一共 10 路", len(P.VESSELS) == 10, len(P.VESSELS))
    ck("规则 3 路", [n for n, f, w in P.VESSELS if w == P.W_RULE]
       == ["v1_trigger", "v2_type_first", "v3_scope_first"])
    ck("模型 7 路", len([n for n, f, w in P.VESSELS if w == P.W_MODEL]) == 7)
    ck("7 个模型问题**互不相同**（不许都问「哪条最相关」）",
       len(set(P.MODEL_QUESTIONS.values())) == 7, len(set(P.MODEL_QUESTIONS.values())))
    ck("7 个问题里没有重复措辞（两两不互为子串）",
       not any(a != b and a in b for a in P.MODEL_QUESTIONS.values()
               for b in P.MODEL_QUESTIONS.values()))
    ck("权重：规则 1.0 / 模型 0.5", P.W_RULE == 1.0 and P.W_MODEL == 0.5)

    print("二、门槛与取数（规格给定，一个数都不许动）")
    ck("有规则票 votes>=2 且 weight>=1.0",
       P.NEED_RULE_VOTES == 2 and P.NEED_RULE_WEIGHT == 1.0)
    ck("纯模型票 votes>=4", P.NEED_MODEL_VOTES == 4)
    ck("第二条 0.6 倍", P.SECOND_RATIO == 0.6)
    ck("最多 2 条", P.TOP_N == 2)

    print("三、计票与门槛真的按规格走（假血管）")
    R_, M_ = P.W_RULE, P.W_MODEL
    got = _fake_recall([(0, R_), (0, R_), (0, R_)] + [(None, R_)] * 7)
    ck("3 规则票 → 召回（w=3.0 v=3）", len(got) == 1 and got[0]["_weight"] == 3.0
       and got[0]["_votes"] == 3, got and (got[0]["_weight"], got[0]["_votes"]))
    got = _fake_recall([(0, R_)] + [(None, R_)] * 9)
    ck("只 1 规则票 → 不给（votes<2）", got == [])
    got = _fake_recall([(0, R_), (0, M_)] + [(None, R_)] * 8)
    ck("1 规则 + 1 模型 → 给（v=2 w=1.5）", len(got) == 1 and got[0]["_weight"] == 1.5)
    got = _fake_recall([(None, R_)] * 3 + [(1, M_)] * 3 + [(None, M_)] * 4)
    ck("纯模型 3 票 → 不给（防同源假多数）", got == [])
    got = _fake_recall([(None, R_)] * 3 + [(1, M_)] * 4 + [(None, M_)] * 3)
    ck("纯模型 4 票 → 给 1 条", len(got) == 1 and got[0]["_idx"] == 1)
    got = _fake_recall([(0, R_), (0, R_), (0, R_), (2, M_), (2, M_)] + [(None, M_)] * 5)
    ck("第二条太弱（1.0 < 3.0x0.6）→ 只 1 条", len(got) == 1)
    got = _fake_recall([(0, R_), (0, R_), (0, R_), (2, M_), (2, M_), (2, R_)]
                       + [(None, M_)] * 4)
    ck("第二条够（2.0 >= 1.8）→ 2 条且第一条在前",
       len(got) == 2 and got[0]["_idx"] == 0 and got[1]["_idx"] == 2)
    got = _fake_recall([(None, R_)] * 10)
    ck("全弃权 → 空（不硬给）", got == [])

    print("四、system 模板：一个字都不许改")
    one = P.build_system([{"text": "用户对花生严重过敏"}])
    ck("有印象分支逐字一致",
       one == ("你是小焦，用户的本地 AI 伙伴。\n\n"
               "你了解关于他的一些事：\n- 用户对花生严重过敏\n\n"
               "听他接着说。"), repr(one))
    ck("无印象分支逐字一致",
       P.build_system([]) == "你是小焦，用户的本地 AI 伙伴。自然地聊。",
       repr(P.build_system([])))
    ck("没有「记得」两个字（规格点名：会被理解成共同经历）", "记得" not in one)
    ck("没有「回应」两个字（规格点名：会让模型编内容）", "回应" not in one)
    ck("没有额外指令词（认识很久/不要编造/必须避开/要排除/朋友）",
       not any(k in one for k in ("认识很久", "不要编造", "必须避开", "要排除", "朋友")), one)
    ck("最多列 2 条",
       P.build_system([{"text": "a"}, {"text": "b"}, {"text": "c"}]).count("- ") == 2)

    print("五、宽松解析（规格：不许严格 JSON）")
    ck("标准 JSON", P.parse_meta('{"type":"约束","triggers":["海鲜","过敏"],'
                            '"scope":"饮食安全"}')
       == {"type": "约束", "triggers": ["海鲜", "过敏"], "scope": "饮食安全"})
    ck("中文冒号 + 顿号", P.parse_meta("type：偏好\ntriggers：咖啡、早上\nscope：日常饮食")
       == {"type": "偏好", "triggers": ["咖啡", "早上"], "scope": "日常饮食"})
    ck("无引号 JSON（4B 常见）", P.parse_meta("{ type: 状态, triggers: 游泳/练习, scope: 运动 }")
       == {"type": "状态", "triggers": ["游泳", "练习"], "scope": "运动"})
    ck("markdown 围栏", P.parse_meta("```json\n{\"type\":\"偏好\",\"triggers\":[\"书\"],"
                                 "\"scope\":\"阅读\"}\n```")["type"] == "偏好")
    r = P.parse_meta('{"type":"瞎写","triggers":[],"scope":""}', text="用户对海鲜过敏")
    ck("type 不在四类 → **降级为背景，不丢弃**", r["type"] == "背景", r)
    ck("triggers 全空 → 从 text 兜底（绝不返回空）",
       r["triggers"] and r["triggers"][0] in "用户对海鲜过敏", r["triggers"])
    ck("完全解析不出来 → 也能给出一条可用画像",
       P.parse_meta("", text="用户喜欢安静")["type"] == "背景")
    ck("triggers 里的单字动词被剔掉",
       "看" not in P.parse_meta('{"type":"背景","triggers":["看","代码"],"scope":"x"}')["triggers"])
    src = io.open(os.path.join(_ROOT, "xiaojiao_profile.py"), encoding="utf-8").read()
    ck("parse_meta 里没有 json.loads（不许严格 JSON 解析）",
       "json.loads" not in src.split("def parse_meta")[1].split("def make_meta")[0])

    print("六、text 后处理（2a 的收尾）")
    ck("剥「画像：」", P.clean_text("画像：用户最近在学吉他") == "用户最近在学吉他")
    ck("剥复述（取最后一个前缀之后）",
       P.clean_text("用户说：我最近在学游泳\n画像：用户最近在学游泳") == "用户最近在学游泳")
    ck("不以用户开头 → 补上", P.clean_text("最近在学游泳") == "用户最近在学游泳")
    ck("「我妈」→「用户妈妈」（不是「用户妈」）",
       P.clean_text("我妈最近身体不太好") == "用户妈妈最近身体不太好",
       P.clean_text("我妈最近身体不太好"))
    ck("「我的猫」→「用户的猫」", P.clean_text("我的猫叫团子") == "用户的猫叫团子")
    _long = P.clean_text("用户喜欢旅游去过很多国家还在学吉他每周三晚上都有课这已经超过三十个字了")
    ck("超 30 字截断", len(_long) == 30, len(_long))

    print("七、判据方向（失败必须朝「不记」）")
    ck("「要记」→ True", P._verdict_of("要记") is True)
    ck("「不记」→ False", P._verdict_of("不记") is False)
    ck("「不要记」→ False（照字面写会判成 True，这是个真坑）",
       P._verdict_of("不要记") is False)
    ck("「不值得记」→ False（它含「值得记」，否定必须先看）",
       P._verdict_of("这句话不值得记") is False)
    ck("先解释再给结论也认（「…值得长期记住。要记」）",
       P._verdict_of("这句话提到了用户的阅读兴趣，值得长期记住。要记") is True)
    ck("空输出 → False", P._verdict_of("") is False)
    ck("胡说八道 → False", P._verdict_of("今天天气不错") is False)

    print("八、画像四条字段一个都不能少")
    for i, p in enumerate(P.SEED):
        miss = [k for k in ("text", "type", "triggers", "scope") if k not in p]
        ck("种子第 %d 条四字段齐全（%s）" % (i + 1, p.get("text", "")[:14]), not miss, miss)
    ck("type 都在四类里", all(p["type"] in P.TYPES for p in P.SEED))
    ck("triggers 都非空且不含单字动词",
       all(p["triggers"] and not (set(p["triggers"]) & P.STOP_TRIGGERS) for p in P.SEED))
    ck("scope 都非空", all(str(p["scope"]).strip() for p in P.SEED))
    ck("STOP_TRIGGERS 就是规格那 16 个字",
       P.STOP_TRIGGERS == {"看", "吃", "喝", "玩", "听", "写", "读", "买", "去", "走",
                           "做", "学", "用", "说", "讲"}, sorted(P.STOP_TRIGGERS))

    print("九、存储：一个 JSON 文档，四字段原样存取")
    tmp = os.path.join(tempfile.gettempdir(), "_xj_profiles_test.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    P.save(P.SEED[:3], tmp, source="测试")
    d = P.load(tmp)
    ck("顶层字段 version/source/updated_at/profiles 齐",
       set(("version", "source", "updated_at", "profiles")) <= set(d), list(d))
    ck("写进去 3 条就读出 3 条", len(d["profiles"]) == 3, len(d["profiles"]))
    ck("四字段一条不少", all(set(("text", "type", "triggers", "scope")) <= set(r)
                        for r in d["profiles"]))
    ck("坏文件 → 空库（不抛异常、不删原文件）",
       (io.open(tmp, "w", encoding="utf-8").write("{坏") or
        P.load(tmp)["profiles"] == []))
    os.remove(tmp)
    ck("库里没文件时 load 也给空库", P.load(os.path.join(tempfile.gettempdir(),
                                                "_definitely_missing.json"))["profiles"] == [])

    print("十、重复过滤器（关卡，只出信号）")
    rows = [{"text": "用户喜欢的作家是村上春树"}]
    ck("完全相同 → 重复", P.is_duplicate("用户喜欢的作家是村上春树", rows, semantic=False)[0])
    ck("被包含 → 重复", P.is_duplicate("村上春树", rows, semantic=False)[0])
    ck("不相干 → 不重复", P.is_duplicate("用户喜欢跑步", rows, semantic=False)[0] is False)
    ck("空画像 → 当成重复（不写垃圾）", P.is_duplicate("", rows, semantic=False)[0])
    idx = P._pick_number("第 3 条", [7, 8, 9, 10])
    ck("序号解析跟随显示顺序（防位置偏见）", idx == 9, idx)
    ck("显示顺序每一问重新洗且可复现",
       P._shuffled_order("推荐本书看看", 18) == P._shuffled_order("推荐本书看看", 18)
       and P._shuffled_order("推荐本书看看", 18) != P._shuffled_order("今天心情不好", 18))

    print("十一、直连本地，不许并发（规格硬性要求）")
    # 【为什么用 AST 而不是找字符串】第一版直接 `"llm_chat(" not in src`，
    # 结果**被自己的注释判红**了（模块头注释里写着"不走 llm_chat()"）——
    # 一个检查如果连注释都当代码，它就会逼着人把注释删掉。
    # 所以这里走 AST：只看**真正被用到的名字**，注释和文档字符串一律不算。
    import ast
    tree = ast.parse(src)
    used, imported = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        elif isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    ck("地址是 127.0.0.1:9292", "127.0.0.1:9292" in src, P.LOCAL_BASE)
    ck("没有 import requests / httpx（用 urllib 直连）",
       not ({"requests", "httpx"} & imported), sorted(imported))
    ck("没有用到 llm_chat（它会首选云端）", "llm_chat" not in used, sorted(used & {"llm_chat"}))
    ck("没有用到 ThreadPoolExecutor（本地 4B 串行）",
       "ThreadPoolExecutor" not in used and "concurrent" not in imported)
    ck("写入链与召回链是两个独立函数（过滤器拒绝 != 失去记忆）",
       "def remember(" in src and "def recall(" in src)

    print("=" * 66)
    print("画像系统自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
