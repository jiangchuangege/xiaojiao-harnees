# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""能力增益包（boost，模块 10）自测 —— 真跑，不模拟（离线、秒级、不调任何模型）

运行：python -W ignore tools/test_boost.py

【为什么这个自测必须离线、必须一秒能跑完】
    boost 七件套的全部价值都在"模型不行的时候载体替它想"。
    如果验一次要真起一个 4B 模型，那这套代码就跟健康系统一样，
    变成**没人跑过的救命代码** —— 只在出事时才被想起来，而那时已经晚了。
    所以这里全程只调纯规则函数：要验的是"载体自己的判断对不对、
    结构有没有真的变大、边界会不会崩"，不是"模型答得好不好"。

【为什么每条断言都要带"证据"】
    `✅ [B] detect_cycle 在真造的环上返回非空  ← ['n1','n2','n3','n1']`
    比 `✅ [B] detect_cycle ok` 有用得多：失败的那天，你不用重跑一遍就能
    从 CI 日志里看出"它到底返回了什么"。这套件的断言密度高（上百条），
    没有证据的话，一条红就只能靠人肉复现。

【为什么自测数据都写到临时目录，只有少数几条故意写真实路径】
    全是临时目录 → 验不出"默认落盘路径到底通不通"（而路径拼错是本项目
    历史上真出过的事）；全写真实路径 → 每跑一次自测就往 logs/boost/ 里
    堆一条测试数据，越堆越多，用户的真实结构被自测灌水。
    所以：**逻辑用临时目录，落盘真实性用真实路径 + 跑完还原文件内容**。
    还原方式是"把原文写回去"，不是删除文件 —— 本项目红线是绝不删除任何文件。

【为什么这里要扫描源码里有没有删除调用（第 H 组）】
    "绝不删除任何文件"是项目红线，而红线这种东西靠自觉是守不住的：
    某天有人为了"清理临时文件"顺手加一句 os.remove，review 时不一定看得见。
    用 ast 扫一遍**真实调用**（不是文本匹配，否则连注释里写"不许 os.remove"都会误报），
    成本几毫秒，却能在合入前就把这类改动拦下来。

覆盖（9 组）：
    A 元推理模板库（≥30 种、覆盖 33 个必备推理概念、规则选型、渲染、追加落盘）
    B 长链因果图（造环/无环、回溯标记不删、冲突、链/根/叶、存档往返）
    C 跨领域联想（≥8 领域、三条必备结构映射、领域向量、异领域类比）
    D 模糊意图（真模糊才反问、明确问题不许反问、候选问法、多假设）
    E 创造性（视角表、算子表、同 seed 可复现、跨进程可复现、随机种子）
    F 单次深度推理（CoT/ToT/自我质疑/分而治之/自动选型/llm_fn=None 规则打分）
    G 超长一致性（实体抽取、别名归一保留首次写法、同名异类冲突、关系矛盾、前后校验）
    H 红线与独立性（没有任何删除调用、独立 import 不拉 Flask/app、落盘真实可读回）
    I 边界（None/空串/超长串/未知 id 一律不崩）
"""
import ast
import os
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.boost import BOOST_DIR, boost_path                    # noqa: E402
from core.boost import read_json, read_jsonl                    # noqa: E402
from core.boost import analogy as AN                            # noqa: E402
from core.boost import causal as CA                             # noqa: E402
from core.boost import consistency as CO                        # noqa: E402
from core.boost import creative as CR                           # noqa: E402
from core.boost import deepthink as DT                          # noqa: E402
from core.boost import reasoning as R                           # noqa: E402
from core.boost import vague as VA                              # noqa: E402

PASS = []
FAIL = []
TMP = tempfile.mkdtemp(prefix="xj_boost_selftest_")

# boost 七件套的源码路径（第 H 组要静态扫它们）
_MODS = {
    "reasoning": os.path.join(_ROOT, "core", "boost", "reasoning.py"),
    "causal": os.path.join(_ROOT, "core", "boost", "causal.py"),
    "analogy": os.path.join(_ROOT, "core", "boost", "analogy.py"),
    "vague": os.path.join(_ROOT, "core", "boost", "vague.py"),
    "creative": os.path.join(_ROOT, "core", "boost", "creative.py"),
    "deepthink": os.path.join(_ROOT, "core", "boost", "deepthink.py"),
    "consistency": os.path.join(_ROOT, "core", "boost", "consistency.py"),
    "init": os.path.join(_ROOT, "core", "boost", "__init__.py"),
}
_MOTTO = [
    "# 小焦系统本身不依赖任何具体模型。",
    "# 它是完整的载体（器官齐全），模型是火种（可替换）。",
    "# 接入任何模型 → 系统活；换任何模型 → 系统不变。",
    '# 这就是"模型平等"和"变形金刚"的工程基础。',
]


def ck(group, name, cond, info=""):
    """记一条断言。为什么返回 bool：调用方偶尔要在后面复用这个判断，避免算两遍。"""
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))
    return bool(cond)


def snap(path):
    """读一个文件的**原始文本**（读不到返回 None）。

    ⚠️ 空文件按 `None` 归一（`or None`）：`restore()` 对 `None` 是**建/清空文件**，
    如果这里让空文件返回 `''`、而 restore 之后还是 `''`，两者本该相等 ——
    但只要有一步把 `None` 变成 `''`（或反过来），断言就会莫名其妙地红。
    实测踩到过：`logs/boost/consistency.json` 事先是 0 字节（外部原因）。
    统一口径：**"没有内容"只有一种表示**（None），省掉一整类"空串 vs None"的假失败。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read() or None
    except Exception:      # noqa: silent-ok — 文件本来不存在就是 None，属于正常情况
        return None


def restore(path, original):
    """把文件内容还原成测试前的样子（**内容截断/写回，绝不删除文件**）。

    为什么不是 os.remove：项目红线是绝不删除任何文件。
    为什么不是"留一份备份"：备份会一直堆在磁盘上，而自测跑完就该像没跑过一样。
    去掉它：每跑一次自测就往 logs/boost/ 里留一条测试数据，跑一百次就有一百条。
    """
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(original if original is not None else "")
        return True
    except Exception:      # noqa: silent-ok — 还原不上也不该让自测变成"失败"
        return False


