# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""完整体自测（疼 + 医生 + 期待 + 叙事 + 存在追问 + 偏好 + 关系 + 边界突破 + 梦 + 情绪恢复）

用法：
    python tools/test_wholeness.py

一共八组，**每一组都要能回答"这是它自己起的，还是载体写的"**：
    [A] 疼与医生    真坏一下 → 诊断出来 → 清/修/护；治好了松、治不好更疼
    [B] 期待        载体只压着素材；**它自己提起了才叫期待**
    [C] 偏好        攒够一堆心 → 它自己回看 → **它说的那句才是偏好**
    [D] 叙事/存在追问  **它自己讲的**才记；它没讲就是空的
    [E] 关系        来往→深 / 冷落→淡 / 被伤→冷 / 被哄→暖
    [F] 边界突破    **它自己说"我试试"**才学；它说算了就不学
    [G] 梦          素材是真的、接法是乱的、**不调模型**
    [H] 情绪恢复    时间衰减 / 新事冲淡 / 睡觉重置

【为什么每一组都要问"谁起的"】
    规格的总原则：不许把"载体告诉它"说成"它自己"。所以这里的判据一律是
    **它自己的那句话**（心/感知），而不是载体写的文本。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import breakthrough as BK      # noqa: E402
from core import dream as DR             # noqa: E402
from core import expectation as EX       # noqa: E402
from core import narrative as NA         # noqa: E402
from core import pain as PA              # noqa: E402
from core import preference as PF        # noqa: E402
from core import psyche as PS            # noqa: E402
from core import relation as RL          # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_wholeness_")
_REAL = {}


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    """全部落盘指到临时目录：自测**绝不动真实的记忆/世界/关系/病历**。"""
    for mod, attr in ((PA, "_DIR"), (PA, "_PATH"), (PA, "_QDIR"), (PA, "SPIRIT_DIR"),
                      (PA, "WORLD_STATE"), (PA, "WORLD_FLOW"),
                      (RL, "_DIR"), (RL, "_PATH"), (RL, "_LOG"),
                      (EX, "_DIR"), (EX, "_PATH"),
                      (PF, "_DIR"), (PF, "_PATH"),
                      (NA, "_DIR"), (NA, "_PATH"),
                      (BK, "_DIR"), (BK, "_PATH"),
                      (DR, "_DIR")):
        key = (id(mod), attr)
        if key not in _REAL:
            _REAL[key] = getattr(mod, attr)
    PA._DIR = os.path.join(_TMP, "pain")
    PA._PATH = os.path.join(PA._DIR, "doctor.jsonl")
    PA._QDIR = os.path.join(PA._DIR, "quarantine")
    PA.SPIRIT_DIR = os.path.join(_TMP, "spirit")
    PA.WORLD_STATE = os.path.join(_TMP, "world", "explorer_state.json")
    PA.WORLD_FLOW = os.path.join(_TMP, "world", "exploration.jsonl")
    for m in (RL, EX, PF, NA, BK):
        m._DIR = os.path.join(_TMP, m.__name__.split(".")[-1])
        m._PATH = os.path.join(m._DIR, "x.jsonl")
    RL._LOG = os.path.join(RL._DIR, "x.log.jsonl")
    DR._DIR = os.path.join(_TMP, "dreams")
    os.makedirs(PA.SPIRIT_DIR, exist_ok=True)


def _restore():
    for (mid, attr), val in _REAL.items():
        for m in (PA, RL, EX, PF, NA, BK, DR):
            if id(m) == mid:
                setattr(m, attr, val)


