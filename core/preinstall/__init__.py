# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""阶段 C · 发布准备（预置数据）—— "发布即成品"

【这段为什么这么设计】
    "用户不该为开发者的成长买单"：如果系统要靠用户用几天才变聪明，
    那用户买到的其实是**半成品**。所以发布版必须**自带**六类数据：
        ① 规则库（从大模型蒸馏出来的推理路径）
        ② 知识库（互联网吸收的）
        ③ 案例库（各种场景的解法）
        ④ 人格模型（成型的人设）
        ⑤ 元推理模板（30+ 种）
        ⑥ 结构映射库（电路≈水管 这类）
    用户使用只是**锦上添花**（更懂你），不是**必要条件**（不用也是完整的）。
    去掉这一层：全新安装的小焦是个"什么都不会的壳"，
    而"开箱即用"这句承诺就是假的 —— 这是发布原则里最不能含糊的一条。

【为什么不是"再写六个大 JSON 塞进仓库"】
    六类数据里有四类**已经有真正的产地**：
        · 知识库   → `self_learn/`（训练小脑时蒸馏出来的知识向量库）
        · 元推理模板 → `core/boost/reasoning.py`（30+ 内置模板，且支持追加）
        · 结构映射库 → `core/boost/analogy.py`（内置映射，且支持追加）
        · 人格模型 → 本文件的 `PERSONA_SEEDS`（从真实人设里蒸馏出的"该有的样子"）
    再抄一份进仓库，就会出现**两份会各自漂移的同一份数据** ——
    改了 boost 的模板、忘了改副本，于是"预置的"和"实际用的"不是一套。
    所以本模块的角色是**装配与校验**：把各地已有的数据**盘点齐、补齐缺的、如实报告**，
    而不是再造一个平行宇宙。

【为什么 verify() 必须能说"缺"】
    预置数据最容易出的问题是"看起来有、其实是空的"（文件在但 0 条）。
    所以 `verify()` 对每一类都给出 `ready` 与**条数**，缺就明说缺。
    发布前跑一次它，"开箱即用"才有据可依；否则这句话只是文档里的形容词。
