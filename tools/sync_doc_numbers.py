# -*- coding: utf-8 -*-
"""文档数字自动对账（2026-10-29）

【要修的问题】外部审计的原话：
  · 文档写 **101** 个工具，实测 **120**；
  · 文档写 **134** 张 Mermaid 图，实际 **155**；
  · 文档写离线测试 **100%**，实际 99.53%。
  结论是"不是造假，是写完没回去更新"。

【为什么第一版被我自己否掉了】
  最初想用正则把正文里的数字**就地改掉**，一跑就发现它把 README 里
  「你有 15 个工具」「引擎里有 18 个工具」这种**举例**也算成总数，6 处全要改错。
  **自动改正文 = 自动破坏文档**。所以改成分两块：

    1. **可自动维护的那一块**：README 里放一段带标记的
       `<!-- AUTO-NUMBERS:BEGIN --> … <!-- AUTO-NUMBERS:END -->`，
       里面只有数字，由本脚本**整体重写**（标记之外一个字不动）；
    2. **正文里人写的数字**：只**报告**漂了多少（给人看），**绝不自动改**
       —— 那是作者的正文，改错了比不改糟得多。

用法：
    python tools/sync_doc_numbers.py            # 对账（标了 WAIT 就返回 1）
    python tools/sync_doc_numbers.py --write    # 只重写标记块里的数字
"""
import argparse
import io
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(_ROOT, "README.md")
_BEGIN = "<!-- AUTO-NUMBERS:BEGIN -->"
_END = "<!-- AUTO-NUMBERS:END -->"


# ============================== 真实数字（现算，不写死） ==============================
def count_tools():
    """工具总数：问运行期对象（`all_tool_names()`），不是数文件。"""
    try:
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        import xiaojiao_app as A
        A._build_tools()
        return len(A.all_tool_names())
    except Exception as e:      # noqa: silent-ok — 拿不到就返回 None（对账时跳过这一项）
        print("  （工具数取不到：%s）" % e)
        return None


def count_routes():
    try:
        txt = io.open(os.path.join(_ROOT, "xiaojiao_app.py"), encoding="utf-8").read()
        return len(re.findall(r"^@app\.route\(", txt, re.M))
    except Exception:      # noqa: silent-ok
        return None


def count_plugins():
    try:
        d = os.path.join(_ROOT, "plugins")
        return len([x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x))])
    except Exception:      # noqa: silent-ok
        return None


def count_mermaid():
    """文档里 Mermaid 图总数（README + docs/**.md 里的 ```mermaid 块）。"""
    n = 0
    files = [README]
    docs = os.path.join(_ROOT, "docs")
    for dirpath, _dn, filenames in os.walk(docs):
        for fn in filenames:
            if fn.endswith(".md"):
                files.append(os.path.join(dirpath, fn))
    for fp in files:
        try:
            txt = io.open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:      # noqa: silent-ok
            continue
        n += len(re.findall(r"^```mermaid", txt, re.M))
    return n


def count_tests():
    try:
        d = os.path.join(_ROOT, "tools")
        return len([x for x in os.listdir(d) if x.startswith("test_") and x.endswith(".py")])
    except Exception:      # noqa: silent-ok
        return None


def count_core_modules():
    try:
        d = os.path.join(_ROOT, "core")
        return len([x for x in os.listdir(d) if x.endswith(".py")])
    except Exception:      # noqa: silent-ok
        return None


def real_numbers():
    nums = {"tools": count_tools(), "routes": count_routes(),
            "plugins": count_plugins(), "mermaid": count_mermaid(),
            "tests": count_tests(), "core_modules": count_core_modules()}
    # 代码行数：现数（不算空文件）
    for key, rel in (("app_lines", "xiaojiao_app.py"),):
        try:
            nums[key] = len(io.open(os.path.join(_ROOT, rel), encoding="utf-8",
                                    errors="ignore").read().split("\n"))
        except Exception:      # noqa: silent-ok
            nums[key] = None
    return nums


_LABEL = [("tools", "可调用工具"), ("routes", "HTTP 路由"), ("plugins", "插件文件"),
          ("core_modules", "core 模块"), ("tests", "自测脚本"),
          ("mermaid", "Mermaid 图"), ("app_lines", "主程序行数")]


def _block(nums):
    rows = ["| 项目 | 实测数字 |", "| --- | --- |"]
    for k, label in _LABEL:
        v = nums.get(k)
        rows.append("| %s | %s |" % (label, "取不到" if v is None else v))
    rows.append("")
    rows.append("> 这张表由 `python tools/sync_doc_numbers.py --write` 现算现写，不是手抄的。")
    return "\n".join([_BEGIN, ""] + rows + ["", _END])


