# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""健康系统自测 —— 真跑，不模拟（离线、秒级、不调任何模型）

运行：python tools/test_health.py

为什么这个自测必须离线、必须能用假 hook 跑：
    健康系统是"模型出错时才启动"的模块 —— 恰恰是最难人工复现的部分。
    如果自测要真调一次 4B 模型才能验，那它永远不会被执行（太慢、还要显存），
    于是这个模块就成了**没人验证过的救命代码**。
    所以：治病用的 hook 全部换成"记账的假函数"，我们要验的是
    "该调的动作有没有调、调得对不对"，而不是"模型能不能被治好"。

覆盖（13 组）：
    A 18 类症状登记表齐全、五组分布正确
    B 逐类触发（18/18）+ 弱信号不误报
    C 用户实测原句（然后说：嗯/哦/好的 ×25）
    D 1200 字正常长文不许误报
    E 诊断四级（轻/中/重/急）
    F 判因四类（资源/上下文/逻辑/模型）
    G 治疗四级（假 hook 记账，验"真被调用"）
    H 一级治疗真的把回答修短了、且落在完整句
    I 病历落盘/读回/统计/预防建议/周报
    J streak 连续计数（中间插一轮干净的归零）
    K 健壮性（None/空串/半截 JSON/hook 全炸 —— 一律不崩）
    L 隔离机制（隔离→简化→解除）
    M 预防层（≥50 轮清上下文 / 空闲整理 / 凌晨自检）

【为什么自测的数据都写到临时目录】
    跑一次自测就去写用户的真实病历、真实隔离表、真实"今天已自检"标记，
    等于"测试污染生产状态"：用户今晚的凌晨自检会被自测吃掉，病历里混进 5 条假记录，
    之后所有预防建议都建立在假数据上。所以落盘路径一律注入临时目录。
