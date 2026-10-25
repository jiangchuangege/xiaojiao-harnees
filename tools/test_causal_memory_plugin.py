# tools/test_causal_memory_plugin.py —— 因果记忆插件（causal-memory）自测
#
# 两段：
#   ① 离线段：用 tests/fake_causal_mcp.py 这个假 MCP server，把**客户端这条链**钉死
#      （握手 / 按行 JSON-RPC / 参数拼得对不对 / 超时与进程死掉怎么办 / 没装二进制时怎么说话）；
#   ② 真机段：如果本机有 causal-memory.exe，就用**真二进制 + 临时库**跑一遍
#      （记一条 → 搜回来 → 动手前预警），没有就**跳过并如实说明**，不当通过。
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL, SKIP = [], [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


def skip(name, why):
    SKIP.append(name)
    print("  ⏭ " + name + "  跳过（" + why + "）")


def load_plugin_module():
    """按小焦的加载方式（plugins/ 目录下按文件路径加载）把插件导进来。"""
    p = os.path.join(ROOT, "plugins", "causal_memory.py")
    spec = importlib.util.spec_from_file_location("causal_memory", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["causal_memory"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    print("== 因果记忆插件自测 ==")
    mod = load_plugin_module()
    fake = os.path.join(ROOT, "tests", "fake_causal_mcp.py")

    # ---------- ① 离线段：假 MCP server ----------
    print("\n-- ① 离线（假 MCP server，验客户端这条链）--")
    logf = os.path.join(tempfile.mkdtemp(prefix="cm_log_"), "calls.jsonl")
    os.environ["FAKE_MCP_LOG"] = logf
    pl = mod.CausalMemoryPlugin()
    pl.cfg = {"cmd": [sys.executable, fake], "task_tag": "显存管理"}
    pl._task_tag = "显存管理"
    ok("假服务：插件认为可用", pl.available is True)
    desc = pl.get_tool_descriptions()
    names = [d["name"] for d in desc]
    ok("工具清单有 6 个（只接小焦缺的那几样）", len(desc) == 6, names)
    # 只接小焦缺的那几样：事实层它自己早有（memory_vec + self_learn），别再来一套
    # ⚠️ 别用子串判（counter**fact**ual 里也有 fact）——第一版就是这么误报的
    ok("清单里没有事实层工具（小焦已有的不重复接）",
       not ({"search_facts", "record_fact"} & set(names)), names)
    ok("每个工具都写了什么时候用", all("什么时候用" in d["description"] for d in desc))

    out = pl.execute("causal_record", {"decision": "先卸载聊天模型再加载视频模型",
                                       "outcome": "显存 5.9G→0.9G，视频跑通",
                                       "relation": "caused"})
    ok("记一条决策→结果：成功", out and "✅ Recorded" in out, (out or "")[:70])
    ok("记的时候带上了默认领域标签", "显存管理" in (out or ""))
    calls = [json.loads(l) for l in open(logf, encoding="utf-8")] if os.path.exists(logf) else []
    rec = [c for c in calls if c["tool"] == "record_decision"]
    ok("参数拼对了（decision/outcome/relation/task_tag）",
       bool(rec) and rec[0]["args"].get("task_tag") == "显存管理"
       and rec[0]["args"].get("relation") == "caused", json.dumps(rec[:1], ensure_ascii=False)[:100])
    ok("搞不清的 relation 一律归成 caused",
       "caused" in (pl.execute("causal_record", {"decision": "x", "outcome": "y", "relation": "乱写的"}) or ""))

    out = pl.execute("causal_search", {"query": "显存不够"})
    ok("查教训：拿到内容", out and "过往教训" in out and "显存不够" in out, (out or "")[:70])
    out = pl.execute("causal_warn", {"action": "把聊天模型装回显存"})
    ok("动手前预警：拿到内容", out and "动手前预警" in out and "WARNING" in out, (out or "")[:70])
    out = pl.execute("causal_trace", {"outcome_description": "视频超时"})
    ok("故障溯源：拿到因果链", out and "故障溯源" in out, (out or "")[:70])
    out = pl.execute("causal_counterfactual", {"decision": "走代理", "alternative": "手写 REST"})
    ok("方案对比：拿到结论", out and "方案对比" in out and "prefer_a" in out, (out or "")[:70])
    out = pl.execute("causal_report", {})
    ok("预测账本：拿到准确率", out and "预测账本" in out, (out or "")[:70])

    _foreign = pl.execute("get_weather", {})
    ok("不是我的工具：返回中文说明（不抛异常、也不静默给空）",
       isinstance(_foreign, str) and "没有" in _foreign and "causal_warn" in _foreign, _foreign)
    ok("忘了给必填参数：给中文提示，不炸",
       "都得给" in (pl.execute("causal_record", {"decision": "只有决策"}) or ""))
    ok("预警没给 action：明确说清", "没给 action" in (pl.execute("causal_warn", {}) or ""))
    # 进程死掉后要能自己重启
    pl._client.stop()
    out2 = pl.execute("causal_search", {"query": "重启之后还能不能用"})
    ok("子进程被杀掉之后：自动重启并继续用", out2 and "过往教训" in out2, (out2 or "")[:60])

    # 空结果要如实说"这条是空的"，不许让人误以为安全
    empty = pl._wrap("过往教训", "", "")
    ok("空结果如实说明（不暗示没问题）", "没有相关记录" in empty and "不代表安全" in empty, empty[:60])

    # ---------- 没装二进制时的说法 ----------
    print("\n-- 没装 causal-memory 时怎么说话 --")
    pl2 = mod.CausalMemoryPlugin()
    pl2.cfg = {"exe": os.path.join(tempfile.gettempdir(), "根本没有这个文件.exe"), "task_tag": "x"}
    ok("找不到二进制：工具一个都不注册（不糊假工具给模型）", pl2.get_tool_descriptions() == [])
    msg = pl2.execute("causal_search", {"query": "x"})
    ok("但真去调它会如实说清缺什么、去哪下",
       msg and "找不到 causal-memory" in msg and "Releases" in msg, (msg or "")[:80])
    ok("缺配置时不抛异常", isinstance(msg, str))

    # ---------- ② 真机段：真二进制 ----------
    print("\n-- ② 真机（真 causal-memory + 临时库）--")
    exe = r"C:\xiaojiao\causal-memory\causal-memory.exe"
    if not os.path.exists(exe):
        skip("真机冒烟（记一条→搜回来→动手前预警）", "本机没有 %s" % exe)
    else:
        dbdir = tempfile.mkdtemp(prefix="cm_real_")
        pl3 = mod.CausalMemoryPlugin()
        pl3.cfg = {"exe": exe, "db": os.path.join(dbdir, "t.db"), "task_tag": "显存管理"}
        pl3._task_tag = "显存管理"
        ok("真机：插件可用", pl3.available is True)
        r = pl3.execute("causal_record", {"decision": "视频生成期间不把聊天模型装回显存",
                                          "outcome": "避免了一段视频从 15 分钟变成 50 分钟",
                                          "relation": "prevented"})
        ok("真机：记一条 prevented 成功", r and "Recorded" in r, (r or "")[:80])
        s = pl3.execute("causal_search", {"query": "显存 视频 变慢"})
        ok("真机：能搜回来", s and "prevented" in s, (s or "")[:90])
        w = pl3.execute("causal_warn", {"action": "跑视频时把聊天模型加载回显存"})
        # ⚠️ 只断言"有输出、说的是仿真链"——**不断言一定是 SAFE/WARNING/DANGER**：
        #    库里只有一条 prevented 边时，真机给的是 UNKNOWN（这是引擎自己的判定口径，
        #    不是插件能决定的）。测试不该替引擎拍板。
        ok("真机：动手前预警有输出（链或明确说没有）",
           bool(w) and ("chain" in w or "Predicted" in w or "没有相关记录" in w), (w or "")[:90])
        try:
            pl3._client and pl3._client.stop()
        except Exception:
            pass

    print("\n通过 %d 项, 失败 %d 项, 跳过 %d 项" % (len(PASS), len(FAIL), len(SKIP)))
    if SKIP:
        print("跳过清单：", "、".join(SKIP))
    if FAIL:
        print("失败清单：", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
