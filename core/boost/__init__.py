# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 能力增益包（boost，模块 10）

【这一包到底解决什么问题】
    4B 模型自己"不会想"。它会把"帮我搞一下"当成一个能立刻回答的问题，
    会把长文第三段里的"沈清"写成"沈青"，会在需要归纳时交出一段散文。
    这些**都不是智力不够**，而是载体没给它脚手架 —— 换成 70B 也一样会犯，
    只是犯得少。所以正确的修法不是换模型，而是**把结构补上**。

【七个模块，一个公式】
    本包七项全部遵守同一个公式（缺任何一环，另外几环就白做）：
      ① 把不确定的东西**结构化**  —— 问题 → 模板 / 图 / 向量 / 实体表
      ② 结构由**载体**维护        —— 判断、打分、连边、归一，全在 Python 里
      ③ 模型每次只做**一小步**    —— 一次只走一格，不许一口气给答案
      ④ 每一步结果**存回结构**    —— 越用越大：模板会变多、映射会变多、实体表会变长
    去掉④（不落盘），前三条就退化成"每次从零开始的提示词工程"，
    系统永远不会比昨天更懂这个用户 —— 这正是本包与普通 prompt 库的分界线。

    10.1 reasoning.py   元推理模板库（≥30 种推理类型，规则选型 + 渲染 + 追加）
    10.2 causal.py      长链因果图（节点/边/环/冲突/回溯，问题先给因再给果）
    10.3 analogy.py     跨领域联想（领域向量 + 结构映射，电路≈水管）
    10.4 vague.py       模糊意图（先判该不该反问，再给候选问法与多假设）
    10.5 creative.py    创造性（多视角采样 + 创意算子 + 可复现随机种子）
    10.6 deepthink.py   单次深度推理（CoT / ToT / 自我质疑 / 分而治之）
    10.7 consistency.py 超长一致性（实体表 + 关系图 + 生成前后校验）

【为什么这七项要凑在一起，而不是散在七个地方】
    它们共用同一批底层判断：中文分词口径、"命中哪些词"、落盘目录、事件流水。
    散开写的结果是"模板库认'是不是'、一致性认'是不是啊'"这种口径分裂 ——
    同一句话在两个模块里得到不同结论，而用户看到的只有最终答案，
    于是表现为"它一会儿记得住一会儿记不住"。工具集中在 __init__、逻辑留在各模块，
    是**唯一**能长期保证口径一致的做法。

【为什么 __init__ 里一个字逻辑都不放（同 core/health 的做法）】
    七个模块都要 `from . import hits`、`from . import boost_dir`，
    本文件若在 import 期反过来把子模块拉进来，就是循环 import：
    单独 `import core.boost.reasoning` 会直接 ImportError。
    于是改用 PEP 562 的模块级 `__getattr__`：**用到才 import**。
    去掉它：`import core.boost as B; B.reasoning.pick(...)` 这种顺手写法会 AttributeError，
    而 `from core.boost import reasoning` 仍然正常。

【数据落盘一律在 logs/boost/ 下】（logs/ 已被 .gitignore 忽略，不脏仓库）
    templates.json     追加的元推理模板（越用越大）
    causal.json        因果图快照
    maps.json          追加的结构映射（越用越大）
    consistency.json   实体表 + 关系图快照
    boost.jsonl        事件流水（谁在什么时候用了哪一项、结果如何）
【绝不删除任何文件】
    本包全程只用"写 / 追加 / 覆盖"，没有任何 os.remove / unlink / rmtree。
    连带后果：`save()` 类函数不做 tmp+rename（Windows 上 rename 覆盖语义接近删旧文件），
    一律直写；写坏了下一次写会覆盖回来。去掉这条自律，
    等于在载体层里埋一个随时可能吃掉用户数据的动作。