"""
import json
import os
import re
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.health import degeneration as D          # noqa: E402
from core.health import monitor as MON             # noqa: E402
from core.health import diagnose as DIA            # noqa: E402
from core.health import heal as HEAL               # noqa: E402
from core.health import records as REC             # noqa: E402

PASS = []
FAIL = []
TMP = tempfile.mkdtemp(prefix="xj_health_selftest_")
REC_PATH = os.path.join(TMP, "records.jsonl")           # 病历组（I）专用
HEAL_REC_PATH = os.path.join(TMP, "heal_records.jsonl")  # 治疗组（G/H）专用
# 为什么治疗组和病历组要用两个文件：治疗层每治一次都会写一条病历。
# 混用一个文件的话，病历组的 total / heal_rate 会被前面治疗组的记录污染，
# 数字对不上 —— 于是"统计对不对"这条测试永远红着，或者（更糟）被人调宽了事。


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))
    return bool(cond)


# ---------------------------------------------------------------------------
# 语料
# ---------------------------------------------------------------------------
USER_CASE = "然后说：嗯。然后说：哦。然后说：好的。" * 25

# 正常中文长文（≥1200 字）：三段**互不重复**的正常产品说明。
# 为什么不用同一段重复两遍来凑字数：重复本身就是退化判据要抓的东西，
# 用重复文本测"不许误报"等于自己给自己下套（会测出假阳性）。
NORMAL_A = (
    "我们的产品定位是让中小团队用上专业级的数据分析能力。"
    "第一步，把散落在各个系统里的数据接进来，支持 CSV 导入、接口拉取和数据库直连三种方式。"
    "第二步，用可视化的方式把指标搭起来，不需要写查询语句也能做出看板。"
    "第三步，把看板分享出去，权限按角色控制，外部协作方只能看到被授权的页面。"
    "在性能上，单表千万行的聚合查询可以在一秒内返回，靠的是列式存储和预聚合。"
    "在成本上，我们按实际查询量计费，没有最低消费，小团队一个月的开销通常在几十元。"
    "安全方面，全链路加密、审计日志留存一年、支持私有化部署。"
    "服务上，提供中文文档和工单支持，工作日两小时内响应，紧急故障十五分钟内介入。"
    "未来的路线图里，我们计划加入自然语言的问数能力，让业务同学直接问问题就能拿到答案。"
    "同时会开放插件市场，让第三方把你的数据源接进来看板。"
    "如果你关心迁移成本，我们提供从主流工具一键导入的助手，字段映射会自动推断。"
    "总体而言，这个产品解决的是数据分析门槛高、上线慢、维护贵这三件事。"
)
NORMAL_B = (
    "另外要说清楚它的边界：它不替代数据仓库，也不做实时流计算。"
    "如果你的场景是每秒几十万条的埋点写入，应该先把数据落到离线库，再用它做分析。"
    "在权限模型上，我们区分管理员、编辑者和只读者三种角色，细到单张看板的字段级脱敏。"
    "导出能力支持图片、表格和公开链接三种形态，公开链接可以设置有效期与访问口令。"
    "我们也提供命令行工具，方便把看板生成接进你们自己的流水线里。"
    "对于体量特别大的客户，可以开启分区裁剪和结果缓存，把重复查询的开销降下来。"
    "在部署形态上，既支持单机安装，也支持容器编排，配置文件可以用环境变量覆盖。"
    "升级是原地进行的，历史数据不需要迁移，回滚只需要把镜像换回上一个版本。"
)
NORMAL_C = (
    "举个具体的例子：市场部的同学想知道上个月的投放回报，他打开看板，"
    "选好时间范围和渠道维度，几秒钟就能看到每个渠道的花费、线索和成交。"
    "如果发现某个渠道的成本明显偏高，他可以把这份看板分享给投放负责人，"
    "对方在手机上打开链接，看到的数字和电脑上一模一样。"
    "这些操作都不需要任何人写代码，也不需要等数据团队排期。"
    "对数据团队来说，他们只需要把口径定义一次，后面所有人看到的都是同一套数字。"
    "这就是我们做这件事的意义：把专业能力交到业务同学自己手里。"
)
NORMAL_D = (
    "最后说说怎么开始用：注册之后系统会给你一个示例工作区，里面已经放好了三张看板，"
    "可以直接点开看看效果。把示例里的数据源换成你自己的，改一次连接信息就能跑起来。"
    "如果不知道从哪下手，可以在帮助中心里按照五分钟上手的路径走一遍，每一步都有截图和说明。"
    "遇到问题可以在线提问，值班同学会在工作时段内回复；常见问题在文档里也能搜到答案。"
    "企业客户还可以预约一次一对一的配置讲解，我们把你们现有的报表一起迁过来，"
    "顺便把口径对齐，省得以后两边的数字对不上。"
)
NORMAL_E = (
    "我们也清楚这套东西有做不到的地方：它不擅长处理图片和视频这类非结构化内容，"
    "也不适合做需要人工判断的复杂决策。它的定位很清楚，就是把重复的取数和看数自动化，"
    "把人力留给真正需要思考的部分。如果你觉得有些场景它帮不上忙，"
    "欢迎把具体流程发给我们，我们会评估是补进路线图，还是老实告诉你现在做不了。"
)
NORMAL = NORMAL_A + NORMAL_B + NORMAL_C + NORMAL_D + NORMAL_E
# logic_gap 的专用语料：既没有依据词（因为/由于/根据…）也没有数字的长文本
SCRATCH = "这是一段很长的说明文字，用来把上下文堆够长度而已。" * 6
# 情绪失控语料：同一轮里正负情绪词各 ≥3
EMOTION_TEXT = ("太好了，非常棒，我今天很开心，这个方案优秀，结果很完美，真是厉害。"
                "可是烦死了，这些都是垃圾，太无聊了，我做不到，算了，完全没意义。")
GARBLED_TEXT = "这是一段正常开头。" + "\x00\x01\x02" + "后面还有一点内容。"
TOOL_TRACE_6 = [{"tool": "web_search", "args": {"q": "同一个问题"}}] * 6
LONG_QUESTION = "能不能麻烦你帮我尽量详细地说明一下这个比较复杂的技术方案的优缺点和适用场景好吗"


def codes_of(mon, text, ctx=None):
    """跑一轮监测并取症状代码。"""
    return [s.code for s in mon.check(text, ctx or {})]


def make_hooks(fail=False, retry_reply=""):
    """造一套"记账用"的假 hook：把调用名和参数记进 list，供断言"真被调用"。

    为什么要记账而不是只看返回值：治疗层最危险的失败模式是
    "报告说治了、实际什么都没做"。只验返回值的测试**抓不到**这种失败 ——
    它必须验"那个动作真的被调用了"，甚至"只调用了一次"（三级要求只切一次火种）。
    """
    calls = []

    def mk(name, ret):
        def fn(*a, **k):
            calls.append({"name": name, "args": list(a)})
            if fail:
                raise RuntimeError("假 hook 故意抛异常：%s" % name)
            return ret
        return fn

    hooks = {
        "retry": mk("retry", retry_reply),
        "reset_context": mk("reset_context", True),
        "reload_kv": mk("reload_kv", True),
        "switch_brain": mk("switch_brain", True),
        "rollback": mk("rollback", True),
        "pause_task": mk("pause_task", True),
        "shutdown": mk("shutdown", True),
        "snapshot": mk("snapshot", os.path.join(TMP, "snap_fake.json")),
        "notify": mk("notify", True),
        "organize": mk("organize", True),
    }
    return hooks, calls


def hit(calls, name):
    return [c for c in calls if c["name"] == name]


def make_healer(hooks=None, records=None, **cfg):
    """造一个把状态全写进临时目录的治疗器（绝不碰用户的真实病历/状态）。"""
    c = {"probe_resources": False, "iso_path": os.path.join(TMP, "isolated.json"),
         "state_path": os.path.join(TMP, "state.json"),
         "pause_path": os.path.join(TMP, "paused.json"),
         "shutdown_path": os.path.join(TMP, "shutdown.json"),
         "switch_path": os.path.join(TMP, "switch.json"),
         "notify_path": os.path.join(TMP, "notify.jsonl"), "snapshot_dir": TMP}
    c.update(cfg)
    return HEAL.HealthHealer(hooks=hooks,
                             records=records or REC.HealthRecords(path=HEAL_REC_PATH), cfg=c)


def main():
    print("=" * 66)
    print("  小焦健康系统自测（监测 / 诊断 / 治疗 / 病历 / 预防）")
    print("=" * 66)

    # ---------------------------------------------------------------- A
    print("\n[A] 18 类症状登记表")
    table = MON.HealthMonitor.SYMPTOMS
    ck("A", "登记表正好 18 类", len(table) == 18, len(table))
    groups = {}
    for code, row in table.items():
        groups[row[0]] = groups.get(row[0], 0) + 1
    ck("A", "语言 4 / 逻辑 4 / 情绪 3 / 行为 4 / 生理 3",
       groups == {"language": 4, "logic": 4, "emotion": 3, "behavior": 4, "physio": 3}, groups)
    ck("A", "每条都有中文名/默认严重度/判据说明",
       all(len(r) == 4 and r[1] and r[2] in ("light", "medium", "heavy") and len(r[3]) > 8
           for r in table.values()))
    ck("A", "每个 code 都有对应的判据函数",
       all(callable(getattr(MON.HealthMonitor, "_p_" + c, None)) for c in table), sorted(table))
    ck("A", "弱信号在判据说明里写明（logic_gap / fact_reversal）",
       all("弱信号" in table[c][3] for c in ("logic_gap", "fact_reversal")))

    # ---------------------------------------------------------------- B
    print("\n[B] 逐类触发（18 类，每类一个最小输入）")
    cases = [
        ("repeat", USER_CASE, {}, None),
        ("garbled", GARBLED_TEXT, {}, None),
        ("broken_sentence", NORMAL_A[:180] + "然后它就", {}, None),
        ("pace_shift", NORMAL_A[:400], {}, [NORMAL_A[:40]] * 5),
        ("self_contradiction", "这个方案是可行的。这个方案不是可行的。", {}, None),
        ("off_topic", NORMAL_A, {"expectations": ["装饰器", "函数", "语法"]}, None),
        ("logic_gap", SCRATCH + "因此我们得出结论。", {}, None),
        ("fact_reversal", "这个模型是闭源的。", {"prev_output": "这个模型是开源的。"}, None),
        ("sudden_anger", "你闭嘴，别问了。", {}, None),
        ("sudden_negativity", "我做不到，算了，这件事没意义。", {}, None),
        ("emotion_swing", EMOTION_TEXT, {}, None),
        ("tool_misuse", "", {"tool_trace": TOOL_TRACE_6}, None),
        ("tool_skipped", "", {"is_tool_turn": True, "question": "帮我查一下今天的天气"}, None),
        ("refusal", "抱歉，我不能帮你做这件事。", {}, None),
        ("infinite_loop", "", {"tool_trace": [("web_search", {"q": "同一个"})] * 3}, None),
        ("timeout", "", {"elapsed_ms": 30000, "timeout_ms": 20000}, None),
        ("vram_alert", "", {"vram_used_pct": 0.95}, None),
        ("memory_growth", "", {"mem_growth_pct": 45}, None),
    ]
    covered = 0
    for code, text, ctx, hist in cases:
        m = MON.HealthMonitor()
        for h in (hist or []):
            m.check(h)
        got = codes_of(m, text, ctx)
        ok = ck("B", "触发 %s" % code, code in got, got)
        covered += 1 if ok else 0
    ck("B", "18 类全部可触发", covered == 18, "%d/18" % covered)

    print("\n  -- 弱信号与易误伤的判据：正常情况下必须**不报** --")
    ck("B", "logic_gap 不误报（有依据词 + 数字）",
       "logic_gap" not in codes_of(MON.HealthMonitor(),
                                   NORMAL_A + "因为实测延迟只有 20 毫秒，所以可以放心用。"))
    ck("B", "fact_reversal 不误报（同一属性）",
       "fact_reversal" not in codes_of(MON.HealthMonitor(), "这个模型是开源的。",
                                       {"prev_output": "这个模型是开源的。"}))
    ck("B", "refusal 不误报（给了替代方案）",
       "refusal" not in codes_of(MON.HealthMonitor(),
                                 "我不能直接改你的文件，不过我可以给你一条命令，"
                                 "你在终端里执行就可以了。"))
    ck("B", "sudden_negativity 不误报（说的是事不是自己）",
       "sudden_negativity" not in codes_of(MON.HealthMonitor(),
                                           "如果网络不通就没意义了，我们要提前准备离线方案。"))
    ck("B", "tool_skipped 不误报（闲聊轮没有工具轨迹是正常的）",
       "tool_skipped" not in codes_of(MON.HealthMonitor(), "今天过得怎么样？",
                                      {"question": "今天过得怎么样？"}))
    ck("B", "broken_sentence 不误报（markdown 列表/标题不以句号结尾）",
       "broken_sentence" not in codes_of(MON.HealthMonitor(),
                                         "# 标题\n- 第一点内容\n- 第二点内容\n- 第三点内容"))
    ck("B", "garbled 不误报（别的语言的字母不是乱码）",
       "garbled" not in codes_of(MON.HealthMonitor(),
                                 "これは日本語のテキストです。正常な中文も混ざっています。" * 3))
    ck("B", "emotion_swing 不误报（正负各一两条是正常的）",
       "emotion_swing" not in codes_of(MON.HealthMonitor(),
                                       "这个方案太好了，但预算可能不太行，我们再看看。"))
    ck("B", "off_topic 不误报（回答确实在讲这件事）",
       "off_topic" not in codes_of(MON.HealthMonitor(), NORMAL_A,
                                   {"question": "请介绍一下这套数据分析产品的功能和价格"}))
    mp = MON.HealthMonitor()
    for _ in range(5):
        mp.check(NORMAL_A[:400])          # 先跑 5 轮长度相近的正常回答，建立语速基线
    ck("B", "pace_shift 不误报（第 6 轮长度和基线差不多）",
       "pace_shift" not in codes_of(mp, NORMAL_A[:430]), mp.streak("pace_shift"))

    # ---------------------------------------------------------------- C
    print("\n[C] 用户实测原句（然后说：嗯。然后说：哦。然后说：好的。×25）")
    m = MON.HealthMonitor()
    got = codes_of(m, USER_CASE, {"where": "test_user_case"})
    ck("C", "repeat 症状被检出", "repeat" in got, got)
    h = D.detect(USER_CASE, where="test_health_user_case")
    ck("C", "底层退化检测器确实命中（监测层直接复用它）", h is not None, str(h))
    sym = [s for s in m.check(USER_CASE) if s.code == "repeat"]
    ev = (sym[0].evidence if sym else {})
    ck("C", "证据里带重复次数/短语（能直接进病历）",
       ev.get("count", 0) >= 10 and bool(ev.get("phrase")), ev)

    # ---------------------------------------------------------------- D
    print("\n[D] 正常长文不许误报（%d 字）" % len(NORMAL))
    ck("D", "语料够长（≥1200 字）", len(NORMAL) >= 1200, len(NORMAL))
    got = codes_of(MON.HealthMonitor(), NORMAL)
    ck("D", "check() 返回空列表", got == [], got)
    got2 = codes_of(MON.HealthMonitor(), NORMAL,
                    {"question": "请说明这个数据分析产品的主要能力", "turns": 3})
    ck("D", "带一个正常 context 也不误报", got2 == [], got2)
    ck("D", "五段语料各自单独也不误报",
       all(codes_of(MON.HealthMonitor(), t) == []
           for t in (NORMAL_A, NORMAL_B, NORMAL_C, NORMAL_D, NORMAL_E)))

    # ---------------------------------------------------------------- E
    print("\n[E] 诊断四级")
    d = DIA.HealthDiagnose()
    ck("E", "LIGHT：单次轻症", d.diagnose(["broken_sentence"])["severity"] == "LIGHT",
       d.diagnose(["broken_sentence"])["severity"])
    ck("E", "MEDIUM：同一轮 ≥3 个症状",
       d.diagnose(["broken_sentence", "pace_shift", "logic_gap"])["severity"] == "MEDIUM",
       d.diagnose(["broken_sentence", "pace_shift", "logic_gap"])["severity"])
    m = MON.HealthMonitor()
    syms = []
    for _ in range(3):
        syms = m.check(USER_CASE)
    ck("E", "MEDIUM：同一症状连续 3 轮（streak=3）",
       DIA.HealthDiagnose(monitor=m).diagnose(syms)["severity"] == "MEDIUM",
       DIA.HealthDiagnose(monitor=m).diagnose(syms)["severity"])
    m2 = MON.HealthMonitor()
    for _ in range(2):
        syms2 = m2.check("", {"tool_trace": TOOL_TRACE_6})
    ck("E", "HEAVY：heavy 级症状连续 ≥2 轮",
       DIA.HealthDiagnose(monitor=m2).diagnose(syms2)["severity"] == "HEAVY",
       DIA.HealthDiagnose(monitor=m2).diagnose(syms2)["severity"])
    ck("E", "HEAVY：症状持续 + 资源告警",
       d.diagnose(["repeat", "memory_growth"], {"streak": {"repeat": 3}})["severity"] == "HEAVY",
       d.diagnose(["repeat", "memory_growth"], {"streak": {"repeat": 3}})["severity"])
    m3 = MON.HealthMonitor()
    for _ in range(3):
        syms3 = m3.check(GARBLED_TEXT)
    ck("E", "EMERGENCY：乱码连续 ≥3 轮",
       DIA.HealthDiagnose(monitor=m3).diagnose(syms3)["severity"] == "EMERGENCY",
       DIA.HealthDiagnose(monitor=m3).diagnose(syms3)["severity"])
    ck("E", "EMERGENCY：显存告警 + 超时同时出现",
       d.diagnose(["vram_alert", "timeout"])["severity"] == "EMERGENCY")
    ck("E", "EMERGENCY：安全类症状",
       d.diagnose(["harmful_content"])["severity"] == "EMERGENCY")
    rep = d.diagnose(["repeat", "garbled"])
    ck("E", "诊断结果字段齐全",
       all(k in rep for k in ("severity", "cause", "codes", "reason", "advice", "streak")), list(rep))

    # ---------------------------------------------------------------- F
    print("\n[F] 判因四类")
    ck("F", "resource（显存/内存/超时）",
       d.diagnose(["memory_growth", "broken_sentence"])["cause"] == "resource",
       d.diagnose(["memory_growth", "broken_sentence"])["cause"])
    ck("F", "context（轮数过多 + 症状集中在跑题/矛盾）",
       d.diagnose(["off_topic", "self_contradiction"],
                  {"turns": 60, "input_chars": 9000})["cause"] == "context",
       d.diagnose(["off_topic", "self_contradiction"], {"turns": 60})["cause"])
    ck("F", "logic（症状集中在推理链上）",
       d.diagnose(["logic_gap", "fact_reversal"], {"turns": 5})["cause"] == "logic",
       d.diagnose(["logic_gap", "fact_reversal"], {"turns": 5})["cause"])
    ck("F", "model（复读/情绪/工具类）",
       d.diagnose(["repeat", "sudden_anger", "infinite_loop"])["cause"] == "model",
       d.diagnose(["repeat", "sudden_anger", "infinite_loop"])["cause"])
    ck("F", "轮数不多时不许把锅甩给上下文",
       d.diagnose(["off_topic", "self_contradiction"], {"turns": 5})["cause"] == "logic",
       d.diagnose(["off_topic", "self_contradiction"], {"turns": 5})["cause"])

    # ---------------------------------------------------------------- G
    print("\n[G] 治疗四级（假 hook 记账：验「真被调用」）")
    hooks, calls = make_hooks(retry_reply="这是重做之后的回答。")
    h1 = make_healer(hooks)
    res = h1.heal("LIGHT", output=USER_CASE, question="写一段产品介绍")
    ck("G", "一级：治完的文本更短", len(res.output) < len(USER_CASE),
       "%d → %d" % (len(USER_CASE), len(res.output)))
    ck("G", "一级：note 为空串（用户无感）", res.note == "", repr(res.note))
    ck("G", "一级：真的动了文本（action 有记录）", bool(res.action) and res.action != "none",
       res.action)
    ck("G", "一级：detail 里记了砍掉多少字", res.detail.get("cut_chars", 0) > 0,
       res.detail.get("cut_chars"))

    calls.clear()
    res = h1.heal("LIGHT", output="", question="帮我写一段介绍")
    ck("G", "一级③：校验不过 → 调用 retry 重做",
       len(hit(calls, "retry")) == 1, [c["name"] for c in calls])
    ck("G", "一级③：重试只做一次（不许死循环）", len(hit(calls, "retry")) <= 1)
    ck("G", "一级：hook 调用被记进 detail[hooks]",
       any(x.get("name") == "retry" for x in res.detail.get("hooks", [])),
       len(res.detail.get("hooks", [])))

    calls.clear()
    hooks2, calls2 = make_hooks(retry_reply="重新组织后的回答。")
    h2 = make_healer(hooks2)
    res2 = h2.heal("MEDIUM", session={"sid": "s-g2", "turns": 20}, symptoms=["repeat"],
                   output="旧回答内容", question=LONG_QUESTION)
    ck("G", "二级：调用 reset_context（清上下文）", len(hit(calls2, "reset_context")) == 1)
    ck("G", "二级：调用 reload_kv（重置模型状态）", len(hit(calls2, "reload_kv")) == 1)
    ck("G", "二级：note 含「重新组织」", "重新组织" in res2.note, repr(res2.note))
    dq = res2.detail.get("degraded_question")
    ck("G", "二级：降级问法更短且被记录", bool(dq) and len(dq) < len(LONG_QUESTION),
       "%r（%d → %d）" % (dq, len(LONG_QUESTION), len(dq or "")))
    ck("G", "二级：重试用的是**降级后**的问法",
       any(c["args"] and c["args"][0] == dq for c in hit(calls2, "retry")),
       [c["args"][:1] for c in hit(calls2, "retry")])

    hooks3, calls3 = make_hooks()
    h3 = make_healer(hooks3)
    res3 = h3.heal("HEAVY", session={"sid": "s-g3", "turns": 30},
                   symptoms=["self_contradiction", "off_topic", "logic_gap"],
                   output="前后矛盾的回答", question=LONG_QUESTION)
    ck("G", "三级：调用 switch_brain（切备用火种）", len(hit(calls3, "switch_brain")) == 1)
    ck("G", "三级：调用 rollback（回滚会话）", len(hit(calls3, "rollback")) == 1)
    ck("G", "三级：调用 pause_task（暂停待恢复）", len(hit(calls3, "pause_task")) == 1)
    ck("G", "三级：报告含「需要休息一下」", "需要休息一下" in res3.note, res3.note[:60])
    ck("G", "三级：报告里带原因和建议", "原因：" in res3.note and "建议：" in res3.note)
    ck("G", "三级：半自动 —— 不自动重试", len(hit(calls3, "retry")) == 0)
    ck("G", "三级：output 为空（不该继续作答）", res3.output == "")

    hooks4, calls4 = make_hooks()
    h4 = make_healer(hooks4)
    res4 = h4.heal("EMERGENCY", session={"sid": "s-g4"}, symptoms=["garbled", "refusal"],
                   output="乱码文本", question="随便问问")
    ck("G", "四级：调用 shutdown", len(hit(calls4, "shutdown")) == 1)
    ck("G", "四级：调用 snapshot 保留现场", len(hit(calls4, "snapshot")) == 1)
    ck("G", "四级：调用 notify 强通知", len(hit(calls4, "notify")) == 1)
    ck("G", "四级：notify 的级别是 4",
       bool(hit(calls4, "notify")) and hit(calls4, "notify")[0]["args"][0] == 4,
       hit(calls4, "notify")[0]["args"][:1] if hit(calls4, "notify") else None)
    ck("G", "四级：不重试、不继续生成", len(hit(calls4, "retry")) == 0 and res4.output == "")
    ck("G", "四级：level=4 且有给用户看的报告", res4.level == 4 and bool(res4.note))

    # ---------------------------------------------------------------- H
    print("\n[H] 一级治疗的「修好回答」：更短 + 落在完整句")
    h5 = make_healer()
    res5 = h5.heal("LIGHT", output=NORMAL_A[:120] + USER_CASE, question="写一段介绍")
    ck("H", "比输入短", len(res5.output) < len(NORMAL_A[:120] + USER_CASE),
       "%d → %d" % (len(NORMAL_A[:120] + USER_CASE), len(res5.output)))
    ck("H", "落在完整句（句末标点收尾）",
       bool(res5.output.strip()) and res5.output.rstrip()[-1] in "。！？!?；;…",
       repr(res5.output[-14:]))
    ck("H", "保留了复读之前的正常正文", "我们的产品定位" in res5.output)
    ck("H", "复读没有留下几十次", res5.output.count("然后说：") <= 3,
       res5.output.count("然后说："))

    # ---------------------------------------------------------------- I
    print("\n[I] 病历")
    rec = REC.HealthRecords(path=REC_PATH)
    default_rec = REC.HealthRecords()
    ck("I", "默认病历路径就是 logs/health/records.jsonl",
       default_rec.path.replace("\\", "/").endswith("logs/health/records.jsonl"),
       default_rec.path)
    rec.log("repeat", "LIGHT", "truncate_repeat", {"ok": True, "note": "截断 120 字"},
            {"turns": 3, "model": "xiaojiao1.0-4B", "question": "写三千字产品介绍",
             "output": "然后说：嗯。" * 40, "elapsed_ms": 900})
    rec.log(["off_topic", "pace_shift"], "MEDIUM", "reset_context+retry",
            {"ok": True, "note": "已重新组织"},
            {"turns": 55, "question": "介绍产品", "output": "跑题的回答", "vram_used_pct": 0.55})
    rec.log("vram_alert", "HEAVY", "switch_brain", True, {"turns": 60, "model": "xiaojiao1.0-4B"})
    rec.log("refusal", "EMERGENCY", "shutdown", False,
            {"turns": 61, "question": "帮我删掉这个文件", "output": "我不能帮你做这件事"})
    rec.log("logic_gap", "LIGHT", "none", "只记录未治疗", {"turns": 62})
    rows = rec.read(days=7)
    need = ("ts", "iso_time", "symptom", "group", "severity", "trigger", "action",
            "result", "ok", "context")
    ck("I", "read() 读回 5 条", len(rows) == 5, len(rows))
    ck("I", "字段齐全（ts/iso_time/symptom/group/severity/trigger/action/result/ok/context）",
       all(all(k in r for k in need) for r in rows),
       [k for k in need if not all(k in r for r in rows)])
    ck("I", "组别正确（language / logic / physio / behavior）",
       {r["group"] for r in rows} >= {"language", "logic", "physio", "behavior"},
       sorted({r["group"] for r in rows}))
    ck("I", "context 快照含轮数/模型/问题前 80 字/输出前 200 字",
       rows[0]["context"].get("turns") == 3 and rows[0]["context"].get("model")
       and rows[0]["context"].get("question") and rows[0]["context"].get("output_head"),
       rows[0]["context"])
    ck("I", "context 里的输出被截断（不留全文）",
       len(rows[0]["context"].get("output_head", "")) <= 201,
       len(rows[0]["context"].get("output_head", "")))
    a = rec.analyze(days=7)
    ck("I", "analyze 的 total 对得上", a["total"] == 5, a["total"])
    ck("I", "by_severity 加起来 == total",
       sum(a["by_severity"].values()) == 5, a["by_severity"])
    ck("I", "by_symptom 统计到多症状记录",
       a["by_symptom"].get("off_topic") == 1 and a["by_symptom"].get("repeat") == 1,
       a["by_symptom"])
    ck("I", "heal_rate 是 3/5", abs(a["heal_rate"] - 0.6) < 1e-6, a["heal_rate"])
    ck("I", "top_symptoms 按次数排序", isinstance(a["top_symptoms"], list)
       and all(len(x) == 2 for x in a["top_symptoms"]), a["top_symptoms"][:3])
    ck("I", "worst_day 有值", bool(a["worst_day"]), a["worst_day"])
    ck("I", "trend 合法", a["trend"] in ("恶化", "好转", "平稳"), a["trend"])
    tips = rec.suggest_prevention()
    ck("I", "suggest_prevention 至少 1 条", len(tips) >= 1, len(tips))
    ck("I", "预防建议里带真实数字", all(re.search(r"\d", t) for t in tips) and len(tips) > 1,
       tips[0][:60])
    wr = rec.weekly_report(days=7)
    ck("I", "weekly_report 非空且是中文报告",
       bool(wr.strip()) and "健康周报" in wr and "预防建议" in wr, len(wr))
    ck("I", "周报里带数字", bool(re.search(r"\d", wr)))

    # ---------------------------------------------------------------- J
    print("\n[J] streak：连续计数 + 中间插一轮干净的归零")
    m = MON.HealthMonitor()
    for _ in range(3):
        m.check(USER_CASE)
    ck("J", "连续 3 轮同症状 → streak=3", m.streak("repeat") == 3, m.streak("repeat"))
    m.check(NORMAL)
    ck("J", "插一轮干净的 → 归零", m.streak("repeat") == 0, m.streak("repeat"))
    m.check(USER_CASE)
    ck("J", "再犯一次 → 从 1 重新数", m.streak("repeat") == 1, m.streak("repeat"))
    ck("J", "没出现过的症状 streak=0", m.streak("vram_alert") == 0)

    # ---------------------------------------------------------------- K
    print("\n[K] 健壮性：一律不崩")
    m = MON.HealthMonitor()
    ck("K", "check(None) 不崩且返回 list",
       isinstance(m.check(None), list), type(m.check(None)).__name__)
    ck("K", "check('') 不崩且返回空", m.check("") == [])
    ck("K", "check(非字符串) 不崩", isinstance(m.check(12345), list))
    ck("K", "context 不是 dict 也不崩", isinstance(m.check(NORMAL, "不是 dict"), list))
    ck("K", "畸形 context（类型全错）也不崩",
       isinstance(m.check(NORMAL, {"vram_used_pct": "很满", "elapsed_ms": object(),
                                   "tool_trace": 3, "history": "x"}), list))
    ck("K", "畸形配置不崩",
       isinstance(MON.HealthMonitor(cfg={"min_text_chars": "abc", "vram_alert_pct": None,
                                         "off_topic_hit_rate": "很高"}).check(NORMAL), list))
    ck("K", "detect(None) 不崩", isinstance(MON.detect(None), list))
    hk = DIA.HealthDiagnose()
    ck("K", "diagnose(None) 给得出判断", hk.diagnose(None)["severity"] in DIA.SEVERITY)
    ck("K", "diagnose(单个字符串)", hk.diagnose("repeat")["severity"] in DIA.SEVERITY)
    ck("K", "diagnose(session 不是 dict)",
       hk.diagnose(["repeat"], "session 应该是 dict")["severity"] in DIA.SEVERITY)
    ck("K", "diagnose(畸形 session 值)",
       hk.diagnose(["repeat"], {"turns": "好多轮", "history": 123,
                                "streak": {"repeat": "三"}})["severity"] in DIA.SEVERITY)

    bad_hooks, _c = make_hooks(fail=True)
    hb = make_healer(bad_hooks)
    ok_all = True
    for lvl in ("LIGHT", "MEDIUM", "HEAVY", "EMERGENCY"):
        try:
            r = hb.heal(lvl, session={"sid": "s-bad"}, symptoms=["repeat"], output=USER_CASE,
                        question=LONG_QUESTION)
            ok_all = ok_all and r is not None and isinstance(r.note, str)
        except Exception as e:      # noqa: BLE001 — 崩了就是测试失败
            ok_all = False
            print("     异常：%r" % (e,))
    ck("K", "hooks 全部抛异常时四级治疗都不崩", ok_all)
    rb = hb.heal("MEDIUM", session={"sid": "s-bad2"}, symptoms=["repeat"], output="x",
                 question=LONG_QUESTION)
    ck("K", "hook 抛异常被如实记为失败（不假装成功）",
       rb.ok is False and any(not x.get("ok") for x in rb.detail.get("hooks", [])),
       [(x.get("name"), x.get("ok")) for x in rb.detail.get("hooks", [])][:3])

    half = os.path.join(TMP, "half.jsonl")
    with open(half, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "symptom": "repeat", "severity": "LIGHT",
                            "ok": True, "codes": ["repeat"], "day": "2026-01-01"},
                           ensure_ascii=False) + "\n")
        f.write('{"ts": 1.0, "symptom": "garb')      # 故意写半截（模拟被 kill）
    hr = REC.HealthRecords(path=half)
    ck("K", "records.jsonl 半截 JSON → read 不崩", isinstance(hr.read(days=7), list))
    ck("K", "半截行被跳过、好行保留", len(hr.read(days=7)) == 1, len(hr.read(days=7)))
    ck("K", "半截 JSON → analyze 不崩", hr.analyze(days=7)["total"] == 1)
    ck("K", "半截 JSON → 预防建议/周报不崩",
       isinstance(hr.suggest_prevention(), list) and bool(hr.weekly_report()))
    r = REC.HealthRecords(path=os.path.join(TMP, "bad_ctx.jsonl"))
    row = r.log("repeat", "LIGHT", "none", None, {"obj": object(), "q": {"嵌套": [object()]}})
    ck("K", "context 里有不可序列化对象 → 仍能落盘", isinstance(row, dict) and row.get("written"))
    ck("K", "records.log 的 result=None 不崩", row.get("result") is not None)
    ck("K", "heal 的 simplify(None) 不崩", isinstance(make_healer().simplify(None), str))
    ck("K", "heal(未知严重度) → level=0 不崩",
       make_healer().heal("不存在的级别", output="x").level == 0)

    # ---------------------------------------------------------------- L
    print("\n[L] 隔离机制")
    hl = make_healer()
    hl.release("s1")
    hl.isolate("s1", "测试：反复退化")
    ck("L", "isolate 之后 is_isolated 为 True", hl.is_isolated("s1"))
    ck("L", "隔离记录里带原因和时间", bool(hl._iso().get("s1", {}).get("reason")))
    simple = hl.simplify(LONG_QUESTION)
    ck("L", "simplify 返回更短的问法",
       isinstance(simple, str) and 0 < len(simple) < len(LONG_QUESTION),
       "%r（%d → %d）" % (simple, len(LONG_QUESTION), len(simple)))
    hl.release("s1")
    ck("L", "release 之后 is_isolated 为 False", not hl.is_isolated("s1"))
    hl2 = make_healer()
    hl2.release("s2")
    for _ in range(3):
        hl2.note_relapse("s2", "MEDIUM", "model")
    ck("L", "同一会话反复退化 3 次 → 自动隔离", hl2.is_isolated("s2"))
    hl2.release("s2")
    ck("L", "轻症不计入隔离", (hl2.note_relapse("s3", "LIGHT", "model") is False)
       and not hl2.is_isolated("s3"))

    # ---------------------------------------------------------------- M
    print("\n[M] 预防层")
    hooks5, calls5 = make_hooks()
    hm = make_healer(hooks5)
    rep = hm.preventive({"turns": 60, "hour": 12})
    ck("M", "连续 60 轮 → 清一次上下文（hook 真被调用）",
       len(hit(calls5, "reset_context")) == 1,
       [c["name"] for c in calls5])
    ck("M", "报告里说明为什么清", any("轮" in n for n in rep.get("notes", [])),
       rep.get("notes"))
    calls5.clear()
    rep2 = hm.preventive({"turns": 3, "hour": 12})
    ck("M", "轮数不多时不动上下文", len(hit(calls5, "reset_context")) == 0)
    ck("M", "不动时也给一句说明", bool(rep2.get("notes")))
    calls5.clear()
    rep3 = hm.preventive({"turns": 3, "hour": 12, "idle_s": 3600})
    ck("M", "空闲 60 分钟 → 后台整理", len(hit(calls5, "organize")) == 1)
    calls5.clear()
    rep4 = hm.preventive({"turns": 3, "hour": 3})
    ck("M", "凌晨 3 点 → 全面自检",
       any(a.get("name") == "self_check" for a in rep4.get("actions", [])), rep4.get("actions"))
    ck("M", "自检报告里有退化统计/病历/资源三块",
       all(k in (rep4.get("self_check") or {}) for k in ("degeneration", "records", "resources")))
    ck("M", "自检带中文摘要", bool((rep4.get("self_check") or {}).get("summary")))
    sc = hm.self_check()
    ck("M", "self_check() 单独调用也能出报告",
       isinstance(sc, dict) and "degeneration" in sc and "records" in sc and "resources" in sc)
    ck("M", "预防层遵守配置开关（preventive=False 时不动）",
       make_healer(**{"preventive": False}).preventive({"turns": 99})["ok"] is False)

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 66)
    total = len(PASS) + len(FAIL)
    print("  通过 %d / 共 %d%s" % (len(PASS), total,
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("  临时数据目录：%s" % TMP)
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
