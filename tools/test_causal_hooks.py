# tools/test_causal_hooks.py —— 「关键动作前后自动埋点」自测（离线，不依赖真二进制）
#
# 这一层是给因果记忆喂料的：动作之前问一句（最多等 2 秒）、动作之后记一笔（丢后台）。
# 它的错会很隐蔽 —— 拖慢每一轮对话、把库刷成噪声、或者编一句"危险"吓唬人。
# 所以这套自测专门钉这几条：
#   ① 只认三类动作（改配置 / 删改文件 / 动显存），只读类、搜索类一律不埋；
#   ② **宁可不说，不许吓唬人**：对面说 UNKNOWN/空/超时 → 一个字都不提示；
#   ③ **绝不挡路**：查询最多等 2 秒，记账必须后台返回（哪怕对面卡 5 秒）；
#   ④ 记账节流：同一个动作短时间内只记一次、每小时有上限；
#   ⑤ 这一层整个坏掉（插件没加载 / 抛异常）也不许影响工具本身。
import importlib.util
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PASS, FAIL = [], []


def ok(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(extra)) if extra else ""))


class FakePlugin:
    """假的因果记忆插件：按脚本回话，并把每次调用记下来。"""

    def __init__(self, warn_text="", sleep_s=0.0, raise_on=None):
        self.available = True
        self.calls = []
        self.warn_text = warn_text
        self.sleep_s = sleep_s
        self.raise_on = raise_on or ()

    def execute(self, tool, params):
        self.calls.append((tool, params))
        if self.sleep_s:
            time.sleep(self.sleep_s)
        if tool in self.raise_on:
            raise RuntimeError("假的失败")
        if tool == "causal_warn":
            return self.warn_text
        return "✅ Recorded"


def install(plugin):
    m = types.ModuleType("causal_memory")
    m._INSTANCE = plugin
    sys.modules["causal_memory"] = m


def uninstall():
    sys.modules.pop("causal_memory", None)


