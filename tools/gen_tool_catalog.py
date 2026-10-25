# -*- coding: utf-8 -*-
"""生成/审计「工具调用清单」：docs/tool-catalog.md + docs/tool-catalog.json

做三件事：
  ① **审计**每个已注册工具能不能被模型精准调用（判据是硬规则，不是感觉）：
     · 名字：小写+下划线，≤40 字符；
     · 说明：中文、非空、≤80 字（4B 只看一眼，长了等于没写）、不许是占位/TODO；
     · 参数：`parameters` 必须是 object；每个属性都要有 type；**每个属性都要有中文 description**
       （没有描述的参数 = 模型不知道该填什么）；required 里的每项都必须出现在 properties 里；
     · 一句话能读出"什么时候用它"（含动词或场景词，避免"某某功能"这种名词短语）。
  ② **生成清单**：把 84 个工具按"插件 → 工具"列出来，每个都给出**精准调用示例**
     （必填参数用真实示例值填好），另附"什么时候用 / 什么时候别用"。
  ③ 输出 QA 表：通过多少、哪几条不合格、为什么。不合格的先修描述再重跑，**不交带病清单**。

跑法：python tools\\gen_tool_catalog.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

MD = os.path.join(ROOT, "docs", "tool-catalog.md")
JS = os.path.join(ROOT, "docs", "tool-catalog.json")

# 参数示例值：让"怎么调"能直接抄
EXAMPLES = {
    "path": r"C:\\Windows\\System32\\notepad.exe",
    "file": r"C:\\Windows\\System32\\notepad.exe",
    "text": "你好",
    "query": "本地大模型怎么部署",
    "q": "小焦",
    "url": "https://example.com",
    "code": "def add(a,b): return a+b",
    "name": "张三",
    "message": "你好呀",
    "prompt": "画一只在窗台晒太阳的猫",
    "seconds": 5,
    "n": 3,
    "k": 5,
    "top_k": 5,
    "lines": 40,
    "count": 3,
    "tool": "open_binary",
    "intent": "反编译 main 函数",
    "target": r"C:\\Windows\\System32\\notepad.exe",
    "focus": "main",
    "args": {},
    "keyword": "pe",
    "model": "xiaojiao",
    "memory_id": "1792160000000-ab12cd",
    "kind": "fact",
    "id": "1792160000000-ab12cd",
    "command": "dir",
    "expr": "1+1",
    "expression": "1+1",
    "topic": "睡眠",
    "persona": "小焦",
    "city": "济南",
    "lang": "zh",
    "style": "简短",
    "audio_path": r"C:\\xiaojiao\\media\\a.mp3",
    "video_path": r"C:\\xiaojiao\\videos\\a.mp4",
    "seconds_per_segment": 5,
}

# 判定用词表
_VERB_HINTS = ("查", "读", "写", "列", "跑", "做", "给", "看", "找", "搜", "生成", "算", "抓",
               "下", "解", "转", "切", "记", "问", "打开", "分析", "检查", "统计", "执行",
               "调用", "保存", "加载", "清理", "对比", "校验", "测", "启动", "停", "换", "装")
_BAD_DESC = ("todo", "占位", "示例", "placeholder", "xxx", "待补")


from core import tool_desc as TD     # 判据唯一真源：说明压句 / 参数说明 / 用词检查都在这


def _is_cjk(s):
    return bool(re.search(r"[\u4e00-\u9fff]", str(s or "")))


def audit_tool(t):
    """返回问题列表（空 = 合格）。判据来自 `core.tool_desc.normalize_tool()`，不另写一套。"""
    bad = []
    name = str(t.get("name") or "")
    if not re.match(r"^[a-z][a-z0-9_]{1,39}$", name):
        bad.append("名字不合规（应小写+下划线、≤40 字符）：%r" % name)
    fn, rep = TD.normalize_tool({"name": name,
                                 "description": t.get("description") or "",
                                 "parameters": t.get("parameters") or {}})
    if rep.get("desc_problem"):
        bad.append(rep["desc_problem"])
    prm = fn.get("parameters") or {}
    props = prm.get("properties") or {}
    for pname, spec in props.items():
        if str((spec or {}).get("description") or "").strip().startswith("（作者未写说明"):
            bad.append("参数 %s 的说明是自动补的占位（作者没写）" % pname)
    for r in (prm.get("required") or []):
        if r not in props:
            bad.append("required 里的 %s 不在 properties 里" % r)
    return bad


def example_call(t):
    """按必填参数拼一个"能直接抄"的调用示例。"""
    name = t.get("name")
    params = t.get("parameters") or {}
    props = params.get("properties") or {}
    req = params.get("required") or []
    args = {}
    for r in req:
        if r in EXAMPLES:
            args[r] = EXAMPLES[r]
        else:
            spec = props.get(r) or {}
            args[r] = {"string": "值", "integer": 1, "number": 1, "boolean": True,
                       "array": [], "object": {}}.get(str(spec.get("type") or "string"), "值")
    if not args:
        return '%s({})' % name
    return "%s(%s)" % (name, json.dumps(args, ensure_ascii=False))


def main():
    print("=" * 84)
    print("  工具调用清单：审计 + 生成（判据写死，不看心情）")
    print("=" * 84)
    import xiaojiao_app as app       # noqa: E402

    plugins = getattr(app, "PLUGINS", {}) or {}
    # **审计的是模型真正看到的那份表**（`_build_tools()` 已把 parameters 规范化、
    # 把过长说明压成第一句）。审计插件的原始声明会误报 —— 两者本来就不一样。
    visible = {}
    for item in (app._build_tools() or []):
        fn = (item or {}).get("function") or {}
        if fn.get("name"):
            visible[fn["name"]] = fn
    builtin_names = set()
    for item in (getattr(app, "TOOLS", None) or []):
        fn = (item or {}).get("function") or {}
        if fn.get("name"):
            builtin_names.add(fn["name"])
    owner, full_desc = {}, {}
    for pname, pv in plugins.items():
        for t in (pv.get("desc") or []):
            if isinstance(t, dict) and t.get("name"):
                owner.setdefault(str(t["name"]), pname)
                full_desc.setdefault(str(t["name"]), str(t.get("description") or ""))

    rows, bad_rows = [], []
    for nm in sorted(visible):
        fn = visible[nm]
        t = {"name": nm, "description": fn.get("description") or "",
             "parameters": fn.get("parameters") or {}}
        probs = audit_tool(t)
        params = t["parameters"] or {}
        rec = {"plugin": owner.get(nm, "内置"),
               "kind": "内置" if nm in builtin_names else "插件",
               "name": nm,
               "description": str(t["description"]),
               "full_description": full_desc.get(nm, str(t["description"])),
               "required": list(params.get("required") or []),
               "properties": list((params.get("properties") or {}).keys()),
               "example": example_call(t),
               "test": "通过" if not probs else "不合格", "problems": probs}
        rows.append(rec)
        if probs:
            bad_rows.append(rec)

    ok = len(rows) - len(bad_rows)
    print("\n工具总数：%d ｜ 合格：%d ｜ 不合格：%d" % (len(rows), ok, len(bad_rows)))
    if bad_rows:
        print("\n不合格清单（先修这些，再生成文档）：")
        for r in bad_rows:
            print("  · %-34s [%s] %s" % (r["name"], r["plugin"], "；".join(r["problems"])[:110]))

    # ---- 写清单 ----
    io.open(JS, "w", encoding="utf-8", newline="\n").write(
        json.dumps({"total": len(rows), "ok": ok, "bad": len(bad_rows), "tools": rows},
                   ensure_ascii=False, indent=1))
    lines = []
    lines.append("# 工具调用清单（模型精准调用指南）\n")
    lines.append("> 这份文件是 `tools/gen_tool_catalog.py` **自动生成**的，别手改 —— ")
    lines.append("> 改了工具描述就重跑一次；`tools/test_tool_contract.py` 会校验它和实际工具表是否一致。\n")
    lines.append("**全部工具：%d 个 ｜ 契约合格：%d 个 ｜ 不合格：%d 个**\n" % (len(rows), ok, len(bad_rows)))
    lines.append("## 怎么读这张表\n")
    lines.append("- **什么时候用**：说明里的第一句就是触发场景；模型按这句话决定要不要挑这个工具。")
    lines.append("- **精准调用**：括号里是**必填参数**，值已经填成能直接抄的例子。")
    lines.append("- **参数说明**：所有参数都必须有中文说明（没有说明的参数 = 模型不知道该填什么，审计会判不合格）。\n")
    lines.append("## 一句话总则\n")
    lines.append("1. 只挑**说明里明确提到当前这件事**的工具；挑不出就不调，直接问用户。")
    lines.append("2. 必填参数齐了才调；缺就先问（`rea_do` 这类入口会替模型把参数补齐或把缺口列出来）。")
    lines.append("3. 同一个意思有多个工具时，优先**更具体**的那个（名字里有具体对象的）。")
    lines.append("4. 工具返回空/报错时，把它说的原话转达给用户，不要自己编结果。\n")
    by_plugin = {}
    for r in rows:
        by_plugin.setdefault((r["kind"], r["plugin"]), []).append(r)
    for (kind, pname), items in sorted(by_plugin.items(), key=lambda x: (x[0][0], x[0][1])):
        lines.append("### %s · %s（%d 个工具）\n" % (kind, pname, len(items)))
        lines.append("| 工具 | 什么时候用（说明） | 精准调用（必填参数已填示例） | 契约 |")
        lines.append("| --- | --- | --- | --- |")
        for r in items:
            desc = r["description"].replace("|", "／").replace("\n", " ")
            lines.append("| `%s` | %s | `%s` | %s |"
                         % (r["name"], desc, r["example"], "✅" if r["test"] == "通过" else "❌"))
        lines.append("")
    io.open(MD, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("\n已写：docs/tool-catalog.md（%.1f KB）、docs/tool-catalog.json（%.1f KB）"
          % (os.path.getsize(MD) / 1024.0, os.path.getsize(JS) / 1024.0))
    return 0 if not bad_rows else 1


if __name__ == "__main__":
    sys.exit(main())
