# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层自测（tools/test_carrier.py）

一条命令跑完：`python tools/test_carrier.py` → 逐条 ✅/❌ + `通过 N / 共 M`，退出码 0/1。
**全程离线**（不碰用户真配置、不碰真模型、不外网）：
  · 本地起一个假 OpenAI 服务（http.server），/models 返回 {"data":[{"id":"m1"}]}
  · 再占一个"必定连不上"的端口当坏火种（先 bind 拿到端口号再立刻 close → 连接必被拒）
  · 临时插件目录造在 logs/carrier/_tmp_plugins/ 下（logs/ 已被 .gitignore 忽略）

三条自测纪律（写在这里是为了以后改测试的人别破坏它们）：
  1) **不删除任何文件**：验证"插件消失"用**改名**（.py → .md），不用 os.remove。
  2) **不写用户的配置**：跑完必须证明 xiaojiao_control.json 的字节与 mtime 一个都没变
     （BrainRegistry 的 persist 默认是内存 no-op，这条断言就是它的守门人）。
  3) **可重复跑**：临时目录按"每次运行一个子目录"（run_<时间>_<pid>）建，不靠删旧目录来保证干净。

分节函数对应需求清单的 1~9（外加一条 applies_to_app 的附加节）：
为什么要分节而不是写成一个长 main：单节超过 80 行就会被仓库自己的
tools/audit_static.py 记成"超长函数"，自测脚本也不该给自己开坏味道的后门。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))      # `python tools/test_carrier.py` 的 sys.path[0] 是 tools/，要补仓库根

try:      # CI/Windows 控制台不是 UTF-8 时，中文与 ✅ 会 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:      # noqa: silent-ok — 老环境没有 reconfigure 也不该让自测挂掉
    pass

from core.carrier import BrainRegistry, CapabilityRegistry      # noqa: E402
from core.carrier.brain_registry import CONTROL_FILE, SWITCH_LOG, CONFIG_LOG   # noqa: E402

CARRIER_DIR = ROOT / "logs" / "carrier"
TMP_PLUGINS = CARRIER_DIR / "_tmp_plugins"
_RESULTS: list = []


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def check(name: str, ok, detail: str = "") -> bool:
    """记一条结果并立刻打印 —— 逐条可见，失败时不用等汇总。"""
    ok = bool(ok)
    _RESULTS.append(ok)
    print("%s %s%s" % ("✅" if ok else "❌", name, ("  —— " + str(detail)) if detail else ""))
    return ok


@contextlib.contextmanager
def _quiet():
    """临时把 stdout 收进缓冲区。

    为什么要它：第一次调 app 接口会 import xiaojiao_app，它会打印一堆启动横幅，
    夹在 ✅/❌ 中间会把自测结果冲得看不清。收起来之后想显示就显示（不隐藏信息，只是挪位置）。
    """
    old, buf = sys.stdout, io.StringIO()
    sys.stdout = buf
    try:
        yield buf
    finally:
        sys.stdout = old


