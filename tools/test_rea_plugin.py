# -*- coding: utf-8 -*-
"""REA 插件 · 自测（确定性；用假 MCP 服务，不依赖 node、不联网、不装包）。

为什么必须有它：这个插件把外部 229 个工具收成三个入口，最容易出的错**全都不报错**：
  ① 启动器路径配错 → 插件静默一个工具都不注册（用户只看到"它不会逆向"）；
  ② args 传成字符串 / 传错类型 → 真 REA 会直接报参数错，而小焦那层会把异常吞掉；
  ③ 结果太长 → 把 229 个工具的说明塞进 4B 的上下文，回答直接崩；
  ④ 工具名写错 → 只回一句"失败"，模型不知道下一步该干什么。
所以这里逐条钉住：注册条件、三个入口的行为、截断、错误话术、超时、以及"绝不抛异常"。
"""
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    t0 = time.time()
    print("=" * 78)
    print("  REA 插件自测（假 MCP 服务；不依赖 node / 网络 / 装包）")
    print("=" * 78)

    import importlib
    fake = os.path.join(_ROOT, "tests", "fake_rea_mcp.py")

    # 让插件指向假服务（走环境变量这一条正规入口）
    os.environ["REA_CMD"] = json.dumps([sys.executable, fake])
    os.environ["REA_CWD"] = _ROOT
    import plugins.rea as rea          # noqa: E402
    importlib.reload(rea)
    cfg = rea._load_cfg()

    # ---------------- 一、注册条件 ----------------
    print("\n[一] 什么时候注册工具")
    tools = rea._PLUGIN.get_tool_descriptions()
    ck("服务可用时注册五个入口（能力被完整保留）", len(tools) == 5, [t["name"] for t in tools])
    ck("名字对得上：status / tools / call / do / help",
       [t["name"] for t in tools] == ["rea_status", "rea_tools", "rea_call", "rea_do", "rea_help"])
    ck("每个工具都有中文说明且不长（4B 好选）",
       all(0 < len(t["description"]) <= 70 for t in tools),
       max(len(t["description"]) for t in tools))
    ck("call 工具声明了必填的 tool 参数",
       tools[2]["parameters"]["required"] == ["tool"], tools[2]["parameters"]["required"])
    ck("do 工具只要 intent（target/focus 可省）",
       tools[3]["parameters"]["required"] == ["intent"], tools[3]["parameters"]["required"])

    # 关掉 + 启动器不存在，两种情况都不许注册工具
    os.environ["REA_CMD"] = json.dumps([sys.executable, fake])
    old_cfg = rea._load_cfg
    try:
        rea._load_cfg = lambda: dict(cfg, on=False)
        ck("配置关掉（rea.on=false）→ 一个工具都不注册",
           rea._PLUGIN.get_tool_descriptions() == [])
        rea._load_cfg = lambda: dict(cfg, cmd=[sys.executable, os.path.join(_ROOT, "不存在", "x.py")])
        ck("启动器不存在 → 一个工具都不注册（不糊假工具给模型）",
           rea._PLUGIN.get_tool_descriptions() == [])
    finally:
        rea._load_cfg = old_cfg

    # ---------------- 二、status ----------------
    print("\n[二] rea_status：服务活着没、版本、工具数")
    out = rea._PLUGIN.execute("rea_status", {})
    ck("报出在线状态和版本", "REA 在线" in out and "0.0.1" in out, out[:70])
    ck("报出工具数量（假的 3 个）", "可用工具 3 个" in out, out[:90])
    ck("报出工作目录与超时上限（排查要用）", _ROOT[:12] in out and "秒" in out)

    # ---------------- 三、tools：目录式检索 ----------------
    print("\n[三] rea_tools：把 229 个工具变成一个可检索的目录")
    out = rea._PLUGIN.execute("rea_tools", {})
    ck("不传关键词 → 列前若干个", "REA 工具（共 3 个" in out, out[:60])
    out = rea._PLUGIN.execute("rea_tools", {"keyword": "artifact"})
    ck("按关键词过滤（inspect_artifact 命中）",
       "inspect_artifact" in out and "binary_overview" not in out, out[:120])
    out = rea._PLUGIN.execute("rea_tools", {"keyword": "字符串"})
    ck("关键词也能匹配中文说明（search_strings 命中）", "search_strings" in out, out[:80])
    out = rea._PLUGIN.execute("rea_tools", {"keyword": "zzz不存在"})
    ck("搜不到时如实说没有，并给出可用的词", "没有匹配" in out and "pe" in out, out[:80])
    out = rea._PLUGIN.execute("rea_tools", {"limit": 1})
    ck("limit 生效（只列 1 条）", out.count("·") == 1, out.count("·"))

    # ---------------- 四、call：真的把参数传过去 ----------------
    print("\n[四] rea_call：参数原样传过去，结果带回来")
    out = rea._PLUGIN.execute("rea_call", {"tool": "inspect_artifact",
                                          "args": {"path": "C:/tmp/a.exe"}})
    ck("调用成功并回传结果", "PE32+" in out and "C:/tmp/a.exe" in out, out[:80])
    out = rea._PLUGIN.execute("rea_call", {"tool": "search_strings",
                                          "args": json.dumps({"path": "x", "pattern": "api"})})
    ck("args 传 JSON 字符串也能用（模型常这么传）", "命中 2 条" in out and "api" in out, out[:70])
    out = rea._PLUGIN.execute("rea_call", {"tool": "inspect_artifact"})
    ck("不传 args → 按空对象传，服务端说缺参数就如实转达",
       "缺少参数" in out or "没有返回任何内容" in out, out[:70])

    # ---------------- 五、错误话术（模型要知道下一步干什么） ----------------
    print("\n[五] 出错时的话必须能指路")
    out = rea._PLUGIN.execute("rea_call", {"tool": "根本不存在"})
    ck("工具名写错 → 说没有这个工具，并给相近候选", "没有叫" in out and "相近" in out, out[:80])
    out = rea._PLUGIN.execute("rea_call", {"tool": "inspect_artifact", "args": "{坏 JSON"})
    ck("args 不是合法 JSON → 中文说明怎么传", "不是合法 JSON" in out, out[:60])
    out = rea._PLUGIN.execute("rea_call", {"tool": "inspect_artifact", "args": [1, 2]})
    ck("args 传成数组 → 说必须是对象", "必须是 JSON 对象" in out, out[:60])
    out = rea._PLUGIN.execute("rea_call", {})
    ck("没说要调哪个 → 指路 rea_tools", "rea_tools" in out, out[:60])
    out = rea._PLUGIN.execute("rea_call", {"tool": "boom", "args": {}})
    ck("服务端报错但没说明 → 如实说服务端报错", "服务端报错" in out or "失败" in out, out[:70])
    out = rea._PLUGIN.execute("不存在的工具", {})
    ck("插件收到不认识的工具名 → 说清楚只有那三个", "未知工具" in out, out[:60])

    # ---------------- 六、把 REA 的结构化报错翻成人话 ----------------
    print("\n[六] REA 的报错 JSON 要翻成人话（4B 看嵌套 JSON 等于没看）")
    prov = json.dumps({"error": {"code": "provider_unavailable", "category": "unavailable",
                                 "message": "The selected analysis provider is unavailable.",
                                 "remediation": {"action": "run `rea doctor`"}}})
    out = rea._friendly_error(prov)
    ck("provider_unavailable → 说清是分析引擎没装，并给下一步",
       "分析引擎" in out and "open_binary" in out, out[:90])
    ck("带上它自己给的建议（rea doctor）", "rea doctor" in out, out[:120])
    inv = json.dumps({"error": {"code": "invalid_input", "message": "arguments do not match schema"}})
    out = rea._friendly_error(inv)
    ck("invalid_input → 指向 rea_tools 看必填参数", "rea_tools" in out, out[:80])
    ck("不是 JSON 的原样返回（不吞内容）", rea._friendly_error("普通文本报错") == "普通文本报错")
    ck("JSON 但没有 error 字段 → 原样返回", '"x":1' in rea._friendly_error('{"x":1}'))
    ck("翻不出来也不许抛异常", isinstance(rea._friendly_error(None), str))

    # ---------------- 七、截断与超时 ----------------
    print("\n[七] 截断和超时（不然 4B 的上下文会被撑爆）")
    old_cfg = rea._load_cfg
    try:
        rea._load_cfg = lambda: dict(cfg, max_chars=400)
        out = rea._PLUGIN.execute("rea_call", {"tool": "inspect_artifact", "args": {"path": "p"}})
        ck("max_chars 生效（短结果不截断）", "截断" not in out, len(out))
        long_text = "x" * 2000
        ck("_clip 会截断并说明原文有多长",
           "截断" in rea._clip(long_text, 400) and "2000" in rea._clip(long_text, 400))
        rea._load_cfg = lambda: dict(cfg, timeout_s=2)
        t1 = time.time()
        out = rea._PLUGIN.execute("rea_call", {"tool": "slow_tool", "args": {}})
        dt = time.time() - t1
        ck("服务不回时按超时返回中文说明，不挂死", "超时" in out and dt < 12, "%s ｜ %.1fs" % (out[:40], dt))
    finally:
        rea._load_cfg = old_cfg

    # ---------------- 八、绝不抛异常 ----------------
    print("\n[八] 任何情况都不许把异常抛出去（上层会把它吞成空串）")
    for bad in ({"tool": None}, {"tool": 123}, {"tool": "inspect_artifact", "args": {"path": None}},
                None):
        try:
            out = rea._PLUGIN.execute("rea_call", bad)
            ck("坏参数 %r → 不抛异常（返回 %s…）" % (str(bad)[:24], out[:12]), isinstance(out, str) and bool(out))
        except Exception as e:
            ck("坏参数 %r → 不该抛异常" % str(bad)[:24], False, "%s: %s" % (type(e).__name__, e))
    old_cfg2 = rea._load_cfg
    try:
        def _boom_cfg():
            raise RuntimeError("读配置炸了")
        rea._load_cfg = _boom_cfg
        out = rea._PLUGIN.execute("rea_status", {})
        ck("连配置都读不出来时也返回中文说明", isinstance(out, str) and "内部出错" in out, out[:60])
    finally:
        rea._load_cfg = old_cfg2

    # ---------------- 九、收尾 ----------------
    print("\n[九] 收尾")
    c = rea._client.get("obj")
    if c is not None:
        c.stop()
    ck("能停掉 MCP 子进程（不留孤儿进程）", c is None or not c.alive())
    ck("配置文件里的默认值可读且合理", rea._load_cfg()["timeout_s"] >= 10)

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