# ============================== 对账 ==============================
# 正文里人写的数字：**只报告，不改**。每条都带足上下文，尽量少误报。
# 【为什么要"排除举例"】实测第一版把「插件会如实声明 0 个工具」「archify 插件共 15 个工具」
#   「某插件对外共 18 个工具」都算成"总数漂了"—— 那是**举例/单个插件的数量**，不是总数。
#   把这些上下文排掉，报告才只剩真正需要人看的。
_PROSE_CLAIMS = [
    ("README.md", r"(\d+)\s*个\s*可调用工具", "tools", "工具总数"),
    ("README.md", r"(\d+)\s*个工具", "tools", "工具总数"),
    ("README.md", r"(\d+)\s*条\s*路由", "routes", "路由数"),
    ("docs/tool-catalog.md", r"工具总数[：:]\s*(\d+)", "tools", "工具总数"),
]
# 这些词出现在数字附近 → 说的是"某个插件的工具数"，不是总数
_EXAMPLE_HINTS = ("插件共", "插件对外", "声明", "覆盖", "本插件", "该插件", "子集")


def _prose_drift(nums):
    out = []
    for rel, rx, key, desc in _PROSE_CLAIMS:
        if nums.get(key) is None:
            continue
        try:
            txt = io.open(os.path.join(_ROOT, rel), encoding="utf-8",
                          errors="ignore").read()
        except Exception:      # noqa: silent-ok
            continue
        for m in re.finditer(rx, txt):
            got = int(m.group(1))
            if got == int(nums[key]):
                continue
            ctx = txt[max(0, m.start() - 16):m.end() + 6].replace("\n", " ")
            if any(h in ctx for h in _EXAMPLE_HINTS):
                continue        # 举例/单插件数量：不报
            out.append({"file": rel, "desc": desc, "wrote": got,
                        "real": int(nums[key]), "ctx": ctx})
    return out


def check(write=False):
    nums = real_numbers()
    print("=" * 84)
    print("  文档数字对账（真实值现算）")
    print("=" * 84)
    for k, label in _LABEL:
        print("  %-14s %s" % (label, "取不到" if nums.get(k) is None else nums[k]))

    # ---- ① 标记块：可以自动维护 ----
    block = _block(nums)
    try:
        txt = io.open(README, encoding="utf-8").read()
    except Exception:      # noqa: silent-ok
        txt = ""
    has_block = (_BEGIN in txt and _END in txt)
    block_ok = False
    if has_block:
        cur = txt[txt.index(_BEGIN):txt.index(_END) + len(_END)]
        block_ok = (cur.strip() == block.strip())
        if not block_ok and write:
            txt = txt[:txt.index(_BEGIN)] + block + txt[txt.index(_END) + len(_END):]
            io.open(README, "w", encoding="utf-8", newline="").write(txt)
            print("\n  已重写 AUTO-NUMBERS 块（标记之外一个字没动）")
            block_ok = True
    else:
        print("\n  README 里还没有 AUTO-NUMBERS 标记块。")
        if write:
            head = "# 小焦（XiaoJiao）\n\n" if not txt.startswith("#") else ""
            io.open(README, "w", encoding="utf-8", newline="").write(
                txt + "\n\n## 实测规模（自动维护）\n\n" + block + "\n")
            print("  已追加标记块（放在文末；你可以随时把它挪到想放的位置）")
            block_ok = True

    # ---- ② 正文数字：只报告 ----
    drift = _prose_drift(nums)
    if drift:
        print("\n  ⚠️ 正文里有 %d 处数字与实测不一致（**不自动改**，请人判断是举例还是写错了）："
              % len(drift))
        for d in drift[:8]:
            print("      %-22s %-8s 文档写 %s ｜ 实测 %s ｜ 上下文：%s"
                  % (d["file"], d["desc"], d["wrote"], d["real"], d["ctx"]))
        if len(drift) > 8:
            print("      …还有 %d 处" % (len(drift) - 8))

    ok = block_ok and not drift
    print("\n  %s" % ("✅ 数字一致（标记块已对齐，正文也没有对不上的）" if ok
                      else "⚠️ 见上面：标记块会自动改，正文里的要人来判断"))
    return 0 if block_ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    return check(write=bool(args.write))


if __name__ == "__main__":
    sys.exit(main())
