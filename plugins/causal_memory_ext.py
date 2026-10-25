# plugins/causal_memory_ext.py —— 因果记忆的**第二批工具**（把小焦没有的补齐，2026-10-15）
#
# 【为什么另开一个文件、而不是改 causal_memory.py】
#   小焦自己的插件规矩就是"往 plugins/ 目录丢文件即生效，不为主程序改一行代码"
#   （见 docs/PLUGINS.md 第 1 节）。所以补齐能力用**新插件**是零修改的扩展方式：
#   这个文件被删掉，小焦一切照旧；主程序、causal_memory.py 都不用动。
#
# 【第一批（causal_memory.py）给了什么】causal_warn / causal_search / causal_record /
#   causal_trace / causal_counterfactual / causal_report —— 覆盖"动手前问、动手后记、查教训"。
# 【这一批补什么】
#   causal_memory_map    库的全貌（多少边、多少节点、最近什么）
#   causal_patterns      引擎自己挖出来的关系：相似 / 重复 / 矛盾 / 精化
#   causal_lesson        从多条散边重建一条可复用的教训
#   causal_unified       统一检索（它那边的事实层 + 因果层一起查）
#   causal_invalidate    把一条**错的**教训软作废（可回滚，不是删除）
#   causal_resolve       LLM 评审：把"同一决策反复记、结局却不同"的发散项合并
#   causal_trace_one     单跳溯源（多跳那个在第一批的 causal_trace）
#   causal_remember      直接把一段对话喂进它的提炼链路（不用手工拆决策/结果）
#   causal_facts         查它那边的事实层（与小焦自己的记忆是两套，别混）
#   （`record_fact` 故意不接：小焦自己有事实记忆，再来一套只会打架。）
#
# 【铁规矩】和第一批一致：拿不到引擎就一个工具都不注册；所有失败/空结果都返回中文说明；
#   空结果要明说"没记录 ≠ 没事"。
import logging
import sys

LOG = logging.getLogger(__name__)


def _base():
    """拿到第一批那个插件模块（复用它的常驻 MCP 客户端，不重复起进程）。"""
    m = sys.modules.get("causal_memory")
    if m is None:
        try:
            import causal_memory as m        # 小焦按文件名加载，模块名就是 causal_memory
        except Exception:      # noqa: silent-ok — 拿不到就当作没这层
            return None
    return m


def _inst():
    m = _base()
    inst = getattr(m, "_INSTANCE", None) if m is not None else None
    if inst is None or not getattr(inst, "available", False):
        return None
    return inst


