# -*- coding: utf-8 -*-
"""偏好闸门自测（离线）：**挡的是"把心象照抄一遍"，放的是"回看出来的倾向"。**

【为什么必须钉】2026-09-19 清库存时实测：存量 4 条 formed 里 3 条根本不是偏好 ——
  · 「数字在眼前转，像被甩进一个没有边界的漩涡，世界突然被重新染色了。」（素材只少一个分句）
  · 「摸到两个红球，世界突然被按了暂停键，连呼吸都慢了下来。」（同族意象句）
  · 「我对数字有种说不出的亲近感」（`from_heart` 为空 = 没有回看的对象）
而 `core/inner.py` 的「此刻的偏向」会把 `top(2)` 直接摆进感知层 ——
**载体自己的一段意象句，被当成"用户的偏好"摆回它面前**。唯一那条真偏好是
「我好像老是注意猫」（素材「看到猫就有点好奇」），它必须**照样能写进去**（不许一闸全封死）。

跑法：python tools/test_preference_gate.py（用**临时库**，不碰真库）
"""
import io
import json
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import preference as PF  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def _lines(p):
    if not os.path.exists(p):
        return []
    return [l for l in io.open(p, encoding="utf-8", errors="replace").read().split("\n") if l.strip()]


def main():
    tmp = tempfile.mkdtemp(prefix="prefgate_")
    real_path, real_vec, real_dir = PF._PATH, PF._vec, PF._DIR
    fake = os.path.join(tmp, "preference.jsonl")
    try:
        PF._PATH = fake
        PF._DIR = tmp
        # 判据不依赖模型：把向量换掉 → `_sim` 走字面退路（快、可复现）
        PF._vec = lambda t: None

        print("一、它自己回看出来的**真偏好**必须照样能写（不许一闸全封死）")
        r = PF.form("我好像老是注意猫", from_heart="看到猫就有点好奇")
        ck("真偏好：写进去了", bool(r.get("ok")), r.get("why"))
        ck("真偏好：库里查得到", [x.get("pref") for x in PF.preferences()] == ["我好像老是注意猫"])
        ck("真偏好：`top()` 拿得到（感知层那条线的来源）", PF.top(2) == ["我好像老是注意猫"])

        print("\n二、把素材照抄一遍 → 不许写（实测那两条的形状）")
        r = PF.form("数字在眼前转，像被甩进一个没有边界的漩涡，世界突然被重新染色了",
                    from_heart="数字在眼前转，像被甩进一个没有边界的漩涡")
        ck("照抄素材：没写", not r.get("ok"), r.get("why"))
        ck("照抄素材：给了理由", bool(r.get("why")))
        r = PF.form("摸到两个红球，世界突然被按了暂停键，连呼吸都慢了下来",
                    from_heart="摸到两个红球，世界突然被按了暂停键，连呼吸都慢了下来")
        ck("一模一样：没写（旧的 `said not in examples` 只管这一种）", not r.get("ok"), r.get("why"))
        # 【这一条走的是**字面**判据，不是向量】：它带着「老是」，前面那道字眼闸放它过去，
        #   靠"把素材原句抄进去了"才挡住。⚠️ 用向量余弦判这一条会**连真偏好一起挡掉**
        #   （回看结论天然跟素材同话题）—— 那是第一版写错、当天在 `test_inner.py` 上翻的车。
        r = PF.form("我老是注意数字在眼前转，像被甩进一个没有边界的漩涡",
                    from_heart="数字在眼前转，像被甩进一个没有边界的漩涡")
        ck("带「老是」但把素材原句抄进去：仍然不写（字面判据）", not r.get("ok"), r.get("why"))
        ck("抄素材的判据是**字面**的（同话题的真偏好不算抄）",
           (not PF._literal_echo("我好像老是注意猫", "看到猫就有点好奇"))
           and bool(PF._literal_echo("数字在眼前转，像被甩进一个没有边界的漩涡，世界突然被重新染色了",
                                     "数字在眼前转，像被甩进一个没有边界的漩涡")),
           repr(PF._literal_echo("我好像老是注意猫", "看到猫就有点好奇")))

        print("\n三、没有「回看倾向」字眼的意象句 → 不许写")
        r = PF.form("世界突然被重新染色了", from_heart="看到数字就有点发懵")
        ck("纯意象句：没写", not r.get("ok"), r.get("why"))
        ck("纯意象句：理由里点出缺什么",
           "回看倾向" in str(r.get("why")), r.get("why"))

        print("\n四、没有素材（`from_heart` 空）→ 不许写：回看得有回看的对象")
        r = PF.form("我对数字有种说不出的亲近感", from_heart="")
        ck("空素材：没写", not r.get("ok"), r.get("why"))

        print("\n五、空话 → 不许写；跨轮去重仍然生效")
        ck("空串：没写", not PF.form("", from_heart="看到猫就有点好奇").get("ok"))
        r = PF.form("我好像老是注意猫", from_heart="看到猫就有点好奇")
        ck("跟已有偏好太像：不重复写", not r.get("ok"), r.get("why"))
        ck("库里仍然只有那一条", len(PF.preferences()) == 1, len(PF.preferences()))

        print("\n六、`observe()`（心之河）不受这道闸影响 —— 它记的是心，不是偏好")
        o = PF.observe("数字在眼前转，像被甩进一个没有边界的漩涡", event="测试", why="自测")
        ck("心之河：照样记", bool(o.get("ok")))
        ck("心之河：不算偏好", len(PF.preferences()) == 1, len(PF.preferences()))

        print("\n七、落盘形状：formed 只有真偏好那一条")
        rows = [json.loads(l) for l in _lines(fake)]
        ck("库里 formed 条数 = 1", len([x for x in rows if x.get("kind") == "formed"]) == 1)
        ck("库里 observe 条数 = 1", len([x for x in rows if x.get("kind") == "observe"]) == 1)
    finally:
        PF._PATH, PF._vec, PF._DIR = real_path, real_vec, real_dir

    print("\n" + "=" * 66)
    print("偏好闸门自测：通过 %d / 共 %d%s"
          % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