class _FakeOpenAI(BaseHTTPRequestHandler):
    """/models 返回一个模型；别的路径 404。故意**不做生成接口**：探测只该用 GET /models。"""

    def do_GET(self):      # noqa: N802 — BaseHTTPRequestHandler 规定的方法名
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps({"data": [{"id": "m1", "object": "model"}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404, "not found")

    def log_message(self, *a):      # noqa: A003 — 关掉访问日志，别把自测输出冲花
        return


def _start_fake_server():
    """起假服务 → 返回 (server, base_url)。端口用 0 让系统分配，避免和真 llama-swap 撞车。"""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="fake-openai", daemon=True).start()
    return srv, "http://127.0.0.1:%d/v1" % srv.server_address[1]


def _dead_base_url() -> str:
    """造一个"必定连不上"的地址：先 bind 拿到一个空闲端口，再立刻 close。

    为什么不是随手写一个端口号：真实环境里那个端口可能正好有服务在跑，
    于是"坏火种"意外地健康，测试就变成了假绿。bind→close 拿到的端口，当下一定没人监听。
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d/v1" % port


# ============================================================ 【1】火种登记
def t1_register(fake_base: str, bad_base: str) -> BrainRegistry:
    section("【1】register：登记两个火种 / 重复登记")
    reg = BrainRegistry(config={"brains": [
        {"name": "假火种", "base_url": fake_base, "model": "m1", "api_key": "test-key",
         "kind": "local", "priority": 10, "ctx": 20224, "note": "自测假火种"},
        {"name": "坏火种", "url": bad_base, "key": "k2", "local": True, "priority": 20,
         "note": "自测坏火种（兼容 url/key/local 老写法）"},
    ], "active_brain": "假火种"})
    names = reg.names()
    check("list_brains() 返回 2 条", len(reg.list_brains()) == 2, names)
    check("names() 与配置一致", names == ["假火种", "坏火种"], names)
    check("按 priority 排序（假火种 10 在前）", reg.list_brains()[0]["name"] == "假火种")
    check("重复 register 同名 → False（不覆盖）",
          reg.register("假火种", {"base_url": fake_base}) is False)
    check("register 新名字 → True", reg.register("临时云端", {"url": bad_base, "local": False}) is True)
    tmp = reg.get("临时云端")
    check("字段兼容：local=False → kind=cloud、url/key 别名认得出",
          tmp is not None and tmp.kind == "cloud" and tmp.local is False
          and tmp.base_url == bad_base and tmp.api_key == "")
    check("to_target() 形状就是 app 那种 {url,model,key,local}",
          set(tmp.to_target()) == {"url", "model", "key", "local"}
          and tmp.to_target()["url"].endswith("/chat/completions"))
    check("get() 返回 Brain 对象、名字对", reg.get("假火种").name == "假火种")
    check("unregister 收回临时火种 → 回到 2 条",
          reg.unregister("临时云端") is True and len(reg.list_brains()) == 2)
    check("重复 unregister → False", reg.unregister("临时云端") is False)
    return reg


# ============================================================ 【2】热插拔
def t2_switch(reg: BrainRegistry, tools_cache: list, tools_snapshot: list,
              control_bytes: bytes, control_mtime: int) -> None:
    section("【2】switch：热插拔 —— 切换前后载体状态对象身份与内容都不变")
    memory_store = ["用户说过：喜欢冰美式", "用户说过：女儿叫小满"]      # 载体记忆（模拟 app 记忆库）
    carrier_state = {
        "memory": memory_store,                        # 记忆
        "tools": tools_cache,                          # 工具（CapabilityRegistry 的缓存对象）
        "world": {"control": control_bytes, "mtime": control_mtime},   # 世界（控制文件快照）
        "session": {"path": str(ROOT / "xiaojiao_sessions.json"), "opened": 3},   # 会话
    }
    state_ref, state_id = carrier_state, id(carrier_state)
    mem_id, tools_id = id(memory_store), id(tools_cache)
    mem_before, world_before = list(memory_store), dict(carrier_state["world"])
    # —— 切换（这里只该发生一件事：当前火种指针变了）——
    check("switch('坏火种') → True", reg.switch("坏火种") is True)
    check("current().name 正确", reg.current() is not None and reg.current().name == "坏火种",
          reg.current().name if reg.current() else "None")
    check("载体状态 dict 本身就是同一个对象（is）",
          carrier_state is state_ref and id(carrier_state) == state_id)
    check("四把钥匙的对象身份都没变：memory / tools 是同一对象（is）",
          carrier_state["memory"] is memory_store and id(carrier_state["memory"]) == mem_id
          and carrier_state["tools"] is tools_cache and id(carrier_state["tools"]) == tools_id)
    check("四把钥匙的内容一个都没变",
          carrier_state["memory"] == mem_before
          and carrier_state["tools"] == tools_snapshot
          and carrier_state["world"] == world_before)
    check("切到不存在的火种 → False（不是抛异常）", reg.switch("并不存在的火种") is False)


# ============================================================ 【3】探测
def t3_probe(reg: BrainRegistry) -> None:
    section("【3】probe：假服务 ok=True 有 m1；坏端口 ok=False 且 error 非空（不许抛）")
    try:
        g = reg.get("假火种").probe(timeout=3)
        raised = ""
    except Exception as e:      # noqa: silent-ok — 探测必须不抛；抛了是这条断言失败，不是自测崩掉
        g, raised = {}, "%s: %s" % (type(e).__name__, e)
    check("假火种 probe → ok=True", g.get("ok") is True, g)
    check("假火种 probe 的 models 含 m1", "m1" in (g.get("models") or []), g.get("models"))
    check("假火种 probe 返回 status/elapsed_ms 字段",
          g.get("status") == 200 and isinstance(g.get("elapsed_ms"), int), g)
    try:
        b = reg.get("坏火种").probe(timeout=3)
        raised_b = ""
    except Exception as e:      # noqa: silent-ok — 同上：连不上必须是 ok=False，不是异常
        b, raised_b = {}, "%s: %s" % (type(e).__name__, e)
    check("坏火种 probe → ok=False", b.get("ok") is False, b.get("error"))
    check("坏火种 probe 的 error 非空", bool(b.get("error")), b.get("error"))
    check("probe 全程没有抛异常", not raised and not raised_b, raised or raised_b)


# ============================================================ 【4】自动兜底
def t4_fallback(reg: BrainRegistry) -> None:
    section("【4】auto_fallback：当前火种不健康 → 自动切到另一个 + 日志真有记录")
    SWITCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    lines_before = len(SWITCH_LOG.read_text(encoding="utf-8").splitlines()) if SWITCH_LOG.exists() else 0
    cur_name = reg.current().name
    check("mark_unhealthy 生效", reg.mark_unhealthy(cur_name, "自测：假装它挂了（401）") is True)
    nxt = reg.auto_fallback(reason="自测自动兜底")
    check("auto_fallback 选出了另一颗火种（假火种）",
          nxt is not None and nxt.name == "假火种", nxt.name if nxt else "None")
    check("当前火种已被切过去", reg.current() is not None and reg.current().name == "假火种")
    lines = SWITCH_LOG.read_text(encoding="utf-8").splitlines() if SWITCH_LOG.exists() else []
    last = json.loads(lines[-1]) if lines else {}
    check("brain_switch.jsonl 真的多了一条记录", len(lines) > lines_before,
          "%d → %d 行" % (lines_before, len(lines)))
    check("日志内容对得上：{ts,from,to,reason,ok}",
          set(("ts", "from", "to", "reason", "ok")).issubset(last)
          and last.get("to") == "假火种" and last.get("ok") is True
          and "自测自动兜底" in last.get("reason", ""), last)
    reg.mark_healthy("坏火种")
    check("mark_healthy 后它又回到备胎池（health_ok=True）", reg.get("坏火种").health_ok() is True)
    check("health_check(all=False) 只探当前火种 → 1 条",
          set(reg.health_check()) == {"假火种"}, reg.snapshot()["active"])
    check("snapshot() 结构完整且不含明文 Key",
          reg.snapshot()["count"] == 2
          and "test-key" not in json.dumps(reg.snapshot(), ensure_ascii=False))


# ============================================================ 【5】默认不写盘
def t5_persist(reg: BrainRegistry, control_bytes: bytes, control_mtime: int) -> None:
    section("【5】persist 默认 no-op：xiaojiao_control.json 的 mtime 与字节都没变")
    check("控制文件字节完全一致", CONTROL_FILE.read_bytes() == control_bytes,
          "%d → %d 字节" % (len(control_bytes), len(CONTROL_FILE.read_bytes())))
    check("控制文件 mtime 完全一致", CONTROL_FILE.stat().st_mtime_ns == control_mtime)
    check("persist 默认（不传回调）不写盘", reg.snapshot()["persist"].startswith("noop"))


# ============================================================ 【6】真 plugins/
def t6_real_capability(cap: CapabilityRegistry, tools_cache: list) -> None:
    section("【6】CapabilityRegistry.scan()：真 plugins/ 的真实工具数（app 接口）")
    with _quiet() as buf:
        real = cap.scan()          # use_app=True（默认）→ 走 app 的真接口
    print("（下面这段是 app 加载时打印的，被临时收起来了）")
    for ln in buf.getvalue().strip().splitlines()[:6]:
        print("   · " + ln)
    check("scan() 走的是 app 真接口（source=app）", real["source"] == "app", real["source"])
    check("真实工具数 > 0", real["count"] > 0, real["count"])
    print("   ★ 真 plugins/ 扫出来的真实工具数 = %d（本次耗时 %d ms，插件文件 %d 个）"
          % (real["count"], real["elapsed_ms"], real["files"]))
    check("工具名排序且无重复", real["tools"] == sorted(set(real["tools"])))
    check("反证：scan() 确实会换掉工具缓存对象（所以第 2 条的 is 断言不是废话）",
          cap._last["tools"] is not tools_cache)
    check("available() 与 scan 结果一致", cap.available() == real["tools"])
    check("reload() 报告增删且不删任何文件",
          cap.reload()["reloaded"] is True and "绝不删除" in cap.reload()["note"])


# ============================================================ 【7】临时插件目录
def t7_temp_plugins() -> CapabilityRegistry:
    section("【7】临时插件目录：丢 .py → 丢 .json → 把 .py 改名成 .md")
    run_dir = TMP_PLUGINS / ("run_%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), os.getpid()))
    run_dir.mkdir(parents=True, exist_ok=True)
    print("临时插件目录：%s（logs/ 已被 .gitignore 忽略；不删任何文件）" % run_dir)
    chk = CapabilityRegistry(plugins_dir=run_dir, state_dir=CARRIER_DIR)
    py_file = run_dir / "tmp_alpha.py"
    py_file.write_text(
        "# 自测临时插件（后面会把本文件**改名**成 .md 来验证「工具消失」，全程不删文件）\n"
        "class TmpAlphaTool:\n"
        "    def get_tool_descriptions(self):\n"
        "        return [{\"name\": \"tmp_alpha\", \"description\": \"临时插件工具A\",\n"
        "                 \"parameters\": {\"type\": \"object\", \"properties\": {}}}]\n\n"
        "    def execute(self, name, params):\n"
        "        return \"ok\"\n", encoding="utf-8")
    s1 = chk.scan()
    check("丢 1 个 .py → scan 得到 1 个工具（tmp_alpha）",
          s1["count"] == 1 and s1["tools"] == ["tmp_alpha"], s1["tools"])
    check("非默认插件目录自动退回目录扫描（source=dir）", s1["source"] == "dir", s1["source"])
    # _disabled 是**停用目录**（用户"停用但不删除"的落点）：里面的插件一个都不该算
    dis_dir = run_dir / "_disabled"
    dis_dir.mkdir(exist_ok=True)
    (dis_dir / "tmp_hidden.py").write_text(
        "class TmpHidden:\n"
        "    def get_tool_descriptions(self):\n"
        "        return [{\"name\": \"tmp_hidden\"}]\n", encoding="utf-8")
    s1b = chk.scan()
    check("plugins/_disabled/ 里的插件被排除（工具数、文件数都不变）",
          s1b["count"] == 1 and "tmp_hidden" not in s1b["tools"] and s1b["files"] == 1,
          "tools=%s files=%s" % (s1b["tools"], s1b["files"]))
    r = chk.register(py_file)
    check("register() 登记刚丢进来的 .py → ok=True 且报出 tmp_alpha",
          r.get("ok") is True and r.get("tools") == ["tmp_alpha"], r)
    bad_reg = chk.register(run_dir / "并不存在.py")
    check("register() 不存在的文件 → ok=False + error",
          bad_reg.get("ok") is False and bool(bad_reg.get("error")), bad_reg.get("error"))
    outside = chk.register(ROOT / "tools" / "test_carrier.py")
    check("register() 插件目录之外的文件 → ok=False（载体不替用户搬文件）",
          outside.get("ok") is False and "不在插件目录" in outside.get("error", ""),
          outside.get("error"))
    (run_dir / "tmp_beta.json").write_text(json.dumps({
        "name": "临时插件包", "type": "tools",
        "tools": [{"name": "tmp_beta", "description": "临时插件工具B",
                   "parameters": {"type": "object", "properties": {}}}]},
        ensure_ascii=False), encoding="utf-8")
    s2 = chk.scan()
    check("再丢 1 个带 tools 字段的 .json → 再 scan，added 里有新工具",
          "tmp_beta" in s2["added"] and s2["count"] == 2, s2["added"])
    check("两次扫描之间没有「消失」的工具", s2["removed"] == [], s2["removed"])
    md_file = run_dir / "tmp_alpha.md"
    py_file.replace(md_file)          # **改名**（不是删除）：.py 变 .md，工具就"消失"了
    s3 = chk.scan()
    check("把 .py 改名成 .md → removed 里有它（全程没删文件）",
          "tmp_alpha" in s3["removed"] and s3["count"] == 1, s3["removed"])
    check("改名的文件还在（.md 存在、.py 不存在）", md_file.exists() and not py_file.exists())
    d = chk.diff()
    check("diff() 报出刚才的新增/消失", d["removed"] == ["tmp_alpha"] and d["count"] == 1, d)
    return chk


def t7b_watch(chk: CapabilityRegistry) -> None:
    """附加：看守线程真的能发现"用户运行中丢了个插件"。"""
    hits: list = []
    chk.watch(on_change=hits.append, interval_s=1)
    time.sleep(1.5)          # 先等看守线程把"当前指纹"记成基线（否则刚起的线程会把新文件当基线）
    (chk.plugins_dir / "tmp_gamma.json").write_text(
        json.dumps({"name": "临时包2", "tools": [{"name": "tmp_gamma"}]}, ensure_ascii=False),
        encoding="utf-8")
    deadline = time.time() + 6
    while not hits and time.time() < deadline:
        time.sleep(0.2)
    chk.stop_watch()
    check("watch() 看守到新文件并回调（on_change 收到 scan 结果）",
          bool(hits) and "tmp_gamma" in hits[-1]["tools"], hits[-1]["added"] if hits else "没回调")


# ============================================================ 【8】清单落盘
def t8_manifest(chk: CapabilityRegistry) -> None:
    section("【8】manifest()：logs/carrier/capabilities.json 真的存在且 count 一致")
    man = chk.manifest()
    mf = CARRIER_DIR / "capabilities.json"
    got = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    check("capabilities.json 文件真的存在", mf.exists(), str(mf))
    check("落盘的 count 与 scan 一致", got.get("count") == man["count"] == chk.scan()["count"],
          "文件=%s / 返回=%s" % (got.get("count"), man["count"]))
    check("落盘内容含 tools 与 files{name:mtime}",
          isinstance(got.get("tools"), list) and isinstance(got.get("files"), dict)
          and all(isinstance(v, (int, float)) for v in got.get("files", {}).values()))


# ============================================================ 【9】坏配置
def t9_bad_config(fake_base: str) -> None:
    section("【9】配置坏掉：brains 写成字符串 / 缺 name → 跳过并记日志，不崩")
    before = len(CONFIG_LOG.read_text(encoding="utf-8").splitlines()) if CONFIG_LOG.exists() else 0
    try:
        r_str = BrainRegistry(config={"brains": "这不是列表，也不是对象"})
        n_str, cur_str, crashed = r_str.names(), r_str.current(), ""
    except Exception as e:      # noqa: silent-ok — 记录崩溃原因用于断言，自测本身要继续跑完
        n_str, cur_str, crashed = None, None, "%s: %s" % (type(e).__name__, e)
    check("brains 是字符串 → 不崩，登记处为空",
          not crashed and n_str == [] and cur_str is None, crashed or ("names=%s" % n_str))
    try:
        r_bad = BrainRegistry(config={"brains": [
            {"base_url": fake_base},                       # 缺 name → 跳过
            "我是一颗火种",                                  # 根本不是对象 → 跳过
            {"name": "好火种", "base_url": fake_base, "model": "m1"},
            {"name": "好火种", "base_url": fake_base},       # 重名 → 跳过后一条
        ]})
        n_bad, crashed2 = r_bad.names(), ""
    except Exception as e:      # noqa: silent-ok — 同上：记下崩溃原因，断言会报出来
        n_bad, crashed2 = None, "%s: %s" % (type(e).__name__, e)
    check("坏条目跳过、好条目照常登记（只剩「好火种」）",
          not crashed2 and n_bad == ["好火种"], crashed2 or str(n_bad))
    check("坏配置留下了日志（brain_config.jsonl 变长了）",
          CONFIG_LOG.exists()
          and len(CONFIG_LOG.read_text(encoding="utf-8").splitlines()) > before, str(CONFIG_LOG))
    r_none = BrainRegistry(config={})       # 没有任何 brains，也没有老写法可兼容 → 空表
    check("空配置 → 空登记处，不崩", r_none.names() == [] and r_none.current() is None)
    check("没有当前火种时 apply_to_app() → False（不抛）",
          BrainRegistry(config={"brains": []}).apply_to_app() is False)


# ============================================================ 附加：应用到 app
def t10_apply_to_app(reg: BrainRegistry, cap: CapabilityRegistry, fake_base: str) -> None:
    section("【附加】apply_to_app：真改 app 的全局变量（热插拔不重启的落点）")
    with _quiet():
        cap.scan()                             # 保证 xiaojiao_app 已经在 sys.modules 里
    app = sys.modules.get("xiaojiao_app")
    if app is None:
        check("xiaojiao_app 可导入（apply_to_app 的前置）", False, "import 失败，跳过附加项")
        return
    old = (getattr(app, "LLM_BASE", None), getattr(app, "LLM_MODEL", None),
           getattr(app, "LLM_KEY", None))
    check("apply_to_app(假火种) → True", reg.apply_to_app(reg.get("假火种")) is True)
    check("app.LLM_BASE / LLM_MODEL 真的被改成了假火种",
          app.LLM_BASE == fake_base and app.LLM_MODEL == "m1", (app.LLM_BASE, app.LLM_MODEL))
    try:
        tgt0 = app._llm_targets()[0]
        check("app._llm_targets() 当场就指向假火种（不用重启）",
              tgt0["url"] == fake_base + "/chat/completions" and tgt0["model"] == "m1", tgt0)
    except Exception as e:      # noqa: silent-ok — 取目标失败就是这条断言失败，别带走后面的检查
        check("app._llm_targets() 当场就指向假火种（不用重启）", False,
              "%s: %s" % (type(e).__name__, e))
    if old[0] is not None:                 # 还原 app 全局变量（自测不该给后续留下改过的状态）
        app.LLM_BASE, app.LLM_MODEL, app.LLM_KEY = old
    _apply_dummy_app(reg)


def _apply_dummy_app(reg: BrainRegistry) -> None:
    """app 里变量名对不上（改版 / 假模块）时必须返回 False 且**绝不抛**。"""
    saved = sys.modules.get("xiaojiao_app")

    class _DummyApp:      # 一个"变量名对不上"的假 app：没有 LLM_BASE/LLM_MODEL/LLM_KEY
        pass

    sys.modules["xiaojiao_app"] = _DummyApp()
    try:
        ok_dummy = reg.apply_to_app(reg.get("假火种"))
        crashed = ""
    except Exception as e:      # noqa: silent-ok — 这一条正是在验"绝不抛"，抛了就算失败
        ok_dummy, crashed = None, "%s: %s" % (type(e).__name__, e)
    finally:
        if saved is not None:
            sys.modules["xiaojiao_app"] = saved
    check("变量名对不上 → 返回 False 且绝不抛", not crashed and ok_dummy is False,
          crashed or str(ok_dummy))


def main() -> int:
    section("小焦 · 载体层自测（离线；不写用户配置、不删任何文件）")
    if os.path.normcase(os.path.abspath(os.getcwd())) != os.path.normcase(str(ROOT)):
        os.chdir(str(ROOT))      # app 的 load_plugins() 用的是相对 CWD 的 "plugins"
        print("（已把工作目录切到仓库根：%s）" % ROOT)
    CARRIER_DIR.mkdir(parents=True, exist_ok=True)
    control_bytes = CONTROL_FILE.read_bytes()          # 跑之前的真配置快照（字节 + mtime 双重比对）
    control_mtime = CONTROL_FILE.stat().st_mtime_ns
    srv, fake_base = _start_fake_server()
    bad_base = _dead_base_url()
    print("假火种 → %s（本地假 OpenAI）" % fake_base)
    print("坏火种 → %s（无人监听的端口）" % bad_base)

    # 准备：真 plugins/ 先做一次**目录源**清点，拿一个"真的载体状态对象"给第 2 条用
    cap = CapabilityRegistry()
    base_scan = cap.scan(use_app=False)
    tools_cache = cap._last["tools"]                   # ← 载体状态里的"工具"那把钥匙（真对象）
    tools_snapshot = list(tools_cache)
    print("真 plugins/ 目录源清点：%d 个工具名（%d 个插件文件，source=%s）"
          % (base_scan["count"], base_scan["files"], base_scan["source"]))

    reg = t1_register(fake_base, bad_base)
    t2_switch(reg, tools_cache, tools_snapshot, control_bytes, control_mtime)
    t3_probe(reg)
    t4_fallback(reg)
    t5_persist(reg, control_bytes, control_mtime)
    t6_real_capability(cap, tools_cache)
    chk = t7_temp_plugins()
    t7b_watch(chk)
    t8_manifest(chk)
    t9_bad_config(fake_base)
    t10_apply_to_app(reg, cap, fake_base)

    check("收尾：控制文件依然一个字节都没动", CONTROL_FILE.read_bytes() == control_bytes
          and CONTROL_FILE.stat().st_mtime_ns == control_mtime)
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:      # noqa: silent-ok — 假服务关不关都不影响已跑完的断言
        pass

    total, passed = len(_RESULTS), sum(1 for r in _RESULTS if r)
    section("汇总")
    print("通过 %d / 共 %d" % (passed, total))
    if passed != total:
        print("失败 %d 条（上面带 ❌ 的）" % (total - passed))
    print("载体数据目录：%s" % CARRIER_DIR)
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:      # noqa: silent-ok — 自测脚本自己崩了也要给退出码 1 并打全栈
        traceback.print_exc()
        raise SystemExit(1)
