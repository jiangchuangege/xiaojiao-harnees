# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 长链因果图（模块 10.2）

【这段为什么这么设计】
    4B 模型最典型的两个毛病合在一起就是灾难：
      ① 把"相关"当"因果" —— 看见"早上堵车"和"我迟到"一起出现，就断言堵车导致了迟到；
      ② 只能看一步   —— 你问"那后来呢"，它把刚才那句话换几个词再说一遍。
    这两件事都不是"算力不够"，而是**载体没给它结构**：模型没有地方存"方向"，
    也没有地方存"第几步了"。所以修法是给它一张图，图由载体维护：
      · 节点 = 命题（一个"因"、一个"果"、或一条"事实"），有 id、可被引用、可被撤回；
      · 边   = "因为"（a → b 读作"a 是 b 的原因"，方向是硬存下来的，模型改不了）；
      · 图   = 上面两者的全集，落盘、可查环、可查冲突、可回溯。
    于是"长链推理"被拆成两半：**长**由载体负责（拼接、去环、找根找叶、防重复），
    **一小步**由模型负责（只回答"这条边的下一步是什么"）。4B 模型做不好前者，
    做后者是够的 —— 这就是本模块的全部立足点。

【去掉它会怎样】
    退回到"每次把前文整段塞给模型，让它一口气讲清因果"：
      · 相关与因果仍然分不清（模型连"谁在前谁在后"的记性都靠不住）；
      · 链条走到第四步开始自相矛盾、成环（A 因为 B、B 因为 A），而且没人发现；
      · 换个措辞说同一件事就变成两个平行节点，链永远接不起来（模型措辞最不稳定）；
      · 用户说"前面那个结论我撤回"，系统只能当没听见 ——
        因为它根本没有"撤回一条并连带其全部下游"的概念。

【共同公式怎么落在这里（四条缺一不可）】
    ① 结构化：含糊的"因为" → {from, to, why, ts, count} 的显式边；
    ② 载体维护：连边、去环、查冲突、回溯、找根叶，全是纯 Python 规则，一次都不问模型；
    ③ 一小步：`render_prompt()` 只问"下一格是什么"，并**明令禁止**一次给出整条长链；
    ④ 存回：`add_edge()` 把模型的答案变成新节点/新边并落盘，图**越用越大**。
    去掉④就成了一个普通的思维导图软件（今天和昨天一样聪明）；
    去掉②就退化成"让模型自己维护一致性"，而那恰恰是它最不擅长的事。

【几个关键取舍（都是预判或踩过坑才这么定的）】
    · **同一个说法 = 同一个命题**：节点按文本去重（"下雨"只有一个节点）。
      不去重的话，模型每次换个措辞就多一个节点，一周后满图同义节点，
      "长链"永远拼不起来 —— 而措辞不稳定正是小模型的固有特征。
    · **撤回是标记，不是删除**：节点与边全部留在图里，只加 `retracted` 标记。
      真删掉的话，"为什么撤"这个问题就永远回答不了了（下游连同它的来路一起消失），
      也与载体层"绝不删除任何东西"的总规矩直接冲突。
    · **全程迭代，绝不递归**：模型可能连着几百步给一条很长的链，
      递归版 DFS/BFS 会在约 1000 层时 RecursionError ——
      而本模块的硬要求是"任何输入都不抛"，长链恰恰是它最该扛住的场景。
    · **环检测用真算法（三色 DFS）**，不用"节点数 vs 边数"这种近似判据：
      有向图里 n 个点 n 条边未必有环、9 个点 8 条边也可能有环。
      近似判据要么漏掉"模型绕回来了"（最该抓的错），要么反过来报假警。
    · **返回给外部的一律是副本**：图是"载体维护的结构"，外部只读。
      直接交出内部 dict，等于让一个手抖的调用脚本就能改坏整张图。

【与其它模块的关系（不重复造轮子）】
    · 文本规整、命中判断、落盘目录、事件流水全部复用 `core.boost` 公共层，
      **不另写一份** —— 两套口径的必然结果是同一句话在两个模块里得到不同结论；
    · `memory_deep.associations()` 用"因果词"猜因果，是**粗筛**；
      本模块把它落成显式图，是正式版（前者给候选，后者给结构，不冲突）；
    · `consistency.py` 管"实体前后一致"，本模块管"因果关系本身自洽"，各管一段。

【数据落盘一律在 logs/boost/ 下】（logs/ 已被 .gitignore 忽略，不脏仓库）
    causal.json         图快照 {"version":1,"updated_at":...,"nodes":[...],"edges":[...]}
    causal_events.jsonl 结构变更流水（加了哪个节点/哪条边、撤回了谁）——
                        "这张图是怎么长成现在这样的"证据，只用追加，从不重写
    boost.jsonl         公共事件流水（由 core.boost.note 写，本模块只上报）

【绝不删除任何文件】
    本模块只有两种落盘动作：append（jsonl）与直写（json 快照）。
    没有任何 os.remove / unlink / rmtree / truncate；`save()` 也不做 tmp+rename
    （Windows 上 rename 覆盖目标，语义上接近删旧文件）。去掉这条自律，
    等于在载体层里埋一个随时可能吃掉用户数据的动作。
