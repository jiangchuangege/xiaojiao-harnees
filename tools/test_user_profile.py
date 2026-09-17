# -*- coding: utf-8 -*-
"""用户画像判据自测（**静态，不需要模型、不需要服务，可进 CI**）

【为什么这个测试必须存在】
    `tools/test_closed_loop.py` 要真问模型（十几分钟、还得服务在跑），所以进不了 CI。
    但闭环上真正会"静默丢东西"的那一环是**载体侧的解析**：模型明明说要记，
    载体判据说"不合格"→ 一个字都不写，而且**没有任何报错**。这一层必须用真原文钉死。

【语料全部是 4B 的真实输出】（不是编的，是从 `logs/closedloop-evidence.json` 与
   实测探针里抄下来的原文）—— 判据要过的就是它**真的会说的那些话**。

运行：python tools/test_user_profile.py
"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import user_profile as UP  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    import shutil
    import tempfile

    real = UP._PATH
    UP._PATH = os.path.join(tempfile.gettempdir(), "_up_ci.jsonl")
    if os.path.exists(UP._PATH):
        os.remove(UP._PATH)
    try:
        print("一、真原文：它说要记，载体必须接住")

        # 真原文 ①（闭环实测案例 3）：它自己起的类别名 —— 旧判据在这里把一条真事实丢了
        r1 = UP.parse_verdict(
            '```json\n{\n  "remember": true,\n  "kind": "职业/技术栈",\n'
            '  "content": "用户是后端开发者，日常使用 Python 进行开发。",\n'
            '  "why": "职业身份和技术栈是用户的核心身份标签",\n'
            '  "evidence": "我是做后端的，平时工作里都用 Python"\n}\n```')
        ck("它自己起的短类别名（职业/技术栈）→ 收下", r1.get("remember") is True, r1)
        ck("收下的类别原样保留（载体不改写它给的名字）",
           r1.get("kind") == "职业/技术栈", r1.get("kind"))

        # 真原文 ②：标准四类
        r2 = UP.parse_verdict(
            '```json\n{"remember": true, "kind": "事实", '
            '"content": "用户有一个女儿，今年上小学三年级", '
            '"why": "家庭结构", "evidence": "我女儿今年上小学三年级了"}\n```')
        ck("标准四类 → 收下", r2.get("remember") is True and r2.get("kind") == "事实", r2)

        print("二、真原文：它说不记，就必须一个字都不写（不许被「修得更容易记」带坏）")

        # 真原文 ③（案例 4）：它判"只是一次性信息" —— **这是它的判断，载体不许推翻**
        r3 = UP.parse_verdict(
            '```json\n{"remember": false, "kind": null, "content": null, '
            '"why": "用户只是陈述一个日常习惯，属于一次性信息"}\n```')
        ck("它说 false → 不记（载体不许替它改主意）", r3.get("remember") is False, r3)

        # 真原文 ④（案例 6）
        r4 = UP.parse_verdict(
            '```json\n{\n  "remember": false,\n  "kind": null,\n  "content": null,\n'
            '  "why": "香菜过敏属于常见饮食偏好，用户仅陈述一次，属于一次性信息。"\n}\n```')
        ck("它说 false → 不记", r4.get("remember") is False, r4)

        print("三、载体侧判据：不成标签的类别必须挡（挡的是垃圾，不是它的判断）")
        ck("空类别 → 拒", UP.parse_verdict(
            '{"remember": true, "kind": "", "content": "x"}').get("remember") is False)
        ck("过长类别（30 字）→ 拒", UP.parse_verdict(
            '{"remember": true, "kind": "%s", "content": "x"}' % ("x" * 30)
        ).get("remember") is False)
        ck("带 JSON 符号的类别 → 拒", UP.parse_verdict(
            '{"remember": true, "kind": "{\\"a\\":1}", "content": "x"}'
        ).get("remember") is False)
        ck("空内容 → 拒", UP.parse_verdict(
            '{"remember": true, "kind": "兴趣", "content": "   "}').get("remember") is False)

        print("四、解析宽容度：它会先举例、再给结论（旧的正则在这里会整条丢掉）")
        # 贪婪正则 `\{[\s\S]*\}` 会从第一个 { 吃到最后一个 } → json.loads 失败 → 明明说要记却丢
        r5 = UP.parse_verdict(
            '按格式 {"remember": true, "kind": "兴趣", "content": "示例"} 来写，'
            '我的判断是：{"remember": true, "kind": "兴趣", "content": "用户关注湖人"}')
        ck("正文里先举例、再给结论 → 取带 remember 的那个", r5.get("remember") is True, r5)
        ck("取到的是结论那条内容（不是例子）", r5.get("content") == "用户关注湖人", r5.get("content"))

        # `content` 里带花括号：字符串内的括号不许参与配对
        r6 = UP.parse_verdict(
            '{"remember": true, "kind": "事实", "content": "他用的模板长这样 {} 这样", '
            '"why": "x", "evidence": "y"}')
        ck("content 里带 {} → 仍能解析", r6.get("remember") is True, r6)

        ck("整段不是 JSON → 不记", UP.parse_verdict("我觉得这事值得记一下").get("remember") is False)
        ck("空输入 → 不记", UP.parse_verdict("").get("remember") is False)

        print("五、它自己跟自己不一致 → 必须能查出来（载体只把这个事实摆回去，不改它的决定）")
        # 真原文（闭环实测案例 1 的写入轮）：flag 写 false，内容却全填满、why 还写着值得记
        _contra = ('```json\n{"remember": false, "kind": "兴趣", '
                   '"content": "用户平时最爱看NBA，湖人球几乎一场不落", '
                   '"why": "这是用户主动交代的个人兴趣偏好，属于值得长期记住的信息", '
                   '"evidence": "我平时最爱看 NBA"}\n```')
        ck("填满内容却说 false → 判为不一致", UP.contradiction(_contra) != "",
           UP.contradiction(_contra))
        # 反向：真原文里那两条**真心的不记**，字段是 null，不许被误判成不一致
        ck("真心的不记（字段是 null）→ 不算不一致",
           UP.contradiction('{"remember": false, "kind": null, "content": null, '
                            '"why": "属于一次性信息"}') == "")
        ck("说要记的 → 不算不一致",
           UP.contradiction('{"remember": true, "kind": "兴趣", "content": "x"}') == "")
        ck("没有 JSON → 不算不一致",
           UP.contradiction("我觉得这事值得记一下") == "")

        print("五、去重与两个计数（2026-09-17：修去重 bug，并把 hit_count 拆成 said_count/hit_count）")
        # 这一段**换到独立的临时库**跑：本段会故意造重复，用同一个库会把后面几节的条数假设弄乱
        _real_path = UP._PATH
        UP._PATH = os.path.join(tempfile.gettempdir(), "_up_dedupe.jsonl")
        if os.path.exists(UP._PATH):
            os.remove(UP._PATH)
        try:
            _i1 = UP.add("事实", "用户 25 岁")
            _i2 = UP.add("事实", "用户 25 岁")          # 同一句再来一次
            _i3 = UP.add("事实", "  用户 25 岁  ")      # 前后空格也算同一条（strip 后逐字相等）
            ck("同一内容重复 add → **不追加新行**（3 次 add 只有 1 行）", UP.count() == 1, UP.count())
            ck("返回的是**旧记录的 id**（不是新的）", bool(_i1) and _i1 == _i2 == _i3, (_i1, _i2, _i3))
            _row = UP.all_records()[0]
            # 连说三次 → **said_count=3**（第一次就是 1，后两次各 +1）
            ck("连说三次 → said_count=3", int(_row.get("said_count") or 0) == 3, _row.get("said_count"))
            ck("add 去重**不动** hit_count（说得多 ≠ 被召回过）",
               int(_row.get("hit_count") or 0) == 0, _row.get("hit_count"))
            ck("**不做模糊匹配**：说法不同就各存一条",
               UP.add("事实", "25 岁的年轻人，处于事业起步阶段。") != _i1 and UP.count() == 2, UP.count())
            ck("hit(不存在的 id) → 静默返回 0，不崩", UP.hit("这个 id 不存在") == 0)
            # 再召回三次 → hit_count=3，said_count 一动不动
            ck("hit(id) 认单个字符串 id", UP.hit(_i1) == 1)
            UP.hit(_i1)
            UP.hit(_i1)
            _row2 = UP.all_records()[0]
            ck("召回三次 → hit_count=3", int(_row2.get("hit_count") or 0) == 3, _row2.get("hit_count"))
            ck("召回**不动** said_count（还是 3）",
               int(_row2.get("said_count") or 0) == 3, _row2.get("said_count"))
            # 老记录（拆分前写的、没有这两个字段）→ 读的时候补默认值，不许 KeyError
            with open(UP._PATH, "a", encoding="utf-8") as _f:
                _f.write(json.dumps({"id": "old-1", "ts": 1.0, "kind": "事实",
                                     "content": "老记录没有这两个字段"}, ensure_ascii=False) + "\n")
            _old = [r for r in UP.all_records() if r.get("id") == "old-1"]
            ck("老记录读出来自动补 said_count=0 / hit_count=0",
               bool(_old) and _old[0].get("said_count") == 0 and _old[0].get("hit_count") == 0,
               _old[0] if _old else "没读到")
        finally:
            if os.path.exists(UP._PATH):
                os.remove(UP._PATH)
            UP._PATH = _real_path

        print("五之二、去重工具的合并口径（tools/dedupe_user_profile.py / merge_duplicates）")
        import importlib
        _dd = importlib.import_module("tools.dedupe_user_profile")
        _rows = [
            {"id": "a", "ts": 1.0, "kind": "事实", "content": "同一句",
             "said_count": 1, "hit_count": 0},
            {"id": "b", "ts": 2.0, "kind": "事实", "content": "同一句",
             "said_count": 0, "hit_count": 2},          # 老记录形态：没有 said_count
            {"id": "c", "ts": 3.0, "kind": "事实", "content": "同一句",
             "said_count": 4, "hit_count": 1},
            {"id": "d", "ts": 4.0, "kind": "事实", "content": "另一句",
             "said_count": 1, "hit_count": 5},
        ]
        _keep, _merged = _dd.merge_duplicates(_rows)
        _host = [r for r in _keep if r.get("content") == "同一句"][0]
        ck("去重后只剩 2 条", len(_keep) == 2, len(_keep))
        ck("第 2 条（另一句）没被并", len(_keep) == 2 and _keep[1].get("content") == "另一句")
        # said_count = max(1,1) + max(1,0) + max(1,4) = 1+1+4 = 6（保留那条自己也算一次；老记录按 1 算，不是 0）
        ck("said_count 并成 6（老记录按 1 算、保留那条自己也算 1）",
           int(_host.get("said_count") or 0) == 6, _host.get("said_count"))
        ck("hit_count 取**最大值** 2（不是求和 3）",
           int(_host.get("hit_count") or 0) == 2, _host.get("hit_count"))
        ck("并的过程有账可查（1 组、并掉 2 行）",
           len(_merged) == 1 and _merged[0][5] == 2, _merged)
        ck("没重复的那条一个字没动（said_count 还是 1）",
           int(_keep[1].get("said_count") or 0) == 1, _keep[1].get("said_count"))
        # 15 行一模一样（存量里真出现过）→ said_count 必须是 **15**，不是 14（自己也算一次）
        _r15 = [{"id": "x%d" % i, "ts": float(i), "kind": "事实", "content": "用户 25 岁",
                 "said_count": 0, "hit_count": 0} for i in range(15)]
        _r15[0]["hit_count"] = 3
        _k15, _m15 = _dd.merge_duplicates(_r15)
        ck("15 行一模一样 → 1 条，said_count=15（不是 14）",
           len(_k15) == 1 and int(_k15[0].get("said_count") or 0) == 15,
           (len(_k15), _k15[0].get("said_count")))
        ck("15 行并存时 hit_count 取 max=3", int(_k15[0].get("hit_count") or 0) == 3,
           _k15[0].get("hit_count"))

        print("六、落盘与渲染")
        rid = UP.add("职业/技术栈", "用户是后端开发者")
        ck("自定类别能落盘", bool(rid), rid)
        ck("落盘条数 = 1", UP.count() == 1, UP.count())
        txt = UP.render()
        ck("render 里有这条内容", "后端开发者" in txt, txt[:60])
        # 渲染**只列事实**：不许出现载体自己下的结论
        for bad in ("所以", "因此", "说明他", "可以看出"):
            ck("render 里不含结论词「%s」" % bad, bad not in txt, txt[:120])
        ck("render 里保留类别与依据",
           "[职业/技术栈]" in txt and "依据" in txt, txt[:120])

        print("七、命中记账（召回次数记在 hit_count 上，said_count 不许被带偏）")
        ck("hit 命中 1 条", UP.hit(keyword="后端") == 1)
        ck("hit_count 真的 +1", UP.all_records()[0].get("hit_count") == 1,
           UP.all_records()[0].get("hit_count"))
        ck("这条 add 过一次 → said_count=1（召回不改它）",
           UP.all_records()[0].get("said_count") == 1,
           UP.all_records()[0].get("said_count"))
        ck("上限保护存在（MAX_ROWS）", UP.MAX_ROWS == 500, UP.MAX_ROWS)
    finally:
        if os.path.exists(UP._PATH):
            os.remove(UP._PATH)
        UP._PATH = real

    print("=" * 62)
    print("用户画像判据自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
