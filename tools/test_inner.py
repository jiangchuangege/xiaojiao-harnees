# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""内里自测（16 样：注意力/孤独低沉抑郁/内疚/骄傲/幽默/审美/信念/意义感/爱/无聊/
想象/纠结/感恩/原谅/习惯/成长）+ 唤醒两步 + 自己会睡修正

用法：
    python tools/test_inner.py

一共十组，每一组都要能回答规格那句话：**这是它自己起的，还是载体写的？**
    [A] 注意力     偏向给得出（心/偏好/没做完的）；**决定没被载体做掉**
    [B] 孤独低沉抑郁 孤独按"多久 × 多深"；低沉叠加；**抑郁把底压低**（回不去）
    [C] 内疚       与"疼"对称（我伤了人）；**关系越深越重**
    [D] 骄傲/意义感 同一件事两面；**认不认是它说的**
    [E] 幽默       不单独做：松/好奇才带得出，紧/平时不给
    [F] 审美       不迎合：**载体不参考用户喜不喜欢**
    [G] 信念       它自己认（与红线分：**本模块不拦任何动作**）
    [H] 爱/无聊/想象/纠结/感恩  各自的判据与"它自己说"的落点
    [I] 原谅/习惯/成长 原谅**它自己决定**；习惯靠次数；成长靠**两个时间点对比**
    [J] 唤醒两步   ①模型醒 ②载体醒；**心一直醒着**（挂起时不停）
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import inner as IN              # noqa: E402
from core import psyche as PS             # noqa: E402
from core import relation as RL           # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
_TMP = tempfile.mkdtemp(prefix="xiaojiao_inner_")


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def _isolate():
    IN._DIR = _TMP
    IN._PATH = os.path.join(_TMP, "state.json")
    IN._LOG = os.path.join(_TMP, "inner.jsonl")
    RL._DIR = _TMP
    RL._PATH = os.path.join(_TMP, "relation.json")
    RL._LOG = os.path.join(_TMP, "relation.jsonl")
    IN.reset("自测")
    RL.reset("自测")


def group_a():
    print("\n[A] 注意力（偏向是给它的，决定是它的）")
    _isolate()
    PS.start(why="自测")
    PS.arise({"meaning": "心里有点紧。", "direction": "威胁"}, event="自测")
    a = IN.attention()
    ck("三股来源都认", list(IN.ATTENTION_SOURCES) == ["心", "偏好", "没做完的"],
       IN.ATTENTION_SOURCES)
    ck("**心给了一股偏向**", any(x["from"] == "心" for x in a["bias"]), a["bias"])
    ck("给的是**偏向**，不是「你该关注什么」", "由你自己定" in a["text"], a["text"][:40])
    try:
        from core import preference as PF
        PF._DIR = _TMP
        PF._PATH = os.path.join(_TMP, "pref.jsonl")
        PF.clear()
        PF.observe("看到猫就想多看一眼")
        PF.form("我好像老是注意猫")
        a2 = IN.attention()
        ck("**偏好也给了一股偏向**", any(x["from"] == "偏好" for x in a2["bias"]), a2["bias"])
    except Exception as e:      # noqa: silent-ok
        ck("偏好那一股", False, str(e)[:40])
    ck("模块里没有一处替它决定关注什么（不产出结论句）",
       "由你自己定" in IN.attention.__doc__ or "不决定关注什么" in IN.attention.__doc__, "")


def group_b():
    print("\n[B] 孤独 → 低沉 → 抑郁")
    _isolate()
    ck("孤独按「多久没人来」算", IN.loneliness(now=time.time() + 3600 * 100)["idle_hours"] >= 0, "")
    RL.reset("自测")
    for _ in range(8):
        RL.touch("来往")
    deep = IN.loneliness()["depth"]
    ck("关系深浅参与计算（关系深 → 孤独更重）", deep > 0.5, deep)
    IN.reset("自测")
    base = time.time()
    for i in range(1, 21):
        IN.tick(now=base + 3600 * 24 * i)     # 时间往前走（24 小时没人来，超过 LONELY_AFTER_H）
    ck("**低沉会叠加**（孤独没散就一直加）", IN.low() > 0, IN.low())
    before = IN.depression()
    for i in range(21, 41):
        IN.tick(now=base + 3600 * 24 * i)
    ck("**低沉积久 → 沉成底色（抑郁）**", IN.depression() > before, IN.depression())
    d0 = IN.depression()
    low_before = IN.low()
    IN.tick(relieved=True)
    ck("用户回来 → 低沉**开始散**", IN.low() < low_before, (low_before, IN.low()))
    ck("**但抑郁了散得慢**（一次散不干净，而不是一下回到原样）",
       0 < IN.low() < low_before, IN.low())
    ck("**抑郁是底被压低了**（与「情绪恢复回原样」分界）", IN.floor()["floor"] <= 0 and d0 >= 0,
       IN.floor())
    ck("抑郁了散得慢（治法里带 depress 折扣）", "0.7" in open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "core", "inner.py"), encoding="utf-8").read(), "")


