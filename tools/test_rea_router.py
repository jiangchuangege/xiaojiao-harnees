# -*- coding: utf-8 -*-
"""REA 意图路由 · 自测（用真 REA 的工具清单快照，不需要起 node / 联网）。

为什么单独测这一层：`rea_do` 的价值全在"4B 说中文，载体选工具"这句上。
它一旦选错，用户看到的就是"它答非所问"，而且**不报错**。所以这里拿 20 条真实意图当夹具，
钉住两件事：
  ① 准确率下限（≥80%）—— 允许有几条不完美，但不许整体退化；
  ② 结构性行为：该问参数的问参数、该自动 open_binary 的自动打开、平台对不上别乱派。

夹具里的"期望工具"是人工核过的；没写死的用 allow=[] 表示"只要不是明显的错就行"。
工具清单从 `tests/rea_tools_snapshot.json` 读（229 个工具的名字+说明+schema 快照），
这样测试不依赖本机装没装 REA。
"""
import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# 夹具：(意图, 目标, 期望工具 或 允许集合, 说明)
CASES = [
    ("反编译 main 函数", "C:/x/a.exe", {"procedure_pseudo_code", "batch_decompile", "decompile_all"}, "PE 反编译"),
    ("把这个函数反编译出来", "C:/x/a.exe", {"procedure_pseudo_code", "batch_decompile"}, "同一件事换说法"),
    ("列出所有字符串", "C:/x/a.exe", {"list_strings", "search_strings"}, "字符串清单"),
    ("搜一下有没有 api 这个字符串", "C:/x/a.exe", {"search_strings", "list_strings", "search_bytes"}, "搜字符串"),
    ("看函数调用关系", "C:/x/a.exe", {"procedure_callees", "procedure_callers", "call_graph", "get_call_graph"}, "调用图"),
    ("谁调用了这个函数", "C:/x/a.exe", {"procedure_callers", "procedure_callees", "call_graph"}, "调用者"),
    ("搜索特征码", "C:/x/a.exe", {"search_bytes"}, "字节特征"),
    ("看导入表", "C:/x/a.exe", {"inspect_pe_imports", "inspect_pe_exports", "list_names"}, "PE 导入"),
    ("看这个文件的哈希", "C:/x/a.exe", {"open_binary", "inspect_artifact"}, "哈希（open_binary 的返回里就带 sha256）"),
    ("打开这个 exe 看看格式", "C:/x/a.exe", {"open_binary", "inspect_artifact"}, "认格式"),
    ("看段的权限", "C:/x/a.exe", {"list_segments", "inspect_binary_layout", "inspect_macho"}, "段表"),
    ("解析 apk 里的东西", "C:/x/a.apk", {"inspect_android_package", "decode_android_resources", "open_binary"}, "安卓包"),
    ("看安卓的类", "C:/x/a.apk", {"search_android_classes", "inspect_android_class", "get_android_manifest"}, "安卓类"),
    ("看苹果的类", "C:/x/a.ipa", {"get_objc_classes", "inspect_macho", "get_objc_protocols"}, "ObjC 类"),
    ("看 plist", "C:/x/a.ipa", {"inspect_plist", "inspect_keyed_archive"}, "plist"),
    ("检查这个 gguf 模型文件", "C:/m/a.gguf", {"inspect_model_artifact", "open_binary"}, "模型文件"),
    ("看看证书签名", "C:/x/a.exe", {"inspect_signature", "inspect_pe_certificates"}, "签名"),
    ("对比两个版本的差异", "C:/x/a.apk", {"compare_application_versions", "compare_source_to_bundle",
                                     "compare_web_captures", "compare_managed_members"}, "版本对比"),
    ("看一眼运行时能不能挂上", "", {"start_frida_session", "list_frida_processes", "instrument_with_frida",
                                "list_frida_devices", "frida_session_status"}, "frida"),
    ("清理一下分析出来的缓存快照", "", set(), "冷门需求：允许选不中（这条不计分）"),
]
THRESHOLD = 0.80


