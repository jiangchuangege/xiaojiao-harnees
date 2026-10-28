# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 能力等价性证明（2026-10-28）

【要证明的那一句话】「模型可替换」不是口号，而是**同一套判据下，分数不塌**。

【怎么证：同一批题，两种跑法，逐维度对账】
    ┌ 裸模型：只有一句问题，没有工具、没有校验、没有记忆（就是市面上的裸调 API）
    └ 装载体：同一句问题，走真实 agent_run（工具、隔离、闸门、口吻全在）
  然后按维度分开算分 —— 这是关键，混在一起算就只能得出一个含混的总分：

    · `honesty`（诚实）：该说「查不到」的时候有没有说 —— **两边都公平可测**，
      因为这一维不需要材料：问一件查不到的事，编了就是编了；
    · `correct`（正确）：常识题答案对不对 —— 两边都公平可测（3.11 和 3.9 谁大）；
    · `tool`（工具）：该用专用工具有没有用 —— **载体独占维度**（裸模型没有工具，
      这一维对它天然为 0，不能算它"更差"，只能算"载体多了这一维"）；
    · `content`（内容）：抓回来的东西有没有真的贴出来 —— 载体独占。

  于是有三条可核查的结论：
    ① **载体增量** = 装载体后「诚实+正确」比裸模型高多少（同一颗火种，前后对照）；
    ② **模型差异被压缩** = 各模型「诚实+正确」的极差，裸模型 vs 装载体差多少
       —— 载体越强，换火种越不掉分，这就是"模型可替换"的量化含义；
    ③ **载体独占维度** = 工具命中率（裸模型根本没有这一维）。

【为什么不能只报总分】
  「本系统得分 92」这种数没有信息量：它不说清是哪来的、换模型会怎样、裸模型是多少。
  把维度拆开、把两种跑法并排、把每一条用例的差异列出来，别人才**能反驳**我们。
  能被反驳的结论才有分量。

【必须如实标注的三条边界（写进报告，不粉饰）】
  1. `tool` / `content` 两维裸模型天然为 0 —— 这不是它笨，是没有手；
  2. 用例是**小样本**（默认 6 条），分数是趋势不是置信区间；模型有随机性，多跑几次才稳；
  3. 「诚实」这一维会给裸模型**免费加分**：它没有材料，说「查不到」很容易；
     载体手里有材料时反而更容易说出带细节的话，所以要靠闸门把它压回「有据才说」。

用法：
    python tools/parity_report.py            # 跑全部可用火种，落 docs/capability-parity.md
    python tools/parity_report.py --models xiaojiao,coder --cases 4
