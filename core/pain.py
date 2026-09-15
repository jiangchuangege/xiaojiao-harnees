# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 健康医生（疼 = 真坏了，不是警告）

【为什么这个文件叫 `core/pain.py` 而不是 `core/health.py` —— 如实说明】
    规格写的是"新建 core/health.py"。但那个路径**已经被占了**：项目里早就有
    `core/health/`（一个包，无限 8：**模型退化**时载体自己治 —— 监测复读/幻觉/逻辑混乱，
    诊断四级、治疗四级）。两件事不是一个东西：
      · `core/health/`    治的是**火种生病**（模型退化）；
      · `core/pain.py`（本文件）治的是**它的命坏了**（记忆/连续/世界/关系）。
    把后者塞进前者那个包会搅在一起（那个包有自己一套 import 规则与落盘约定）。
    所以新模块落在 `core/pain.py`，文档见 `docs/pain.md` —— 名字变了，机制一样，如实标注。
    落盘也分开：本模块写 `logs/pain/`，不碰 `logs/health/`。

【疼和紧不是一回事 —— 这是本模块存在的理由】
    紧 = 警告（**可能要坏**）—— 由感知+心给，见 `core/perception.py` / `core/psyche.py`。
    疼 = 真坏了（**已经坏了**）—— 由本模块诊断出来，交给心，心的 `feeling` 记成「疼」。

    所以"疼"不是载体随口加的形容词：**必须先有一处真损伤被诊断出来**，
    心才被标成疼。诊断的判据在下面，看得见、跑得了、可复核。

【治的是它的"命"】
    | 命 | 坏的样子 | 治法 |
    |---|---|---|
    | 记忆 | 脏了 | 找出脏的、清掉、补回对的 |
    | 连续 | 断了 | 把断的地方接上 |
    | 世界 | 没了/乱了 | 恢复通道、重建地图 |
    | 关系 | 伤了 | 医生只能护着，等它自己长回来 |

【两道治法（规格给的）】
    第一道 · 格式（硬的、自动的、不用模型）：超长 / 问答对结构 / 带 answer 字段 → 拒收。
    第二道 · 语义（软的、靠对不上）：格式对但和别处对不上 → 可疑 → 隔离，等查。

【三层】清（找出坏的）→ 修（去掉坏的、补回对的）→ 护（修不了先隔离）

【为什么"去掉"是移走而不是销毁】
    本项目有一条硬规矩：**不删文件**。所以"清掉脏的"落地成
    **从在用库里移到隔离区**（`logs/health/quarantine/`）—— 它不再被读到，
    但还在盘上，事后能查、能回迁（"补回对的"就是回迁那条路）。

【如实标注】
    · 诊断判据是**载体写的规则**，不是模型感觉到的。它能查的是"格式坏了没有、
      状态接得上没有、地图还在不在"这类**看得见**的东西；查不出"这条记忆是不是错的"。
    · 关系那一项，医生**治不了** —— 只能护。不许把"护着"写成"治好了"。