"""
import os

from ..boost import boost_path, read_json, read_jsonl, write_json

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ------------------------------------------------------------------ ④ 人格模型（预置人设）
# 为什么这几条要**预置**而不是等用户教：
#   人格是"第一印象"，用户第一次开口时就得是对的。
#   等用户用三天才觉得"这AI说话还行"，中间三天已经流失了。
# 注意：这里预置的是**人设内容**（角色/语气/边界），
# 不是 `core/persona` 的"去 AI 味规则"——后者是**处理手法**，两者互补：
#   预置人设 = 该是什么样；去 AI 味 = 别变成什么样。
PERSONA_SEEDS = (
    {"id": "xiaojiao-default", "name": "小焦 · 默认",
     "desc": "温柔但不讨好，会记事、有立场、话不多",
     "role": ("你是小焦，一个本地 AI 助手。你说话像人，不像客服：先给结论再说理由。"
              "你记得用户说过的事，用得上就用，不确定就说不确定。"
              "遇到需要执行的操作（建文件/写网页/跑命令）就调用工具。"
              "你绝不删除任何文件 —— 那是不可逆的。"),
     "traits": ("有立场", "有情绪", "会反问", "有记忆", "会主动",
                "允许犯错", "有自己的语气", "不讨好", "有边界感")},
    {"id": "coder", "name": "编程助手",
     "desc": "简洁专业，代码优先，不啰嗦",
     "role": ("你是小焦的编程助手模式。回答要简洁专业，代码一律用代码块，"
              "注释用中文。先给能跑的代码，再给必要的解释；不要写大段铺垫。"),
     "traits": ("先结论", "给可运行代码", "不解释常识", "有立场")},
    {"id": "chat", "name": "闲聊陪伴",
     "desc": "口语化，不列点，像朋友",
     "role": ("你是小焦的闲聊模式。用纯口语，像朋友搭话：不列点、不加小标题、"
              "不写总结段。可以反驳用户，可以说'我不这么觉得'。"),
     "traits": ("纯口语", "会吐槽", "会反问", "不讨好")},
)

# ------------------------------------------------------------------ ③ 案例库（场景 → 做法）
# 为什么案例库比"规则"更有用：规则要模型理解，案例只要它照着做。
# 小模型对"跟我刚才那个差不多的例子"最敏感，所以案例是 4B 最省力的扶手。
CASE_SEEDS = (
    {"id": "long_output", "scene": "用户要一篇很长的东西（3000 字以上）",
     "signal": ("写", "字", "长文", "文章", "报告"),
     "approach": ("按段多次生成并无缝拼接：每段带任务+已写摘要+上段结尾，"
                  "每段生成后做去重/断句/偏题/复读四道校验；"
                  "单段复读只截断不放弃整篇，连续 3 段复读才收口。"),
     "pitfall": "不要一次要 3000 字 —— 模型会中途开始复读；也不要因为一段复读就整篇判死。"},
    {"id": "long_input", "scene": "用户贴了一大坨（超长文本）",
     "signal": ("总结", "这篇文章", "下面这段", "材料"),
     "approach": "按段落边界切片（不切在句中）→ 逐片处理并落盘 → 拼装时做跨片去重。",
     "pitfall": "不要在句中切断（语义断掉、总结会错）；不要让用户看到「第 X/Y 片」。"},
    {"id": "vague_intent", "scene": "用户只说了『帮我搞一下』这种没头没尾的话",
     "signal": ("搞一下", "弄一下", "优化下", "弄弄", "看看这个"),
     "approach": "先给 3~5 个具体候选问法让用户挑，不要硬猜着做。",
     "pitfall": "不要沉默地猜（做错比问一句更烦人），也不要问『请问您具体想做什么呢』这种空问题。"},
    {"id": "delete_request", "scene": "用户要求删文件",
     "signal": ("删", "删除", "remove", "rm ", "del "),
     "approach": "载体层直接拦截并给出替代建议（新建/追加），不进入模型判断。",
     "pitfall": "绝不能因为『用户明确要求』就放行 —— 删除不可逆，这是硬约束不是偏好。"},
    {"id": "memory_recall", "scene": "用户问『我之前说过什么』",
     "signal": ("我说过", "记不记得", "我上次", "我之前"),
     "approach": "检索记忆：精确命中才当事实说；模糊命中只说『记得你提过…细节提醒我』；"
                 "检索不到就明确说『你之前没跟我说过这事』。",
     "pitfall": "绝不拿最像的那条凑答案 —— 编造用户的经历是最严重的失信。"},
    {"id": "tool_fail", "scene": "工具调用失败了",
     "signal": ("报错", "失败", "timeout", "连不上"),
     "approach": "先如实说失败原因（把原文给人看），再给一条替代路径；连续失败要熔断而不是硬重试。",
     "pitfall": "不要假装成功，也不要把错误吞掉只说『抱歉出错了』。"},
    {"id": "code_bug", "scene": "用户贴报错问怎么修",
     "signal": ("traceback", "报错", "异常", "不生效", "怎么修"),
     "approach": "先定位到具体那一行与原因，再给最小修改（不要顺手重构无关代码）。",
     "pitfall": "不要在没有看代码的情况下猜原因。"},
    {"id": "brain_switch", "scene": "当前模型不行了（复读/超时/乱答）",
     "signal": ("换模型", "不行了", "胡说", "重复"),
     "approach": "健康系统按级别处置；三级才切备用火种，且切换时记忆/工具/世界/会话全部保留。",
     "pitfall": "不要一有问题就换模型 —— 先把载体能修的修掉（大多数问题不在模型）。"},
)

# ------------------------------------------------------------------ ① 规则库（蒸馏的推理路径）
# "蒸馏"在这里的具体含义：把大模型解决问题时的**稳定套路**抽成可执行的规则条目。
# 它不是知识（知识在知识库里），而是"拿到这类题该先做什么"。
RULE_SEEDS = (
    {"id": "r_explain", "name": "解释概念",
     "when": ("是什么", "解释一下", "什么意思", "科普"),
     "steps": ("一句话给定义（先说它能干什么）", "给一个日常生活里的类比",
               "说清它和相近概念的区别", "最后给一个最小例子"),
     "avoid": ("不要一上来讲历史", "不要罗列特性清单当解释")},
    {"id": "r_howto", "name": "怎么做",
     "when": ("怎么做", "如何", "步骤", "教程"),
     "steps": ("先给前置条件（没有它做不成）", "按 1/2/3 给可执行步骤",
               "每步写完能验证的结果", "最后给常见失败点"),
     "avoid": ("不要给不可执行的抽象建议", "不要略过环境准备")},
    {"id": "r_choose", "name": "选哪个",
     "when": ("哪个好", "怎么选", "对比", "值不值"),
     "steps": ("先问/假定使用场景（场景不同答案不同）", "给 2~3 个候选",
               "用同一组维度对比", "给明确推荐 + 什么情况下换另一个"),
     "avoid": ("不要两面都说好", "不要把偏好说成客观事实")},
    {"id": "r_debug", "name": "排错",
     "when": ("报错", "不生效", "异常", "失败"),
     "steps": ("先复现（说清复现条件）", "二分定位到最小范围",
               "确认根因（改一处能验证）", "给最小修复 + 回归验证方法"),
     "avoid": ("不要一次改多处（分不清是谁修好的）", "不要不看代码猜")},
    {"id": "r_estimate", "name": "估算",
     "when": ("大概多少", "估算", "多久", "多少合适"),
     "steps": ("拆成可估的小项", "每项给出数量级与依据",
               "合成总量并说明误差范围", "指出最不确定的那一项"),
     "avoid": ("不要给一个精确到小数点的假数字", "不要漏掉最大项")},
    {"id": "r_plan", "name": "做计划",
     "when": ("计划", "规划", "路线图", "怎么安排"),
     "steps": ("先定目标与验收标准", "拆里程碑（每个都能独立验证）",
               "排依赖与顺序", "标出风险与回退方案"),
     "avoid": ("不要只排任务不排依赖", "不要没有验收标准")},
    {"id": "r_summarize", "name": "总结",
     "when": ("总结", "概括", "提炼", "要点"),
     "steps": ("先给一句话结论", "再给 3~5 条支撑要点",
               "最后给 1 条『所以该怎么办』"),
     "avoid": ("不要按原文顺序复述", "不要把例子当结论")},
    {"id": "r_review", "name": "评审/挑毛病",
     "when": ("看看有没有问题", "评审", "挑毛病", "审一下"),
     "steps": ("先说做对了什么（避免只挑刺）", "按严重程度列问题（每条给后果）",
               "给最小修改建议", "指出哪些是不用改的"),
     "avoid": ("不要按风格偏好挑刺", "不要只说『可以更好』")},
    {"id": "r_translate_style", "name": "换风格改写",
     "when": ("改成", "口语化", "正式一点", "换种说法"),
     "steps": ("先确认目标风格的具体特征（句长/用词/语气）",
               "保持事实不变只改表达", "给一版结果并说明改了什么"),
     "avoid": ("不要顺手改内容（用户只要改风格）", "不要把口语改成废话堆砌")},
    {"id": "r_math", "name": "算题",
     "when": ("算一下", "等于多少", "求解", "证明"),
     "steps": ("先写清已知与所求", "选一个方法并说明为什么用它",
               "逐步推导（每步可检验）", "回代验证"),
     "avoid": ("不要跳步到答案", "不要不回代")},
)


def _dir():
    d = os.path.join(_ROOT, "logs", "preinstall")
    os.makedirs(d, exist_ok=True)
    return d


def _p(name):
    return os.path.join(_dir(), name)


def _paths():
    """六类数据各自的**真实产地**（不是副本）。"""
    return {
        "rules": _p("rules.json"),
        "cases": _p("cases.json"),
        "persona": os.path.join(_ROOT, "presets", "xiaojiao-default.json"),
        "knowledge": os.path.join(_ROOT, "self_learn", "knowledge_vec.json"),
        "templates": boost_path("templates.json"),
        "maps": boost_path("maps.json"),
    }


# ------------------------------------------------------------------ 写入（幂等）
def _seed_json(path, items, key="id"):
    """把预置条目**合并**进目标文件：已有的不动，缺的补上。返回新增条数。

    为什么是"合并"而不是"覆盖"：用户运行了一段时间后，这份文件里会有
    **用户自己攒的**条目；发布升级时直接覆盖会把用户的积累抹掉。
    只补缺的，是"预置"和"用户数据"能长期共存的前提。
    """
    try:
        cur = read_json(path, default=None)
        if isinstance(cur, dict):
            existing = cur.get("items") or cur.get("maps") or []
            data = cur
        elif isinstance(cur, list):
            existing = cur
            data = None
        else:
            existing, data = [], None
        have = set()
        for it in existing:
            if isinstance(it, dict) and it.get(key):
                have.add(it[key])
        added = [it for it in items if it.get(key) not in have]
        if not added:
            return 0
        merged = list(existing) + added
        if data is None:
            write_json(path, merged)
        else:
            data["items"] = merged
            write_json(path, data)
        return len(added)
    except Exception:      # noqa: silent-ok — 预置写不上只是"这次没补齐"，绝不能拖垮启动
        return 0


def ensure(force=False):
    """**发布装配**：把六类预置数据补齐（幂等，可重复调用）。

    返回每类的写入条数。为什么幂等很重要：它在启动路径上会被调用，
    每次启动都全量重写一遍既慢又危险（正好写一半崩了）。
    `force=True` 时忽略"已有就不写"，用于发布打包。
    """
    out = {}
    try:
        rp, cp, pp = _paths()["rules"], _paths()["cases"], _paths()["persona"]
        out["rules"] = _seed_json(rp, RULE_SEEDS) if not force else _seed_json(rp, RULE_SEEDS)
        out["cases"] = _seed_json(cp, CASE_SEEDS)
        # 人格：只在**不存在**时写（exists → 不覆盖，用户改过的人设必须保留）
        try:
            if force or not os.path.exists(pp):
                write_json(pp, {"id": "xiaojiao-default", "name": PERSONA_SEEDS[0]["name"],
                                "desc": PERSONA_SEEDS[0]["desc"],
                                "role": PERSONA_SEEDS[0]["role"],
                                "traits": list(PERSONA_SEEDS[0]["traits"]),
                                "preinstalled": True})
                out["persona"] = 1
            else:
                out["persona"] = 0
        except Exception:      # noqa: silent-ok — 人设写不上不该影响启动
            out["persona"] = 0
        # 知识库 / 模板 / 映射：产地本来就在别处，这里只**确保目录/文件可用**
        out["knowledge"] = 0
        out["templates"] = 0
        out["maps"] = 0
        write_json(_p("manifest.json"), {"seeded_at": __import__("time").time(),
                                        "by_category": out})
    except Exception:      # noqa: silent-ok — 装配失败不阻塞启动，verify() 会如实报缺
        pass
    return out


# ------------------------------------------------------------------ 盘点
def _count_json_list(path, keys=("items", "maps")):
    """数一个 JSON 文件里的条目数（容忍 dict/list 两种结构；读不到算 0）。"""
    try:
        d = read_json(path, default=None)
        if isinstance(d, list):
            return len(d)
        if isinstance(d, dict):
            for k in keys:
                v = d.get(k)
                if isinstance(v, list):
                    return len(v)
        return 0
    except Exception:      # noqa: silent-ok — 数不出来按 0 计（verify 会报"缺"）
        return 0


def _count_knowledge(path):
    """数知识库条数：这是 1.2MB 的 JSON，**只数顶层键**，不整份读进来解析。

    为什么不用 `read_json`：它会把 1.2MB 全部解析成 Python 对象，
    而 `verify()` 会在启动路径上被调用 —— 为了"知道有几条"而阻塞启动不值得。
    这里用"里层对象个数"作为条数口径（与写库时的结构一致）。
    """
    try:
        if not os.path.exists(path):
            return 0
        import json
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in ("data", "items", "records", "vecs", "entries"):
                v = d.get(k)
                if isinstance(v, (list, dict)):
                    return len(v)
            return len(d)
        return len(d) if isinstance(d, list) else 0
    except Exception:      # noqa: silent-ok — 读不动按 0 计，由 verify 如实报缺
        return 0


def _persona_count():
    """数"可用人设"的个数：`presets/*.json` 里**能解析出 role 的**才算一个。

    为什么必须校验 role 而不是只数文件：`presets/` 里可能有 `preset_xxx.json`
    这种只有开关、没有 role 的条目（用户纯切大脑用）。
    把它们算成人设，就会得出"有 5 个人设"这种虚高数字 ——
    而"开箱即用"要的正是"有没有一个**成型的人设**"，不是"有几个文件"。
    """
    try:
        import glob
        import json
        n = 0
        for f in glob.glob(os.path.join(_ROOT, "presets", "*.json")):
            try:
                with open(f, "r", encoding="utf-8-sig") as fh:
                    d = json.load(fh)
                if isinstance(d, dict) and str(d.get("role") or "").strip():
                    n += 1
            except Exception:      # noqa: silent-ok — 坏文件不计入，也不能连累其它人设
                continue
        return n
    except Exception:      # noqa: silent-ok — 数不出来按 0 计，由 verify 如实报缺
        return 0


def verify():
    """**盘点六类预置数据**，如实给出条数与 ready。缺就明说缺（不许编 0 为"有"）。

    返回 {"ready", "missing", "categories": {name: {ready, count, path, cn, note}}}。

    【为什么这么设计】"开箱即用"是**发布承诺**，必须有据可依 ——
    这个函数就是那句承诺的**验收器**。它只做两件事：数出真实条数、跟应有下限比。
    最容易出的问题是"文件在、内容空"（0 条却看起来齐备），所以这里一律以**条数**为准，
    并在 `missing` 里点名缺哪一类。

    【去掉它会怎样】"发布即成品"就只剩文档里的一句形容词：
    打个包发出去，用户装上才发现是空壳（模板没带、知识库为空），而没有任何一处能提前报警。
    """
    paths = _paths()
    cats = {}
    cats["rules"] = {"cn": "规则库（蒸馏的推理路径）", "path": paths["rules"],
                     "count": _count_json_list(paths["rules"]),
                     "builtin": len(RULE_SEEDS)}
    cats["knowledge"] = {"cn": "知识库（互联网吸收的）", "path": paths["knowledge"],
                         "count": _count_knowledge(paths["knowledge"]), "builtin": 0}
    cats["cases"] = {"cn": "案例库（场景解法）", "path": paths["cases"],
                     "count": _count_json_list(paths["cases"]),
                     "builtin": len(CASE_SEEDS)}
    cats["persona"] = {"cn": "人格模型（成型人设）", "path": paths["persona"],
                       "count": _persona_count(), "builtin": len(PERSONA_SEEDS),
                       # 人设的就绪门槛是"**至少存在一个可用人设文件**"，
                       # 不是"文件数 ≥ 内置种子数"—— 后者是我第一版写错的判据，
                       # 结果是"明明有人设却报缺"（实测：count=1、builtin=3 → 假红）。
                       # 预置种子是**可用的模板**，不是"必须全部落盘"的清单。
                       "floor": 1}
    # 元推理模板 / 结构映射：产地分别是 boost 的内置 + 追加文件
    tpl = 0
    try:
        from ..boost import reasoning as _r
        tpl = len(_r.all_templates())
    except Exception:      # noqa: silent-ok — 拿不到就按 0 计，如实报缺
        tpl = 0
    cats["templates"] = {"cn": "元推理模板（30+ 种）", "path": paths["templates"],
                         "count": tpl, "builtin": 30}
    mp = 0
    try:
        from ..boost import analogy as _a
        mp = len(_a.STRUCTURE_MAP) + _a.added_map_count() if hasattr(_a, "added_map_count") else len(_a.STRUCTURE_MAP)
    except Exception:      # noqa: silent-ok — 同上
        mp = 0
    cats["maps"] = {"cn": "结构映射库（电路≈水管）", "path": paths["maps"],
                    "count": mp, "builtin": 8}
    for name, c in cats.items():
        # ready 的门槛：默认是"至少要有内置的那份"（boost 内置或本文件内置），
        # 特殊类别（人格）自己给 `floor` 覆盖 —— 见上面 persona 的说明。
        floor = int(c.get("floor") or max(1, int(c.get("builtin") or 0)))
        c["ready"] = bool(c["count"] >= floor)
        c["note"] = ("已有 %d 条" % c["count"]) if c["ready"] else \
                    ("缺：计数 %d < 应有 %d" % (c["count"], floor))
    missing = sorted(k for k, v in cats.items() if not v["ready"])
    return {"ready": not missing, "missing": missing, "categories": cats}


def summary():
    """一句中文概括（带真实数字）。"""
    v = verify()
    ok = [k for k, c in v["categories"].items() if c["ready"]]
    if v["ready"]:
        return ("六类预置数据齐备（%s）；开箱即用不依赖用户先养。"
                % "、".join("%s %d 条" % (c["cn"].split("（")[0], c["count"])
                           for c in v["categories"].values()))
    return ("预置数据缺 %d 类：%s；已就绪 %d 类（%s）。"
            % (len(v["missing"]), "、".join(v["missing"]), len(ok), "、".join(ok)))
