# tools/test_causal_memory_ext.py —— 因果记忆**第二批插件**的自测（离线，不依赖真引擎）
#
# 为什么要单独测这一批：它跟第一批的错法不一样。
#   第一批错在"连不上"，这一批最容易错在**调错工具**和**调错方法** ——
#   实测踩到的那个坑就是后者：第一批插件的 `execute()` 只认它自己那 6 个工具名，
#   第二批如果图省事走 `execute()`，十个工具会**全部**返回"没有相关记录"，
#   看起来像库是空的，其实是调用被过滤掉了。这条在这个文件里钉死（stub 里 execute 一被调用就炸）。
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


# 期望的映射：插件工具名 → 引擎真正的 MCP 工具名
EXPECT = {
    "causal_memory_map": "causal_directory",
    "causal_patterns": "search_patterns",
    "causal_lesson": "reconstruct_lesson",
    "causal_unified": "search_memory",
    "causal_invalidate": "invalidate_decision",
    "causal_invalidate_pattern": "invalidate_pattern",
    "causal_resolve": "resolve_updates",
    "causal_trace_one": "trace_cause",
    "causal_remember": "remember",
    "causal_facts": "search_facts",
}


class FakeBase:
    """假的"第一批插件实例"：只暴露第二批真正会用到的那两个东西。"""

    def __init__(self):
        self.available = True
        self._task_tag = "小焦运维"
        self.calls = []
        self.reply = {}          # tool -> (text, err)
        self.execute_called = False

    def _call(self, tool, args, timeout=60):
        self.calls.append((tool, args))
        return self.reply.get(tool, ("", ""))

    def execute(self, tool, params):      # 第二批**不该**用它
        self.execute_called = True
        raise AssertionError("第二批插件去调了第一批的 execute() —— 那个方法只认第一批的 6 个工具名")


def install(base):
    m = types.ModuleType("causal_memory")
    m._INSTANCE = base
    sys.modules["causal_memory"] = m


def uninstall():
    sys.modules.pop("causal_memory", None)


def load_ext():
    p = os.path.join(ROOT, "plugins", "causal_memory_ext.py")
    spec = importlib.util.spec_from_file_location("causal_memory_ext", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["causal_memory_ext"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    print("== 因果记忆·第二批插件 自测 ==")
    mod = load_ext()

    # ---------- 没启用时：一个工具都不注册 ----------
    uninstall()
    pl0 = mod.CausalMemoryExtPlugin()
    ok("引擎不可用 → 工具清单为空（不糊假工具）", pl0.get_tool_descriptions() == [])
    msg = pl0.execute("causal_memory_map", {})
    ok("引擎不可用 → 真去调会如实说清原因", "没启用" in (msg or ""), (msg or "")[:50])

    # ---------- 启用后：工具清单 ----------
    base = FakeBase()
    install(base)
    pl = mod.CausalMemoryExtPlugin()
    desc = pl.get_tool_descriptions()
    names = [d["name"] for d in desc]
    ok("启用后 10 个工具", len(desc) == 10, len(desc))
    ok("工具名与映射表一致", set(names) == set(EXPECT), sorted(set(names) ^ set(EXPECT)))
    ok("每个工具都写了什么时候用", all("什么时候用" in d["description"] for d in desc))
    ok("参数都带说明", all(isinstance(d.get("parameters"), dict) for d in desc))

    # ---------- 每个工具都得打到对的 MCP 工具上 ----------
    print("\n-- 逐个工具：调的是不是引擎里那个（还有别走 execute）--")
    args_by_tool = {
        "causal_memory_map": {"limit": 3},
        "causal_patterns": {"query": "显存", "limit": 5},
        "causal_lesson": {"query": "视频 显存"},
        "causal_unified": {"query": "卸载模型"},
        "causal_invalidate": {"edge_id": "42", "reason": "过时了"},
        "causal_invalidate_pattern": {"edge_id": "77", "reason": "误判"},
        "causal_resolve": {"apply": False},
        "causal_trace_one": {"outcome_description": "视频超时"},
        "causal_remember": {"messages": "用户问A\n小焦答B", "date": "2026-10-15"},
        "causal_facts": {"query": "部署路径"},
    }
    for tool, mcp in EXPECT.items():
        base.calls.clear()
        base.reply[mcp] = ("（引擎返回的内容）", "")
        out = pl.execute(tool, args_by_tool[tool])
        called = [c[0] for c in base.calls]
        ok("%s → %s" % (tool, mcp), called == [mcp], called)
        ok("%s 回话带出处" % tool, "【因果记忆·" in (out or ""), (out or "")[:40])
    ok("全程没调用第一批的 execute()（回归）", base.execute_called is False)

    # ---------- 参数传对了没有 ----------
    print("\n-- 参数拼装 --")
    base.calls.clear(); base.reply["remember"] = ("ok", "")
    pl.execute("causal_remember", {"messages": "第一行\n第二行\n\n第三行", "date": "2026-10-01"})
    got = base.calls[-1][1]
    ok("causal_remember 把多行拆成消息数组（去掉空行）",
       got.get("messages") == ["第一行", "第二行", "第三行"] and got.get("date") == "2026-10-01", got)
    base.calls.clear(); base.reply["search_causal"] = ("", "")
    pl.execute("causal_patterns", {"query": "显存", "limit": "7"})
    ok("limit 传字符串也转成数字", base.calls[-1][1].get("limit") == 7, base.calls[-1][1])
    base.calls.clear()
    pl.execute("causal_unified", {"query": "x"})
    ok("没给可选参数时不硬塞", set(base.calls[-1][1].keys()) == {"query", "limit"}, base.calls[-1][1])

    # ---------- 缺必填 / 空结果 / 报错 ----------
    print("\n-- 边界：缺参数、空结果、引擎报错 --")
    base.calls.clear()
    r = pl.execute("causal_invalidate", {})
    ok("缺 edge_id → 中文提示且不打扰引擎", ("edge_id" in (r or "")) and not base.calls, (r or "")[:50])
    r = pl.execute("causal_lesson", {})
    ok("缺 query → 明确说要给什么", "query" in (r or ""), (r or "")[:50])
    r = pl.execute("causal_remember", {"messages": "   "})
    ok("喂空内容 → 拒绝", "空" in (r or ""), (r or "")[:50])
    base.reply["search_facts"] = ("", "")
    r = pl.execute("causal_facts", {"query": "没有的东西"})
    ok("空结果如实说（不暗示没事）", "没有相关记录" in (r or "") and "不代表没事" in (r or ""), (r or "")[:60])
    base.reply["causal_directory"] = ("", "等超时（60 秒没回）")
    r = pl.execute("causal_memory_map", {})
    ok("引擎报错 → 如实转达，不吞", "没查成" in (r or "") and "超时" in (r or ""), (r or "")[:60])
    base.reply["causal_directory"] = ("x", "")
    ok("不是我的工具 → 返回 None（不抢别人）", pl.execute("get_weather", {}) is None)

    # ---------- 注入的异常不许往上抛 ----------
    class Boom(FakeBase):
        def _call(self, tool, args, timeout=60):
            raise RuntimeError("引擎炸了")

    install(Boom())
    pl2 = mod.CausalMemoryExtPlugin()
    r = pl2.execute("causal_patterns", {"limit": 1})
    ok("插件内部异常 → 转成中文说明（小焦那层会吞掉异常，必须自己说）",
       isinstance(r, str) and "调用出错" in r, (r or "")[:60])

    uninstall()
    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