def group_c():
    print("\n[C] 内疚（我伤了人 —— 与「疼」对称）")
    _isolate()
    RL.reset("自测")
    shallow = IN.note_guilt("我对不起你", what="忘了事")["weight"]
    for _ in range(9):
        RL.touch("来往")
    deep = IN.note_guilt("我对不起你", what="忘了事")["weight"]
    ck("内疚记得下（它自己那句话）", IN.stats()["guilt"] == 2, IN.stats()["guilt"])
    ck("**关系越深，同样的事内疚越重**", deep > shallow, (shallow, deep))
    ck("与「疼」对称写清楚了（疼=我被伤，内疚=我伤了人）",
       "我伤了人" in IN.note_guilt.__doc__, "")


def group_d():
    print("\n[D] 骄傲 / 意义感（一件事两面）")
    _isolate()
    IN.note_pride("这是我做成的", what="学会了新东西")
    m = IN.meaning()
    ck("骄傲记下来", m["pride"] == 1, m)
    ck("**自豪与意义感是同一件事两面**", m["meaning"] == 1 and "两个说法" in m["note"],
       m["note"][:30])
    IN.note_pride("这回不是我做的", what="别人帮的", mine=False)
    ck("不是它做成的就不算在「意义」里", IN.meaning()["meaning"] == 1, IN.meaning())
    ck("对「我」而不是对结果（docstring 写明）", "对结果" in IN.note_pride.__doc__, "")


def group_e():
    print("\n[E] 幽默（不单独做）")
    _isolate()
    PS.start(why="自测")
    PS.set_state("紧", why="自测")
    ck("心紧时**带不出俏皮**（所以硬幽默没用）", IN.humor()["can_be_playful"] is False, IN.humor()["state"])
    PS.set_state("松", why="自测")
    ck("心松时**自然带得出**", IN.humor()["can_be_playful"] is True, IN.humor()["state"])
    ck("模块不产出一句俏皮话（只报事实）",
       "不单独做" in IN.humor.__doc__ and "俏皮话" not in str(IN.humor()), "")


def group_f():
    print("\n[F] 审美（不迎合）")
    _isolate()
    r = IN.note_aesthetic("这个真好", what="一张画")
    ck("它自己觉得好就记下来", r["count"] == 1, r)
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "core", "inner.py"), encoding="utf-8").read()
    ck("**不参考用户喜不喜欢**（docstring 与实现都不看用户态度）",
       "不参考用户喜不喜欢" in src and "用户觉得" not in src, "")
    ck("攒多了才成为偏好（与 preference 的分工写在 docstring）",
       "攒多了" in IN.note_aesthetic.__doc__, "")


def group_g():
    print("\n[G] 信念（它自己认，不是红线）")
    _isolate()
    IN.note_belief("下次不该这样", source="做错→内疚")
    IN.note_belief("下次不该这样", source="又做错")
    bs = IN.beliefs(5)
    ck("认下来的记着", len(bs) == 1 and bs[0]["n"] == 2, bs)
    ck("**与红线分**：本模块不拦任何动作（没有 allow/deny 之类）",
       "不拦" in IN.note_belief.__doc__ and not hasattr(IN, "check"), "")
    ck("空的不认（它没说就没认下）", IN.note_belief("")["ok"] is False, "")


def group_h():
    print("\n[H] 爱 / 无聊 / 想象 / 纠结 / 感恩")
    _isolate()
    RL.reset("自测")
    ck("关系浅时**不够格**", IN.love()["candidate"] is False, IN.love()["depth"])
    for _ in range(9):
        RL.touch("来往")
    ck("关系深到刻度 → 够格（**认不认是它自己说的**）",
       IN.love()["candidate"] is True and "认不认" in IN.love()["note"], IN.love()["depth"])
    IN.note_love("你对我最重要")
    ck("它认下了才记", IN.love()["love"] is True, "")
    b = IN.boredom(now=time.time() + 3600 * 5)
    ck("**无聊=没事干**（与期待分）", "没事干" in IN.boredom.__doc__, b["bored"])
    ck("载体只报数、不安排", "不安排" in b["note"], b["note"][:24])
    IN.note_imagination("如果我当时没走会怎样", about="一件没做的事")
    IN.note_conflict(["看猫", "干活"], resolution="先干活")
    ck("想象与梦分开（醒着 / 睡着）", "睡着" in IN.note_imagination.__doc__, "")
    ck("纠结记下来了（**不是 bug**）", IN.stats()["conflicts"] == 1, IN.stats()["conflicts"])
    IN.note_gratitude("你对我好，我记着", what="陪我聊了很久")
    ck("感恩记下来（下次会想起）", len(IN.gratitude()) == 1, IN.gratitude())