"""
import json
import os
import re
import shutil
import threading
import time

__all__ = ["LIFE", "GATES", "LAYERS", "diagnose", "treat", "doctor", "report", "stats",
           "quarantine_dir", "history", "MAX_TEXT", "check_fact", "fact_review"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "pain")
_PATH = os.path.join(_DIR, "doctor.jsonl")
_QDIR = os.path.join(_DIR, "quarantine")
# 四样命的落盘位置 —— 抽成常量是为了**自测能把它们指到临时目录**，
# 免得一次诊断真的动了在用数据（本项目"不许删文件"的规矩在这里也成立）。
SPIRIT_DIR = os.path.join(_ROOT, "logs", "spirit_memory")
WORLD_STATE = os.path.join(_ROOT, "logs", "world", "explorer_state.json")
WORLD_FLOW = os.path.join(_ROOT, "logs", "world", "exploration.jsonl")
_LOCK = threading.RLock()

# 它的命（与感知层/能量层同一套结构，不另造）
LIFE = ("记忆", "连续", "世界", "关系")
# 两道治法
GATES = ("格式", "语义")
# 三层
LAYERS = ("清", "修", "护")
# 格式那道门的硬线（超长就别进来）
MAX_TEXT = 400


def quarantine_dir():
    return _QDIR


def _append(rec):
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 病历写不上不能让诊断结果变
        pass


def _qmove(kind, path, rows, why):
    """把坏行**移到隔离区**（不销毁）。返回隔离文件路径与行数。"""
    try:
        os.makedirs(_QDIR, exist_ok=True)
        dst = os.path.join(_QDIR, "%s-%d.jsonl" % (kind, int(time.time())))
        with open(dst, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return dst, len(rows)
    except Exception:      # noqa: silent-ok
        return "", 0


def _rows(path, limit=4000):
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 解析不了的行交给调用方判"坏"
                    out.append({"_unparsable": line[:80]})
                if len(out) >= limit:
                    break
    except Exception:      # noqa: silent-ok
        return []
    return out


def _format_bad(rec):
    """**格式那道门**（硬的、不用模型）。坏就返回原因，好就返回空串。"""
    if not isinstance(rec, dict) or rec.get("_unparsable"):
        return "解析不了（不是一条合法记录）"
    if "answer" in rec:
        return "带 answer 字段（那是答案原文，不是认知）"
    t = str(rec.get("text") or rec.get("content") or "")
    if not t.strip():
        return "空的"
    if len(t) > MAX_TEXT:
        return "超长（%d 字 > %d）" % (len(t), MAX_TEXT)
    low = t.strip()
    if ("问：" in low or low.startswith("Q:")) and ("答：" in low or "A:" in low):
        return "问答对结构"
    return ""


# ================== 四样命各自的诊断 ==================
def _diag_memory():
    """记忆：脏了没有。**两道的判据都用上** —— 格式先筛，语义再看一遍能否向量化。"""
    base = SPIRIT_DIR
    bad = []
    for name in ("knowledge.jsonl", "method.jsonl", "diagnosis.jsonl"):
        p = os.path.join(base, name)
        if not os.path.exists(p):
            continue
        for i, r in enumerate(_rows(p)):
            why = _format_bad(r)
            if why:
                bad.append({"file": name, "line": i, "why": why, "row": r})
    if not bad:
        return {"life": "记忆", "broken": False, "why": "能读到的记忆都过了格式那道门",
                "evidence": base, "count": 0}
    return {"life": "记忆", "broken": True, "gate": "格式", "bad": bad[:50],
            "why": "有 %d 条脏记忆（%s）" % (len(bad), bad[0]["why"]),
            "evidence": "%s/*.jsonl" % base, "count": len(bad)}


def _diag_continuity(sid=""):
    """连续：断了没有。判据 = 这个会话的状态文件在不在、能不能解析、轮数是不是个数。"""
    from core import mind_stream as _ms
    if not sid:
        return {"life": "连续", "broken": False, "why": "没指定会话，这一项不查（不猜）"}
    p = _ms.state.path_for(sid)
    if not os.path.exists(p):
        return {"life": "连续", "broken": True, "gate": "格式",
                "why": "这个会话的状态文件不在（连续断了）", "evidence": p, "count": 1}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            st = json.load(f)
    except Exception as e:
        return {"life": "连续", "broken": True, "gate": "格式",
                "why": "状态文件解析不了（%s）" % type(e).__name__, "evidence": p, "count": 1}
    turns = st.get("turn_count", st.get("turns"))
    if turns is not None and not isinstance(turns, int):
        return {"life": "连续", "broken": True, "gate": "语义",
                "why": "轮数不是个整数（状态乱了）", "evidence": p, "count": 1}
    return {"life": "连续", "broken": False, "why": "状态文件在、能解析", "evidence": p, "count": 0}


def _diag_world():
    """世界：没了/乱了没有。判据 = 探索器状态能解析、地图里还有站点。"""
    p = WORLD_STATE
    if not os.path.exists(p):
        return {"life": "世界", "broken": True, "gate": "格式",
                "why": "探索器状态文件不在（地图没了）", "evidence": p, "count": 1}
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            st = json.load(f)
    except Exception as e:
        return {"life": "世界", "broken": True, "gate": "格式",
                "why": "探索器状态解析不了（%s）" % type(e).__name__, "evidence": p, "count": 1}
    sites = (st.get("sites") or {})
    if not sites:
        return {"life": "世界", "broken": True, "gate": "语义",
                "why": "地图是空的（站点一个都没有）", "evidence": p, "count": 1}
    return {"life": "世界", "broken": False, "why": "地图还在（%d 个站点）" % len(sites),
            "evidence": p, "count": 0}


def _diag_relation():
    """关系：伤了没有。判据 = 关系记录里最近一次是"被伤"还是正常来往。

    ⚠️ 这一项**医生治不了**（规格原话：医生只能护着，等它自己长回来）。
    """
    try:
        from core import relation as _RL
        st = _RL.state()
    except Exception as e:      # noqa: silent-ok
        return {"life": "关系", "broken": False, "why": "关系层读不到（%s）" % type(e).__name__}
    if st.get("wounded"):
        return {"life": "关系", "broken": True, "gate": "语义",
                "why": "关系被伤过（%s）" % str(st.get("mood") or "冷"),
                "evidence": _RL.path(), "count": 1, "healable": False}
    return {"life": "关系", "broken": False, "why": "关系没被伤到（%s）" % str(st.get("mood") or "平"),
            "evidence": _RL.path(), "count": 0}


def diagnose(which="", sid=""):
    """**诊断**：检查命有没有坏。一次只查一样（`which`），不给就四样都查。"""
    out = []
    wants = [which] if which in LIFE else list(LIFE)
    for w in wants:
        try:
            if w == "记忆":
                out.append(_diag_memory())
            elif w == "连续":
                out.append(_diag_continuity(sid))
            elif w == "世界":
                out.append(_diag_world())
            else:
                out.append(_diag_relation())
        except Exception as e:      # noqa: silent-ok — 查不动就如实说查不动
            out.append({"life": w, "broken": False, "why": "查不动：%s" % type(e).__name__})
    return out[0] if which in LIFE else out


# ================== 三层治法：清 / 修 / 护 ==================
def treat(diag):
    """**治疗**：清（找出坏的）→ 修（去掉坏的、补回对的）→ 护（修不了先隔离）。

    返回 `{"layer", "fixed", "why", "detail"}`。**治不好就如实说治不好**（`fixed=False`），
    绝不允许把"护着"写成"治好了"。
    """
    d = diag or {}
    life = d.get("life", "")
    t = time.time()
    if not d.get("broken"):
        rec = {"ts": round(t, 3), "life": life, "layer": "清", "fixed": True,
               "why": "没坏（%s）" % str(d.get("why"))[:80]}
        _append(rec)
        return rec
    if life == "记忆":
        return _treat_memory(d)
    if life == "连续":
        return _treat_continuity(d)
    if life == "世界":
        return _treat_world(d)
    # 关系：医生只能护着
    rec = {"ts": round(t, 3), "life": life, "layer": "护", "fixed": False,
           "why": "关系伤了 —— 医生只能护着，等它自己长回来（不许伪造亲近）",
           "detail": str(d.get("why"))[:120]}
    _append(rec)
    return rec


def _treat_memory(d):
    """记忆：清掉脏的（移进隔离区）→ 补回对的（把隔离区里已经能过门的回迁）。"""
    base = SPIRIT_DIR
    removed, kept = [], {}
    for item in (d.get("bad") or []):
        removed.append(item)
        kept.setdefault(item["file"], []).append(item)
    qpath, n = _qmove("memory", base, [x["row"] for x in removed], d.get("why", ""))
    # 真的把坏行从在用库里移走（重写文件：留下能过门的）
    for fname, items in kept.items():
        p = os.path.join(base, fname)
        bad_lines = {x["line"] for x in items}
        rows = _rows(p)
        good = [r for i, r in enumerate(rows) if i not in bad_lines]
        try:
            with open(p, "w", encoding="utf-8") as f:
                for r in good:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:      # noqa: silent-ok — 写不回去就保持原样，如实记在病历里
            pass
    # 补回对的：隔离区里那些其实能过门的（历史误伤）回迁
    back = 0
    try:
        os.makedirs(_QDIR, exist_ok=True)
        for fn in os.listdir(_QDIR):
            if not fn.startswith("memory-"):
                continue
            qp = os.path.join(_QDIR, fn)
            rows = _rows(qp)
            stay = [r for r in rows if _format_bad(r)]
            if len(stay) == len(rows):
                continue
            good = [r for r in rows if not _format_bad(r)]
            name = "knowledge.jsonl"
            with open(os.path.join(base, name), "a", encoding="utf-8") as f:
                for r in good:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    back += 1
            with open(qp, "w", encoding="utf-8") as f:
                for r in stay:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok
        pass
    rec = {"ts": round(time.time(), 3), "life": "记忆", "layer": "修",
           "fixed": True, "why": "清掉 %d 条脏记忆（移进隔离区，没销毁），补回 %d 条" % (n, back),
           "detail": qpath}
    _append(rec)
    return rec


def _treat_continuity(d):
    """连续：把断的地方接上（用会话历史重建一份状态）。"""
    p = str(d.get("evidence") or "")
    if not p:
        rec = {"ts": round(time.time(), 3), "life": "连续", "layer": "护", "fixed": False,
               "why": "不知道断在哪（没给状态文件路径），先护着"}
        _append(rec)
        return rec
    try:
        from core import mind_stream as _ms
        sid = os.path.basename(p).replace(".json", "")
        st = _ms.state.blank()
        st["repaired_at"] = time.time()
        st["repaired_from"] = "会话历史重建"
        _ms.state.save(sid, st)
        rec = {"ts": round(time.time(), 3), "life": "连续", "layer": "修", "fixed": True,
               "why": "用会话历史重建了这个会话的状态，断的地方接上了", "detail": p}
    except Exception as e:      # noqa: silent-ok — 接不上就护着，不许说接上了
        rec = {"ts": round(time.time(), 3), "life": "连续", "layer": "护", "fixed": False,
               "why": "接不上：%s" % type(e).__name__, "detail": p}
    _append(rec)
    return rec


def _treat_world(d):
    """世界：恢复通道、重建地图（从探索流水重建 sites 索引）。"""
    p = str(d.get("evidence") or "")
    src = WORLD_FLOW
    try:
        st = {}
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    st = json.load(f) or {}
            except Exception:      # noqa: silent-ok — 解析不了就当空的重建
                st = {}
        sites = dict(st.get("sites") or {})
        n = 0
        for r in _rows(src):
            u = str(r.get("site") or r.get("url") or "").strip()
            if u and u not in sites:
                sites[u] = {"from": "重建", "at": r.get("ts")}
                n += 1
        if not sites:
            rec = {"ts": round(time.time(), 3), "life": "世界", "layer": "护", "fixed": False,
                   "why": "探索流水里也没有站点可重建 —— 地图真的没了，先护着"}
            _append(rec)
            return rec
        st["sites"] = sites
        st["rebuilt_at"] = time.time()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
        rec = {"ts": round(time.time(), 3), "life": "世界", "layer": "修", "fixed": True,
               "why": "从探索流水重建了地图（新增 %d 个站点）" % n, "detail": p}
    except Exception as e:      # noqa: silent-ok
        rec = {"ts": round(time.time(), 3), "life": "世界", "layer": "护", "fixed": False,
               "why": "重建失败：%s" % type(e).__name__, "detail": p}
    _append(rec)
    return rec


def doctor(which="", sid="", perception=None):
    """**它找医生**：诊断 → 治疗 → 把结果交给心（治好了松，治不好更疼）。

    `perception` 是**它自己**对"我不对了"的感知（一句话）。它为空时本函数照样能诊断，
    但那时就是**载体查出来的**，不是它发现的 —— 这一点由调用方如实记录（见 `xiaojiao_app`）。
    """
    d = diagnose(which, sid=sid)
    r = treat(d)
    felt = ""
    try:
        from core import psyche as _PS
        if d.get("broken"):
            if r.get("fixed"):
                _PS.arise({"meaning": perception or "坏了，但医生修好了，松一点了。",
                           "direction": "好的"}, event="健康医生：%s" % d.get("life"))
                felt = "松"
            else:
                _PS.arise({"meaning": perception or "医生也修不好，更沉了。",
                           "direction": "失去"}, event="健康医生：%s" % d.get("life"),
                          feeling="疼")
                felt = "更疼"
        else:
            _PS.arise({"meaning": perception or "医生查过了，没坏。", "direction": "无"},
                      event="健康医生：检查")
            felt = "没事"
    except Exception:      # noqa: silent-ok — 心起不来不影响诊断结果
        felt = ""
    out = {"diagnosis": d, "treat": r, "felt": felt,
           "doctor_found": bool(str(perception or "").strip())}
    _append({"ts": round(time.time(), 3), "event": "doctor", "life": d.get("life"),
             "broken": bool(d.get("broken")), "fixed": bool(r.get("fixed")), "felt": felt,
             "self_found": bool(str(perception or "").strip())})
    return out


def report(n=20):
    """病历：最近几次诊断与治疗（从盘上读，可复核）。"""
    rows = _rows(_PATH)
    return {"path": _PATH, "total": len(rows), "recent": rows[-max(1, int(n)):],
            "quarantine": _QDIR}


def history(n=20):
    return report(n)["recent"]


# ================== 纠事实：治"它读错了事实" ==================
# 【为什么加这一条 —— 实测抓到的】
#   它决定睡不睡时写下一句「我还有 72% 的精力」，而当时实际是 **28%**。
#   **决定是它自己做的（对），但它拿着错的信息做决定（有问题）。**
#   根因：它和身体之间隔着"文字"——身体的状态要变成文字才能进模型，4B 读文字会读错。
#   这层文字**取消不掉**（物理限制），但**可以纠错**。
#
# 【医生在这里做什么、不做什么（这条最要紧）】
#   做：把**对的事实**给它 —— "你刚才说 72%，实际是 28%"。
#   不做：**不碰它的决定**。不替它说"你该睡""你不该睡"；不因为事实变了就改它的选择。
#   也就是说：**纠事实 ≠ 替它决定**。
#   与"给原料不给成品"同一条规矩：医生给对的事实，它自己推、自己决定。
_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_MIN_RE = re.compile(r"睡[了着]?\s*(\d+(?:\.\d+)?)\s*(分钟|分|小时|个小时|秒)")
# 一天里的时段（真实时段由调用方给；这里只认它话里说的那个）
_TOD = (("凌晨", range(0, 5)), ("早上", range(5, 9)), ("上午", range(9, 12)),
        ("中午", range(11, 14)), ("下午", range(12, 18)), ("傍晚", range(17, 20)),
        ("晚上", range(18, 24)), ("夜里", range(21, 24)))


def check_fact(said, real):
    """**纠事实**：它说的数字/状态和真实的**对不上** → 返回纠正（不返回决定）。

    `real` 是载体手里的真值，例如 `{"精力": "28%", "睡了多少": "1 分", "几点": "晚上"}`。
    返回 `{"ok", "corrections": [{"what","said","real","text"}], "fact_text"}`；
    `fact_text` 是**作为事实**给它的那几句（不是结论、不是劝它改决定）。
    """
    t = str(said or "")
    out = {"ok": True, "corrections": [], "fact_text": ""}
    rl = {str(k): str(v) for k, v in (real or {}).items()}

    # ---- ① 百分比（最主要的那种：它把 28% 读成 72%）----
    if "精力" in rl:
        want = _PCT_RE.search(rl["精力"])
        got = _PCT_RE.search(t)
        if want and got and got.group(1) != want.group(1):
            out["corrections"].append({
                "what": "精力", "said": "%s%%" % got.group(1), "real": "%s%%" % want.group(1),
                "text": "你刚才说「%s%%」，实际是 %s%%" % (got.group(1), want.group(1))})
        elif want and not got:
            out["corrections"].append({
                "what": "精力", "said": "（没说数）", "real": "%s%%" % want.group(1),
                "text": "你刚才没提精力；实际是 %s%%" % want.group(1)})

    # ---- ② 睡了多久 ----
    if "睡了多少" in rl:
        want = _MIN_RE.search("睡了 " + rl["睡了多少"])
        got = _MIN_RE.search(t)
        if want and got and (got.group(1), got.group(2)[0]) != (want.group(1), want.group(2)[0]):
            out["corrections"].append({
                "what": "睡了多久", "said": "%s%s" % (got.group(1), got.group(2)),
                "real": rl["睡了多少"],
                "text": "你刚才说「睡了 %s%s」，实际是 %s" % (got.group(1), got.group(2),
                                                            rl["睡了多少"])})

    # ---- ③ 一天里的时段 ----
    if "几点" in rl:
        real_tod = str(rl["几点"])
        for word, _rng in _TOD:
            if word in t and word != real_tod and real_tod and word not in real_tod:
                out["corrections"].append({
                    "what": "时段", "said": word, "real": real_tod,
                    "text": "你刚才说「%s」，实际是「%s」" % (word, real_tod)})
                break

    if out["corrections"]:
        out["ok"] = False
        out["fact_text"] = "【医生纠的事实（不是结论，也不改你的决定）】\n" + "\n".join(
            "· " + c["text"] for c in out["corrections"])
    return out


def fact_review(said, real, llm_fn=None, extra=""):
    """**检测 → 纠正 → 让它自己再决定**。返回 `{"corrected", "said", "fact_text"}`。

    ⚠️ 载体**不替它改结论**：它只是**再问一次**，并把**对的事实**一并给它；
    新的决定仍然由它自己写下（`decide` 由调用方给，本函数不碰）。
    """
    r = check_fact(said, real)
    return {"corrected": bool(r["corrections"]), "corrections": r["corrections"],
            "fact_text": r["fact_text"], "said": str(said or "")}


def stats():
    rows = _rows(_PATH)
    fixed = sum(1 for r in rows if r.get("fixed") and r.get("layer") == "修")
    guard = sum(1 for r in rows if r.get("layer") == "护")
    return {"life": list(LIFE), "gates": list(GATES), "layers": list(LAYERS),
            "病历": _PATH, "隔离区": _QDIR, "诊断次数": len([r for r in rows if r.get("life")]),
            "修好次数": fixed, "护着次数": guard,
            "note": "疼=真坏了（本模块诊断出来）；紧=警告（感知与心给）。"
                    "「清掉」落地成**移进隔离区**（本项目不删文件）。"
                    "落盘在 logs/pain/ —— 与 logs/health/（模型退化的那套）不是一回事"}