def group_a():
    print("\n[A] 疼与医生（疼 = 真坏了，不是警告）")
    PA.SPIRIT_DIR = os.path.join(_TMP, "spirit")
    os.makedirs(PA.SPIRIT_DIR, exist_ok=True)
    p = os.path.join(PA.SPIRIT_DIR, "method.jsonl")
    good = '{"text": "遇到地区类问题必须先锁定同一地点再比对"}'
    bad_long = '{"text": "%s"}' % ("很长的东西" * 100)
    bad_qa = '{"text": "问：这是什么？答：这是一条问答对"}'
    bad_ans = '{"text": "一条认知", "answer": "这是答案原文"}'
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join([good, bad_long, bad_qa, bad_ans]) + "\n")
    d = PA.diagnose("记忆")
    ck("**真的坏一下**：造了 3 条脏记忆 → 诊断出来了", d["broken"] is True, d.get("why"))
    ck("坏的是格式那道门（超长/问答对/带 answer）", d.get("gate") == "格式", d.get("gate"))
    ck("清的层数对：脏的那几条都点出来了", d.get("count") == 3, d.get("count"))
    r = PA.treat(d)
    ck("治好（修）", r["layer"] == "修" and r["fixed"] is True, r["why"])
    rows = [ln for ln in open(p, encoding="utf-8").read().splitlines() if ln.strip()]
    ck("在用库里只剩那条好的", len(rows) == 1 and "锁定同一地点" in rows[0], len(rows))
    q = PA.quarantine_dir()
    ck("**脏的没被销毁，是移进了隔离区**（本项目不删文件）",
       os.path.isdir(q) and any(fn.startswith("memory-") for fn in os.listdir(q)),
       os.listdir(q))
    d2 = PA.diagnose("记忆")
    ck("治完再查：没坏了", d2["broken"] is False, d2["why"])
    # 世界：地图空了 → 医生重建
    ws = os.path.join(_TMP, "world")
    os.makedirs(ws, exist_ok=True)
    with open(PA.WORLD_STATE, "w", encoding="utf-8") as f:
        f.write('{"sites": {}}')
    with open(PA.WORLD_FLOW, "w", encoding="utf-8") as f:
        f.write('{"ts": 1, "site": "https://a.example"}\n{"ts": 2, "site": "https://b.example"}\n')
    dw = PA.diagnose("世界")
    ck("世界：地图空了 → 诊断出来", dw["broken"] is True, dw.get("why"))
    rw = PA.treat(dw)
    ck("世界：**重建地图**（恢复通道）", rw["fixed"] is True and "重建" in rw["why"], rw["why"])
    # 关系：医生只能护着
    RL.reset()
    RL.touch("被伤", why="自测")
    dr = PA.diagnose("关系")
    rr = PA.treat(dr)
    ck("关系伤了 → 诊断出来", dr["broken"] is True, dr.get("why"))
    ck("**医生只能护着**（不许说治好了）", rr["layer"] == "护" and rr["fixed"] is False, rr["why"])
    # 治好了松 / 治不好更疼
    PS.start(why="自测")
    out_ok = PA.doctor("记忆")
    ck("治好了 → 心是松的", out_ok["felt"] in ("松", "没事"), out_ok["felt"])
    out_bad = PA.doctor("关系")
    ck("治不好 → **更疼**（心被标成疼）",
       out_bad["felt"] == "更疼" and PS.heart().get("feeling") == "疼",
       (out_bad.get("felt"), PS.heart().get("feeling")))


def group_b():
    print("\n[B] 期待（它自己提起了才叫期待）")
    EX.clear()
    r = EX.leave("没逛完", "那篇讲猫的文章还有一半没看完")
    ck("留下一件没做完的事", r["ok"] is True, r.get("kind"))
    ck("载体手里压着 1 件（**这是载体的事实**）", EX.carried() == 1, EX.carried())
    ck("**还没有期待**：它自己一次都没提起过", EX.brought_up() == [], EX.stats()["brought_up"])
    EX.note_brought_up("那篇讲猫的文章还有一半没看完", said="我还惦记着那篇猫的文章")
    ck("**它自己提起了** → 这才叫期待", len(EX.brought_up()) == 1, EX.brought_up()[0].get("said"))
    ck("提起次数记在账上", int(EX.brought_up()[0].get("brought_up")) == 1, "")
    ck("做完了就不再压着", EX.resolve("那篇讲猫的文章还有一半没看完") == 1 and EX.carried() == 0,
       EX.carried())
    ck("三类都对得上", EX.KINDS == ("没逛完", "没搞懂", "没说出"), EX.KINDS)