"""
import copy
import os

from . import boost_dir, boost_path, norm, hits, has_any, now, note
from . import append_jsonl, read_jsonl, read_json, write_json

# 快照与流水的文件名。为什么写成模块常量而不是散在函数里：
# 文件名是本模块对外的**契约**（别的模块、自检脚本、以后的数据迁移都要按名字找），
# 散写的话改一处漏一处，就会出现"写进了 causal2.json、读的还是 causal.json"。
SNAPSHOT_NAME = "causal.json"
EVENTS_NAME = "causal_events.jsonl"

# 节点的三种身份。为什么只留三种、不多留（比如"假设""预测"）：
# 这三种是**图上真正需要区别对待**的角色 —— 因是起点、果是终点、事实是锚点；
# 再加几种，模型就得先学会这套分类才肯干活，而它本来就学不动。
NODE_KINDS = ("cause", "effect", "fact")
KIND_CN = {"cause": "因", "effect": "果", "fact": "事实"}
# 非法 kind 的归一目标。为什么倒向 "fact" 而不是 "cause"：
# fact 是"图上最中性的一条命题"，当成因或果都会**替模型下结论**（凭空指定方向）；
# 倒向 fact 只是"我知道有这条命题，但不知道它在因果里的位置"，不谎报也不丢信息。
KIND_DEFAULT = "fact"

# 链数上限。为什么封顶：4B 的用法是"每次走一格"，它只看得懂几条链；
# 一个扇出 10 的图在 depth=3 时能裂出上千条链，全塞进 prompt 只会把它淹到更笨。
# 去掉上限：图越大，渲染出来的 prompt 越大，模型表现反而**越差**（与"越用越大"的初衷相反）。
MAX_CHAINS = 64
# 渲染 prompt 时列多少节点/边。理由同上：上下文是模型的稀缺资源，
# 全量倾倒等于把"结构"这一优势又还给噪声。
MAX_PROMPT_NODES = 40
MAX_PROMPT_EDGES = 40
# 别名与"额外理由"各自的保留上限。为什么要有上限：它们都是"顺手记下的附带信息"，
# 无上限追加会让一条边的 why_more 长成几千字，落盘文件逐次膨胀且没人会读。
MAX_ALIASES = 8
MAX_WHY_MORE = 8

# 问题里的"不确定词"。为什么让载体来认这几个词、而不是让模型自己判断该不该标不确定：
# 模型对自己"知不知道"是最没有判断力的（它会自信地编），
# 而这个判断只需要一个词表 —— 纯规则能做的事，不该去麻烦模型。
_HEDGE_WORDS = ("可能", "也许", "大概", "或许", "不确定", "说不准", "是否", "是不是",
                "据说", "好像是", "应该", "猜", "感觉", "未必", "不一定")


def _as_float(x, default=0.0):
    """把任意输入转成 float，转不动就给 default（**绝不抛**）。

    为什么时间读不出来时给 0 而不是 `now()`：
    给 now() 会把一条陈年命题伪装成"刚刚写的"，图按时间排序立刻失真，
    而 0 明确表示"时间未知"。去掉这个区分，排查"这条怎么排在前面"时就只能靠猜。
    """
    try:
        return float(x)
    except Exception:      # noqa: silent-ok — None / 未知字符串都按"时间未知"处理
        return default


def _as_int(x, default=1):
    """把任意输入转成 int（用于 count 之类），转不动给 default。"""
    try:
        return int(x)
    except Exception:      # noqa: silent-ok — 坏字段按 1 算：一条边至少被说过一次
        return default


def _events_path():
    """结构变更流水的完整路径。

    为什么走 `boost_dir()` 而不是自己拼字符串：目录"在哪儿"只允许有一个定义
    （见 `core/boost/__init__.py` 的 boost_dir），这里再拼一次就多出一份会过期的口径，
    而且 boost_dir() 会顺手把目录建出来，写入点不必自己再兜一次。
    """
    return os.path.join(boost_dir(), EVENTS_NAME)


class CausalGraph:
    """长链因果图：节点是命题，边是"因为"，图由载体维护、模型每次只补一格。

    【这段为什么这么设计】
        把"图"做成一个对象（而不是一堆模块级函数操作一个全局字典），是为了让
        **一张图可以被单独拿出来推演**：自测要能在临时目录里造一张假图、
        跑坏它、验环、验撤回，而不碰到用户真实的 `logs/boost/causal.json`。
        为此 `__init__` 允许注入 path —— 这是本类唯一为"可测"而开的接口。

    【去掉它会怎样（改成模块级全局图）】
        · 自测与真实使用共用一份内存状态，验完"撤回"就把用户真实的图标记成作废；
        · 两张图（比如"这个用户的"和"项目本身的"）无法并存 ——
          而小焦真实场景里就有多个讨论对象；
        · 也无法"读一份旧快照进来看看当时是什么样"。

    【线程安全说明（如实交代）】
        本类不做加锁。它的调用点在对话主路径上，由上层串行驱动；
        真要多线程用，请在上层自己串行化。写在这里是为了不让读者以为它天生线程安全。
    """

    # -------------------------------------------------------------- 生命周期
    def __init__(self, path=None):
        """建一张空图；`path` 是落盘路径，默认 `logs/boost/causal.json`。

        为什么默认路径走 `boost_path()` 而不是自己拼 `logs/boost/...`：
        路径口径只许有一份（同 `health_dir` 的理由），拼错一级就会"写进去了但读不到"。
        为什么空串也落到默认路径：`path=""` 在调用方眼里就是"没指定"；
        若把它当成一个真实路径，图会被写到一个名为空字符串的位置（实际是当前目录），
        而调用方还以为是默认位置 —— 这类"静默写到别处"最难查。
        """
        self.path = norm(path) or boost_path(SNAPSHOT_NAME)
        self._clear()

    def _clear(self):
        """把内存图清空（**只清内存，不碰任何文件**）。load 失败时靠它回到"空图"。"""
        self._nodes = []          # 节点，保持插入顺序（顺序即"图长成这样的过程"）
        self._edges = []          # 边，保持插入顺序（parents/children 的顺序据此而定）
        self._by_id = {}          # id -> 节点 dict（同一份对象，改它就是改图）
        self._id_by_text = {}     # 文本 -> id（"同一说法即同一命题"的唯一索引）
        self._edge_of = {}        # (from, to) -> 边 dict（重复边靠它合并）
        self._seq = 0             # 自增 id 游标（n1/n2/...）

    # -------------------------------------------------------------- 内部：id 与规整
    def _next_id(self):
        """给一个可读、确定、唯一的 id：n1、n2、n3……

        为什么不用 uuid / 时间戳：模型要**引用**这些 id（"因为 n3"）。
        uuid 它抄不对、时间戳它记不住，而 `n1` 这种短 id 在 4B 的上下文里刚好够用。
        确定性还带来一个好处：同样的输入序列一定得到同一张图，自测可复现。
        去掉唯一性检查（直接 `n%d % (seq+1)`）会怎样：外部手塞过 `n2` 之后，
        自增又发出一个 `n2`，两个节点撞 id —— 图当场错乱且**全程不报错**。
        """
        while True:
            self._seq += 1
            cand = "n%d" % self._seq
            if cand not in self._by_id:
                return cand

    def _bump_seq(self, node_id):
        """外部自带的 id（如 n7）出现后，把自增游标推到它之后，避免将来撞号。"""
        s = norm(node_id)
        if len(s) > 1 and s[0] == "n" and s[1:].isdigit():
            v = _as_int(s[1:], 0)
            if v > self._seq:
                self._seq = v

    def _resolve(self, ref):
        """把"id 或文本"解析成图中真实存在的 id；解析不出来返回 ""（**绝不抛**）。

        为什么容忍传文本：调用方手里常常只有句子（模型返回的是自然语言），
        why：调用方手里常常只有句子（模型返回的是自然语言），
        每次都要它先自己查 id 会到处出现"我明明传了那句话却说没这个节点"。
        为什么解析失败返回空串而不是 None 或抛异常：下面所有遍历函数据此统一返回 []，
        于是"未知 id 不抛"这条硬要求在**一个地方**就满足了，不用每个函数各兜一次。
        顺序是**先 id 后文本**：`add_edge("n1", "n2")` 里那两个显然是 id，
        若先去文本索引里找，就会把 id 当成一句话的内容、凭空造出同名的假节点（真踩过，见 _touch_edge）。
        """
        s = norm(ref)
        if not s:
            return ""
        if s in self._by_id:
            return s
        nid = self._id_by_text.get(s)
        return nid if nid in self._by_id else ""

    def _remember_alias(self, node, text):
        """把一个"同一命题的另一种说法"记进节点别名（不覆盖原命题）。

        为什么保留别名而不是覆盖 text：节点文本是用户与模型共同的锚点，
        覆盖它会让先前引用这段文字的人（和模型）对不上号。
        别名只是"它还被这么叫过"的记录 —— 既不丢信息，也不破坏锚点。
        去掉它：同一个节点被反复用不同措辞提起时，信息静默消失（只剩第一次的说法）。
        """
        t = norm(text)
        if node is None or not t or t == norm(node.get("text")):
            return
        meta = node.get("meta")
        if not isinstance(meta, dict):
            meta = {}
        aliases = meta.get("aliases")
        if not isinstance(aliases, list):
            aliases = []
        if t not in aliases and len(aliases) < MAX_ALIASES:
            aliases.append(t)
        meta["aliases"] = aliases
        node["meta"] = meta

    # -------------------------------------------------------------- 内部：造节点/连边
    def _new_node(self, text, kind="cause", node_id=None, log=True):
        """造节点（或复用一个已存在的同义节点），返回 id。内部实现，供 add_node 与 add_edge 共用。

        【为什么 add_edge 也要能造节点】
            调用方（尤其是模型）手里往往是两句话，而不是两个 id。
            强制"先 add_node 再 add_edge"会把最常用的动作变成两步，
            而模型最不擅长的就是多步流程 —— 它一定会漏掉第一步。
            所以 `add_edge` 自己把缺的节点补上，调用方只说"因为 A 所以 B"就够。

        【为什么空文本也要发一个 id，但不记进文本索引】
            空文本不是一个"命题"，无从判定它和另一条空文本是不是同一件事。
            若把它们偷偷合并到一个公共空节点上，`count` 就会把两条互不相干的空边
            说成"同一件事被说了两次" —— 那是假证据。
            所以空文本每次都发新节点；不抛、可用，但不谎称它们相同。
        """
        t = norm(text)
        want = norm(node_id)

        # ① 调用方点名要一个已存在的 id —— 直接用它，并把新说法记成别名（绝不覆盖原命题）
        if want and want in self._by_id:
            self._remember_alias(self._by_id[want], t)
            return want
        # ② 这个说法已经在图上 —— 同一个说法就是同一个命题（图不因措辞重复而分裂）
        if t and t in self._id_by_text:
            nid = self._id_by_text[t]
            if nid in self._by_id:
                return nid

        nid = want or self._next_id()
        if want:
            self._bump_seq(want)

        k = norm(kind)
        kl = k.lower()
        node = {"id": nid, "text": t, "kind": kl if kl in NODE_KINDS else KIND_DEFAULT,
                "ts": now(), "retracted": False, "meta": {}}
        # kind_raw 只在"写法不规范/非法"时出现：合法写法再记一遍原始值只是噪声，
        # 而非法写法必须留痕 —— 事后才回答得了"这个节点当初是被当成什么加进来的"。
        if kl not in NODE_KINDS:
            node["kind_raw"] = k
        elif k != kl:
            node["kind_raw"] = k

        self._nodes.append(node)
        self._by_id[nid] = node
        if t:
            self._id_by_text[t] = nid
        if log:
            self._ev("node_add", node=nid, kind=node["kind"], chars=len(t))
        return nid

    def _touch_edge(self, a, b, why="", log=True):
        """连一条 `a → b`（a 是因，b 是果）；已存在就合并并累加 count。返回边 dict 的副本。

        【为什么重复边是合并而不是拒绝、也不是各留一条】
            "同一个原因导致同一个结果"被说第二次，本身就是**证据的加强**（count=2），
            而不是错误 —— 拒绝它会丢掉"这件事被重复确认过"这个信息。
            各留一条则更糟：`children()` 会把同一个 id 列出两次，
            下游要渲染边关系的地方就得各自去重，那是分歧的开始。

        【为什么自环（a == b）不报错、也不特殊处理】
            它是模型真会犯的一种错（"A 因为 A"）。这里**如实存下来**，
            交给 `detect_cycle()` 去抓 —— 检测归检测、录入归录入。
            若在录入时就拒掉，等于把这条错误证据藏起来，事后无法解释"它当时怎么想的"。
        """
        # 先按 id 认、认不出再当文本处理 —— 这一步**必须有**，而且是自测当场抓出来的真 bug：
        # 早先这里直接调 `_new_node(a, ...)`，于是 `add_edge("n1", "n2")` 里那两个 id 被当成
        # **文本** "n1"/"n2"，凭空多造出两个节点（各带一条 a→b 的边），
        # 结果是"3 个节点的环"变成 6 个节点的图，`detect_cycle()` 报出的是 n4→n5→n6→n4 ——
        # 全程一处都不报错，只有节点数悄悄翻倍。id 必须优先于文本：
        # 传 id 是契约行为，传文本是宽容行为，宽容行为不该悄悄盖掉契约行为。
        na = self._resolve(a) or self._new_node(a, "cause", log=log)
        nb = self._resolve(b) or self._new_node(b, "effect", log=log)
        key = (na, nb)
        e = self._edge_of.get(key)
        if e is not None:
            e["count"] = _as_int(e.get("count"), 1) + 1
            e["ts"] = now()
            w = norm(why)
            if w and w != norm(e.get("why")):
                more = e.get("why_more")
                if not isinstance(more, list):
                    more = []
                if w not in more and len(more) < MAX_WHY_MORE:
                    more.append(w)
                e["why_more"] = more
            if log:
                self._ev("edge_merge", frm=na, to=nb, count=e["count"])
            return copy.deepcopy(e)

        e = {"from": na, "to": nb, "why": norm(why), "ts": now(), "count": 1,
             "retracted": False, "why_more": []}
        self._edges.append(e)
        self._edge_of[key] = e
        if log:
            self._ev("edge_add", frm=na, to=nb, why=norm(why)[:40])
        return copy.deepcopy(e)

    def _parents_ids(self, nid):
        """直接前驱 id（按边插入顺序，去重，只认图里真实存在的节点）。"""
        out, seen = [], set()
        for e in self._edges:
            if e.get("to") != nid:
                continue
            f = e.get("from")
            if f in seen or f not in self._by_id:
                continue
            seen.add(f)
            out.append(f)
        return out

    def _children_ids(self, nid):
        """直接后继 id（按边插入顺序，去重，只认图里真实存在的节点）。

        为什么过滤"图里不存在"的端点：文件被手改坏时可能留下悬空边（from/to 指向不存在的 id）。
        边本身**保留不删**（如实），但遍历不能认它 —— 否则 `parents()` 会返回一个
        根本不在 `nodes()` 里的 id，调用方拿去查节点就得到 None，
        表现为"图里明明说有一个父节点，却怎么都找不到它"。
        """
        out, seen = [], set()
        for e in self._edges:
            if e.get("from") != nid:
                continue
            c = e.get("to")
            if c in seen or c not in self._by_id:
                continue
            seen.add(c)
            out.append(c)
        return out

    def _row(self, nid):
        """节点副本；不存在返回 None。"""
        n = self._by_id.get(norm(nid))
        return copy.deepcopy(n) if n is not None else None

    def _text_of(self, nid):
        """节点文本；不存在返回空串（用于把 id 翻译成人看得懂的话）。"""
        n = self._by_id.get(norm(nid))
        return norm(n.get("text")) if n is not None else ""

    def _ev(self, event, **kw):
        """往 `logs/boost/causal_events.jsonl` 追加一条**结构变更**流水。

        为什么要单独一份流水，而不是全靠快照：快照只有"现在长什么样"，
        没有"怎么长成这样" —— 而排查"图上为什么多了一堆同义节点"时，
        需要的是"谁在哪一步加的"，不是一个静态结果。
        为什么写不进去也绝不抛：流水只是证据，不是功能；
        为了记一条日志让用户的对话失败，是明显不划算的交换（同 boost.note 的理由）。
        """
        rec = {"ts": now(), "event": norm(event), "graph": self.path}
        try:
            rec.update(kw)
        except Exception:      # noqa: silent-ok — kw 里塞了不可序列化对象也不能崩
            pass
        try:
            append_jsonl(_events_path(), rec)
        except Exception:      # noqa: silent-ok — 结构流水写不进去绝不影响图本身
            pass
        return rec

    def _event_count(self):
        """结构流水的条数（**如实读回来**，不用内存计数器）。

        为什么不用内存计数：计数器一 `load()` 就归零，统计会谎报"这张图只有 3 条历史"，
        而文件里躺着 300 条。读数慢一点没关系（它只在自检/界面里被调用），
        谎报会让"越用越大"这件事变得无法验证 —— 那正是本模块最想证明的东西。
        """
        try:
            return len(read_jsonl(_events_path()))
        except Exception:      # noqa: silent-ok — 流水读不出来就报 0，不能因为统计把 stats 弄崩
            return 0

    # -------------------------------------------------------------- 公开：加节点 / 加边
    def add_node(self, text, kind="cause", node_id=None):
        """加一个节点，返回 node_id（文本为空、kind 非法、id 重复都不抛）。

        kind 取值 `"cause" | "effect" | "fact"`；非法值归一到 `"fact"` 并在节点里记 `kind_raw`。
        详见 `_new_node`（真正的实现在那里，因为 add_edge 也要走同一套去重逻辑）。
        """
        try:
            return self._new_node(text, kind, node_id, log=True)
        except Exception:      # noqa: silent-ok — 造节点失败也要给一个可用的 id，绝不能把异常抛回对话
            return ""

    def add_edge(self, a, b, why=""):
        """加一条 `a → b`（a 是因，b 是果）。a/b 可以是 id，也可以是节点文本。

        文本不存在时**自动建节点**（调用方不必先 add_node）；自环、重复边都不抛，
        重复边**合并**并累加 `count`。返回边 dict（副本），至少含
        `{"from","to","why","ts","count"}`。

        为什么返回副本：见类 docstring —— 图是载体维护的结构，外部只读。
        去掉副本（直接交内部 dict）：一次误改 `e["count"]=999` 就能永久污染落盘快照，
        而且没有任何地方会报错。
        """
        try:
            return self._touch_edge(a, b, why, log=True)
        except Exception:      # noqa: silent-ok — 连边失败返回空 dict，调用方判空即可，绝不抛
            return {}

    # -------------------------------------------------------------- 公开：读图
    def nodes(self):
        """全部节点（**副本**）。被撤回的节点也在里面，只是多了 `retracted` 等标记。

        为什么必须能读出被撤回的节点：撤回是"标记而不是删除"的**唯一验收方式** ——
        读不出来就等于删了。同时它是回答"为什么撤"的前提（节点还在，才谈得上解释）。
        """
        return copy.deepcopy(self._nodes)

    def edges(self):
        """全部边（**副本**）。被撤回/作废的边同样留在里面。"""
        return copy.deepcopy(self._edges)

    def parents(self, node_id):
        """直接前驱的 id 列表（**按插入顺序**，确定性）。未知 id / None → `[]`，不抛。

        为什么顺序要是确定的（插入顺序）：同一条链两个进程跑出来顺序不同，
        日志与 prompt 就没法比对，排查"昨天它为什么这么说"时无从下手。
        """
        nid = self._resolve(node_id)
        return self._parents_ids(nid) if nid else []

    def children(self, node_id):
        """直接后继的 id 列表（**按插入顺序**，确定性）。未知 id / None → `[]`，不抛。

        它是"长链"的关键一步：模型每回答一次，载体就用它把游标往前挪一格。
        """
        nid = self._resolve(node_id)
        return self._children_ids(nid) if nid else []

    def chains(self, node_id, depth=3):
        """从 `node_id` 向下游走、**链上节点数 ≤ depth** 的所有链（元素是 id）。无后继 → `[[node_id]]`。

        【深度口径（容易误解，写清楚）】
            depth 数的是**链上的节点个数**，不是"跳数"：depth=3 → 长度 1/2/3 的链。
            于是 depth=1 就是"只看起点自己"。为什么这么定：调用方想看"三步之内的因果"，
            心里想的是"三个命题"，而不是"从起点出发走三次、得到四个命题"。
            链太长也没意义 —— 模型每次只补一格。

        【为什么必须处理环】
            a→b→a 是模型最常犯的错。不判环的话，`chains()` 会沿着环一直走下去，
            直到 depth 限制或无限递归。这里用"路径内去重"（同一个节点在同一条链里不出现两次），
            所以 2-环只会给出 `[[n1],[n1,n2]]` 两条链 —— 该循环的信息由 `detect_cycle()` 负责报，
            链列表只负责"从这儿往前能走到哪"。

        【为什么封顶 MAX_CHAINS、为什么短的排前面】
            封顶理由见常量注释（prompt 会被淹）。短的排前面，是因为本模块的用法是
            "每次走一格"：最短的那条链就是**下一步**，长链是背景。
            去掉排序（保持 DFS 发现顺序）会出现"想找下一步，结果列表第一条是走到头的最长链"。
        """
        start = self._resolve(node_id)
        if not start:
            return []
        d = _as_int(depth, 3)
        # depth ≤ 0 也要给出 [[start]]：否则调用方拿到空列表会以为"这个节点不存在"，
        # 而它其实只是"没往后看"。把"没往后看"和"没这个节点"混成同一个返回值，是最典型的口径分裂。
        d = max(1, d)

        out = []
        stack = [(start, [start])]
        while stack:
            node, path = stack.pop()
            out.append(list(path))
            if len(path) >= d or len(out) >= MAX_CHAINS:
                continue
            # 先压后取（栈是后进先出）→ 反转一次，使弹出顺序与边的插入顺序一致（确定性）
            for c in reversed(self._children_ids(node)):
                if c in path:
                    continue
                if len(out) + len(stack) >= MAX_CHAINS * 4:
                    break          # 粗档保护：极端扇出的图不把内存吃光
                stack.append((c, path + [c]))
        out.sort(key=lambda ch: (len(ch), ch))
        return out[:MAX_CHAINS]

    def roots(self):
        """入度为 0 的节点 id（没有任何前驱 = 因果链的起点）。

        为什么它是本模块最有用的一张清单："这件事到底为什么会发生"，
        答案就是沿 parents 一直上溯到根 —— 载体做这一步是瞬时的，
        而让 4B 模型自己上溯，它到第二步就开始编。
        """
        return [n["id"] for n in self._nodes if not self._parents_ids(n["id"])]

    def leaves(self):
        """出度为 0 的节点 id（没有任何后继 = 因果链的终点，即"后来呢"暂时没有答案的地方）。

        它与 `roots()` 一起构成本模块的"待补清单"：根是"因还不明"，叶是"果还没接"。
        """
        return [n["id"] for n in self._nodes if not self._children_ids(n["id"])]

    # -------------------------------------------------------------- 公开：结构诊断
    def detect_cycle(self):
        """找到**任意一个**环，返回形如 `["n1","n2","n3","n1"]`（首尾相同）；无环返回 `[]`。

        【为什么用三色 DFS，而不是"节点数 vs 边数"这类近似判据】
            有向图里 n 个点 n 条边未必有环（一条链加一条回头边走别的方向就没有），
            少于 n 条边也可能有环（9 个点 8 条边照样能绕回来）。
            近似判据的两种后果都不可接受：漏掉"模型绕回来了"（最该抓的错），
            或者反过来在一条正常链上报假警（那会让用户开始不信这张图）。
            三色（白=未访问 / 灰=在当前路径上 / 黑=已定案）是**判定有向环的标准做法**，
            灰->灰才叫环，一步都不含糊。

        【为什么是迭代而不是递归】
            见类 docstring：几百个节点的长链会让递归版撞上 RecursionError，
            而"绝不抛异常"是本模块的硬要求。手写栈没有这个风险。

        【返回的环从哪开始】
            从"最深那个还在栈上的灰点"开始 —— 也就是 DFS 第一次真正咬住环的位置，
            保证同一个图每次跑出来是同一个环（确定性），自测才可复现。
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n["id"]: WHITE for n in self._nodes}
        for start in [n["id"] for n in self._nodes]:
            if color.get(start, WHITE) != WHITE:
                continue
            color[start] = GRAY
            path = [start]
            stack = [(start, iter(self._children_ids(start)))]
            while stack:
                node, it = stack[-1]
                found = None
                for child in it:
                    c = color.get(child, WHITE)
                    if c == GRAY and child in path:
                        found = child
                        break
                    if c == WHITE:
                        color[child] = GRAY
                        path.append(child)
                        stack.append((child, iter(self._children_ids(child))))
                        found = None
                        break
                if found is not None:
                    i = path.index(found)
                    return path[i:] + [found]
                if stack and stack[-1][0] == node and stack[-1][1] is it:
                    # 上面的 for 正常耗尽（没有 break 出子节点）→ 本节点定案为黑，出栈
                    color[node] = BLACK
                    stack.pop()
                    if path and path[-1] == node:
                        path.pop()
        return []

    def _pair_of(self, p):
        """把一对输入规整成 (a, b)；认 tuple/list 也认 dict（含 a/b 或 from/to）。不抛。"""
        try:
            if isinstance(p, dict):
                return (p.get("a", p.get("from")), p.get("b", p.get("to")))
            if isinstance(p, (tuple, list)) and len(p) >= 2:
                return (p[0], p[1])
        except Exception:      # noqa: silent-ok — 认不出的形状一律当"这对不用查"
            pass
        return (None, None)

    def _contradiction_row(self, a, b, fwd, rev):
        """拼一条冲突记录：a/b 用**文本**（可读），同时保留 id（可回查）。"""
        return {"a": self._text_of(a), "b": self._text_of(b), "a_id": a, "b_id": b,
                "why": "「%s」既是「%s」的原因，又是「%s」的结果（两条边方向相反）"
                       % (self._text_of(a) or a, self._text_of(b) or b, self._text_of(b) or b),
                "edges": [copy.deepcopy(fwd), copy.deepcopy(rev)]}

    def detect_contradiction(self, pairs=None):
        """同一对节点既有正向边又有反向边（`a→b` 且 `b→a`）→ 冲突。

        返回 `[{"a":<文本>,"b":<文本>,"a_id":..,"b_id":..,"edges":[正向边,反向边],"why":..}]`。
        `pairs=None` 时检查全部；也可以显式给 `[(id1,id2), ...]`（每项可传文本或 id）。

        【为什么"文本 + id"两个都给】
            文本是给人（和模型）看的：`"下雨" 既是 "地面湿" 的原因，又是它的结果`
            一眼就知道哪里错了。id 是给程序回查的：光有文本，下游想改这条边还得再查一次表。
            只给 id → 日志不可读；只给文本 → 拿到后无法直接操作。两个都给才自洽。

        【为什么自环（a == b）不算冲突，交给 detect_cycle】
            一条 `a→a` 既是"正向"又是"反向"，算进来会让同一条边被报告两次；
            而它的性质是**环**，不是"两个方向互相矛盾"。各归各的检测器，日志才不重不漏。

        【为什么 pairs 参数必须存在】
            图大了以后全量两两检查是 O(边数)；而调用方常常只关心刚加进来的那几对
            （"模型刚说了 A 导致 B，但它前面说过 B 导致 A 吗"）。给个显式入口，
            才不用为了查一对而把整张图扫一遍。
        """
        out, seen = [], set()
        if pairs is None:
            for e in self._edges:
                a, b = norm(e.get("from")), norm(e.get("to"))
                if not a or not b or a == b:
                    continue
                if a not in self._by_id or b not in self._by_id:
                    continue
                rev = self._edge_of.get((b, a))
                if rev is None:
                    continue
                key = (a, b) if a < b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                out.append(self._contradiction_row(a, b, e, rev))
        else:
            try:
                items = list(pairs)
            except Exception:      # noqa: silent-ok — 传了个不可迭代的东西就当"没有要查的对"
                items = []
            for p in items:
                a_ref, b_ref = self._pair_of(p)
                a, b = self._resolve(a_ref), self._resolve(b_ref)
                if not a or not b or a == b:
                    continue
                key = (a, b) if a < b else (b, a)
                if key in seen:
                    continue
                fwd, rev = self._edge_of.get((a, b)), self._edge_of.get((b, a))
                if fwd is None or rev is None:
                    continue
                seen.add(key)
                out.append(self._contradiction_row(a, b, fwd, rev))
        return out

    # -------------------------------------------------------------- 公开：回溯
    def retract(self, node_id, reason=""):
        """**回溯**：撤销一个节点的结论及其**全部下游**（标记而不删除）。

        返回 `{"ok": bool, "retracted": [id...], "reason": str, "count": int}`。
        未知 id → `ok=False`，其余字段为空，**不抛**。

        【为什么是标记而不是删除（本模块最重要的一条）】
            · 删了，"为什么撤"就永远答不了 —— 下游连同它的来路一起消失，
              用户问"我那条结论怎么没了"，系统只能沉默；
            · 真删会与载体层"绝不删除任何东西"的总规矩冲突；
            · 标记是可逆的：将来用户说"算了，还是算上吧"，改一个 True 就回来了。
            所以节点/边一个字不动，只加 `retracted` / `retract_reason` / `retracted_at`
            以及 `meta["retracted_by"]`（**是哪个上游把它带下来的**）。

        【为什么下游要记 retracted_by】
            "撤"的原始理由（reason）只有用户说得清，而**传播路径**只有载体算得出。
            不记它的话，"下游这个节点为什么也废了"就只能回答"因为上游废了"，
            指不出具体是哪个上游 —— 而一个节点常有多个上游，用户需要知道是哪条链带来的。

        【为什么保留第一次的标记、不因二次撤回而覆盖】
            第一次才是"为什么撤"的原始答案。二次撤回若覆盖 reason/retracted_by，
            历史理由就被后来的话顶掉了 —— 而"当初为什么撤"恰恰是事后最想知道的事。
            所以已标记的节点保持原样，但仍会出现在本次返回值里（调用方要的是"现在作废的有哪些"）。

        【边的作废判据为什么是"任一端在作废区"】
            fail-safe 方向：宁可多标"这条边别再用了"，不可漏标"这条边还能用"。
            多标的代价只是保守（模型少一条依据），漏标的代价是模型拿着一条
            已经作废的因果继续往下推 —— 那正是"把相关当因果"的翻版。
        """
        start = self._resolve(node_id)
        r = norm(reason)
        if not start:
            self._ev("retract_miss", node=norm(node_id), reason=r)
            return {"ok": False, "retracted": [], "reason": r, "count": 0}

        ts = now()
        order = [start]
        by = {start: ""}          # 谁把它带下来的；起点是"人手点的"，没有上游
        seen = {start}
        i = 0
        # 迭代 BFS（不用递归，理由见类 docstring）。只沿"出边"走 —— 撤回的方向是因果的正向：
        # 撤掉一个因，它导出的果才作废；而它的因（上游）不受影响（上游可能另有解释）。
        while i < len(order):
            cur = order[i]
            i += 1
            for c in self._children_ids(cur):
                if c in seen:
                    continue
                seen.add(c)
                by[c] = cur
                order.append(c)

        for nid in order:
            n = self._by_id.get(nid)
            if n is None:
                continue
            meta = n.get("meta")
            if not isinstance(meta, dict):
                meta = {}
            if not n.get("retracted"):
                n["retracted"] = True
                n["retract_reason"] = r
                n["retracted_at"] = ts
                meta["retracted_by"] = by.get(nid, "")
                meta["retract_source"] = "manual" if nid == start else "upstream"
            else:
                meta.setdefault("retracted_by", by.get(nid, ""))
            n["meta"] = meta

        for e in self._edges:
            f, t = norm(e.get("from")), norm(e.get("to"))
            if f in seen or t in seen:
                if not e.get("retracted"):
                    e["retracted"] = True
                    e["retracted_at"] = ts
                e["retract_side"] = ("both" if (f in seen and t in seen)
                                     else ("from" if f in seen else "to"))

        self._ev("retract", node=start, reason=r, count=len(order))
        note("causal_retract", node=start, reason=r, count=len(order))
        return {"ok": True, "retracted": list(order), "reason": r, "count": len(order)}

    # -------------------------------------------------------------- 公开：渲染给模型的问题
    def _context(self, question):
        """挑出这次要写进 prompt 的节点/边（按相关性裁剪，不是全量倾倒）。

        优先级：问题里点名的节点 > 根（因从哪儿起） > 叶（果到哪儿断） > 其余（按最近加入）。
        为什么这么排：模型这次只走一步，"问题里刚提到的那条"最可能就是它要接的那一格；
        根和叶是"链的两端"，是缺了它就断线的地方；剩下的都是背景。

        返回 (节点 id 列表(按图内顺序), 边列表, 被点名的 id 集合, 问题里有没有不确定词)。
        """
        q = norm(question)
        mentioned = set()
        if q:
            texts = [n["text"] for n in self._nodes if n.get("text")]
            # 用公共层 hits()：口径与其它模块完全一致（同一句话在哪都命中同一批词）。
            # 自己写一套 `in` 判断的结果是"模糊意图认为命中了、因果图认为没命中"。
            for t in hits(q, texts):
                nid = self._id_by_text.get(t)
                if nid:
                    mentioned.add(nid)

        picked, picked_set = [], set()

        def take(nid):
            if nid and nid not in picked_set and len(picked) < MAX_PROMPT_NODES:
                picked_set.add(nid)
                picked.append(nid)

        for nid in [n["id"] for n in self._nodes if n["id"] in mentioned]:
            take(nid)
        for nid in self.roots():
            take(nid)
        for nid in self.leaves():
            take(nid)
        for n in reversed(self._nodes):        # 越晚加入的越可能是当前话题
            take(n["id"])

        # 回到图内插入顺序：列表读起来和用户看图时的顺序一致（确定性，也更好读）
        sel = [n["id"] for n in self._nodes if n["id"] in picked_set]

        edges = []
        for e in self._edges:
            if e.get("from") in picked_set and e.get("to") in picked_set:
                edges.append(e)
                if len(edges) >= MAX_PROMPT_EDGES:
                    break
        hedged = has_any(q, _HEDGE_WORDS)
        return sel, edges, mentioned, hedged

    def render_prompt(self, question):
        """给模型的问题模板：**先给因、再给果、并标出不确定的地方**，同时把已知图作为上下文列进去。

        【这段为什么这么设计】
            模型的自由发挥是"另起一套说法"的源头：你让它解释因果，它会造新名词，
            于是图里多出一堆同义节点、链再也接不起来。所以模板三件事缺一不可：
              ① 顺序锁死（先因后果）—— 逼它给出**方向**，而不是一段"A 和 B 有关"的散文；
              ② 上下文给全（已知命题的编号 + 已知的"因为"）—— 让它**沿用**已有说法；
              ③ 强制标注不确定 —— 把它"不知道自己不知道"这件事，变成一行必须写出来的字。
            再加一条硬约束："只回答相邻一步"。整条长链由载体自己拼 ——
            这正是"模型每次只做一小步"的落地方式。

        【去掉它会怎样】
            回到"用户问一句、模型答一段"：相关与因果依然分不清（没有方向约束），
            每次换个措辞就多一批同义节点，而且它会把"编的"和"记得的"混在一段话里交出来 ——
            不确定性从不外露，用户无从分辨。

        【为什么问题里的不确定词要让载体来认】
            模型对自己"知不知道"最没有判断力（它会自信地编）。这个判断只需要一个词表，
            纯规则就够。认出来之后，模板会额外要求它"逐条写不确定"，而不是靠它自觉。
        """
        q = norm(question)
        sel, edges, mentioned, hedged = self._context(q)
        lines = []
        lines.append("【因果图 · 这一轮只走一小步】")
        lines.append("")
        lines.append("问题：%s" % (q or "（没给具体问题，就接着图上最后一条命题往下走一步）"))
        lines.append("")

        if not sel:
            lines.append("已知命题：现在还是空的（这是第一条因果，由你来起头）。")
            lines.append("已知的「因为」关系：无。")
        else:
            lines.append("已知命题（请沿用下面的编号和说法，不要另起一套名字）：")
            for nid in sel:
                n = self._by_id.get(nid) or {}
                tag = KIND_CN.get(norm(n.get("kind")), "事实")
                extra = ""
                if n.get("retracted"):
                    extra = "【已撤回：%s，不要再拿它当依据】" % (
                        norm(n.get("retract_reason")) or "未给理由")
                mark = "（问题里提到了它）" if nid in mentioned else ""
                lines.append("  %s [%s] %s%s%s" % (nid, tag, norm(n.get("text")) or "（空命题）",
                                                   extra, mark))
            lines.append("")
            lines.append("已知的「因为」关系（读作：前者是后者的原因）：")
            if not edges:
                lines.append("  （暂时还没有连起来的边）")
            for e in edges:
                lines.append("  %s(%s) → %s(%s)%s" % (
                    e.get("from"), self._text_of(e.get("from")) or "空",
                    e.get("to"), self._text_of(e.get("to")) or "空",
                    ("  理由：%s" % norm(e.get("why"))) if norm(e.get("why")) else ""))
            hidden = len(self._nodes) - len(sel)
            if hidden > 0:
                lines.append("  （图里还有 %d 条命题没列出来，需要时按编号追问，别猜）" % hidden)
        lines.append("")
        lines.append("要求（按顺序写，缺一项就算没答）：")
        lines.append("1) 因：先写「因为什么」。优先从上面已知命题里选，并写出它的编号（如 n1）。")
        lines.append("2) 果：再写「导致了什么」。同样要写编号；图里没有的写成「新：<一句话>」。")
        lines.append("3) 不确定：单独写一行「不确定：…」，把你没把握的地方列出来；确实没有就写「不确定：无」。")
        lines.append("4) 只写**相邻的一步**，不要一次给出整条长链（长链由系统自己拼）。")
        if hedged:
            lines.append("")
            lines.append("注意：问题里带了「可能/是否/大概」这类词，第 3 项必须是认真作答，"
                         "不许用「不确定：无」敷衍过去。")
        lines.append("")
        lines.append("（如果上面某条命题已经标了「已撤回」，不要再用它推出任何结论。）")

        text = "\n".join(lines)
        question_preview = q[:40]
        self._ev("render_prompt", chars=len(text), nodes=len(sel), edges=len(edges),
                 hedged=hedged)
        note("causal_render", question=question_preview, nodes=len(sel), edges=len(edges),
             graph_nodes=len(self._nodes), graph_edges=len(self._edges))
        return text

    # -------------------------------------------------------------- 公开：落盘
    def _path_of(self, path):
        """这次读写用哪个路径：显式给了就用它，否则用对象自己的路径。

        为什么显式 path **不**顺手改掉 `self.path`：
        否则一次自测性质的 `load(tmp)` 会让后续所有 `save()` 悄悄写到临时目录去，
        用户的真实图从此不再更新，而系统看起来一切正常 —— 这类"静默改目的地"最难查。
        """
        return norm(path) or self.path

    def save(self, path=None):
        """把图落盘成 `{"version":1,"updated_at":<float>,"nodes":[...],"edges":[...]}`。返回 True/False，**绝不抛**。

        【为什么是直写而不是 tmp+rename】
            rename 在 Windows 上要覆盖目标，语义上等同"删掉旧文件"，
            而本层有一条硬规矩是**绝不删除任何文件**。这里写的是自己的快照，
            内容全在内存，写坏了下一次 save 就覆盖回来 —— 直写足够，且不越线。
        【为什么失败只返回 False 而不抛】
            落盘成功与否是"这次记住没有"，不是"这次回答对不对"。
            为了存一张图让用户的对话失败，交换明显不划算。
        """
        p = self._path_of(path)
        data = {"version": 1, "updated_at": now(),
                "nodes": copy.deepcopy(self._nodes),
                "edges": copy.deepcopy(self._edges)}
        ok = False
        try:
            ok = bool(write_json(p, data))
        except Exception:      # noqa: silent-ok — 写不进去只是"这次没存上"，绝不把异常抛回对话
            ok = False
        self._ev("save", path=p, ok=ok, nodes=len(self._nodes), edges=len(self._edges))
        note("causal_save", path=p, ok=ok,
             nodes=len(self._nodes), edges=len(self._edges))
        return ok

    def load(self, path=None):
        """从落盘快照读回图。成功 True；读不到/格式坏了 → False **且图保持为空**，绝不抛。

        【为什么失败时清空成空图】
            规格就是这么定的，而且它有一层实际好处：调用方不必区分"没读到"和"读到一个空图"，
            一次 `if not g.load(): 从头开始` 就够了。
            **注意范围**：清空的只是**内存视图**，落盘文件一个字都没动 ——
            `write_json`/`append_jsonl` 之外的任何删除动作在本模块里根本不存在，
            新数据会在下一次 `save()` 时覆盖回去。
        【为什么容错到这种程度（坏行跳过、缺 id 补发、坏字段给默认值）】
            快照可能被手改、被旧版本写过、被半截写入（进程被杀）。
            一处坏字段就让整张图读不回来，等于用户几个月攒的因果结构一次报废；
            而跳过一个坏节点只是少一条命题 —— 两害相权，必须选后者。
        """
        p = self._path_of(path)
        raw = None
        try:
            raw = read_json(p, default=None)
        except Exception:      # noqa: silent-ok — read_json 本身已兜底，这里再兜一层不影响语义
            raw = None

        self._clear()
        ok = False
        try:
            if isinstance(raw, dict):
                nodes = raw.get("nodes")
                edges = raw.get("edges")
                if isinstance(nodes, list) and isinstance(edges, list):
                    self._load_nodes(nodes)
                    self._load_edges(edges)
                    ok = True
        except Exception:      # noqa: silent-ok — 解析途中出任何意外都退化成"没读到"，绝不抛
            self._clear()
            ok = False

        self._ev("load", path=p, ok=ok, nodes=len(self._nodes), edges=len(self._edges))
        note("causal_load", path=p, ok=ok,
             nodes=len(self._nodes), edges=len(self._edges))
        return ok

    def _load_nodes(self, rows):
        """把快照里的节点行读进内存（坏行跳过、缺 id 补发、字段归一）。"""
        for r in rows:
            if not isinstance(r, dict):
                continue
            nid = norm(r.get("id"))
            if not nid or nid in self._by_id:
                # id 缺了或撞了：补发一个新 id。扔掉的代价是"少一条命题"，而留下撞号
                # 会让整张图错乱（两个节点同名同 id 的图没有任何地方救得回来）。
                nid = self._next_id()
            k = norm(r.get("kind"))
            if k not in NODE_KINDS:
                k = KIND_DEFAULT
            meta = r.get("meta")
            node = {"id": nid, "text": norm(r.get("text")), "kind": k,
                    "ts": _as_float(r.get("ts"), 0.0),
                    "retracted": bool(r.get("retracted")),
                    "meta": meta if isinstance(meta, dict) else {}}
            if norm(r.get("kind_raw")):
                node["kind_raw"] = norm(r.get("kind_raw"))
            if norm(r.get("retract_reason")):
                node["retract_reason"] = norm(r.get("retract_reason"))
            if r.get("retracted_at") is not None:
                node["retracted_at"] = _as_float(r.get("retracted_at"), 0.0)
            self._nodes.append(node)
            self._by_id[nid] = node
            self._bump_seq(nid)
            if node["text"] and node["text"] not in self._id_by_text:
                self._id_by_text[node["text"]] = nid

    def _load_edges(self, rows):
        """把快照里的边行读进内存（同一对只留一条，count 相加；悬空边如实保留）。"""
        for r in rows:
            if not isinstance(r, dict):
                continue
            a, b = norm(r.get("from")), norm(r.get("to"))
            if not a or not b:
                continue       # 没有端点就构不成一条边，跳过（它不是数据，是噪声）
            key = (a, b)
            exist = self._edge_of.get(key)
            if exist is not None:
                # 同一对出现两条：合并并把 count 相加，而不是留下两条"同款边"。
                # 留下两条的话 children() 会把同一个 id 列出两次，下游每处都得各自去重。
                exist["count"] = _as_int(exist.get("count"), 1) + _as_int(r.get("count"), 1)
                continue
            more = r.get("why_more")
            e = {"from": a, "to": b, "why": norm(r.get("why")),
                 "ts": _as_float(r.get("ts"), 0.0),
                 "count": max(1, _as_int(r.get("count"), 1)),
                 "retracted": bool(r.get("retracted")),
                 "why_more": [norm(x) for x in more if norm(x)][:MAX_WHY_MORE]
                             if isinstance(more, list) else []}
            if r.get("retracted_at") is not None:
                e["retracted_at"] = _as_float(r.get("retracted_at"), 0.0)
            if norm(r.get("retract_side")):
                e["retract_side"] = norm(r.get("retract_side"))
            self._edges.append(e)
            self._edge_of[key] = e

    # -------------------------------------------------------------- 公开：概览
    def stats(self):
        """给界面/自检用的概览。至少含
        `{"nodes","edges","roots","leaves","has_cycle","retracted"}`，**全部是真实统计**，没有就写 0。

        为什么要连 `cycles`/`contradictions` 一起算：这两个数才是这张图的"体检结论"
        （不是"有几条边"这种体量数字）。用户真正需要知道的是"我的因果里有没有绕回去的、
        有没有自相矛盾的" —— 让界面只显示节点数，等于把体检报告换成了体重秤。
        """
        cyc = self.detect_cycle()
        con = self.detect_contradiction()
        kinds, retracted = {}, 0
        for n in self._nodes:
            k = norm(n.get("kind")) or KIND_DEFAULT
            kinds[k] = kinds.get(k, 0) + 1
            if n.get("retracted"):
                retracted += 1
        dangling = sum(1 for e in self._edges
                       if norm(e.get("from")) not in self._by_id
                       or norm(e.get("to")) not in self._by_id)
        return {"nodes": len(self._nodes), "edges": len(self._edges),
                "roots": len(self.roots()), "leaves": len(self.leaves()),
                "has_cycle": bool(cyc), "retracted": retracted,
                "cycle": list(cyc), "contradictions": len(con),
                "has_contradiction": bool(con), "kinds": kinds,
                "dangling_edges": dangling, "events": self._event_count(),
                "path": self.path}


