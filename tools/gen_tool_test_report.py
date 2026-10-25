# -*- coding: utf-8 -*-
"""生成 docs/tool-catalog-tests.md：工具可调用性的**测试通过表**（数字全来自实跑）。

为什么单独一份：`tool-catalog.md` 回答「每个工具怎么精准调」，这份回答「凭什么说它可调」——
逐条列出相关自测、通过数与耗时，结论由脚本算，不手写。
"""
import io
import json
import os
import subprocess
import sys
import time

ROOT = r"C:\xiaojiao\xiaojiao harness"
os.chdir(ROOT)
OUT = os.path.join(ROOT, "docs", "tool-catalog-tests.md")
JS = os.path.join(ROOT, "docs", "tool-catalog.json")

TESTS = [
    ("tools/test_tool_contract.py", "工具调用契约（说明 / 参数 / 执行入口 / 清单一致性）"),
    ("tools/test_rea_plugin.py", "REA 插件本体（假 MCP 服务）"),
    ("tools/test_rea_router.py", "REA 意图路由（20 条真实意图）"),
    ("tools/test_causal_memory_plugin.py", "因果记忆插件 A（6 个工具）"),
    ("tools/test_causal_memory_ext.py", "因果记忆插件 B（10 个工具）"),
    ("tools/test_causal_hooks.py", "因果记忆自动埋点"),
    ("tools/test_memory_depth.py", "记忆深度（分层 / 降级 / 压缩 / 巩固 / 联想）"),
    ("tools/test_memory_gate.py", "记忆口径判据"),
    ("tools/test_memory_gate_wiring.py", "记忆口径接线"),
    ("tools/test_memory_upkeep.py", "记忆保养本体"),
    ("tools/test_memory_upkeep_wiring.py", "记忆保养接线"),
    ("tools/test_memory_vec_index.py", "向量索引一致性"),
    ("tools/test_mem_filter.py", "写入侧过滤"),
    ("tools/test_mem_source.py", "记忆来源可信度"),
    ("tools/test_memory_write_dedupe.py", "写入侧去重"),
    ("tools/test_video_ui_wiring.py", "视频界面接线"),
    ("tools/test_video_audio.py", "视频与配音"),
    ("tools/test_cloud_video_spec.py", "云端视频协议适配"),
    ("tools/test_cloud_video_worker.py", "云端视频 worker"),
    ("tools/test_model_add_keeps_video_api.py", "加模型不丢视频协议"),
]


def run(script):
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-u", script], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=1200)
        out = (r.stdout or "") + (r.stderr or "")
        rc = r.returncode
    except Exception as e:
        return False, "跑不起来：%s" % e, time.time() - t0
    stat = ""
    for line in reversed(out.splitlines()):
        s = line.strip()
        if s.startswith("通过 ") or "失败：" in s:
            stat = s[:120]
            break
    return rc == 0, stat, time.time() - t0


def main():
    rows = []
    for script, note in TESTS:
        if not os.path.exists(os.path.join(ROOT, script)):
            rows.append((script, note, "（不存在）", False, 0.0))
            continue
        ok, stat, dt = run(script)
        rows.append((script, note, stat, ok, dt))
        print("%s %-46s %s" % ("✅" if ok else "❌", script, stat[:56]))

    total, passed = len(rows), len([r for r in rows if r[3]])
    info = {}
    if os.path.exists(JS):
        info = json.load(io.open(JS, encoding="utf-8"))

    L = []
    L.append("# 工具可调用性 · 测试通过表\n")
    L.append("> 由脚本实跑生成，数字不是手写的。配套清单见 [tool-catalog.md](tool-catalog.md)。\n")
    L.append("**工具表 %s 个 ｜ 契约合格 %s 个 ｜ 相关自测 %d 个，通过 %d 个**\n"
             % (info.get("total", "?"), info.get("ok", "?"), total, passed))
    L.append("## 一、逐条自测结果\n")
    L.append("| 自测 | 验什么 | 结果 | 统计 |")
    L.append("| --- | --- | --- | --- |")
    for script, note, stat, ok, dt in rows:
        L.append("| `%s` | %s | %s | %s |"
                 % (script, note, "✅ 通过" if ok else "❌ 未通过", stat or "—"))
    L.append("")
    L.append("## 二、凭什么说模型能精准调用\n")
    L.append("1. **看得懂**：每个工具的说明都被压成一句（不超过 60 字，统一在 `core/tool_desc.py` 里做），")
    L.append("   读的是「什么时候用它」。参数缺说明会先查通用词典（url / selector / session_id / diagram_type 等），")
    L.append("   词典里也没有就如实标「作者未写说明」，**不编语义**。")
    L.append("2. **知道填什么**：清单里每个工具都给了调用示例，必填参数已填成能直接抄的值；")
    L.append("   契约自测会校验「示例里的参数名必须真实存在于 schema 里」。")
    L.append("3. **不会静默失败**：所有插件收到不认识的工具名都返回中文说明（列出自己有哪些工具），")
    L.append("   不再返回 None 或裸 dict —— 那两种在调用方看来都是「没有输出」，出问题毫无线索。")
    L.append("4. **清单不许过期**：契约自测会比「清单里的工具集合」和「当前真实工具表」是否相等，")
    L.append("   改了工具却没重新生成清单，直接判不合格。\n")
    L.append("## 三、怎么维护这份清单\n")
    L.append("```")
    L.append("python tools/gen_tool_catalog.py       # 改了插件说明或参数后重新生成")
    L.append("python tools/test_tool_contract.py     # 契约自测，不到全绿不算交付")
    L.append("python tools/gen_tool_test_report.py   # 重新生成这份通过表")
    L.append("```\n")
    L.append("模型侧的实际调用姿势：不确定时先说一句中文「要干什么」（`rea_do` 这类意图入口会替它选工具、")
    L.append("补参数）；确定工具名时直接按清单里的那一行调。\n")
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
    print("\n已写：%s（%.1f KB）" % (OUT, os.path.getsize(OUT) / 1024.0))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