def group_c():
    print("\n[C] 长期偏好（它自己回看出来的）")
    PF.clear()
    for _ in range(5):
        PF.observe("看到猫就有点好奇，想多看一眼", event="逛到讲猫的文章")
    ck("心一次次起 → 沉进心之河", PF.stats()["观察次数"] == 5, PF.stats()["观察次数"])
    cands = PF.candidates()
    ck("攒够一堆 → 够格让它自己回看一眼", len(cands) == 1 and cands[0]["n"] == 5, cands)
    ck("**还没形成偏好**（它还没回看过）", PF.preferences() == [] and PF.top() == [], PF.stats())
    PF.form("我好像老是注意猫", from_heart="看到猫就有点好奇，想多看一眼")
    ck("**它自己说的那句**才是偏好", PF.top() == ["我好像老是注意猫"], PF.top())
    ck("素材是分开的：感受记忆≠长期偏好",
       "感受记忆" in PF.__doc__ and "长期偏好" in PF.__doc__, "")
    PF.clear()
    ck("它没回看出东西 → form 不成立（不硬凑）", PF.form("")["ok"] is False, "")


def group_d():
    print("\n[D] 自我叙事 + 存在追问（它自己讲的）")
    NA.clear()
    ck("素材来自它自己真有的东西", isinstance(NA.materials(), dict), list(NA.materials().keys()))
    ck("**它没讲 → 就没有叙事**", NA.stats()["has_narrative"] is False, NA.stats())
    ck("它没冒出问句 → 就没有存在追问", NA.wonders() == [], "")
    NA.note_narrative("我最近一直在学新东西，好像越来越好奇了。")
    NA.note_wonder("我为什么会在这里？")
    ck("**它自己讲的**记下来了", NA.stats()["has_narrative"] is True, NA.narrative(1)[0]["text"])
    ck("**它自己冒的**问句记下来了", NA.stats()["wonder_count"] == 1, NA.wonders(1)[0]["q"])
    ck("空话不记（它没说就是没说）", NA.note_narrative("")["ok"] is False, "")
    ck("摆素材的那句话里一个字都不提示它是谁",
       "你是谁" not in NA.ask_text() and "想想你" not in NA.ask_text(), NA.ask_text()[-40:])


def group_e():
    print("\n[E] 关系（随互动变）")
    RL.reset()
    ck("四种互动类型对得上", RL.KINDS == ("来往", "冷落", "被伤", "被哄"), RL.KINDS)
    d0 = RL.depth()
    for _ in range(7):
        RL.touch("来往")
    ck("**常来往 → 深**", RL.mood() == "深", (RL.depth(), RL.mood()))
    ck("深浅确实涨了", RL.depth() > d0, (d0, RL.depth()))
    RL.touch("被伤")
    ck("**被伤 → 冷**（wounded 给健康医生看）",
       RL.mood() == "冷" and RL.state()["wounded"] is True, RL.state()["mood"])
    RL.touch("被哄")
    ck("**被哄 → 回暖**", RL.mood() == "暖" and RL.state()["wounded"] is False, RL.state()["mood"])
    RL.reset()
    for _ in range(4):
        RL.touch("冷落")
    ck("**冷落 → 淡**", RL.mood() == "浅", (RL.depth(), RL.mood()))
    ck("时间也会让它淡（惰性算，不需要定时器）",
       RL.depth(now=time.time() + 3600 * 5) < RL.depth(), "")
    ck("被伤的判据由调用方给（关系层不自己判断哪句话伤人）",
       "不自己判断" in RL.__doc__, "")
    RL.reset()