def build_from_pairs(pairs, path=None):
    """从 `[("原因文本","结果文本"), ...]` 快速建一张图，返回 `CausalGraph`。

    【这段为什么这么设计】
        无论自测还是调用方，"我手上有一批因果对，想立刻变成图"是最常见的起点。
        若逼调用方自己 `for` 循环调 `add_edge`，每个人都会写出略有差异的循环
        （有人忘了判空、有人把顺序写反），图的样子就开始分叉。

    【为什么入参容错到这个程度（dict / 单项 / 空 / None 都收）】
        调用方传进来的是"想法"，不是"严格结构"：`{"from":..,"to":..}`、
        `("因","果","理由")`、`None` 都可能出现，尤其在上层是从模型输出解析出来的时候。
        一种形状不认就整体抛异常，等于让一句格式不对的回答毁掉整批数据。

    【为什么**不**自动 save】
        写盘必须是**显式动作**。自动落盘会让一次自测/推演顺手改掉用户真实的图，
        而系统看起来一切正常（这正是最难查的一类事故）。
        调用方要存就显式 `build_from_pairs(...).save()`。
    """
    g = CausalGraph(path)
    items = []
    try:
        if pairs is not None:
            items = list(pairs)
    except Exception:      # noqa: silent-ok — 不可迭代就当没有输入，返回空图而不是崩
        items = []

    n = 0
    for p in items:
        a = b = why = ""
        try:
            if isinstance(p, dict):
                a, b = p.get("from", p.get("cause", p.get("a"))), p.get("to", p.get("effect", p.get("b")))
                why = p.get("why", "")
            elif isinstance(p, (tuple, list)) and len(p) >= 2:
                a, b = p[0], p[1]
                why = p[2] if len(p) >= 3 else ""
        except Exception:      # noqa: silent-ok — 单条形状不认就跳过它，不能拖垮整批
            continue
        if not norm(a) or not norm(b):
            continue           # 缺一端的"因果对"不是因果，跳过（计数也不加）
        # log=False：批量建图时逐条写流水会把 causal_events.jsonl 淹掉，
        # 真正有意义的是"这一次批量加了什么"，所以只在下面记一条汇总。
        g._touch_edge(a, b, why, log=False)
        n += 1

    g._ev("build", pairs=n, nodes=len(g._nodes), edges=len(g._edges))
    note("causal_build", pairs=n, nodes=len(g._nodes), edges=len(g._edges), path=g.path)
    return g


__all__ = ["CausalGraph", "build_from_pairs", "NODE_KINDS", "KIND_CN", "KIND_DEFAULT",
           "SNAPSHOT_NAME", "EVENTS_NAME"]