"""
import os
import time

# 仓库根：core/boost/__init__.py → 上溯三级
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOST_DIR = os.path.join(_REPO_ROOT, "logs", "boost")

# 为什么复用 core.health 的四个读写函数，而不是各写一份：
# 它们已经把"日志是边写边读的、最后一行可能是半截 JSON"这件事处理过了
# （坏行跳过、读不动返回默认值、绝不抛）。再抄一份的结果是两套容错程度不同的实现，
# 早晚出现"健康系统读得进、boost 读不进"的灵异现象，而排查时你会发现两处代码长得几乎一样。
# 去掉复用改成本地实现：容错行为立刻分叉，且没人会同时改两个文件。
from ..health import append_jsonl, read_json, read_jsonl, write_json  # noqa: F401


def boost_dir(sub=None):
    """boost 数据目录（默认 `logs/boost/`）；建不出来也不抛，各写入点自己还会兜一层。

    为什么集中在这里算路径：七个模块各用 `os.path.dirname(__file__)` 拼一次的话，
    早晚有人拼错一级，数据就散到仓库别处去了 —— 排查"模板怎么没存上"时，
    你会发现它其实好好地存在另一个目录里。去掉它就会这样。
    """
    d = BOOST_DIR if not sub else os.path.join(BOOST_DIR, sub)
    try:
        os.makedirs(os.path.dirname(d) if os.path.splitext(d)[1] else d, exist_ok=True)
    except Exception:      # noqa: silent-ok — 目录建不出来时写入点自己再兜一层
        pass
    return d


def boost_path(name):
    """`logs/boost/<name>` 的完整路径（只算路径，不建目录、不碰文件）。"""
    return os.path.join(BOOST_DIR, name)


def now():
    """统一时间入口。为什么不让各模块自己 `time.time()`：
    自测要能把"时间"当成一个可以被替换的输入（否则跟时间有关的判据无法稳定复现），
    更重要的是**只有一个地方能改**，将来换成毫秒精度或注入时钟时不会漏掉某个模块。"""
    return time.time()


# ------------------------------------------------------------------ 中文文本的规则工具
# 为什么这五个小函数放在共用层，而不是各模块自己写：
# "命中哪些词"这件事，模板选型、领域打分、模糊判据、关系抽取**全都**要用。
# 各写一份的必然结局是三处不同的去重口径、三处不同的排序口径，
# 于是同一句话在两个模块里命中数不一样。这是最容易发生、也最难查的一类不一致。
def norm(text):
    """把任意输入规整成可安全处理的字符串（None → ""，去首尾空白）。

    为什么不做更激进的清洗（去标点/全角半角归一）：那些改动会**改变原句**，
    而本包里"用户原话里有没有'？'"本身就是判据（模糊意图要看问句形态）。
    去掉这一步不做（直接用 text）会怎样：调用方传 None 就 TypeError，
    而 None 在这里是完全合法的输入（没有上下文就是没有）。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:      # noqa: silent-ok — 连 str() 都失败就当作空
            return ""
    return text.strip()


def cjk_count(text):
    """数中日韩统一表意文字个数。

    为什么不用 `len(text)`：`len("你好")` 和 `len("hello")` 分别是 2 和 5，
    但信息量正相反。模糊意图要判"是不是太短"，用字符数会把 "在吗"（2 字）和
    "ok"（2 字）等同看待，而中文 2 字常常已经是完整的一句话。
    去掉它改用 len：阈值就得为不同语言各调一套，且永远调不准。
    """
    return sum(1 for c in norm(text) if "\u4e00" <= c <= "\u9fff")


def bigrams(text):
    """中文二元组（bigram）。为什么用 bigram 而不是"按空格分词"：
    中文没有空格，按空格切等于整句一个 token，任何"词命中"都失效；
    而引入 jieba 这类分词是新增 pip 依赖（本项目禁止）。bigram 是零依赖、
    且对本包要做的"粗糙但稳定"的匹配完全够用的最小单位。
    去掉改用单字：`"电压"` 会命中 `"电"` 和 `"压"` 两个无关的字，
    领域打分会被"电"这种高频字灌水。
    """
    s = norm(text)
    return [s[i:i + 2] for i in range(len(s) - 1)]