def src_of(path):
    """读源码文本（读不到返回空串）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:      # noqa: silent-ok — 缺文件由"存在性"那条断言负责报错
        return ""


def deletion_calls(path):
    """用 ast 扫源码里**真实调用**到的删除类函数，返回名字列表。

    为什么用 ast 而不是正则扫文本：本项目的注释里到处写着"不许 os.remove /
    shutil.rmtree"，正则扫法会把**注释和文档字符串**当成违规，天天误报，
    误报到后来就没人看了 —— 那时红线就真的没人守了。ast 只看调用表达式。
    """
    try:
        tree = ast.parse(src_of(path))
    except Exception:      # noqa: silent-ok — 语法错由别的断言报，这里不重复报
        return []
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("remove", "unlink", "rmtree", "truncate",
                                  "rmdir", "removedirs", "unlink_"):
                bad.append(node.func.attr)
    return bad


def isolated_import(modname):
    """在**独立子进程**里 import 一个模块，返回 (ok, 证据)。

    为什么非要开子进程：本进程里 `core.boost` 早就 import 过了，
    就算这个模块偷偷依赖 Flask 也看不出来（Flask 可能已经被别的测试拉进来了）。
    只有全新解释器才能回答"单独装它一个能不能跑起来"这个真问题。
    """
    code = ("import sys\n"
            "import core.boost.%s as m\n"
            "bad = [k for k in ('flask', 'xiaojiao_app') if k in sys.modules]\n"
            "print('CLEAN' if not bad else 'DIRTY:' + ','.join(bad))\n" % modname)
    try:
        p = subprocess.run([sys.executable, "-W", "ignore", "-c", code],
                           cwd=_ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except Exception as e:      # noqa: silent-ok — 起不了子进程时如实报，不伪装通过
        return False, "子进程起不来：%r" % (e,)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    ok = (p.returncode == 0 and "CLEAN" in out)
    return ok, out.splitlines()[-1] if out else "(无输出)"


# ---------------------------------------------------------------------------
# 语料
# ---------------------------------------------------------------------------
# 一个信息完整的长问句：主语、对象、动作、约束全都齐了 —— 载体**不许**对它反问。
CLEAR_Q = "请把这段 Python 代码里的死循环改成 for 循环，并保留原来的注释"
# 一个典型的中文模糊请求：只有动词没有对象，还用了"搞一下"这种万能词。
VAGUE_Q = "帮我搞一下"
CIRCUIT = "电压不够，电流就小，电阻太大，整个回路断电了"

# 元推理模板库必须覆盖的 33 个概念（任务规格里点名的那些）
RSN_NEED = ("归纳", "演绎", "类比", "反证", "分解", "回溯", "博弈", "概率", "约束",
            "二分", "排除", "反事实", "极端", "量纲", "对称", "不变", "贪心",
            "动态规划", "分治", "逆向", "特例", "边界", "构造", "枚举", "剪枝",
            "优先级", "权衡", "成本", "风险", "第一性原理", "苏格拉底", "证伪", "奥卡姆")
PERS_NEED = ("孩子", "工程师", "诗人", "产品经理", "黑客", "老人", "外星人",
             "银行家", "老师", "医生")
OP_NEED = ("反转", "嫁接", "夸张", "缩小", "移位", "替换", "组合", "借形",
           "降维", "升维", "随机")
DOM_NEED = ("电路", "水管", "免疫", "安全", "市场", "生态", "建筑", "人体", "交通", "农业")


def main():
    print("=" * 68)
    print("  小焦 · 能力增益包（boost）自测 —— 真跑，不模拟")
    print("  临时数据目录：%s" % TMP)
    print("=" * 68)

    # ================================================================== A
    print("\n[A] 元推理模板库（10.1）")
    tp = R.TEMPLATES
    ck("A", "内置元推理模板 ≥30 种", len(tp) >= 30, "%d 种" % len(tp))
    ids = [t.get("id") for t in tp]
    ck("A", "30 个 id 全都唯一", len(set(ids)) == len(ids) and None not in ids,
       "%d 个 id / %d 个唯一" % (len(ids), len(set(ids))))
    fields_ok = all(all(t.get(f) for f in ("id", "name", "name_en", "when",
                                           "steps", "pitfalls"))
                    for t in tp)
    badf = [t.get("id") for t in tp
            if not all(t.get(f) for f in ("id", "name", "name_en", "when",
                                          "steps", "pitfalls"))]
    ck("A", "每条模板都含 id/name/name_en/when/steps/pitfalls", fields_ok, badf[:4])
    ck("A", "每条模板 name 与 name_en 都是非空字符串（中英文名都有）",
       all(isinstance(t.get("name"), str) and isinstance(t.get("name_en"), str)
           and t.get("name") and t.get("name_en") for t in tp))
    ck("A", "每条 steps 都是 ≥3 条非空提示词片段",
       all(isinstance(t.get("steps"), list) and len(t["steps"]) >= 3
           and all(isinstance(x, str) and x.strip() for x in t["steps"]) for t in tp),
       "最少 %d 步" % min(len(t.get("steps") or []) for t in tp))
    ck("A", "每条 pitfalls 都是 ≥2 条非空中文提醒",
       all(isinstance(t.get("pitfalls"), list) and len(t["pitfalls"]) >= 2
           and all(isinstance(x, str) and x.strip() for x in t["pitfalls"]) for t in tp))
    blob = " ".join("%s %s %s" % (t.get("name", ""), t.get("name_en", ""), t.get("id", ""))
                    for t in tp)
    miss = [k for k in RSN_NEED if k not in blob]
    ck("A", "规格点名的 33 个推理概念全都覆盖到了", not miss, ("缺：%s" % miss) if miss else "33/33")

    p1 = R.pick("为什么水结冰以后体积会变大")
    ck("A", "pick 对真问题返回模板（含 score/why 解释）",
       isinstance(p1, dict) and p1.get("id") and isinstance(p1.get("score"), float)
       and len(str(p1.get("why") or "")) > 2,
       "%s score=%s" % ((p1 or {}).get("id"), (p1 or {}).get("score")))
    ck("A", "pick 返回的就是库里的模板（id 可对上）",
       isinstance(p1, dict) and p1.get("id") in set(ids), (p1 or {}).get("id"))
    ck("A", "pick 的 why 引用到了命中的关键词（可解释）",
       isinstance(p1, dict) and any(k in str(p1.get("why")) for k in (p1.get("keywords") or [])
                                    if k), str((p1 or {}).get("why"))[:60])
    ck("A", "pick(None) 返回 None（没有信号就不许硬塞）", R.pick(None) is None)
    ck("A", "pick('') 返回 None", R.pick("") is None)
    ck("A", "pick('嗯嗯') 返回 None（寒暄不是推理题）", R.pick("嗯嗯") is None)
    ck("A", "pick 是可复现的（同问句两次同结果）",
       (R.pick("为什么水结冰以后体积会变大") or {}).get("id")
       == (R.pick("为什么水结冰以后体积会变大") or {}).get("id"))

    rp = R.render("induction", "为什么水结冰以后体积会变大")
    ck("A", "render 产出给模型的提示词（含原问题）",
       isinstance(rp, str) and "水结冰" in rp and len(rp) > 80, "%d 字" % len(rp or ""))
    ck("A", "render 里带上了 pitfalls（把这类推理的坑先讲清）",
       isinstance(rp, str) and any(k in rp for k in ("陷阱", "避免", "不要", "别", "坑")),
       rp[:60] if rp else "")
    ck("A", "render 对不存在的模板 id 不抛且仍有输出",
       isinstance(R.render("zz_not_exist_zz", "问题"), str))
    ck("A", "render(None, None) 不抛", isinstance(R.render(None, None), str))

    st = R.stats()
    ck("A", "stats 含 total/builtin/extended 且 total ≥ 30",
       isinstance(st, dict) and st.get("total", 0) >= 30
       and "builtin" in st and "extended" in st, st)
    at = R.all_templates()
    ck("A", "all_templates ≥ 内置条数（内置 + 追加合并）",
       isinstance(at, list) and len(at) >= len(tp), len(at))
    at2 = R.all_templates()
    if at2:
        at2[0]["name"] = "被自测改坏了"
    ck("A", "all_templates 返回副本（改它不污染库）",
       R.all_templates()[0].get("name") != "被自测改坏了")
    R.add({"id": "zz_selftest_tmp", "name": "自测临时模板", "name_en": "SelftestTmp",
           "when": "只在自测里用", "steps": ["一步", "两步", "三步"],
           "pitfalls": ["坑一", "坑二"], "keywords": ["自测临时"]}, save=True)
    ids2 = [t.get("id") for t in R.all_templates()]
    ck("A", "add 之后新模板进了合并库", "zz_selftest_tmp" in ids2)
    R.add({"id": "zz_selftest_tmp", "name": "自测临时模板改", "name_en": "SelftestTmp2",
           "when": "改", "steps": ["一"], "pitfalls": ["坑"], "keywords": []}, save=True)
    hit = [t for t in R.all_templates() if t.get("id") == "zz_selftest_tmp"]
    ck("A", "add 同 id 是覆盖不是新增（库里只有一个）",
       len(hit) == 1 and hit[0].get("name") == "自测临时模板改", len(hit))
    ck("A", "add({}) 缺字段也不抛（补默认值）", isinstance(R.add({}), dict))
    ck("A", "add(None) 不抛", isinstance(R.add(None), dict))
    ck("A", "load_extended 读不到时返回列表（不抛）",
       isinstance(R.load_extended(), list))

    # ================================================================== B
    print("\n[B] 长链因果图（10.2）")
    p_cyc = os.path.join(TMP, "cyc.json")
    g = CA.CausalGraph(path=p_cyc)
    a = g.add_node("下雨", kind="cause")
    b = g.add_node("地面湿", kind="effect")
    c = g.add_node("滑倒", kind="effect")
    g.add_edge(a, b, why="雨把地面打湿")
    g.add_edge(b, c, why="湿地面容易滑")
    ck("B", "无环图 detect_cycle 返回 []", g.detect_cycle() == [], g.detect_cycle())
    g.add_edge(c, a, why="自测故意造一个环")
    cyc = g.detect_cycle()
    ck("B", "真造了环 → detect_cycle 返回非空", bool(cyc), cyc)
    ck("B", "返回的环首尾是同一个节点（是闭链）",
       bool(cyc) and len(cyc) >= 3 and cyc[0] == cyc[-1], cyc)

    p_acy = os.path.join(TMP, "acy.json")
    g2 = CA.CausalGraph(path=p_acy)
    x = g2.add_node("A")
    y = g2.add_node("B")
    z = g2.add_node("C")
    g2.add_edge(x, y)
    g2.add_edge(y, z)
    ck("B", "干净的链式图 detect_cycle 仍为 []", g2.detect_cycle() == [])
    ck("B", "parents/children 认得对（B 的父=A 子=C）",
       g2.parents(y) == [x] and g2.children(y) == [z],
       "%s / %s" % (g2.parents(y), g2.children(y)))
    ck("B", "parents/children 对未知 id 返回 []（不抛）",
       g2.parents("zz_no_such_id") == [] and g2.children(None) == [])
    ch = g2.chains(x, depth=3)
    ck("B", "chains 从根出发给出非空链，且长度 ≤ depth",
       bool(ch) and max(len(c1) for c1 in ch) <= 3, ch)
    ck("B", "roots/leaves 认得对", g2.roots() == [x] and g2.leaves() == [z],
       "%s / %s" % (g2.roots(), g2.leaves()))
    gc = CA.CausalGraph(path=os.path.join(TMP, "cyc2.json"))
    gc.add_edge("甲", "乙")
    gc.add_edge("乙", "甲")
    conf = gc.detect_contradiction()
    ck("B", "同一对节点正反两条边 → detect_contradiction 非空", bool(conf), conf)
    ck("B", "无冲突的图 detect_contradiction 返回 []", g2.detect_contradiction() == [])
    ck("B", "add_edge 传文本会自动建节点（不必先 add_node）",
       len(gc.nodes()) == 2, [n.get("text") for n in gc.nodes()])

    p_ret = os.path.join(TMP, "ret.json")
    gr = CA.CausalGraph(path=p_ret)
    r1 = gr.add_node("前提：样本够大")
    r2 = gr.add_node("结论：分布稳定")
    r3 = gr.add_node("下游：可以直接下判断")
    gr.add_edge(r1, r2)
    gr.add_edge(r2, r3)
    n_before = len(gr.nodes())
    rr = gr.retract(r2, reason="自测：样本其实不够大")
    marked = {n.get("id"): n for n in gr.nodes()}
    ck("B", "retract 标记了下游节点（下游也失效）",
       bool(rr) and r3 in (rr.get("retracted") or []) if isinstance(rr, dict) else False,
       (rr or {}).get("retracted"))
    ck("B", "retract 之后节点**没被删除**（数量不变）",
       len(gr.nodes()) == n_before, "%d → %d" % (n_before, len(gr.nodes())))
    ck("B", "被撤的节点仍在 nodes() 里且带撤销理由",
       marked.get(r2, {}).get("retracted") is True
       and len(str(marked.get(r2, {}).get("retract_reason") or "")) > 0,
       marked.get(r2))
    ck("B", "retract 返回里带 reason（留下「为什么撤」）",
       isinstance(rr, dict) and "自测" in str(rr.get("reason") or ""), (rr or {}).get("reason"))
    ck("B", "retract 未知 id → ok=False 且不抛",
       isinstance(gr.retract("zz_no_such"), dict)
       and gr.retract("zz_no_such").get("ok") is False)

    prompt = gr.render_prompt("为什么最近销量下滑")
    ck("B", "render_prompt 要求先给因、再给果",
       isinstance(prompt, str) and "因" in prompt and "果" in prompt, prompt[:50])
    ck("B", "render_prompt 要求标不确定", "不确定" in (prompt or ""), prompt[-80:])
    ck("B", "render_prompt 把已知节点带进上下文", "样本够大" in (prompt or ""))
    ck("B", "render_prompt(None) 不抛", isinstance(gr.render_prompt(None), str))

    p_sl = os.path.join(TMP, "save.json")
    gs = CA.CausalGraph(path=p_sl)
    gs.add_edge("原因一", "结果一")
    gs.add_edge("结果一", "结果二")
    ck("B", "save 返回 True 且文件真的产生", gs.save() is True and os.path.exists(p_sl), p_sl)
    gl = CA.CausalGraph(path=p_sl)
    ck("B", "load 能把存档读回来", gl.load() is True)
    ck("B", "读回的节点数与边数与存前一致",
       len(gl.nodes()) == len(gs.nodes()) and len(gl.edges()) == len(gs.edges()),
       "%d节点/%d边 vs %d节点/%d边" % (len(gl.nodes()), len(gl.edges()),
                                       len(gs.nodes()), len(gs.edges())))
    gb = CA.build_from_pairs([("因A", "果A"), ("果A", "果B")])
    ck("B", "build_from_pairs 能从纯文本对快速建图",
       len(gb.nodes()) == 3 and len(gb.edges()) == 2,
       "%d节点/%d边" % (len(gb.nodes()), len(gb.edges())))
    ck("B", "stats 含 nodes/edges/roots/leaves/has_cycle",
       all(k in gs.stats() for k in ("nodes", "edges", "roots", "leaves", "has_cycle")),
       gs.stats())

    # ================================================================== C
    print("\n[C] 跨领域联想（10.3）")
    ck("C", "领域表 ≥8 个领域", len(AN.DOMAINS) >= 8, "%d 个" % len(AN.DOMAINS))
    ck("C", "规格点名的 10 个领域全都在",
       all(d in AN.DOMAINS for d in DOM_NEED),
       [d for d in DOM_NEED if d not in AN.DOMAINS])
    thin = [d for d, ws in AN.DOMAINS.items() if len(ws) < 5]
    ck("C", "每个领域 ≥5 个概念词", not thin, thin)
    ck("C", "结构映射库 ≥8 条", len(AN.STRUCTURE_MAP) >= 8, "%d 条" % len(AN.STRUCTURE_MAP))
    ck("C", "每条结构映射的 pairs 都 ≥3 对、每对两个词",
       all(len(m.get("pairs") or []) >= 3
           and all(len(p) == 2 for p in (m.get("pairs") or []))
           for m in AN.STRUCTURE_MAP))

    def has_map(fr, to):
        return any(m.get("from") == fr and m.get("to") == to for m in AN.STRUCTURE_MAP)

    must = [("电路", "水管"), ("免疫", "安全"), ("市场", "生态")]
    missing_map = ["%s≈%s" % (f, t) for f, t in must if not has_map(f, t)]
    ck("C", "三条必备结构映射都在（电路≈水管 / 免疫≈安全 / 市场≈生态）",
       not missing_map, missing_map)
    dv = AN.domain_vector(CIRCUIT)
    ck("C", "domain_vector 为每个领域都给分（0~1）",
       isinstance(dv, dict) and all(d in dv for d in AN.DOMAINS)
       and all(0.0 <= float(v) <= 1.0 for v in dv.values()),
       dv)
    ck("C", "domain_vector 定位得出「电路」",
       AN.best_domain(CIRCUIT) == "电路", AN.best_domain(CIRCUIT))
    ck("C", "domain_vector(None) 全 0 且不抛",
       all(float(v) == 0.0 for v in AN.domain_vector(None).values()))
    ck("C", "定位不出领域时 best_domain 返回 None（不硬塞）",
       AN.best_domain(None) is None)

    ms = AN.map_structure(CIRCUIT)
    ck("C", "map_structure 命中映射并给出跨领域说法",
       isinstance(ms, dict) and (ms.get("statements") or []), (ms or {}).get("statements"))
    ck("C", "map_structure 的源/目标领域不同（不是自己映射自己）",
       isinstance(ms, dict) and ms.get("from") != ms.get("to"),
       ((ms or {}).get("from"), (ms or {}).get("to")))
    anas = AN.analogies(CIRCUIT, limit=3)
    src = AN.best_domain(CIRCUIT)
    ck("C", "analogies 给出 1~3 个跨领域类比",
       1 <= len(anas) <= 3, [a.get("to") for a in anas])
    ck("C", "类比里不含同领域的（from != to）",
       bool(anas) and all(a.get("from") != a.get("to") for a in anas),
       [(a.get("from"), a.get("to")) for a in anas])
    ck("C", "类比的目标领域都不是源领域本身",
       bool(anas) and all(a.get("to") != src for a in anas),
       "源=%s 目标=%s" % (src, [a.get("to") for a in anas]))
    ck("C", "优先不同领域（目标领域互不重复）",
       len({a.get("to") for a in anas}) == len(anas), [a.get("to") for a in anas])
    ck("C", "analogies 是可复现的（两次同结果）",
       [a.get("to") for a in AN.analogies(CIRCUIT)] == [a.get("to") for a in AN.analogies(CIRCUIT)])
    ck("C", "定位不出领域时 analogies 返回 []（不编造）",
       AN.analogies("") == [] and AN.analogies(None) == [])

    # ================================================================== D
    print("\n[D] 模糊意图（10.4）")
    av = VA.ambiguity(VAGUE_Q)
    ck("D", "ambiguity 返回 is_vague/score/signals 三件套",
       isinstance(av, dict) and "is_vague" in av and "score" in av and "signals" in av, av)
    ck("D", "score 落在 0~1、is_vague 是 bool",
       isinstance(av.get("is_vague"), bool) and 0.0 <= float(av.get("score")) <= 1.0, av)
    ck("D", "「帮我搞一下」被判为模糊", av.get("is_vague") is True, av)
    ck("D", "模糊时给出具体信号（不能只说一句「模糊」）",
       bool(av.get("signals")) and all(isinstance(s, str) for s in av["signals"]), av.get("signals"))
    ac = VA.ambiguity(CLEAR_Q)
    ck("D", "信息完整的长问句 score < 0.5（不许误伤）",
       float(ac.get("score")) < 0.5, ac)
    ck("D", "信息完整的长问句不被判为模糊", ac.get("is_vague") is False, ac)
    ck("D", "should_ask 对明确问题返回 False（不误反问）",
       VA.should_ask(CLEAR_Q) is False)
    ck("D", "should_ask 对真模糊返回 True", VA.should_ask(VAGUE_Q) is True)
    ck("D", "ambiguity(None) 判为模糊且不抛（没说清就是没说清）",
       VA.ambiguity(None).get("is_vague") is True)
    ck("D", "ambiguity('') 不抛", isinstance(VA.ambiguity(""), dict))
    ck("D", "ambiguity 可复现（同句两次同结果）",
       VA.ambiguity(VAGUE_Q) == VA.ambiguity(VAGUE_Q))

    cands = VA.clarify_candidates(VAGUE_Q, n=5)
    ck("D", "clarify_candidates 给出 3~5 个候选问法",
       3 <= len(cands) <= 5, len(cands))
    ck("D", "候选问法都是具体可点选的非空字符串",
       all(isinstance(c, str) and len(c) >= 8 for c in cands), cands[:2])
    ck("D", "候选问法互不相同",
       len(set(cands)) == len(cands))
    ck("D", "clarify_candidates(None) 也给候选且不抛",
       3 <= len(VA.clarify_candidates(None)) <= 5)
    ck("D", "n 被夹到合法区间（要 1 个也给 3 个）",
       3 <= len(VA.clarify_candidates(VAGUE_Q, n=1)) <= 5)

    hs = VA.hypotheses(VAGUE_Q, n=3)
    ck("D", "hypotheses 返回 n 条多假设",
       isinstance(hs, list) and len(hs) == 3, len(hs) if isinstance(hs, list) else hs)
    ck("D", "每条假设含 assumption/answer_shape/confidence",
       all(all(k in h for k in ("assumption", "answer_shape", "confidence")) for h in hs),
       hs[0] if hs else None)
    ck("D", "confidence 是 0~1 的启发式数值",
       all(0.0 <= float(h.get("confidence")) <= 1.0 for h in hs))
    ck("D", "多条假设互不相同（不是复读同一条）",
       len({h.get("assumption") for h in hs}) == len(hs))
    ck("D", "explain 给出一句中文理由（为什么模糊）",
       isinstance(VA.explain(VAGUE_Q), str) and len(VA.explain(VAGUE_Q)) > 4,
       VA.explain(VAGUE_Q)[:60])
    ck("D", "explain 对明确问题也能说明为什么清楚",
       isinstance(VA.explain(CLEAR_Q), str) and len(VA.explain(CLEAR_Q)) > 4)

    # ================================================================== E
    print("\n[E] 创造性（10.5）")
    ck("E", "视角表 ≥8 个视角", len(CR.PERSPECTIVES) >= 8, "%d 个" % len(CR.PERSPECTIVES))
    pblob = " ".join(str(p.get("name")) for p in CR.PERSPECTIVES)
    pmiss = [p for p in PERS_NEED if p not in pblob]
    ck("E", "规格点名的 10 个视角全都在", not pmiss, pmiss)
    ck("E", "每个视角都带 lens 与 ≥2 个待问问题",
       all(p.get("lens") and len(p.get("questions") or []) >= 2 for p in CR.PERSPECTIVES))
    ck("E", "创意算子库 ≥10 个算子", len(CR.OPERATORS) >= 10, "%d 个" % len(CR.OPERATORS))
    oblob = " ".join(str(o.get("name")) for o in CR.OPERATORS)
    omiss = [o for o in OP_NEED if o not in oblob]
    ck("E", "规格点名的 11 类算子全都在", not omiss, omiss)

    Q = "怎么做一碗让人记住的面"
    rs = CR.resample(Q, n=5)
    ck("E", "resample 返回 n 个不同视角的采样",
       isinstance(rs, list) and len(rs) == 5, len(rs) if isinstance(rs, list) else rs)
    ck("E", "每个采样都带视角名和可交给模型的提示词",
       all(s.get("name") and s.get("prompt") and len(s["prompt"]) > 20 for s in rs),
       (rs[0] or {}).get("name") if rs else None)
    ck("E", "采样的视角互不相同", len({s.get("perspective") for s in rs}) == len(rs))
    ck("E", "resample 可复现（同样输入同批视角）",
       [s.get("perspective") for s in CR.resample(Q, n=5)]
       == [s.get("perspective") for s in CR.resample(Q, n=5)])

    op1 = CR.apply_operator("invert", seed="seed-abc")
    op2 = CR.apply_operator("invert", seed="seed-abc")
    ck("E", "apply_operator 返回算子+扰动+提示词",
       isinstance(op1, dict) and op1.get("op") and op1.get("twist") and op1.get("prompt"), op1)
    ck("E", "同 seed 的 apply_operator 结果完全一致（可复现）", op1 == op2,
       (op1 or {}).get("twist"))
    twists = {CR.apply_operator("invert", seed="s%d" % i).get("twist") for i in range(12)}
    ck("E", "不同 seed 能给出不同扰动（不是假随机）", len(twists) >= 2, "%d 种" % len(twists))
    ck("E", "未知算子 id 不抛且给出可用结果",
       isinstance(CR.apply_operator("zz_no_such_op", seed="x"), dict))
    ok_sub, ev_sub = isolated_import("creative")
    code = ("import core.boost.creative as C\n"
            "print(C.apply_operator('invert', seed='seed-abc')['twist'])\n")
    try:
        pp = subprocess.run([sys.executable, "-W", "ignore", "-c", code], cwd=_ROOT,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60)
        cross = (pp.stdout or "").strip()
    except Exception as e:      # noqa: silent-ok — 起不了子进程时如实报，不伪装通过
        cross = "子进程起不来：%r" % (e,)
    ck("E", "apply_operator 跨进程也可复现（没用到内置 hash）",
       cross == str(op1.get("twist")), "%r vs %r" % (cross, op1.get("twist")))

    sd = CR.random_seeds(Q, n=3)
    ck("E", "random_seeds 返回 n 条随机种子",
       isinstance(sd, list) and len(sd) == 3, sd)
    ck("E", "random_seeds 可复现（同问题两次同结果）", sd == CR.random_seeds(Q, n=3))
    ck("E", "换一个问题种子会变（不是写死的）",
       CR.random_seeds(Q, n=3) != CR.random_seeds("怎么养一只不闹的猫", n=3))
    ck("E", "random_seeds(None) 不抛", isinstance(CR.random_seeds(None), list))
    ck("E", "stats 报出视角数/算子数", all(k in CR.stats() for k in
                                        ("perspectives", "operators")), CR.stats())

    # ================================================================== F
    print("\n[F] 单次深度推理（10.6）")
    ck("F", "cot_prompt 强制分步（提示词里要求逐步并给依据）",
       isinstance(DT.cot_prompt(Q), str) and Q in DT.cot_prompt(Q)
       and any(k in DT.cot_prompt(Q) for k in ("步", "依据", "理由")),
       DT.cot_prompt(Q)[:50])
    ck("F", "cot_prompt(None) 不抛", isinstance(DT.cot_prompt(None), str))
    tb = DT.tot_branches(Q, n=3)
    ck("F", "tot_branches 给出 n 条探索分支",
       isinstance(tb, list) and len(tb) == 3, len(tb) if isinstance(tb, list) else tb)
    ck("F", "分支之间互不相同（不是只换编号）", len(set(tb)) == len(tb))
    ck("F", "每条分支都要求写清「这一步在赌什么」",
       all(("赌" in t) or ("押" in t) or ("假设" in t) for t in tb), tb[0][:60] if tb else "")
    ck("F", "self_doubt 要求模型找自己最可能错的地方",
       isinstance(DT.self_doubt("答案是 42"), str)
       and any(k in DT.self_doubt("答案是 42") for k in ("错", "质疑", "漏洞")),
       DT.self_doubt("答案是 42")[:50])
    ck("F", "self_doubt(None) 不抛", isinstance(DT.self_doubt(None), str))
    dv2 = DT.divide(Q, n=4)
    ck("F", "divide 拆成 n 个子问题", isinstance(dv2, list) and len(dv2) == 4, len(dv2) if isinstance(dv2, list) else dv2)
    ck("F", "子问题互不相同且各自独立可答",
       len(set(dv2)) == len(dv2) and all(len(s) > 8 for s in dv2))
    ck("F", "divide(None) 不抛", isinstance(DT.divide(None), list))

    pl = DT.plan("为什么天是蓝的")
    ck("F", "plan 返回 mode/prompts/why 三件套",
       isinstance(pl, dict) and pl.get("mode") and pl.get("prompts") and pl.get("why"), pl.get("mode"))
    ck("F", "「为什么…」类问题自动选到 cot（分步）", pl.get("mode") == "cot", pl.get("mode"))
    ck("F", "「帮我看看对不对」类问题自动选到 doubt（自我质疑）",
       DT.plan("帮我看看我写的这个方案对不对")["mode"] == "doubt",
       DT.plan("帮我看看我写的这个方案对不对")["mode"])
    ck("F", "显式指定 mode 会被尊重",
       DT.plan(Q, mode="tot")["mode"] == "tot")
    ck("F", "非法 mode 回退 auto 且不抛",
       DT.plan(Q, mode="zz_no_such_mode").get("mode") in ("cot", "tot", "doubt", "divide"))
    ck("F", "plan 自动选型可复现", DT.plan("为什么天是蓝的")["mode"] == DT.plan("为什么天是蓝的")["mode"])

    cands2 = ["短", "因为 A，所以 B。例如 C。另外还要注意 D：先做 E，再做 F。",
              "因为 A，所以 B。例如 C。另外还要注意 D：先做 E，再做 F。因为 A，所以 B。"]
    ev = DT.evaluate(cands2, llm_fn=None)
    ck("F", "evaluate(llm_fn=None) 用规则打分并如实标注 scored_by=rule",
       isinstance(ev, dict) and ev.get("scored_by") == "rule", ev.get("scored_by"))
    ck("F", "evaluate 选出的最优确实来自候选",
       ev.get("best") in cands2, str(ev.get("best"))[:30])
    ck("F", "evaluate 给出全部候选的排名与理由",
       len(ev.get("ranked") or []) == len(cands2)
       and all("score" in r and "why" in r for r in ev["ranked"]), ev.get("ranked"))
    ck("F", "evaluate(None 候选/空列表) 不抛且如实返回空",
       DT.evaluate([], None).get("best_index") == -1 and DT.evaluate(None, None).get("best_index") == -1)
    ck("F", "evaluate 规则打分可复现",
       DT.evaluate(cands2, None).get("best") == DT.evaluate(cands2, None).get("best"))

    ev_llm = DT.evaluate(cands2, llm_fn=lambda p: "2")
    ck("F", "给了 llm_fn 且能抽到编号 → scored_by=llm",
       ev_llm.get("scored_by") == "llm", (ev_llm.get("scored_by"), ev_llm.get("note")))
    ck("F", "llm 路径选出的最优仍在候选里",
       ev_llm.get("best") in cands2, str(ev_llm.get("best"))[:30])
    ev_bad = DT.evaluate(cands2, llm_fn=lambda p: "我觉得第一个挺好")
    ck("F", "llm_fn 返回抽不到编号的废话 → 回退规则打分（不假装模型评过）",
       ev_bad.get("scored_by") == "rule", (ev_bad.get("scored_by"), ev_bad.get("note")))

    def _boom(p):
        raise RuntimeError("自测故意让模型炸掉")

    ck("F", "llm_fn 抛异常 → 不向上抛，回退规则打分",
       DT.evaluate(cands2, llm_fn=_boom).get("scored_by") == "rule")

    # ================================================================== G
    print("\n[G] 超长一致性（10.7）")
    TEXT = "沈清是医生，他住在济南。2026年9月14日，沈清认识了李医生，两人都在市医院工作。"
    tb2, rg2 = CO.extract(TEXT)
    names = {e.get("name") for e in tb2.all()}
    ck("G", "纯规则抽取出中文人名（沈清）", "沈清" in names, sorted(names))
    ck("G", "抽取出地名（济南）",
       any(e.get("kind") == "place" and "济南" in str(e.get("name")) for e in tb2.all()),
       [(e.get("name"), e.get("kind")) for e in tb2.all()])
    ck("G", "抽取出时间词", any(e.get("kind") == "time" for e in tb2.all()),
       [(e.get("name"), e.get("kind")) for e in tb2.all()])
    rels_txt = [(r.get("a"), r.get("rel"), r.get("b")) for r in rg2.all()]
    ck("G", "抽取出关系（是/住在/认识 之类）", len(rels_txt) >= 2, rels_txt[:4])
    ck("G", "extract(None) 返回空表空图且不抛",
       isinstance(CO.extract(None), tuple) and len(CO.extract(None)) == 2)

    et = CO.EntityTable()
    et.add("沈清", kind="person", first_seen="2026-09-14")
    n1 = len(et.all())
    et.add("沈清", kind="person", first_seen="2026-10-01")
    ck("G", "同名重复添加不新增条目", len(et.all()) == n1 == 1, len(et.all()))
    ck("G", "重复添加只累加次数", et.get("沈清").get("count", 0) >= 2, et.get("沈清", {}).get("count"))
    ck("G", "重复添加不覆盖首次出现时间",
       et.get("沈清").get("first_seen") == "2026-09-14", et.get("沈清").get("first_seen"))
    et.add("", kind="person")
    ck("G", "空名字不会被登记成实体", all(e.get("name") for e in et.all()))
    ck("G", "get 未知实体返回 None（不编造）", et.get("查无此人") is None)

    et2 = CO.EntityTable()
    et2.add("沈清", kind="person")
    et2.add("沈清舟", kind="person")
    n_before2 = len(et2.all())
    mr = et2.merge_alias("沈清", "沈清舟")
    ck("G", "merge_alias 之后只剩一个条目（同一个人归一）",
       n_before2 == 2 and len(et2.all()) == 1, "%d → %d" % (n_before2, len(et2.all())))
    ck("G", "merge_alias 保留**首次**写法作规范名",
       et2.all()[0].get("name") == "沈清" and mr.get("canonical") == "沈清",
       (et2.all()[0].get("name"), mr.get("canonical")))
    ck("G", "被并掉的写法进 aliases",
       "沈清舟" in (et2.all()[0].get("aliases") or []), et2.all()[0].get("aliases"))
    ck("G", "用别名 get 也能取到同一条",
       et2.get("沈清舟") is not None
       and et2.get("沈清舟", ).get("name") == "沈清", et2.get("沈清舟"))
    ck("G", "merge_alias 自己跟自己合并 → ok=False 且不改动",
       et2.merge_alias("沈清", "沈清").get("ok") is False and len(et2.all()) == 1)
    et3 = CO.EntityTable()
    et3.add("小王", kind="person")
    ck("G", "merge_alias 遇到没登记过的名字会自动补建（不失败）",
       et3.merge_alias("小王", "王小明").get("ok") is True and len(et3.all()) == 1,
       len(et3.all()))
    et4 = CO.EntityTable()
    et4.add("苹果", kind="object")
    et4.add("苹果", kind="person")
    cfs = et4.conflicts()
    ck("G", "同名不同 kind → conflicts 抓得到", bool(cfs), cfs)
    ck("G", "无冲突时返回 []", CO.EntityTable().conflicts() == [])

    rgA = CO.RelationGraph()
    rgA.add("小明", "是", "医生")
    rgA.add("小明", "喜欢", "猫")
    ck("G", "RelationGraph 能按实体查到相关关系",
       len(rgA.relations_of("小明")) >= 2, len(rgA.relations_of("小明")))
    ck("G", "relations_of 双向都能查到（当宾语也算）", len(rgA.relations_of("医生")) >= 1)
    rgB = CO.RelationGraph()
    rgB.add("小明", "是", "医生")
    rgB.add("小明", "不是", "医生")
    cj = rgB.contradictions()
    ck("G", "同一对出现互斥关系 → contradictions 抓得到", bool(cj), cj)
    ck("G", "无矛盾时返回 []", rgA.contradictions() == [])

    et5 = CO.EntityTable()
    et5.add("沈清", kind="person")
    et5.add("沈清舟", kind="person")
    et5.merge_alias("沈清", "沈清舟")
    chk = CO.check("沈清舟后来搬到了青岛。", et5, CO.RelationGraph())
    ck("G", "check 返回 ok/issues/names_varied 三件套",
       isinstance(chk, dict) and "ok" in chk and "issues" in chk and "names_varied" in chk, chk)
    ck("G", "生成后校验能抓到「名字变了」（用了别名写法）",
       chk.get("names_varied") is True, chk.get("issues"))
    ck("G", "校验结果 ok 与 issues 自洽（有名字问题就不 ok）",
       chk.get("ok") is False or not chk.get("issues"), (chk.get("ok"), chk.get("issues")))
    ck("G", "check(None,None,None) 不抛", isinstance(CO.check(None, None, None), dict))

    inj = CO.inject(et5, "请继续写这个故事")
    ck("G", "inject 把已知实体（含别名→规范名）喂进提示词",
       isinstance(inj, str) and "沈清" in inj and "沈清舟" in inj and "请继续写这个故事" in inj,
       inj[:70])
    ck("G", "表为空时如实说明「还没有已登记实体」（不假装有）",
       "还没有" in CO.inject(CO.EntityTable(), "继续") or "暂无" in CO.inject(CO.EntityTable(), "继续"),
       CO.inject(CO.EntityTable(), "继续")[:60])
    ck("G", "inject(table, None) 不抛", isinstance(CO.inject(et5, None), str))

    p_cs = os.path.join(TMP, "cons.json")
    ck("G", "consistency save 返回 True 且文件产生",
       CO.save(et5, rgA, path=p_cs) is True and os.path.exists(p_cs), p_cs)
    et6, rg6 = CO.load(path=p_cs)
    ck("G", "load 把实体表与关系图都读回来",
       len(et6.all()) == len(et5.all()) and len(rg6.all()) == len(rgA.all()),
       "%d实体/%d关系 vs %d实体/%d关系" % (len(et6.all()), len(rg6.all()),
                                           len(et5.all()), len(rgA.all())))
    ck("G", "load 读不到时返回空表空图（不抛）",
       len(CO.load(path=os.path.join(TMP, "zz_no_such.json"))[0].all()) == 0)

    # ================================================================== H
    print("\n[H] 红线与独立性")
    del_bad = {}
    for nm, p in _MODS.items():
        d = deletion_calls(p)
        if d:
            del_bad[nm] = d
    ck("H", "boost 七个模块源码里没有任何删除文件调用（红线）", not del_bad, del_bad)
    ck("H", "boost 各文件都存在（七个 + __init__）",
       all(os.path.exists(p) for p in _MODS.values()),
       [n for n, p in _MODS.items() if not os.path.exists(p)])
    no_motto = []
    for nm, p in _MODS.items():
        head = src_of(p)[:2000]
        if not all(m in head for m in _MOTTO):
            no_motto.append(nm)
    ck("H", "每个文件顶部都有那段总纲注释（一字不差）", not no_motto, no_motto)

    iso_bad = {}
    for nm in _MODS:
        if nm == "init":
            continue
        ok_i, ev_i = isolated_import(nm)
        if not ok_i:
            iso_bad[nm] = ev_i
    ck("H", "七个模块都能在干净子进程里独立 import（不依赖 Flask / xiaojiao_app）",
       not iso_bad, iso_bad)

    ck("H", "boost 数据目录真的产生了", os.path.isdir(BOOST_DIR), BOOST_DIR)
    ev_log = read_jsonl(boost_path("boost.jsonl"))
    ck("H", "事件流水 boost.jsonl 可读回（越用越大的证据）",
       isinstance(ev_log, list) and len(ev_log) >= 1, "%d 条" % len(ev_log))
    ck("H", "流水里记了 pick/plan/apply_operator 这类真实事件",
       any(isinstance(r, dict) and r.get("event") for r in ev_log),
       sorted({r.get("event") for r in ev_log if isinstance(r, dict)})[:6])

    # --- 落盘真实性（真实路径，跑完还原内容；绝不删文件）
    tp_path = boost_path("templates.json")
    orig_tp = snap(tp_path)
    R.add({"id": "zz_selftest_disk", "name": "自测落盘用", "name_en": "SelftestDisk",
           "when": "只验落盘", "steps": ["一", "二", "三"],
           "pitfalls": ["坑一", "坑二"], "keywords": ["落盘自测"]}, save=True)
    R.save_extended()
    ext = R.load_extended()
    ck("H", "reasoning 追加的模板真的落进 logs/boost/templates.json 并读得回",
       any(t.get("id") == "zz_selftest_disk" for t in ext), [t.get("id") for t in ext][-3:])
    ck("H", "templates.json 是合法 JSON（read_json 读得出 dict）",
       isinstance(read_json(tp_path, default=None), dict))
    restore(tp_path, orig_tp)

    cp_path = boost_path("causal.json")
    orig_cp = snap(cp_path)
    gdisk = CA.CausalGraph()
    gdisk.add_node("自测落盘节点", kind="fact")
    gdisk.save()
    g_read = CA.CausalGraph()
    load_ok = g_read.load()
    ck("H", "causal 默认路径 logs/boost/causal.json 真的落盘且读得回",
       load_ok is True and any(n.get("text") == "自测落盘节点" for n in g_read.nodes()),
       [n.get("text") for n in g_read.nodes()][:3])
    restore(cp_path, orig_cp)

    mp_path = boost_path("maps.json")
    orig_mp = snap(mp_path)
    AN.add_map("电路", "水管", [["电压", "水压"], ["电流", "流量"], ["电阻", "管径"]],
               m_id="zz_selftest_map", note="自测落盘用")
    maps = AN.list_maps()
    ck("H", "analogy 追加的映射真的落进 logs/boost/maps.json 并读得回",
       any(m.get("id") == "zz_selftest_map" for m in maps), len(maps))
    ck("H", "maps.json 是合法 JSON", isinstance(read_json(mp_path, default=None), dict))
    restore(mp_path, orig_mp)

    kp_path = boost_path("consistency.json")
    orig_kp = snap(kp_path)
    etd = CO.EntityTable()
    etd.add("自测人物", kind="person")
    rgd = CO.RelationGraph()
    rgd.add("自测人物", "住在", "自测城")
    CO.save(etd, rgd)
    etd2, rgd2 = CO.load()
    ck("H", "consistency 默认路径 logs/boost/consistency.json 真的落盘且读得回",
       any(e.get("name") == "自测人物" for e in etd2.all()),
       [e.get("name") for e in etd2.all()][:3])
    ck("H", "读回的关系图上关系还在",
       any(r.get("rel") == "住在" for r in rgd2.all()),
       [(r.get("a"), r.get("rel"), r.get("b")) for r in rgd2.all()][:3])
    restore(kp_path, orig_kp)

    ck("H", "自测用标记数据已从真实路径还原（内容写回，未删除任何文件）",
       snap(tp_path) == orig_tp and snap(cp_path) == orig_cp
       and snap(mp_path) == orig_mp and snap(kp_path) == orig_kp)
    ck("H", "临时目录里的数据也都可读回（不污染真实日志）",
       os.path.isdir(TMP) and os.path.exists(p_sl) and os.path.exists(p_cs))

    # ================================================================== I
    print("\n[I] 边界（一律不许崩）")
    long_q = "请分析" + "这是一段很长的背景材料。" * 300 + "的核心问题"
    ck("I", "超长输入 pick 不崩", R.pick(long_q) is None or isinstance(R.pick(long_q), dict))
    ck("I", "超长输入 render 不崩", isinstance(R.render("induction", long_q), str))
    ck("I", "超长输入 ambiguity 不崩", isinstance(VA.ambiguity(long_q), dict))
    ck("I", "超长输入 extract 不崩", isinstance(CO.extract(long_q), tuple))
    ck("I", "超长输入 analogies 不崩", isinstance(AN.analogies(long_q), list))
    ck("I", "超长输入 plan 不崩", isinstance(DT.plan(long_q), dict))
    ck("I", "超长输入 resample 不崩", isinstance(CR.resample(long_q, n=2), list))
    ck("I", "超长输入 causal 建图不崩",
       CA.CausalGraph(path=os.path.join(TMP, "long.json")).add_node(long_q) is not None)
    ck("I", "非字符串输入（数字/列表/dict）一律不崩",
       R.pick(123) is None or isinstance(R.pick(123), dict))
    ck("I", "非字符串输入 ambiguity 不崩", isinstance(VA.ambiguity(123), dict))
    ck("I", "非字符串输入 inject 不崩", isinstance(CO.inject(CO.EntityTable(), 123), str))
    ck("I", "add_edge 的空 why / 自环不崩",
       isinstance(CA.CausalGraph(path=os.path.join(TMP, "self.json")).add_edge("自", "自"), dict))

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 68)
    total = len(PASS) + len(FAIL)
    print("  通过 %d / 共 %d%s" % (len(PASS), total,
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("  临时数据目录：%s" % TMP)
    print("  真实落盘目录：%s（自测标记数据已还原）" % BOOST_DIR)
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