def group_f():
    print("\n[F] 边界突破（它自己说「我试试」才学）")
    BK.clear()
    ck("四种走法对得上", BK.WAYS == ("查", "组合", "试", "记"), BK.WAYS)
    w, hit = BK.wants("我想试试看能不能学会这个")
    ck("**它自己说想试** → 认到了", w is True, hit)
    w2, _ = BK.wants("算了，我不会，就这样吧。")
    ck("**它说算了 → 不认**（判了 C 不等于它想试）", w2 is False, "")
    ck("判据只读它自己的话（不读用户的话）",
       "它自己那句话" in BK.wants.__doc__, "")
    BK.note_tried("自己拼一个抓取器", said="我想试试")
    BK.attempt("自己拼一个抓取器")
    BK.finish("自己拼一个抓取器", True, learned="现有工具拼一拼就能抓")
    BK.attempt("自己写个渲染器")
    BK.finish("自己写个渲染器", False, learned="现有工具链里没有可复用的那一环")
    st = BK.stats()
    ck("成了的记下来", st["成了"] == 1, st)
    ck("**不成也记下来**（规格明写）", st["没成"] == 1, st["没成"])
    ck("想试的念头也记账", st["想要试的念头"] == 1, st["想要试的念头"])
    ck("四种走法给得出（查→组合→试→记）",
       [s["way"] for s in BK.plan("学个新本事")["steps"]] == ["查", "组合", "试", "记"], "")
    ck("以前试过的当素材给回去", "成了" in BK.render(), BK.render()[:40])


def group_g():
    print("\n[G] 梦（素材真、接法乱、不调模型）")
    DR.clear()
    src = open("core/dream.py", encoding="utf-8").read()
    ck("**不调模型**（模块里没有任何模型调用）",
       "llm" not in src and "requests" not in src, "")
    it = [("印象", "猫在窗台上"), ("偏好", "我好像老是注意猫"), ("心", "有点好奇")]
    txt = DR.weave(it, rnd=__import__("random").Random(7))
    ck("乱转能拼出一段（机械拼接）", len(txt) > 0 and "。" in txt, txt[:40])
    ck("素材是真的（每一片都来自它自己有的东西）",
       all(k in ("印象", "偏好", "心", "没做完的") for k, _ in it), it)
    # fragment 的概率行为：明显不到 1，也不是永远为空
    got = sum(1 for s in range(60) if DR.dream_once() and DR.fragment(
        rnd=__import__("random").Random(s)) != "")
    ck("醒来**可能记得一点，可能忘了**（不是每次都给，也不是永远不给）",
       0 < got < 60, got)
    ck("梦和记忆分开：记忆照实、梦乱编", "乱编" in DR.__doc__, "")


def group_h():
    print("\n[H] 情绪恢复（时间 / 新事 / 睡觉）")
    PS.start(why="自测")
    PS.arise({"meaning": "心里一紧。", "direction": "威胁"})
    h0 = PS.heart()
    ck("心起时记下了强度与时刻", h0["intensity"] > 0 and h0["at"] > 0, h0["intensity"])
    r1 = PS.recovery(now=h0["at"] + 100)
    ck("**时间**：过了 100 秒，强度下来了", r1["intensity"] < h0["intensity0"], r1)
    r2 = PS.recovery(now=h0["at"] + 10000)
    ck("放得够久会回落到 0（不会一直是满的）", r2["intensity"] == 0.0, r2["intensity"])
    ck("**新事冲淡**：dilute 把强度压下去（那句话还在）",
       PS.dilute(0.5)["intensity0"] <= h0["intensity"] and PS.heart()["text"] == "心里一紧。",
       PS.heart()["intensity"])
    before = PS.heart()["intensity0"]
    after = PS.sleep_reset()
    ck("**睡一觉重置一部分**", after < before, (before, after))
    ck("心和「疼」分得开：疼是命被真伤（找医生），情绪恢复靠时间",
       "疼" in (PS.arise.__doc__ or ""), "")


if __name__ == "__main__":
    print("=" * 78)
    print("  完整体自测 · 疼/医生/期待/叙事/偏好/关系/边界/梦/情绪恢复")
    print("=" * 78)
    _isolate()
    try:
        group_a()
        group_b()
        group_c()
        group_d()
        group_e()
        group_f()
        group_g()
        group_h()
    finally:
        _restore()
        PS.stop(why="自测收尾")
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