def load_hooks():
    p = os.path.join(ROOT, "core", "causal_hooks.py")
    spec = importlib.util.spec_from_file_location("causal_hooks", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["causal_hooks"] = mod
    spec.loader.exec_module(mod)
    return mod


def reset(H, cfg=None):
    H._seen.clear()
    del H._hour[:]
    H._cfg = lambda: (cfg or {})
    return H


def main():
    print("== 关键动作埋点 自测 ==")
    H = load_hooks()

    # ---------- ① 分类：只认三类 ----------
    print("\n-- ① 分类（少而准，别把每个调用都记一遍）--")
    cfg_path = {"path": "C:/xiaojiao/xiaojiao_control.json"}
    txt_path = {"path": "C:/Users/Jiao/Desktop/a.txt"}
    ok("写配置文件 → config 类", (H.classify("write_file", cfg_path) or {}).get("kind") == "config")
    ok("改 llama-swap.yaml → config 类",
       (H.classify("edit_file", {"path": "C:/x/llama-swap.yaml"}) or {}).get("kind") == "config")
    ok("写普通文件 → file 类", (H.classify("write_file", txt_path) or {}).get("kind") == "file")
    ok("删/覆盖类命令 → file 类",
       (H.classify("run_command", {"command": "Remove-Item C:/x -Recurse"}) or {}).get("kind") == "file")
    ok("命令里改配置文件 → config 类",
       (H.classify("run_command", {"command": "Set-Content C:/x/xiaojiao_control.json {}"}) or {}).get("kind") == "config")
    ok("只读类不埋（read_file）", H.classify("read_file", {"path": "C:/x.txt"}) is None)
    ok("搜索类不埋（web_search）", H.classify("web_search", {"query": "x"}) is None)
    ok("普通命令不埋（dir）", H.classify("run_command", {"command": "dir"}) is None)
    ok("写文件但没给路径 → 不埋", H.classify("write_file", {}) is None)

    # ---------- ② 宁可不说，不许吓唬人 ----------
    print("\n-- ② 预警：只有 WARNING/DANGER 才提示 --")
    reset(H)
    install(FakePlugin(warn_text="[bm25] Predicted: Chain 1 ℹ️ UNKNOWN (60%)"))
    r_unknown = H.before("write_file", cfg_path)
    ok("对面说 UNKNOWN → 不当成危险（不许吓唬人）",
       "DANGER" not in r_unknown.upper() and "WARNING" not in r_unknown.upper(), r_unknown[:60])
    ok("但如实摆出「有相关记录、引擎没给档位」",
       "有相关历史记录" in r_unknown and "仅供参考" in r_unknown, r_unknown[:80])
    reset(H, {"auto_show_related": False})
    install(FakePlugin(warn_text="[bm25] Predicted: Chain 1 ℹ️ UNKNOWN (60%)"))
    ok("auto_show_related=false → 连参考也不说", H.before("write_file", cfg_path) == "")
    reset(H)
    install(FakePlugin(warn_text=""))
    ok("对面没记录 → 不说", H.before("write_file", cfg_path) == "")
    install(FakePlugin(warn_text="Chain 1 ⚠️ WARNING: 以前这么干出过事"))
    w = H.before("write_file", cfg_path)
    ok("对面说 WARNING → 提示，并标明出处",
       "因果记忆" in w and "WARNING" in w and "动手前提醒" in w, w[:60])
    install(FakePlugin(warn_text="Chain 1 🛑 DANGER: 曾造成事故"))
    ok("对面说 DANGER → 提示", "DANGER" in H.before("write_file", cfg_path))
    install(FakePlugin(warn_text="WARNING", sleep_s=5.0))
    t0 = time.time()
    r = H.before("write_file", cfg_path)
    el = time.time() - t0
    ok("对面卡 5 秒：最多等 2 秒就走（绝不拖慢动作）", el < 3.2 and r == "", "%.1f 秒" % el)
    install(FakePlugin(raise_on=("causal_warn",)))
    ok("对面抛异常 → 安静返回空（不炸工具）", H.before("write_file", cfg_path) == "")
    uninstall()
    ok("插件根本没加载 → 安静返回空", H.before("write_file", cfg_path) == "")

    # ---------- ③ 记账：后台、节流 ----------
    print("\n-- ③ 记账：后台返回 + 节流 --")
    reset(H)
    fp = FakePlugin(sleep_s=5.0)
    install(fp)
    t0 = time.time()
    H.after("write_file", txt_path, "写好了", ok=True)
    el = time.time() - t0
    ok("对面慢 5 秒：after 立刻返回（不挡用户）", el < 0.5, "%.2f 秒" % el)
    time.sleep(0.3)
    ok("记账确实发出去了（causal_record）",
       any(c[0] == "causal_record" for c in fp.calls), [c[0] for c in fp.calls])
    rec = [c for c in fp.calls if c[0] == "causal_record"]
    ok("记的是决策→结果两条内容",
       bool(rec) and "写文件" in rec[0][1].get("decision", "") and rec[0][1].get("outcome"),
       str(rec[:1])[:90])
    ok("relation 用的是 caused", bool(rec) and rec[0][1].get("relation") == "caused")

    reset(H)
    fp2 = FakePlugin()
    install(fp2)
    H.after("write_file", txt_path, "第一次", ok=True)
    time.sleep(0.25)
    H.after("write_file", txt_path, "第二次（同一动作，10 分钟内）", ok=True)
    time.sleep(0.25)
    n1 = len([c for c in fp2.calls if c[0] == "causal_record"])
    ok("同一个动作 10 分钟内只记一次（不刷库）", n1 == 1, "记了 %d 次" % n1)
    H.after("write_file", cfg_path, "换了一个动作", ok=True)
    time.sleep(0.25)
    n2 = len([c for c in fp2.calls if c[0] == "causal_record"])
    ok("换了动作就照记", n2 == 2, "记了 %d 次" % n2)

    reset(H, {"auto_max_per_hour": 2, "auto_min_interval_s": 0})
    fp3 = FakePlugin()
    install(fp3)
    for i in range(5):
        H.after("write_file", {"path": "C:/tmp/f%d.txt" % i}, "第%d次" % i, ok=True)
        time.sleep(0.2)
    n3 = len([c for c in fp3.calls if c[0] == "causal_record"])
    ok("每小时上限生效（配了 2 就最多 2 条）", n3 == 2, "记了 %d 次" % n3)

    reset(H)
    fp4 = FakePlugin()
    install(fp4)
    H.after("write_file", txt_path, "❌ 写入失败：拒绝访问", ok=False)
    time.sleep(0.25)
    rec4 = [c for c in fp4.calls if c[0] == "causal_record"]
    ok("失败的动作：结果里如实带「失败」", bool(rec4) and "失败" in rec4[0][1]["outcome"],
       str(rec4[:1])[:80])

    reset(H)
    fp5 = FakePlugin(raise_on=("causal_record",))
    install(fp5)
    H.after("write_file", txt_path, "x", ok=True)
    time.sleep(0.3)
    ok("记账抛异常：不影响调用方（after 不抛）", True)

    # ---------- ④ 开关与类别过滤 ----------
    print("\n-- ④ 开关 / 只留某几类 --")
    reset(H, {"auto": False})
    install(FakePlugin(warn_text="Chain 1 ⚠️ WARNING"))
    ok("auto=false → 预警安静", H.before("write_file", cfg_path) == "")
    fp6 = FakePlugin()
    install(fp6)
    H.after("write_file", txt_path, "x", ok=True)
    time.sleep(0.25)
    ok("auto=false → 一条都不记", not fp6.calls)
    reset(H, {"auto_kinds": ["config"]})
    fp7 = FakePlugin()
    install(fp7)
    H.after("write_file", txt_path, "普通文件不该记", ok=True)
    time.sleep(0.2)
    ok("只留 config 类时：普通文件不记", not fp7.calls)
    H.after("write_file", cfg_path, "配置该记", ok=True)
    time.sleep(0.25)
    ok("只留 config 类时：配置照记", len(fp7.calls) == 1, len(fp7.calls))

    # ---------- ⑤ 显存那一类 ----------
    print("\n-- ⑤ 显存（换大脑）--")
    reset(H)
    fp8 = FakePlugin()
    install(fp8)
    H.note_vram("video", {"switched": "video", "from": ["chat"], "ok": True})
    time.sleep(0.3)
    rec8 = [c for c in fp8.calls if c[0] == "causal_record"]
    ok("换大脑记一笔：决策里带目标", bool(rec8) and "video" in rec8[0][1]["decision"], str(rec8[:1])[:90])
    ok("切换结果也如实记（成功/失败）", bool(rec8) and "成功" in rec8[0][1]["outcome"])
    reset(H, {"auto_kinds": ["config"]})
    fp9 = FakePlugin()
    install(fp9)
    H.note_vram("video", {"ok": True})
    time.sleep(0.2)
    ok("类别里没有 vram 时不记", not fp9.calls)
    reset(H)
    fp10 = FakePlugin()
    install(fp10)
    t0 = time.time()
    H.note_vram("chat", {"ok": False, "from": ["video"]})
    ok("note_vram 也是后台返回（不挡切换）", (time.time() - t0) < 0.3)
    time.sleep(0.3)
    rec10 = [c for c in fp10.calls if c[0] == "causal_record"]
    ok("切换失败也照实记", bool(rec10) and "失败" in rec10[0][1]["outcome"], str(rec10[:1])[:80])

    reset(H)
    ok("stats() 给得出状态", isinstance(H.stats(), dict) and "enabled" in H.stats())

    uninstall()
    print("\n通过 %d 项, 失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：", "、".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