class CausalMemoryExtPlugin:
    """因果记忆的扩展工具（只补小焦没有的那部分）。"""

    TOOLS = ("causal_memory_map", "causal_patterns", "causal_lesson", "causal_unified",
             "causal_invalidate", "causal_invalidate_pattern", "causal_resolve",
             "causal_trace_one", "causal_remember", "causal_facts")

    def __init__(self):
        self._tag = "小焦运维"
        try:
            m = _base()
            if m is not None and getattr(m, "_INSTANCE", None) is not None:
                self._tag = getattr(m._INSTANCE, "_task_tag", self._tag)
        except Exception:      # noqa: silent-ok — 拿不到标签就用默认
            pass

    def get_tool_descriptions(self):
        if _inst() is None:
            LOG.info("因果记忆扩展工具未启用（第一批插件没加载或引擎不可用）")
            return []
        return [
            {"name": "causal_memory_map",
             "description": "看一眼因果记忆库的全貌（多少条因果边、多少节点、最近记了什么）。"
                            "什么时候用：想确认'它到底学过什么'，或者吃完一顿操作后看看记进去没有。",
             "parameters": {"limit": "可选，列几条最近的，默认 8"}},
            {"name": "causal_patterns",
             "description": "看引擎自己挖出来的关系：哪些经验**相似**、哪些**互相矛盾**、哪些在**重复**。"
                            "什么时候用：怀疑自己前后做法不一致、或想找同类经验时。",
             "parameters": {"query": "可选，只在这个话题里找", "limit": "可选，默认 8"}},
            {"name": "causal_lesson",
             "description": "从库里多条散着的边**重建一条教训**（比单条边更适合直接照做）。"
                            "什么时候用：要总结'这一类事我以前吃了什么亏'时。",
             "parameters": {"query": "要重建教训的话题", "max_edges": "可选，最多用几条边，默认 5"}},
            {"name": "causal_unified",
             "description": "统一检索：它那边的事实层和因果层一起查。"
                            "什么时候用：不确定要找的是'一个事实'还是'一条教训'时。",
             "parameters": {"query": "要查的东西", "limit": "可选，默认 5"}},
            {"name": "causal_invalidate",
             "description": "把一条**错的**教训软作废（不是删除，可回滚；库里仍留痕）。"
                            "什么时候用：发现某条经验已经不对了（世界变了、当时的结论是错的）。",
             "parameters": {"edge_id": "要作废的边号（从因果记忆的返回里能看到）",
                            "reason": "为什么作废，一句话"}},
            {"name": "causal_invalidate_pattern",
             "description": "把引擎挖出来的某条**关系**软作废（相似/矛盾/重复那类 meta 边）。"
                            "什么时候用：它把两条不相干的经验算成'相似'、或把不该算矛盾的算成矛盾时。",
             "parameters": {"edge_id": "那条关系的边号（用 causal_patterns 能看到）",
                            "reason": "为什么作废，一句话"}},
            {"name": "causal_resolve",
             "description": "让引擎评审'同一个决策反复记录、结局却不一样'的发散项，并决定要不要取代旧结论。"
                            "什么时候用：觉得库里同一个做法有两种相反结论时。",
             "parameters": {"apply": "可选，true 才真改；不填只做预演"}},
            {"name": "causal_trace_one",
             "description": "单跳溯源：这个结果**直接**是哪个决策造成的。"
                            "什么时候用：只想找最直接的原因（要找整条链用 causal_trace）。",
             "parameters": {"outcome_description": "那个结果/现象的描述"}},
            {"name": "causal_remember",
             "description": "直接把一段对话（几条消息）喂进因果记忆的提炼链路，由它自己拆出决策与结果。"
                            "什么时候用：刚做完一件有教训的事，懒得一条条手动记。",
             "parameters": {"messages": "对话内容，几条之间用换行分隔（一条一行）",
                            "date": "可选，这轮对话的日期 YYYY-MM-DD"}},
            {"name": "causal_facts",
             "description": "查因果记忆**它自己那边**的事实层（不是小焦自己的记忆库，两套别混）。"
                            "什么时候用：明确知道东西记在它那边时。",
             "parameters": {"query": "要查的事实", "limit": "可选，默认 5"}},
        ]

    # ---------- 执行 ----------
    def execute(self, tool_name, params):
        """⚠️ 这里必须走第一个插件的 `_call`（直接对 MCP 说话），**不能**走它的 `execute` ——
        它的 `execute` 只认自己那 6 个工具名，别的名字一律返回 None。
        第一版就是踩了这个：四个工具全返回"没有相关记录"，看起来像库是空的，其实是调用被它过滤掉了。"""
        params = params or {}
        if tool_name not in self.TOOLS:
            # 同上：不返回 None，改成中文说明并列出现有工具（10 个）。
            return ("因果记忆第二批里没有「%s」这个工具（它只有 %s）。"
                    % (tool_name, " / ".join(sorted(self.TOOLS))))
        p = _inst()
        if p is None:
            return "因果记忆扩展工具没启用：第一批插件（causal_memory）没加载，或引擎二进制没配。"
        try:
            if tool_name == "causal_memory_map":
                return self._w("库的全貌", p._call("causal_directory", {"limit": int(params.get("limit") or 8)}))
            if tool_name == "causal_patterns":
                args = {"limit": int(params.get("limit") or 8)}
                if params.get("query"):
                    args["query"] = str(params["query"])
                return self._w("挖出来的关系", p._call("search_patterns", args))
            if tool_name == "causal_lesson":
                q = str(params.get("query") or "").strip()
                if not q:
                    return "要重建教训，得先说要重建哪一类（query）"
                return self._w("重建的教训", p._call("reconstruct_lesson",
                                                     {"query": q, "max_edges": int(params.get("max_edges") or 5)}))
            if tool_name == "causal_unified":
                q = str(params.get("query") or "").strip()
                if not q:
                    return "统一检索要给 query"
                return self._w("统一检索", p._call("search_memory",
                                                   {"query": q, "limit": int(params.get("limit") or 5)}))
            if tool_name == "causal_invalidate":
                eid = str(params.get("edge_id") or "").strip()
                if not eid:
                    return "要作废哪条边？给个 edge_id（从因果记忆的返回里能看到）"
                return self._w("已软作废（可回滚）",
                               p._call("invalidate_decision",
                                       {"edge_id": eid, "reason": str(params.get("reason") or "判定为过时/错误")}))
            if tool_name == "causal_invalidate_pattern":
                eid = str(params.get("edge_id") or "").strip()
                if not eid:
                    return "要作废哪条关系？给个 edge_id（用 causal_patterns 能看到）"
                return self._w("关系已软作废（可回滚）",
                               p._call("invalidate_pattern",
                                       {"edge_id": eid, "reason": str(params.get("reason") or "判定为误判")}))
            if tool_name == "causal_resolve":
                return self._w("发散项评审",
                               p._call("resolve_updates", {"apply": bool(params.get("apply"))}))
            if tool_name == "causal_trace_one":
                d = str(params.get("outcome_description") or "").strip()
                if not d:
                    return "单跳溯源要说清是哪个结果（outcome_description）"
                return self._w("单跳溯源", p._call("trace_cause", {"outcome_description": d}))
            if tool_name == "causal_remember":
                raw = str(params.get("messages") or "").strip()
                if not raw:
                    return "要喂进库的内容是空的（messages 一行一条）"
                msgs = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                args = {"messages": msgs}
                if params.get("date"):
                    args["date"] = str(params["date"])
                return self._w("已交给它提炼", p._call("remember", args))
            if tool_name == "causal_facts":
                q = str(params.get("query") or "").strip()
                if not q:
                    return "查事实层要给 query"
                return self._w("它那边的事实层", p._call("search_facts",
                                                         {"query": q, "limit": int(params.get("limit") or 5)}))
        except Exception as e:      # noqa: silent-ok — 这一层绝不许把异常抛给小焦
            LOG.warning("因果记忆扩展工具出错（%s）：%s", tool_name, e)
            return "因果记忆（%s）调用出错（%s: %s）—— 不影响本轮其它工具" % (
                tool_name, type(e).__name__, str(e)[:120])
        return None

    def _w(self, title, res):
        """`res` 是 `_call` 的返回值 —— (文本, 错误串)。"""
        try:
            text, err = res
        except Exception:      # noqa: silent-ok — 形状不对就当作没拿到
            text, err = "", "返回形状不对"
        if err:
            return "因果记忆（%s）没查成：%s" % (title, err)
        if not text:
            return "因果记忆（%s）：没有相关记录（空的，不代表没事）" % title
        return "【因果记忆·%s】%s" % (title, text.strip()[:1200])
