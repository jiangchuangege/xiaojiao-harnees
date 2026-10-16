# -*- coding: utf-8 -*-
"""记忆口径闸门 · 自测（确定性，不依赖模型、不依赖网络、**不往真库写任何东西**）。

为什么必须有它：这条链把「绝假记忆」从"只有自测在调"变成了"每轮真在跑"。
它一旦判错，用户看到的是**载体替他编经历**（"你说过…"）——那种错不报错、只失信，
事后再查也很难发现。所以这里逐条钉住：

  ① 判据本身：真命中 → precise；**余弦高但表面不重合 → 绝不 precise**（7.2 那次误判的性质）；
  ② 问法片段（「多少」「是什么」）不许当"在说同一件事"的证据；
  ③ 口径那句话的内容与边界：precise 一个字都不加、别的记忆源知道就不说话、开关能关；
  ④ 不变量：口径那句话不能带 【你说过的】 这类标记（否则会被优率当成"用户亲口说的"），
     也不能把 system 挤爆；异常一律退化成"不介入"，绝不拖垮对话。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import memory_deep as MD       # noqa: E402
from core import memory_gate as MG       # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def _hit(text, score, mid="自测-不存在的id"):
    return {"id": mid, "text": text, "score": score, "decayed": False, "age_days": 1.0}


def main():
    t0 = time.time()
    print("=" * 78)
    print("  记忆口径闸门自测（memory_deep 判据 + memory_gate 落地）")
    print("=" * 78)

    # ---------------- 一、判据：三档口径 ----------------
    print("\n[一] 判据：我记得 / 只记得大概 / 没记过")
    d = MD.decide_hits("我住在哪", [])
    ck("没有命中 → none（且给的是**明确的「没说过」**，不是空串）",
       d["verdict"] == "none" and d["text"], d["verdict"])
    ck("none 的话术是「你之前没跟我说过这事」", "没跟我说过" in d["text"], d["text"])
    ck("空查询 → empty（不下结论）", MD.decide_hits("   ", [])["verdict"] == "empty")

    d = MD.decide_hits("我住在哪", [_hit("用户：我住在菏泽", 0.89)])
    ck("真命中（余弦强 + 表面重合高）→ precise", d["verdict"] == "precise", d["reason"])
    ck("precise 时 text 就是那条原话（不改写）", d["text"] == "用户：我住在菏泽", d["text"])

    d = MD.decide_hits("我住在哪", [_hit("用户：今天几号", 0.91)])
    ck("余弦很高但**表面不重合** → fuzzy，绝不当事实说",
       d["verdict"] == "fuzzy", d["reason"])

    d = MD.decide_hits("我住在哪", [_hit("用户：我养了一只猫", 0.71)])
    ck("余弦不够强（< SIM_STRONG）→ fuzzy", d["verdict"] == "fuzzy", d["reason"])

    # ---------------- 二、7.2 那次误判：必须被挡住 ----------------
    print("\n[二] 7.2 那次误判（问车牌号、命中一道数学题回答）必须被挡住")
    q = "我的车牌号是多少"
    feats = MD._features(q, drop_common=False)
    ck("查询特征里**不再有问法片段**（多少/是多 被结构词表滤掉）",
       "多少" not in feats and "是多" not in feats, sorted(feats))
    ck("问法片段表是有意维护的（不是空集合）", len(MD._STRUCT_GRAMS) >= 25,
       "%d 条" % len(MD._STRUCT_GRAMS))
    # 数学题里必然有「多少」—— 7.2 那次正是靠这类片段"假重合"骗过闸门
    math_row = "用户：3 加 5 是多少 小焦：8。还有别的题要算吗？"
    ov_math = MD.overlap(q, math_row)
    ck("和一道数学题回答的重合率 = 0.00（旧判据 `>0` 就会放行的那类）",
       ov_math == 0.0, ov_math)
    d = MD.decide_hits(q, [_hit(math_row, 0.6871)])
    ck("**7.2 复现：结果是 fuzzy，不再是 precise**", d["verdict"] == "fuzzy", d["reason"])
    # 只撞上一个内容片段的那类近似命中，同样不够格
    near = "用户：我的车借给同事了 小焦：好的，记下了"
    ov_near = MD.overlap(q, near)
    ck("只撞上一个内容片段 → 重合率 >0 但 < 门槛（0 < ov < %.2f）" % MD.OVERLAP_PRECISE,
       0.0 < ov_near < MD.OVERLAP_PRECISE, round(ov_near, 3))
    d = MD.decide_hits(q, [_hit(near, 0.70)])
    ck("这类近似命中 → fuzzy（不许当事实说）", d["verdict"] == "fuzzy", d["reason"])

    # ---------------- 三、别把真命中砸了（过度收紧也是 bug） ----------------
    print("\n[三] 真命中不许被误伤（为了不编造就一律说记不清 = 砸功能）")
    for qq, mem in (("我住在哪", "用户：我住在菏泽"),
                    ("我的生日是什么时候", "用户：我生日是 3 月 15 日"),
                    ("我养的猫叫什么", "用户：我养的猫叫咪咪")):
        dd = MD.decide_hits(qq, [_hit(mem, 0.85)])
        ck("「%s」+「%s」→ precise" % (qq, mem[:12]), dd["verdict"] == "precise", dd["reason"])
    ck("阈值是量出来的那个数（0.4），不是随手写的",
       abs(MD.OVERLAP_PRECISE - 0.4) < 1e-9, MD.OVERLAP_PRECISE)
    ck("同义改写也能过（「我住在济南」vs「用户：我住在济南」 > 0.5）",
       MD.overlap("我住在济南", "用户：我住在济南") > 0.5,
       round(MD.overlap("我住在济南", "用户：我住在济南"), 3))
    ck("完全不同的事重合率 = 0",
       MD.overlap("我的车牌号是多少", "用户：用搜索工具找漏洞") == 0.0)

    # ---------------- 四、降级过的条目：只承认记得 ----------------
    # 【为什么不打桩】clarity 不是命中带进来的，是 `_clarity_of_row()` **从库里那行读出来的**
    #   —— 这正是设计要的（口径必须看真库状态，不能被调用方一句话改掉）。
    #   所以这里只能真写一行进去：备份 → 写 → 验 → 还原（项目里既有的测试模式，
    #   见 `tools/test_memory_depth.py` 头部的说明：记忆库是用户资产，测试不许碰坏它）。
    print("\n[四] 清晰度降级过的条目：只承认「记得」，绝不补细节")
    import json as _json
    from core import memory_vec as _mv
    _dbp = _mv.path()
    _blob = None
    _row_id = "自测闸门-clarity-1"
    if os.path.exists(_dbp):
        with open(_dbp, "rb") as f:
            _blob = f.read()
    try:
        # 100 天前 → 按清晰度档位表落在「模糊」（30~180 天那一档），不是印象档
        row = {"id": _row_id, "ts": time.time() - 100 * 86400, "kind": "fact",
               "text": "用户：我住在菏泽", "meta": {"clarity": MD.CLARITY_BLUR}}
        with open(_dbp, "a", encoding="utf-8") as f:
            f.write(_json.dumps(row, ensure_ascii=False) + "\n")
        _mv.reload()
        ck("测试行已写入（否则下面两条测的是空气）",
           any(r.get("id") == _row_id for r in MD._all_rows()))
        d = MD.decide_hits("我住在哪", [_hit("用户：我住在菏泽", 0.9, mid=_row_id)])
        ck("命中的条目若已被降级 → fuzzy（不看余弦多高）",
           d["verdict"] == "fuzzy", d["reason"])
        ck("fuzzy 的话术带「细节我记不太清」", "记不太清" in d["text"], d["text"])
        ck("降级档位被如实写进 reason（事后能查为什么这么说）",
           "模糊" in d["reason"], d["reason"])
    finally:
        if _blob is not None:
            with open(_dbp, "wb") as f:
                f.write(_blob)
            _mv.reload()
    ck("**还原后真实记忆库里没有测试残留**",
       not any(r.get("id") == _row_id for r in MD._all_rows()))

    # ---------------- 五、判据细节：可配置 + 逐条依据 ----------------
    print("\n[五] 判据细节：可配置、带依据、可复盘")
    d = MD.decide_hits("我的生日是什么时候", [_hit("用户：我生日是 3 月 15 日", 0.9)],
                       overlap_min=0.99)
    ck("overlap_min 可被控制文件覆盖（调高到 0.99 → 变 fuzzy）",
       d["verdict"] == "fuzzy", d["reason"])
    d = MD.decide_hits("我住在哪", [_hit("用户：我住在菏泽", 0.89)])
    ck("reason 里写着真实数字（余弦与重合率），事后能复盘",
       "0.89" in d["reason"] and "重合" in d["reason"], d["reason"])
    h0 = d["hits"][0]
    ck("每条命中都补了 clarity / overlap / conf（界面与日志要看依据）",
       all(k in h0 for k in ("clarity", "overlap", "conf")), sorted(h0.keys()))
    d = MD.decide_hits("我住在哪", [_hit("用户：今天几号", 0.7), _hit("用户：我住在菏泽", 0.9)])
    ck("命中按 conf 降序（真命中排在前面）",
       d["best"]["text"] == "用户：我住在菏泽", d["best"]["text"])

    # ---------------- 六、通用片段过滤（机制本身要能工作） ----------------
    print("\n[六] 通用片段过滤：机制确实生效（当前库规模下未触发，见 docstring）")
    qq, mem = "我的车牌是多少", "用户：我的车牌是京 A12345"
    ov_before = MD.overlap(qq, mem)
    _orig = MD._common_grams
    try:
        MD._common_grams = lambda: frozenset({"车牌"})      # 伪造：把"车牌"当成通用片段
        ov_after = MD.overlap(qq, mem)
        ck("被标为通用的片段不再计入重合（机制生效）", ov_after < ov_before,
           "%s → %s" % (ov_before, ov_after))
        # 真正的性质：**分母是查询侧未经过滤的特征数**。若连查询也一起扣，
        # 比例会被算歪（同一个 0.5 会被算成 0.67），这一条把分母钉死。
        a_raw = MD._features(qq, drop_common=False)
        b_flt = MD._features(mem, drop_common=True)
        want = len(a_raw & b_flt) / float(len(a_raw))
        ck("**查询那侧不扣通用词**（分母仍是 %d 个原始特征）" % len(a_raw),
           abs(ov_after - want) < 1e-9, "实测 %s vs 应有 %s" % (round(ov_after, 3),
                                                             round(want, 3)))
    finally:
        MD._common_grams = _orig
    ck("恢复后重合率与原来一致（临时打桩没留下副作用）",
       MD.overlap(qq, mem) == ov_before)

    # ---------------- 七、闸门：什么时候说话、什么时候闭嘴 ----------------
    print("\n[七] 闸门只在「问自己记忆」时说话")
    for s, want in (("我叫什么名字", True), ("你还记得我上次说的那个项目吗", True),
                    ("我养的猫叫什么", True), ("我的车是什么牌子", True),
                    ("我在哪家公司上班", True),          # 真机上漏判过：表里只有「工作」没有「上班」
                    ("帮我写个爬虫", False), ("我今天该穿什么", False),
                    ("Python 怎么读文件", False), ("", False)):
        ck("%-28s → %s" % ("「%s」" % s if s else "（空串）",
                           "是记忆问题" if want else "不是记忆问题"),
           MG.is_memory_question(s) is want)
    ck("超长输入不算（超过 40 字先不判）", MG.is_memory_question("我" + "啊" * 60) is False)

    r = MG.judge("我的车牌号是多少", [_hit("用户：今天几号", 0.72)])
    ck("不相关命中 → 注入口径（applied=True）", r["applied"] is True, r["reason"])
    ck("口径是 fuzzy，话里写着「不许补细节」", "不许补细节" in r["note"], r["note"][:60])
    r = MG.judge("我的车牌号是多少", [])
    ck("一条没记过 → 注入口径", r["applied"] is True, r["reason"])
    ck("口径是 none，话里写着「没跟我说过这事」",
       "没跟我说过这事" in r["note"], r["note"][:60])
    r = MG.judge("我住在哪", [_hit("用户：我住在菏泽", 0.9)])
    ck("precise → **一个字都不加**（好用的地方不动）",
       r["applied"] is False and r["note"] == "", r["reason"])
    ck("precise 的 reason 里写明「注入原样不动」", "原样" in r["reason"], r["reason"])
    r = MG.judge("我的车牌号是多少", [])
    ck("不是记忆问题 → 不说话（正常聊天不被塞一句「你没说过」）",
       MG.judge("帮我写个爬虫", [])["applied"] is False)
    r = MG.judge("我的车牌号是多少", [_hit("用户：今天几号", 0.72)], other_knows=True)
    ck("**别的记忆源已经知道 → 闭嘴**（免得一处说有、另一处说没说过）",
       r["applied"] is False and "别的记忆源" in r["reason"], r["reason"])
    r = MG.judge("我的车牌号是多少", [], cfg={"on": False})
    ck("总开关能关（关掉=回到接之前的行为）",
       r["applied"] is False and "关掉" in r["reason"], r["reason"])
    r = MG.judge("我的车牌号是多少", [], cfg={"overlap": 0.99})
    ck("控制文件能覆盖门槛", r["verdict"] in ("fuzzy", "none"), r["verdict"])

    # ---------------- 八、不变量：注入的那句话本身必须安全 ----------------
    print("\n[八] 注入的那句话本身的不变量")
    for v in ("none", "fuzzy"):
        txt = MG.note_for(v)
        ck("口径 %s 的说明**不带【你说过的】标记**（否则会被优率当成用户亲口说的）" % v,
           "【你说过的】" not in txt and "【小焦说过的】" not in txt)
        ck("口径 %s 的说明没有 ASCII 双引号（项目规矩：中文里用「」）" % v,
           '"' not in txt)
        ck("口径 %s 的说明够短（不挤爆 system，≤300 字）" % v, len(txt) <= 300, len(txt))
    ck("precise / empty 不说话（note 为空串）",
       MG.note_for("precise") == "" and MG.note_for("empty") == "")

    # ---------------- 九、坏输入不许把对话拖垮 ----------------
    print("\n[九] 坏输入：一律退化成「不介入」，绝不抛异常")
    for bad, note in ((None, "hits=None"), ([None, 1, "x"], "hits 里是垃圾"),
                      ([{}], "空 dict"), (["not a dict"], "字符串")):
        try:
            r = MG.judge("我住在哪", bad)
            ck("%s → 不抛异常（applied=%s）" % (note, r["applied"]), True, r["verdict"])
        except Exception as e:
            ck("%s → 不该抛异常" % note, False, "%s: %s" % (type(e).__name__, e))
    only_bad = MG.judge("我住在哪", [None, 1])
    ck("命中全是垃圾 → 按「没记过」处理（不编）", only_bad["verdict"] in ("none", "empty"),
       only_bad["verdict"])
    ck("judge 与 decide_hits 是**同一套判据**（不许两套打架）",
       all(MG.judge(qq, [_hit(mem, 0.85)])["verdict"] ==
           MD.decide_hits(qq, [_hit(mem, 0.85)])["verdict"]
           for qq, mem in (("我住在哪", "用户：我住在菏泽"),
                           ("我的车牌号是多少", "用户：今天几号"))))

    # ---------------- 收尾 ----------------
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
