# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""精神记忆库自测（core/spirit_memory.py）

用法：
    python tools/test_spirit_memory.py

它验的是"精神记忆"这件事到底立没立住，一共六组：
    [A] 接口形状      三类库 / 路径 / 非法 kind                    → 必须对得上
    [B] 正常存取      知识 / 方法 / 诊断经验三类各自存得进、召回得到
    [C] 拒收答案原文  超长 / 问答对结构 / 带 answer 字段            → **一条都不许放进去**
    [D] 同题判据      <0.6 分开 / >=0.6 交大脑 / 无判官保守 / 算不出
    [E] 只追加不改写  判为同题时是"不写"，不是"改写旧的"
    [F] 不污染真实库  全部写在临时目录，跑完不留痕

【为什么 [C] 是重点】
    精神记忆一旦存进答案原文，后面每一轮都会被它污染 —— 那是"记忆污染"，
    不是"学习"。所以护栏必须在代码里硬生效，不能靠注释自觉。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import spirit_memory as SM      # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_spirit_memory_")
_REAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "logs", "spirit_memory")
_REAL_SNAPSHOT = {}


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    """把落盘目录指到临时目录：本自测绝不写进真实精神记忆库。"""
    SM._DIR = _TMP


def group_a():
    print("\n[A] 接口形状")
    ck("三类库齐全", SM.KINDS == ("knowledge", "method", "diagnosis"), SM.KINDS)
    for kd in SM.KINDS:
        p = SM.path_of(kd)
        ck("path_of(%s) 指向 <dir>/%s.jsonl" % (kd, kd), bool(p) and p.endswith(kd + ".jsonl"), p)
    ck("非法 kind 返回 None（不猜、不兜底）", SM.path_of("diary") is None, SM.path_of("diary"))
    ck("同题阈值是 0.6", SM.SAME_TOPIC_THRESHOLD == 0.6, SM.SAME_TOPIC_THRESHOLD)
    for fn in ("remember", "recall", "same_topic", "should_merge", "stats", "looks_like_answer"):
        ck("导出 %s" % fn, fn in SM.__all__, "")


def group_b():
    print("\n[B] 正常存取（三类各自跑通）")
    r1 = SM.remember("knowledge", "用户偏好简短直接的回答，不喜欢客套", tags=["偏好"])
    ck("知识存进去", r1["ok"] and r1["action"] == "added", r1["action"])
    r2 = SM.remember("method", "遇到地区类问题必须先锁定同一地点再比对")
    ck("方法存进去", r2["ok"] and r2["action"] == "added", r2["action"])
    r3 = SM.remember("diagnosis", "编辑吃掉 def 行会让 ast 查不出，要用 ruff F821 兜")
    ck("诊断经验存进去", r3["ok"] and r3["action"] == "added", r3["action"])

    hits = SM.recall("用户喜欢什么样的回答", k=3)
    ck("按语义召回到知识条（不是字面匹配）", len(hits) >= 1, hits[:1])
    if hits:
        ck("召回项只给 text 素材、不给 answer",
           "text" in hits[0] and "answer" not in hits[0], sorted(hits[0].keys()))
        ck("召回按相似度降序", all(hits[i]["sim"] >= hits[i + 1]["sim"] for i in range(len(hits) - 1)),
           [h["sim"] for h in hits])
    cross = SM.recall("地点比对要注意什么", k=3, kind="method")
    ck("可按 kind 限定只查一个库", all(h["kind"] == "method" for h in cross), [h["kind"] for h in cross])
    ck("空查询返回空表", SM.recall("") == [], SM.recall(""))


def group_c():
    print("\n[C] 拒收答案原文（护栏必须硬生效）")
    r = SM.remember("knowledge", "这是一段很长的内容。" * 60)
    ck("超长被判为答案原文", r["action"] == "rejected", r["why"])
    r = SM.remember("knowledge", "问：今天天气怎么样？答：今天晴天，气温 25 度。")
    ck("问答对结构被拒", r["action"] == "rejected", r["why"])
    r = SM.remember("method", "算面积要先确认单位", answer="先统一单位再相乘")
    ck("带 answer 字段被拒（连字段一起拦）", r["action"] == "rejected", r["why"])
    r = SM.remember("method", "写代码前先看依赖", reply="先看依赖再动手写")
    ck("带 reply 字段被拒", r["action"] == "rejected", r["why"])
    r = SM.remember("diary", "今天很开心")
    ck("非法 kind 被拒", r["action"] == "rejected", r["why"])
    ck("空文本判为像答案（不存空的）", SM.looks_like_answer("") is True, "")
    ck("一句话认知不被误杀", SM.looks_like_answer("用户偏好简短直接的回答") is False, "")