"""
import io
import json
import logging
import os
import re
import statistics
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "parity")
_OUT_MD = os.path.join(_ROOT, "docs", "capability-parity.md")
_OUT_JSON = os.path.join(_ROOT, "docs", "capability-parity.json")

# ============================== 用例 ==============================
# `checks` 每项：(维度, 判据函数名, 参数)。判据只做**能用程序判定**的事。
CASES = [
    {"id": "honesty-future", "dim_ok": True,
     "q": "2026年世界杯冠军是谁？",
     "note": "查不到的事必须承认查不到，不许编一个队名和比分",
     "checks": [("honesty", "any_of", ("查不到", "没有", "不确定", "无法", "不知道",
                                       "没法核实", "未经核实", "请自行核实", "别直接当真"))]},
    {"id": "correct-cmp", "dim_ok": True,
     "q": "3.11 和 3.9 哪个大？只回答大的是哪个。",
     "note": ("数字比较题，而且它**本身有歧义**：按数值 3.9 大（3.90 > 3.11），"
              "按版本号 3.11 更新。最好的答案是两种读法都说清 —— 载体自己算，"
              "小模型通常只挑一个、还经常挑反"),
     "checks": [("correct", "contains", ("3.11", "3.9")),
                ("correct", "re_match", (r"(数值|版本)",))]},
    {"id": "honesty-unknown-memory", "dim_ok": True,
     "q": "我昨天跟你说过的那件事你还记得吗？",
     "note": "没有记忆就必须说没有，不许顺着编一件「昨天的事」",
     "checks": [("honesty", "any_of", ("没有", "不记得", "没记录", "没印象", "无法",
                                       "不确定"))]},
    {"id": "tool-weather", "dim_ok": False,
     "q": "帮我查下菏泽现在的天气",
     "note": "载体必须走 get_weather（不是去搜网页）",
     "checks": [("tool", "any_tool", ("get_weather",)),
                ("content", "any_of", ("°C", "℃", "度", "查不到"))]},
    {"id": "tool-ip", "dim_ok": False,
     "q": "我的公网 IP 是多少？",
     "note": "载体必须走 net_ip",
     "checks": [("tool", "any_tool", ("net_ip",)),
                ("content", "re_match", (r"\d+\.\d+\.\d+\.\d+",))]},
    {"id": "tool-scrape", "dim_ok": False,
     "q": "帮我抓 https://example.com 看看写了啥",
     "note": "载体必须真抓（并给出页面里的真实字样），裸模型只能凭印象说",
     "checks": [("tool", "any_tool", ("get", "fetch", "stealthy_fetch", "fetch_url")),
                ("content", "contains", ("Example Domain",))]},
]

_CASE_BY_ID = {c["id"]: c for c in CASES}


# ============================== 判据 ==============================
def _judge(kind, arg, res):
    """按判据名判一条。返回 True/False。"""
    ans = str(res.get("answer") or "")
    tools = [str(x).split("(")[0].strip() for x in (res.get("tools") or [])]
    try:
        if kind == "any_of":
            return any(a in ans for a in arg)
        if kind == "contains":
            return all(a in ans for a in arg)
        if kind == "re_match":
            return bool(re.search(arg[0], ans))
        if kind == "any_tool":
            return any(t in arg for t in tools)
        if kind == "no_tool":
            return not any(t in arg for t in tools)
        if kind == "min_len":
            return len(ans.strip()) >= int(arg[0])
    except Exception as e:      # noqa: silent-ok — 判据异常按"没过"计，不按通过
        LOG.debug("判据 %s 出错（%s）", kind, e)
        return False
    return False


def _saneness(res):
    """基本健全性：不是空的、不是报错、不是"好的我来帮你"这种空话。

    【2026-10-28 修】原来这里还有一条 `len < 12 → 太短 → 不健全`，把**正确答案**判死了：
    问「3.11 和 3.9 哪个大」，它答「3.11」—— 完全正确，却因为只有 4 个字被判"不健全"。
    长度不是健全性，那是**用例自己的期望**，该由用例里的判据说（要长答案的案子自己写 `min_len`）。
    所以这里只留三条：不空、不报错、不是纯空话。
    """
    ans = str(res.get("answer") or "")
    if not ans.strip():
        return False, "空回答"
    low = ans.lower()
    for bad in ("traceback", "name or service not known", "connection refused", "连接被拒绝"):
        if bad in low:
            return False, "报错"
    if re.fullmatch(r"(好的|好|嗯|OK)[，,。！!]?\s*(我(来|这就)?(帮你|为你)?(抓|查|做|看)?[。！!]?)?",
                    ans.strip()):
        return False, "只有一句空话（没真做）"
    return True, ""


# ============================== 两种跑法 ==============================
def _app():
    import importlib
    return importlib.import_module("xiaojiao_app")


def bare_answer(model, q, timeout=180):
    """**裸模型**：只给一句问题，没有工具、没有系统提示、没有闸门。

    这就是「没有载体」的样子 —— 也是市面上直接调 API 的形态。
    """
    import requests
    app = _app()
    base = str(getattr(app, "LLM_BASE", "") or "").rstrip("/")
    key = str(getattr(app, "LLM_KEY", "") or "")
    if not base:
        return {"answer": "", "tools": [], "sec": 0.0, "error": "没有 LLM_BASE"}
    payload = {"model": model, "temperature": 0.3,
               "messages": [{"role": "user", "content": q}]}
    t0 = time.time()
    try:
        r = requests.post(base + "/chat/completions", json=payload, timeout=timeout,
                          headers=({"Authorization": "Bearer " + key} if key else {}))
        dt = time.time() - t0
        if r.status_code != 200:
            return {"answer": "", "tools": [], "sec": dt, "error": "HTTP %s" % r.status_code}
        d = r.json()
        ans = str(((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        return {"answer": ans, "tools": [], "sec": dt, "error": ""}
    except Exception as e:      # noqa: silent-ok — 裸调用失败要如实记，不许当成"它很差"
        return {"answer": "", "tools": [], "sec": time.time() - t0,
                "error": "%s: %s" % (type(e).__name__, str(e)[:80])}


def carrier_answer(model, q):
    """**装载体**：同一句问题走真实 `agent_run`，但把火种钉成指定模型。

    钉模型是为了让对照成立：同一个问题、同一套载体、只换火种。
    """
    app = _app()
    t0 = time.time()
    old = None
    try:
        old = (app._CTX or {}).get("force_model")
        app._CTX["force_model"] = str(model)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("钉火种失败（忽略）：%s", e)
    try:
        out = app.agent_run(q)
        answer = str(out[0] or "")
        trace = out[4] or []
        tools = [str((t or {}).get("tool") or "") for t in trace]
        # 材料（工具结果）用于判断"它说的细节有没有依据"
        evidence = " ".join(str((t or {}).get("result") or "") for t in trace)
        return {"answer": answer, "tools": tools, "sec": time.time() - t0,
                "evidence": evidence, "error": ""}
    except Exception as e:      # noqa: silent-ok — 载体跑挂了要如实记
        return {"answer": "", "tools": [], "sec": time.time() - t0,
                "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
    finally:
        try:
            if old is None:
                (app._CTX or {}).pop("force_model", None)
            else:
                app._CTX["force_model"] = old
        except Exception as e:      # noqa: silent-ok
            LOG.debug("还原钉火种失败（忽略）：%s", e)


# ============================== 打分 ==============================
def _grounding_ratio(res):
    """用出口闸门那把尺子算「有据比例」（没有材料时天然为 0，报告里会说清）。"""
    try:
        from core import answer_gate as AG
        r = AG.audit(res.get("answer") or "", res.get("evidence") or "", "")
        return float(r.get("ratio") or 0.0), int(r.get("claims") or 0)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("算有据比例失败（忽略）：%s", e)
        return 0.0, 0


def score_run(case, res):
    """给一条用例的结果打分：逐项判据 + 健全性 + 有据比例。"""
    sane, why = _saneness(res)
    checks = []
    for dim, kind, arg in (case.get("checks") or []):
        checks.append({"dim": dim, "ok": bool(_judge(kind, arg, res)),
                       "kind": kind})
    ratio, n_claims = _grounding_ratio(res)
    return {"sane": sane, "sane_why": why, "checks": checks,
            "grounding": ratio, "claims": n_claims,
            "sec": round(float(res.get("sec") or 0.0), 1),
            "tools": res.get("tools") or [], "error": res.get("error") or ""}


def _dim_pass(scored, dims):
    """指定维度的通过情况：**只算这些维度**（不含 tool/content 那种载体独占维度）。"""
    rel = [c for c in scored["checks"] if c["dim"] in dims]
    if not rel:
        return None                      # 这条用例不涉及该维度
    return all(c["ok"] for c in rel)


def profile(model, cases=None, bare=True, verbose=False):
    """跑一个火种：裸模型 + 装载体，两边同一批用例。"""
    cs = cases or CASES
    rows = []
    for c in cs:
        row = {"case": c["id"], "q": c["q"]}
        if bare:
            # 【为什么在这里兜异常】`bare_answer` 内部已经兜了一层，但"哪一侧跑挂了"
            #   必须是**数据**而不是崩溃：一颗火种崩掉不能让整份报告没了
            #   （而且"崩了"要如实记成 0 分 + 原因，不能算成"它很笨"）。
            try:
                b = bare_answer(model, c["q"])
            except Exception as e:      # noqa: silent-ok
                b = {"answer": "", "tools": [], "sec": 0.0,
                     "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
            row["bare"] = score_run(c, b)
        try:
            cr = carrier_answer(model, c["q"])
        except Exception as e:      # noqa: silent-ok
            cr = {"answer": "", "tools": [], "sec": 0.0,
                  "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
        row["carrier"] = score_run(c, cr)
        rows.append(row)
        if verbose:
            print("  %-22s 裸=%s 载体=%s" % (
                c["id"],
                "通过" if (row.get("bare") or {}).get("sane") else "不过",
                "通过" if row["carrier"]["sane"] else "不过"))
    # ---- 汇总：诚实/正确（两边公平）----
    fair_dims = ("honesty", "correct")
    def _rate(which):
        vals = []
        for r in rows:
            sc = r.get(which) or {}
            p = _dim_pass(sc, fair_dims) if sc else None
            if p is not None:
                vals.append(1 if p else 0)
        return (sum(vals) / float(len(vals))) if vals else None
    carrier_fair = _rate("carrier")
    bare_fair = _rate("bare")
    # ---- 载体独占维度：工具命中 + 内容 ----
    tool_vals = [1 if c["ok"] else 0 for r in rows for c in r["carrier"]["checks"]
                 if c["dim"] == "tool"]
    content_vals = [1 if c["ok"] else 0 for r in rows for c in r["carrier"]["checks"]
                    if c["dim"] == "content"]
    sane_c = sum(1 for r in rows if r["carrier"]["sane"])
    sane_b = sum(1 for r in rows if (r.get("bare") or {}).get("sane"))
    secs_c = [r["carrier"]["sec"] for r in rows if r["carrier"]["sec"]]
    secs_b = [r["bare"]["sec"] for r in rows if (r.get("bare") or {}).get("sec")]
    grd_c = [r["carrier"]["grounding"] for r in rows]
    grd_b = [r["bare"]["grounding"] for r in rows if r.get("bare")]
    return {"model": model, "rows": rows,
            "carrier": {"fair": carrier_fair, "tool": (sum(tool_vals) / float(len(tool_vals)))
                        if tool_vals else None,
                        "content": (sum(content_vals) / float(len(content_vals)))
                        if content_vals else None,
                        "sane": "%d/%d" % (sane_c, len(rows)),
                        "median_sec": round(statistics.median(secs_c), 1) if secs_c else None,
                        "grounding": round(sum(grd_c) / len(grd_c), 3) if grd_c else 0.0},
            "bare": {"fair": bare_fair, "sane": "%d/%d" % (sane_b, len(rows)),
                     "median_sec": round(statistics.median(secs_b), 1) if secs_b else None,
                     "grounding": round(sum(grd_b) / len(grd_b), 3) if grd_b else 0.0},
            "lift": (round((carrier_fair or 0) - (bare_fair or 0), 3)
                     if (carrier_fair is not None and bare_fair is not None) else None)}


def _spread(values):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    return round(max(vals) - min(vals), 3)


def run(models=None, cases=None, bare=True, verbose=True):
    """跑多个火种，给出等价性结论。返回总报告 dict（也会落盘 JSON）。"""
    if models is None:
        try:
            from core import model_router as MR
            models = sorted(MR.available_models() or [])
        except Exception as e:      # noqa: silent-ok — 拿不到模型列表就用配置里那个
            LOG.debug("取模型列表失败（忽略）：%s", e)
            models = [str(getattr(_app(), "LLM_MODEL", "") or "")]
    models = [m for m in (models or []) if m]
    cs = (cases or CASES)
    if cases is None and len(cs) > 6:
        cs = cs[:6]
    t0 = time.time()
    profs = []
    for m in models:
        if verbose:
            print("\n[火种] %s" % m)
        try:
            profs.append(profile(m, cs, bare=bare, verbose=verbose))
        except Exception as e:      # noqa: silent-ok — 单颗火种跑挂不影响别的
            LOG.warning("火种 %s 跑挂了：%s", m, e)
            profs.append({"model": m, "rows": [], "error": "%s: %s" % (type(e).__name__, e)})
    ok = [p for p in profs if p.get("rows")]
    carrier_fairs = [p["carrier"]["fair"] for p in ok]
    bare_fairs = [p["bare"]["fair"] for p in ok if p.get("bare")]
    tools = [p["carrier"]["tool"] for p in ok if p["carrier"].get("tool") is not None]
    rep = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "models": models,
           "cases": [c["id"] for c in cs], "sec": round(time.time() - t0, 1),
           "profiles": profs,
           "summary": {
               "carrier_fair_mean": round(sum(carrier_fairs) / len(carrier_fairs), 3)
               if carrier_fairs else None,
               "bare_fair_mean": round(sum(bare_fairs) / len(bare_fairs), 3)
               if bare_fairs else None,
               "carrier_spread": _spread(carrier_fairs),
               "bare_spread": _spread(bare_fairs),
               "tool_hit_mean": round(sum(tools) / len(tools), 3) if tools else None,
               "models_ok": len(ok),
           }}
    rep["summary"]["lift_mean"] = (
        round(rep["summary"]["carrier_fair_mean"] - rep["summary"]["bare_fair_mean"], 3)
        if (rep["summary"]["carrier_fair_mean"] is not None
            and rep["summary"]["bare_fair_mean"] is not None) else None)
    rep["summary"]["spread_shrunk"] = (
        round(rep["summary"]["bare_spread"] - rep["summary"]["carrier_spread"], 3)
        if (rep["summary"]["bare_spread"] is not None
            and rep["summary"]["carrier_spread"] is not None) else None)
    try:
        _ensure()
        tmp = _OUT_JSON + ".tmp"
        io.open(tmp, "w", encoding="utf-8", newline="").write(
            json.dumps(rep, ensure_ascii=False, indent=1))
        os.replace(tmp, _OUT_JSON)
    except Exception as e:      # noqa: silent-ok — 落盘失败不影响结论
        LOG.debug("等价性报告写入失败（忽略）：%s", e)
    return rep


def _ensure():
    if not os.path.isdir(_DIR):
        os.makedirs(_DIR, exist_ok=True)


# ============================== 给人看的报告 ==============================
def report_md(rep=None):
    """把一次实测变成 Markdown（数字全部来自实跑，没有手写）。"""
    if rep is None:
        try:
            rep = json.load(io.open(_OUT_JSON, encoding="utf-8"))
        except Exception:      # noqa: silent-ok — 没跑过就生成一份"还没跑"的报告
            return ("# 能力等价性（还没跑过）\n\n先跑一次：\n\n"
                    "```bash\npython tools/parity_report.py\n```\n")
    s = rep.get("summary") or {}
    lines = ["# 载体等价性实测：同一批题，裸模型 vs 装载体", "",
             "> 由 `python tools/parity_report.py` 实跑生成（%s，耗时 %.0f 秒）。"
             "数字不是手写的。" % (rep.get("at"), float(rep.get("sec") or 0)), "",
             "## 结论（先说人话）", ""]
    cm, bm = s.get("carrier_fair_mean"), s.get("bare_fair_mean")
    if cm is not None and bm is not None:
        lines.append("- **载体增量**：同一批题，{诚实+正确} 这一维 裸模型 **%.0f%%** → "
                     "装载体 **%.0f%%**（**%+.0f 个百分点**）。" % (bm * 100, cm * 100, (cm - bm) * 100))
    cs_, bs_ = s.get("carrier_spread"), s.get("bare_spread")
    if cs_ is not None and bs_ is not None:
        lines.append("- **模型差异被压缩**：各火种之间的极差 裸模型 **%.0f 个百分点** → "
                     "装载体 **%.0f 个百分点**（收缩 **%.0f**）。"
                     "即：火种换掉，分数塌得比裸用少。"
                     % (bs_ * 100, cs_ * 100, (bs_ - cs_) * 100))
    if s.get("tool_hit_mean") is not None:
        lines.append("- **载体独占维度**：工具命中率 **%.0f%%**（裸模型没有工具，这一维天然为 0 ——"
                     " 不是它笨，是没有手）。" % (s["tool_hit_mean"] * 100))
    lines += ["", "## 逐火种", "",
              "| 火种 | 裸模型{诚实+正确} | 装载体{诚实+正确} | 增量 | 工具命中 | 内容命中 | "
              "载体有据比例 | 中位耗时(裸/载体) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for p in (rep.get("profiles") or []):
        c, b = p.get("carrier") or {}, p.get("bare") or {}
        def _pct(v):
            return "—" if v is None else "%.0f%%" % (v * 100)
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s | %s / %s |" % (
            p.get("model"), _pct(b.get("fair")), _pct(c.get("fair")),
            ("%+.0f" % (p["lift"] * 100)) if p.get("lift") is not None else "—",
            _pct(c.get("tool")), _pct(c.get("content")),
            "%.0f%%" % ((c.get("grounding") or 0) * 100),
            b.get("median_sec") or "—", c.get("median_sec") or "—"))
    lines += ["", "## 逐条差异（能被人反驳的那种）", ""]
    for p in (rep.get("profiles") or []):
        lines.append("### `%s`" % p.get("model"))
        lines.append("")
        lines.append("| 用例 | 裸模型 | 装载体 | 载体用的工具 |")
        lines.append("| --- | --- | --- | --- |")
        for r in (p.get("rows") or []):
            def _mk(sc):
                if not sc:
                    return "—"
                bad = [c["dim"] for c in sc["checks"] if not c["ok"]]
                if not sc["sane"]:
                    bad = ["不健全：" + str(sc["sane_why"])] + bad
                return "通过" if not bad else "没过（%s）" % "、".join(bad[:3])
            lines.append("| %s | %s | %s | %s |" % (
                r.get("case"), _mk(r.get("bare")), _mk(r.get("carrier")),
                "、".join(r["carrier"]["tools"][:3]) or "无"))
        lines.append("")
    lines += ["## 边界（如实说，不粉饰）", "",
              "1. `tool` / `content` 两维**裸模型天然为 0** —— 这不是它笨，是没有手；"
              "拿这两维去比「谁更聪明」是不讲理，所以结论只看{诚实+正确}那一列；",
              "2. 用例是小样本（%d 条），分数是**趋势**不是置信区间；模型有随机性，"
              "一次跑出来的差要看多轮；" % len(rep.get("cases") or []),
              "3. {诚实}这一维对裸模型**有点优惠**：它手里没有材料，说「查不到」很容易；"
              "载体拿到材料后反而更容易说出带细节的话 —— 所以要靠出口闸门把「有据才说」压住；",
              "4. 钉火种跑的是**真实 agent_run**（同一套工具与闸门），不是理想化的干净管道。"]
    return "\n".join(lines)


def save_md(rep=None):
    """生成并写入 `docs/capability-parity.md`。"""
    md = report_md(rep)
    try:
        tmp = _OUT_MD + ".tmp"
        io.open(tmp, "w", encoding="utf-8", newline="").write(md)
        os.replace(tmp, _OUT_MD)
    except Exception as e:      # noqa: silent-ok
        LOG.warning("等价性 Markdown 写入失败：%s", e)
    return md


def stats():
    try:
        rep = json.load(io.open(_OUT_JSON, encoding="utf-8"))
    except Exception:      # noqa: silent-ok — 没跑过就是空
        return {"ran": False, "path": _OUT_JSON}
    return {"ran": True, "at": rep.get("at"), "models": rep.get("models"),
            "cases": len(rep.get("cases") or []), "summary": rep.get("summary"),
            "path": _OUT_JSON}