def hits(text, words):
    """`text` 里命中了 `words` 中的哪些词，**按在原文中首次出现的位置排序**，去重。

    为什么按位置排序而不是按 words 的书写顺序：
    调用方常常要"取第一个命中的词当理由"（比如"命中事实信号「2026年9月」"），
    按位置排序才能保证这条理由是**原文里最先出现的那个**，
    而不是"我恰好在 words 元组里先写了那个"。反过来写的后果是
    理由跟原文读起来的顺序对不上，日志看起来像乱说的。
    """
    t = norm(text)
    if not t or not words:
        return []
    found = {}
    for w in words:
        w = norm(w)
        if not w:
            continue
        i = t.find(w)
        if i >= 0 and w not in found:
            found[w] = i
    return [w for w, _i in sorted(found.items(), key=lambda kv: kv[1])]


def has_any(text, words):
    """是否命中 `words` 中任意一个（`hits` 的布尔快路径，语义完全一致）。"""
    return bool(hits(text, words))


def weighted_hits(text, words, weight=1.0):
    """命中词数 × 权重（浮点）。

    为什么要单独给一个"加权"入口：领域打分要按"命中密度"排序，
    而密度是浮点。如果各模块各自写 `len(hits(...)) / n`，就会出现
    "有的地方按字算分母、有的按 bigram 算"，同一段文字两个分数。
    去掉它不影响正确性，但会把一个除法口径复制到四个模块里。
    """
    return len(hits(text, words)) * float(weight)


def note(event, **kw):
    """往 `logs/boost/boost.jsonl` 追加一条事件（谁用了哪一项、结果如何）。

    为什么要有这条流水：本包的卖点是"越用越大"，而"变大"必须能被**看见**，
    否则没人知道模板库到底有没有长过。自测直接读这个文件来验"真的落盘了"。
    为什么写不进去也不抛：流水只是证据，不是功能；为了记一条日志
    让用户的对话失败，是明显不划算的交换。
    """
    rec = {"ts": now(), "event": norm(event)}
    try:
        rec.update(kw)
    except Exception:      # noqa: silent-ok — kw 里塞了不可序列化对象也不能崩
        pass
    try:
        append_jsonl(boost_path("boost.jsonl"), rec)
    except Exception:      # noqa: silent-ok — 流水写不进去绝不影响功能
        pass
    return rec


def _lazy(name):
    """按需 import 子模块（PEP 562 用）。"""
    import importlib
    return importlib.import_module("." + name, __name__)


_SUBMODULES = ("reasoning", "causal", "analogy", "vague",
               "creative", "deepthink", "consistency")

__all__ = list(_SUBMODULES) + [
    "BOOST_DIR", "boost_dir", "boost_path", "now", "norm", "cjk_count",
    "bigrams", "hits", "has_any", "weighted_hits", "note",
    "append_jsonl", "read_jsonl", "read_json", "write_json",
]