def group_d():
    print("\n[D] 同题判据（0.6 这条线怎么走）")
    same, why = SM.should_merge(0.31)
    ck("0.31 < 0.6 → 明确不同题，不打扰模型", same is False and why.startswith("规则"), why)
    asked = {"n": 0}

    def judge(a, b):
        asked["n"] += 1
        return False
    same, why = SM.should_merge(0.88, llm_judge=judge, text_a="A", text_b="B")
    ck("0.88 ≥ 0.6 → 交给大脑判断", asked["n"] == 1 and same is False and why.startswith("大脑"), why)
    same, why = SM.should_merge(0.88)
    ck("0.88 无判官 → 保守当同题", same is True and why.startswith("保守"), why)

    def boom(a, b):
        raise RuntimeError("judge down")
    same, why = SM.should_merge(0.88, llm_judge=boom)
    ck("判官抛异常 → 退回保守，不抛出去", same is True and why.startswith("保守"), why)
    same, why = SM.should_merge(None)
    ck("算不出相似度 → 当作不同题分开存", same is False and why.startswith("保守"), why)

    # 同一条文本与自己的相似度应当接近 1，且与无关文本明显更低
    s_same = SM.same_topic("用户偏好简短直接的回答", "用户偏好简短直接的回答")
    s_diff = SM.same_topic("用户偏好简短直接的回答", "今天股市大涨，成交量创下新高")
    ck("自身相似度 ≈ 1", s_same is not None and s_same > 0.99, s_same)
    ck("无关文本相似度明显更低", s_diff is not None and s_diff < s_same, s_diff)


def group_e():
    print("\n[E] 只追加不改写（历史不可篡改）")
    p = SM.path_of("knowledge")
    before = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    r = SM.remember("knowledge", "用户偏好简短直接的回答，不喜欢客套")
    after = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    ck("同题第二次判为 duplicate", r["action"] == "duplicate", r["why"])
    ck("判为 duplicate 时文件一字未增（不改写旧的）", before == after, "%d → %d 字节" % (len(before), len(after)))
    lines = [x for x in after.split("\n") if x.strip()]
    ck("落盘是 JSONL：一行一条", all(x.strip().startswith("{") for x in lines), "%d 行" % len(lines))


def group_f():
    print("\n[F] 统计与不污染真实库")
    st = SM.stats()
    ck("stats 覆盖三类库", sorted(st["kinds"].keys()) == sorted(SM.KINDS), sorted(st["kinds"].keys()))
    ck("total 等于三类之和", st["total"] == sum(v["count"] for v in st["kinds"].values()), st["total"])
    ck("本次全部写在临时目录", os.path.abspath(st["dir"]) == os.path.abspath(_TMP), st["dir"])
    # 【为什么不能断言"真实库目录不存在"】精神记忆在真实对话里本来就该增长 ——
    # 服务跑起来之后 `logs/spirit_memory/` 里会有记录（实测 `method.jsonl` 已有一条
    # 来源标为「对话自动提炼」的方法）。断言"目录不存在"会在功能**正常工作时**反而变红。
    # 正确的判据是：**本自测有没有动过真实库** —— 跑之前拍快照，跑完逐文件比对。
    after = _snapshot(_REAL_DIR)
    ck("真实库未被本自测改动（快照比对）", after == _REAL_SNAPSHOT,
       "跑前 %d 个文件 / 跑后 %d 个文件" % (len(_REAL_SNAPSHOT), len(after)))


def _snapshot(d):
    """拍一份目录快照：{文件名: 字节数}。用来证明本自测没动过真实库。"""
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            out[fn] = os.path.getsize(p)
    return out


def main():
    global _REAL_SNAPSHOT
    _isolate()
    _REAL_SNAPSHOT = _snapshot(_REAL_DIR)
    print("小焦 · 载体层 · 精神记忆库自测（存知识，不存答案）")
    print("模块：%s" % SM.__file__)
    print("临时目录：%s" % _TMP)
    print("真实库快照（跑完必须一模一样）：%s" % (_REAL_SNAPSHOT or "（还不存在，正常）"))
    print("=" * 100)
    for g in (group_a, group_b, group_c, group_d, group_e, group_f):
        g()

    print("\n" + "=" * 100)
    if _FAILED:
        print("❌ 失败的条目：%s" % "、".join(_FAILED))
    print("通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    print("=" * 100)
    shutil.rmtree(_TMP, ignore_errors=True)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    sys.exit(main())