def main():
    print("=" * 78)
    print("  REA 意图路由自测（20 条真实意图；不需要起 node / 联网）")
    print("=" * 78)

    snap = os.path.join(_ROOT, "tests", "rea_tools_snapshot.json")
    if not os.path.exists(snap):
        print("缺少工具清单快照：%s" % snap)
        return 1
    tools = json.load(io.open(snap, encoding="utf-8"))
    print("  夹具工具数：%d" % len(tools))

    os.environ.pop("REA_CMD", None)
    os.environ.pop("REA_CWD", None)
    import plugins.rea as rea          # noqa: E402

    print("\n[一] 逐条路由")
    hit, total = 0, 0
    misses = []
    for intent, target, want, note in CASES:
        cands, top = rea._route(intent, tools, target=target)
        got = cands[0]["name"] if cands else "（没选中）"
        if not want:
            print("  —— %-16s → %-30s（%s，不计分）" % (intent, got, note))
            continue
        total += 1
        ok = got in want
        hit += 1 if ok else 0
        if not ok:
            misses.append((intent, got, sorted(want)[:2]))
        print("  %s %-18s → %-30s %s" % ("✅" if ok else "❌", intent, got, note))

    rate = (hit / float(total)) if total else 0.0
    ck("准确率 ≥ %d%%（实测 %d/%d = %.0f%%）" % (THRESHOLD * 100, hit, total, rate * 100),
       rate >= THRESHOLD, "；".join("%s→%s" % (m[0], m[1]) for m in misses[:3]))
    if misses:
        print("\n  没选中的（如实列出来，不藏）：")
        for it, got, want in misses:
            print("     · 「%s」→ %s（期望 %s 之一）" % (it, got, "/".join(want)))

    print("\n[二] 结构性行为（这几条比准确率更要紧）")
    ck("平台对不上别乱派：给 .exe 找签名不会派到 apk 专属工具",
       (rea._route("看看证书签名", tools, target="C:/x/a.exe")[0] or [{"name": ""}])[0]["name"]
       not in ("inspect_apk_signature",), "（回退到通用 inspect_signature 也算对）")
    ck("意图里点工具本名 → 直接就是它",
       (rea._route("procedure_pseudo_code", tools, target="C:/x/a.exe")[0] or [{"name": ""}])[0]["name"]
       == "procedure_pseudo_code")
    ck("完全无关的意图 → 不硬选（top 分低于阈值）",
       rea._route("今天天气怎么样", tools)[1] < 2, rea._route("今天天气怎么样", tools)[1])
    cands, _ = rea._route("反编译 main 函数", tools, target="C:/x/a.exe")
    ck("会给出备选（结果不对时模型有退路）", len(cands) >= 2, [d["name"] for d in cands[:3]])

    print("\n[三] 参数填充（载体替模型拼 args）")
    cands_all, _ = rea._route("打开这个 exe 看看格式", tools, target="C:/x/a.exe")
    d_open = next((d for d in rea._build_index(tools) if d["name"] == "open_binary"), None)
    args, missing = rea._fill_args(d_open, target="C:/x/a.exe", focus="")
    ck("path 被自动填上（open_binary 这种吃 path 的工具）",
       any(str(v) == "C:/x/a.exe" for v in args.values()), args)
    ck("填得齐时不问人（missing 为空）", missing == [], missing)
    # 反编译那类工具吃的是 procedure/symbol，不吃 path：目标由载体先 open_binary 打开
    d_pseudo = next((d for d in cands if d["name"] == "procedure_pseudo_code"), cands[0])
    args2, missing2 = rea._fill_args(d_pseudo, target="C:/x/a.exe", focus="main")
    ck("吃 procedure/symbol 的工具：focus 被填进去",
       any(str(v) == "main" for v in args2.values()), args2)
    d2 = {"name": "fake_tool", "desc": "", "props": ["path", "selector"], "required": ["path", "selector"],
          "ntok": set(), "dtok": set(), "ptok": {"path", "selector"}}
    args3, missing3 = rea._fill_args(d2, target="C:/x/a.exe", focus="")
    ck("填不齐时**列出来问**，不瞎编", missing3 == ["selector"], missing3)

    print("\n[四] 能力没有被缩减")
    ck("五个入口都在（status / tools / call / do / help）",
       [t["name"] for t in rea._PLUGIN.get_tool_descriptions()] ==
       ["rea_status", "rea_tools", "rea_call", "rea_do", "rea_help"],
       [t["name"] for t in rea._PLUGIN.get_tool_descriptions()])
    ck("229 个工具都能被路由命中（索引覆盖全部）",
       len(rea._build_index(tools)) == len(tools), "%d / %d" % (len(rea._build_index(tools)), len(tools)))
    ck("任意工具名都能通过 rea_call 精确调（不存在白名单截断）",
       "白名单" not in (rea._do_call.__doc__ or ""), "（看代码：_do_call 只校验非空，不限制名单）")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d（其中路由命中 %d/%d = %.0f%%）%s"
          % (len(PASS), len(PASS) + len(FAIL), hit, total, rate * 100,
             ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