def __getattr__(name):
    """让 `core.boost.reasoning` 这类顺手写法可用，且**不引入 import 环**。

    只有被真正取用时才 import 对应子模块；`__all__` 里的七个名字全部覆盖。
    去掉它：`import core.boost as B; B.reasoning.TEMPLATES` 报 AttributeError
    （得写全 `from core.boost import reasoning`）。
    """
    if name in _SUBMODULES:
        return _lazy(name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


# ------------------------------------------------------------------ 接入层
# 【为什么要有 `dispatch()` —— 验收发现的真问题】
#   七个模块各自都写好了、自测全绿，但 **`agent_run` 一次都没调用过它们** ——
#   也就是说"极限补刀 7 项"全是**离线能力**，用户对话时一项都不会被触发。
#   自测全绿只证明"函数是对的"，不证明"接入过"。所以这里统一做一个**选型入口**：
#   一轮对话只挑**最合适的一种补刀**（不是全上，全上会把提示词塞爆、也互相打架）。
#
# 【为什么不全部注入】七种提示词同时塞进 system，等于让模型同时做七件事，
#   实测（提示词工程的常识）会互相干扰；而且每项都要吃 token（无限 6 有硬上限）。
#   所以按"问题类型"挑一个，命不中就**什么都不加**（这一点和 reasoning.pick 的
#   "选不出来就别硬塞"是同一条原则）。
# 【为什么还要一张 `_EXPLICIT_ANALOGY` 表】
#   `analogy.DOMAINS` 是按**领域词汇**建索引的（电压/电流/管路…），
#   而用户说的是**领域名**（"用物理学的思维"）或**抽象对象**（"公司现金流"）——
#   两者都不在词汇表里，于是 `analogies()` 返回空、整块跳过（用户明确要了跨域却不给）。
#   这张表补的是"从**说出来的那个词**到一套可用结构"的直接对应，
#   每条尽量挑真的结构同构的（钱在系统里流动 ≈ 水在管里流动）。
#   它**只在兜底时用**：能自己判出领域时不会走到这里，所以不会盖掉模块原有判断。
_EXPLICIT_ANALOGY = (
    ("物理", "电路", "水管"),
    ("现金流", "水管", "人体"),
    ("资金", "水管", "人体"),
    ("流量", "水管", "人体"),
    ("管道", "水管", "人体"),
    ("血管", "水管", "人体"),
    ("公司", "市场", "生态"),
    ("商业", "市场", "生态"),
    ("生意", "市场", "生态"),
    ("竞争", "市场", "生态"),
    ("组织", "建筑", "人体"),
    ("团队", "建筑", "人体"),
    ("架构", "建筑", "人体"),
    ("系统", "电路", "水管"),
)


def _explicit_analogy(q):
    """从"说出来的词"直接找一套可借用的结构（兜底）。返回 `(from, to, pairs)` 或 None。

    按触发词长度降序匹配（"现金流"优先于"现金"），避免短词抢走长词的对应。
    """
    try:
        _an = _lazy("analogy")
        for kw, f, t in sorted(_EXPLICIT_ANALOGY, key=lambda x: -len(x[0])):
            if kw not in q:
                continue
            for m in getattr(_an, "STRUCTURE_MAP", ()):
                if m.get("from") == f and m.get("to") == t:
                    return f, t, (m.get("pairs") or [])
    except Exception:      # noqa: silent-ok — 兜底查不到就当没有，绝不影响对话
        pass
    return None


def dispatch(question):
    """按问题类型挑一种补刀，返回 `{"kind","text","why","evidence"}`；不命中返回 kind="none"。

    `evidence` 是给人看的短标签（日志/验证用），证明"这次真的走了哪个模块"。
    全程**只读、纯规则、不调模型** —— 它每轮都跑，必须便宜且确定。
    """
    q = norm(question)
    none = {"kind": "none", "text": "", "why": "", "evidence": ""}
    if not q or len(q) < 4:
        return none

    # ---- 10.3 跨领域联想：明确要求"用某某领域的思维/视角" ----
    # ⚠️ 必须排在 vague 之前：实测"用物理学的思维分析一下公司现金流"会被 vague 判为
    #    "缺主语/缺宾语"（它确实短、确实没有明确宾语），但用户**已经把方法说清了** ——
    #    这种"方法明确、对象抽象"的句子该走跨域联想，不该被反问。
    #    判据：出现"思维/视角/角度/类比"这类**显式跨域信号**就先认它。
    try:
        _an = _lazy("analogy")
        if has_any(q, ("思维", "视角", "角度", "类比", "打个比方", "跨界")):
            ans = _an.analogies(q, limit=2)
            if not ans:
                # 【为什么要有这条兜底 —— 验收实测踩到的】
                #   `analogies()` 靠"领域词汇命中"找源领域，而
                #   "用物理学的思维分析一下公司现金流"里**没有领域词汇**（现金流不是表里的词），
                #   于是源领域判为 None → 返回空 → 整块跳过（用户明确要了跨域却不给）。
                #   这里换个找法：拿**问题里的词**去撞结构映射表的每一对，
                #   哪一对能撞上就用哪一对（现金流 → 交通/水管映射里的"流量"）。
                #   这样"方法明确、对象抽象"的要求也能落到一条真实的结构映射上。
                _cands = []
                for _m in getattr(_an, "STRUCTURE_MAP", ()):
                    _hitw = []
                    for _p in (_m.get("pairs") or []):
                        for _w in _p:
                            if _w and _w in q:
                                _hitw.append(_w)
                    if _hitw:
                        _cands.append((len(_hitw), _m, _hitw))
                _cands.sort(key=lambda z: -z[0])
                if _cands:
                    _n, _m, _hitw = _cands[0]
                    _pairs = "；".join("%s↔%s" % (p[0], p[1])
                                       for p in (_m.get("pairs") or [])[:5])
                    return {"kind": "analogy",
                            "text": ("【跨领域联想】借「%s ↔ %s」这套结构来想：\n%s\n"
                                     "（沿用这套对应关系去推；结构对不上的地方要明说，"
                                     "不要生搬名词。）" % (_m.get("from"), _m.get("to"), _pairs)),
                            "why": "显式跨域要求；按概念「%s」命中映射 %s↔%s"
                                   % ("、".join(_hitw[:3]), _m.get("from"), _m.get("to")),
                            "evidence": "analogy:map=%s->%s(hit=%s)"
                                        % (_m.get("from"), _m.get("to"), ",".join(_hitw[:2]))}
                # 再兜一层：按"说出来的词"直接查那张对应表（见 `_EXPLICIT_ANALOGY` 的说明）
                _ex = _explicit_analogy(q)
                if _ex:
                    _f, _t, _pl = _ex
                    _pairs = "；".join("%s↔%s" % (p[0], p[1]) for p in _pl[:5])
                    return {"kind": "analogy",
                            "text": ("【跨领域联想】借「%s ↔ %s」这套结构来想：\n%s\n"
                                     "（沿用这套对应关系去推；结构对不上的地方要明说。）"
                                     % (_f, _t, _pairs)),
                            "why": "显式跨域要求；按词命中对应表 → %s↔%s" % (_f, _t),
                            "evidence": "analogy:explicit=%s->%s" % (_f, _t)}
            if ans:
                maps = _an.map_structure(q) or {}
                body = "\n".join("- %s ← %s（%s）"
                                 % (a.get("to") or "", a.get("from") or "",
                                    a.get("why") or "") for a in ans)
                pairs = "；".join("%s↔%s" % (p[0], p[1])
                                  for p in (maps.get("pairs") or [])[:4])
                return {"kind": "analogy",
                        "text": ("【跨领域联想】可以用别的领域的结构来想这件事：\n" + body
                                 + (("\n对应关系：" + pairs) if pairs else "")
                                 + "\n（只借结构，不要生搬名词；结构对不上的地方要明说。）"),
                        "why": "命中跨领域联想：%s" % (ans[0].get("from") or ""),
                        "evidence": "analogy:%s->%s" % (ans[0].get("from"),
                                                        ans[0].get("to"))}
    except Exception:      # noqa: silent-ok — 单项失败就当没命中，绝不影响对话
        pass

    # ---- 10.5 创造性：要多份不同风格/多个视角 ----
    try:
        _cr = _lazy("creative")
        if (has_any(q, ("不同风格", "几个不同的", "多个版本", "换着写", "不同角度"))
                or (("个" in q) and has_any(q, ("开场白", "标题", "slogan", "广告语")))):
            rs = _cr.resample(q, n=3)
            if rs:
                body = "\n".join("- 用「%s」的视角：%s"
                                 % (r.get("perspective") or "", (r.get("prompt") or "")[:80])
                                 for r in rs)
                tw = _cr.apply_operator("invert", seed=q[:8])
                extra = ("\n另外可以用这个创意算子换一下：%s —— %s"
                         % (tw.get("name") or "", (tw.get("twist") or "")[:60])) if tw else ""
                return {"kind": "creative",
                        "text": "【创造性】这一问要的是**多个不同方向**，请分别给，不要混成一个：\n"
                                + body + extra,
                        "why": "命中多视角采样（%d 个视角）" % len(rs),
                        "evidence": "creative:resample=%d" % len(rs)}
    except Exception:      # noqa: silent-ok — 同上
        pass

    # ---- 10.7 超长一致性：要写长文/小说（要实体表守着人名） ----
    try:
        _co = _lazy("consistency")
        import re as _re
        m = _re.search(r"(\d{3,6})\s*字", q)
        if m and int(m.group(1)) >= 1000 and has_any(
                q, ("写", "小说", "故事", "文章", "报告", "剧本")):
            names = _re.findall(r"(?:主角|主人公|名字)(?:叫|是|：|:)\s*([\u4e00-\u9fa5]{2,4})", q)
            return {"kind": "consistency",
                    "text": ("【超长一致性】这篇很长，必须全程保持同一套设定：\n"
                             "① 人名/地名/时间一次定死，之后**一个字都不许换写法**；\n"
                             "② 每段开头先在心里对齐「现在在哪、谁在场」再写；\n"
                             "③ 不要中途改设定（性格、关系、已发生的事）。"
                             + (("\n本篇已登记的人名：" + "、".join(names)) if names else "")),
                    "why": "命中超长文一致性（目标 %s 字）" % m.group(1),
                    "evidence": "consistency:longform=%s%s"
                                % (m.group(1), ("names=" + ",".join(names)) if names else "")}
    except Exception:      # noqa: silent-ok — 同上
        pass

    # ---- 10.6 深度推理：问"为什么/原理/机制" ----
    try:
        _dt = _lazy("deepthink")
        if has_any(q, ("为什么", "原理", "机制", "怎么运作", "本质", "为什么会")):
            pl = _dt.plan(q)
            if pl and pl.get("prompts"):
                return {"kind": "deepthink",
                        "text": pl["prompts"][0],
                        "why": "命中深度推理：auto 选型 = %s" % pl.get("mode"),
                        "evidence": "deepthink:mode=%s" % pl.get("mode")}
    except Exception:      # noqa: silent-ok — 同上
        pass

    # ---- 10.1 元推理模板：概率/逻辑/约束类题 ----
    try:
        _r = _lazy("reasoning")
        t = _r.pick(q)
        if t:
            return {"kind": "reasoning",
                    "text": _r.render(t["id"], q),
                    "why": t.get("why") or "",
                    "evidence": "reasoning:%s" % t["id"]}
    except Exception:      # noqa: silent-ok — 同上
        pass

    # ---- 10.2 长链因果：多个"比…"或明确因果链 ----
    try:
        _ca = _lazy("causal")
        if q.count("比") >= 2 or q.count("→") >= 2 or has_any(
                q, ("谁最", "排序", "排列", "高低顺序")):
            g = _ca.build_from_pairs([])
            return {"kind": "causal",
                    "text": g.render_prompt(q),
                    "why": "命中长链因果（多处比较/因果递推）",
                    "evidence": "causal:render_prompt"}
    except Exception:      # noqa: silent-ok — 同上
        pass

    # ---- 10.4 模糊意图：短句 + 指代/含糊（在融合之后仍显含糊才问） ----
    try:
        _vg = _lazy("vague")
        am = _vg.ambiguity(q)
        if am and am.get("is_vague"):
            cands = _vg.clarify_candidates(q, n=4) or []
            if cands:
                body = "\n".join("%d. %s" % (i + 1, c) for i, c in enumerate(cands))
                return {"kind": "vague",
                        "text": ("【意图可能不清】在答之前先给用户几个可选方向让他挑"
                                 "（别自己硬猜）：\n" + body),
                        "why": "判为模糊意图（%s）" % ",".join(am.get("signals") or [])[:40],
                        "evidence": "vague:signals=%s" % ",".join(am.get("signals") or [])[:30]}
    except Exception:      # noqa: silent-ok — 同上
        pass

    return none
