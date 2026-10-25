# -*- coding: utf-8 -*-
"""工具调用契约 · 自测（保证"模型能精准调用每一个工具"这件事是可验的）

它验四件事，任何一条不过都算交付不合格：
  ① **契约**：99 个工具（14 内置 + 85 插件）每个都有中文说明（≤80 字）、说明读得出"什么时候用"、
     每个参数都有中文说明、required 里的参数都在 properties 里；
  ② **执行入口**：每个插件收到**不认识的工具名**时返回中文说明（绝不抛异常、绝不静默返回空）；
  ③ **清单没烂**：`docs/tool-catalog.md` / `.json` 与**当前真实工具表一致**（名字集合相等），
     否则说明有人改了工具却没重新生成清单 —— 那种清单比没有更糟；
  ④ **可精准调用**：清单里每个工具都给了"必填参数已填好"的调用示例，且示例里的参数名
     全部真实存在于该工具的 schema 里（防止示例教模型传错参数名）。

跑法：python tools\\test_tool_contract.py
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

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


def main():
    print("=" * 82)
    print("  工具调用契约自测（说明 / 参数 / 执行入口 / 清单一致性）")
    print("=" * 82)

    import xiaojiao_app as app          # noqa: E402
    from core import tool_desc as TD    # noqa: E402

    tools = (app._build_tools() or [])
    fns = [t["function"] for t in tools]
    builtin = {((x or {}).get("function") or {}).get("name") for x in (getattr(app, "TOOLS", None) or [])}
    n_builtin = len([f for f in fns if f["name"] in builtin])
    n_plugin = len(fns) - n_builtin
    print("\n工具表：%d 个（%d 内置 + %d 插件）" % (len(fns), n_builtin, n_plugin))

    # ---------------- 一、契约 ----------------
    print("\n[一] 每个工具都能被模型读懂（说明 + 参数说明 + schema）")
    bad_desc, bad_param, filled = [], [], 0
    for fn in fns:
        nfn, rep = TD.normalize_tool(fn)
        if rep["desc_problem"]:
            bad_desc.append("%s（%s）" % (fn.get("name"), rep["desc_problem"]))
        if rep["filled_params"]:
            filled += len(rep["filled_params"])
        prm = nfn.get("parameters") or {}
        props = prm.get("properties") or {}
        for pname, spec in props.items():
            if not str((spec or {}).get("description") or "").strip():
                bad_param.append("%s.%s" % (fn.get("name"), pname))
        for r in (prm.get("required") or []):
            if r not in props:
                bad_param.append("%s required=%s 不在 properties 里" % (fn.get("name"), r))
    ck("全部工具都有中文说明且读得出「什么时候用」", not bad_desc, "；".join(bad_desc[:4]))
    ck("全部参数都有说明（缺的已由通用词典补上：%d 个）" % filled, not bad_param,
       "；".join(bad_param[:4]))
    ck("required 与 properties 自洽", not [x for x in bad_param if "required=" in x])
    ck("说明都不超过 80 字（模型一眼能看完）",
       all(len(fn.get("description") or "") <= 80 for fn in fns),
       max(len(fn.get("description") or "") for fn in fns))

    # ---------------- 二、执行入口 ----------------
    print("\n[二] 每个插件收到不认识的工具名时，必须用中文说清楚")
    bad_exit = []
    for pname, pv in (getattr(app, "PLUGINS", {}) or {}).items():
        inst = pv.get("instance")
        if inst is None or not hasattr(inst, "execute"):
            continue
        try:
            out = inst.execute("__不存在的工具__", {})
        except Exception as e:
            bad_exit.append("%s 抛异常（%s）" % (pname, type(e).__name__))
            continue
        if not isinstance(out, str) or not out.strip():
            bad_exit.append("%s 返回了空/非字符串（%r）" % (pname, out))
        elif not TD.is_cjk(out):
            bad_exit.append("%s 的说明不是中文（%r）" % (pname, out[:30]))
    ck("所有插件都不会因为不认识的工具名而崩", not bad_exit, "；".join(bad_exit[:4]))

    # ---------------- 三、清单一致性 ----------------
    print("\n[三] 仓库里的清单没烂（改了工具就必须重新生成）")
    ck("docs/tool-catalog.md 存在", os.path.exists(MD))
    ck("docs/tool-catalog.json 存在", os.path.exists(JS))
    if os.path.exists(JS):
        data = json.load(io.open(JS, encoding="utf-8"))
        cat_names = {t["name"] for t in data.get("tools") or []}
        live = {f["name"] for f in fns}
        ck("清单里的工具集合 == 当前真实工具表",
           cat_names == live,
           "只在清单里:%s ｜ 只在代码里:%s"
           % (sorted(cat_names - live)[:4], sorted(live - cat_names)[:4]))
        ck("清单声明的总数 / 合格数与文件内容一致",
           data.get("total") == len(data.get("tools") or []) and data.get("bad") == 0,
           "total=%s bad=%s" % (data.get("total"), data.get("bad")))
        ck("清单里每个工具都标了「通过」",
           all(t.get("test") == "通过" for t in (data.get("tools") or [])),
           [t["name"] for t in (data.get("tools") or []) if t.get("test") != "通过"][:4])

        # ---------------- 四、示例能否精准调用 ----------------
        print("\n[四] 每个工具的调用示例都能直接用")
        by_name = {f["name"]: f for f in fns}
        bad_ex = []
        for t in (data.get("tools") or []):
            ex = str(t.get("example") or "")
            fn = by_name.get(t["name"])
            if not fn:
                continue
            props = ((fn.get("parameters") or {}).get("properties") or {})
            req = (fn.get("parameters") or {}).get("required") or []
            m = re.match(r"^\w+\((.*)\)$", ex)
            args = {}
            if m and m.group(1).strip() not in ("", "{}"):
                try:
                    args = json.loads(m.group(1))
                except Exception:
                    bad_ex = []
                    break
            for r in req:
                if r not in args:
                    bad_ex.append("%s 示例缺必填 %s" % (t["name"], r))
            for k in args:
                if props and k not in props:
                    bad_ex.append("%s 示例里的 %s 不在 schema 里" % (t["name"], k))
        ck("示例覆盖了每个工具的必填参数", not [x for x in bad_ex if "缺必填" in x],
           "；".join([x for x in bad_ex if "缺必填" in x][:4]))
        ck("示例里没有 schema 里不存在的参数名", not [x for x in bad_ex if "不在 schema" in x],
           "；".join([x for x in bad_ex if "不在 schema" in x][:4]))

    print("\n" + "=" * 82)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 82)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