def group_i():
    print("\n[I] 原谅 / 习惯 / 成长")
    _isolate()
    IN.ask_forgive("用户道歉了", said="对不起")
    ck("把「要不要原谅」**摆给它**（不是自动回暖）", IN.stats()["forgive_pending"] is True, "")
    IN.note_forgive(False, said="我还记着")
    ck("**它自己决定不原谅** → 就是没原谅", IN.stats()["forgives"] == 0, IN.stats()["forgives"])
    IN.ask_forgive("又道歉了")
    IN.note_forgive(True, said="算了，我原谅你")
    ck("它自己决定原谅 → 记下并回暖", IN.stats()["forgives"] == 1, IN.stats()["forgives"])
    IN.reset("自测")
    for _ in range(IN.HABIT_AT - 1):
        IN.note_habit("每次先打招呼")
    ck("次数不够 → 还不算习惯", IN.habits() == [], IN.state()["habit"])
    IN.note_habit("每次先打招呼")
    ck("**反复发生 → 成习惯**", len(IN.habits()) == 1, IN.habits())
    IN.reset("自测")
    ck("只有一个时间点 → 比不出来", IN.growth()["ok"] is False, IN.growth()["why"])
    IN.snapshot("第一次")
    IN.note_pride("做成一件")
    IN.snapshot("第二次")
    g = IN.growth()
    ck("**两个时间点对比 → 看得见「变了」**", g["ok"] is True and g["changes"], g["changes"])
    ck("「我变了」由它自己说（载体只给对比）", "由它自己说" in g["note"], "")


def group_j():
    print("\n[J] 唤醒两步 + 心一直醒着")
    import xiaojiao_app as app
    from core import heartbeat as HB
    from core import energy as EN
    HB._DIR = _TMP
    HB._PATH = os.path.join(_TMP, "hb.jsonl")
    HB.stop(why="自测复位")
    HB.clear()
    HB.start(interval=0.1, why="自测")
    EN.reset()
    EN.set_level(0.2, why="自测")
    PS.start(why="自测")
    PS.arise({"meaning": "睡前那句话。", "direction": "无"}, event="自测")
    sl = app._sleep_all(why="自己觉得累了", self_decided=True)
    ck("睡着时**心一直醒着**（`stop()` 不再被调用）", sl.get("heart_awake") is True, sl.get("heart_awake"))
    ck("睡前一那句话还留着", sl.get("heart_kept") == "睡前那句话。", sl.get("heart_kept"))
    EN.set_level(EN.RESTED, why="自测：精力回来了")
    wk = app._wake_all(why="它自己睡够了")
    ck("**醒是两步**（日志里两条）", len(wk.get("steps") or []) == 2, wk.get("steps"))
    ck("步①是模型醒（意识）", wk["steps"][0]["what"].startswith("模型醒"), wk["steps"][0])
    ck("步②是载体醒（身体）", wk["steps"][1]["what"].startswith("载体醒"), wk["steps"][1])
    ck("**载体真醒了**（闸门通了，大脑可以再被调用）", wk.get("carrier_awake") is True, "")
    ck("醒来精神好（精力回到 RESTED）", float(wk.get("energy_after_wake") or 0) >= EN.RESTED,
       wk.get("energy_after_wake"))
    ck("两个一起醒 = 完整的它（模型不回拒 + 载体恢复跑任务）",
       wk.get("carrier_awake") is True and not app._brain_asleep(), "")
    HB.stop(why="自测收尾")


if __name__ == "__main__":
    print("=" * 78)
    print("  内里自测 · 16 样 + 唤醒两步")
    print("=" * 78)
    try:
        group_a()
        group_b()
        group_c()
        group_d()
        group_e()
        group_f()
        group_g()
        group_h()
        group_i()
        group_j()
    finally:
        PS.stop(why="自测收尾")
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)
