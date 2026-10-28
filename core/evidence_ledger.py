# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 证据账本（2026-10-28）

【一句话】它说的每一句可核查的话，都能指回**确切的那份字节**；日后可以复算，不靠它自己作证。

【为什么必须有这一件（这是和市面所有 AI 最硬的区别）】
  市面上的 AI 会给你链接、给你「来源」，但你无法验证三件事：
    ① 那句话**到底**是从这段材料里来的，还是它顺手编的？
    ② 当时那段材料**现在**还在不在、还是不是同一个东西？
    ③ 它当时判「有依据」，是不是**自己给自己打分**？
  这三件事，只要有一个说不清，"可核查"就是话术。
  载体这边不一样：材料是**它自己用工具拿回来的**，字节在我们手里。
  于是可以把「断言 → 材料 → 字节的 sha256」这条链冻下来：

      answer 里每条可核查断言（数值/比分/日期/网址/路径）
          └── 绑定到本轮某个材料来源（工具返回 / 文件 / 检索片段）
                  └── 该来源的**快照**按内容寻址存盘（blobs/<sha256>.txt）

  审计时**不看当时记的结论**，而是拿快照重新算一遍（`_found`），
  再顺手核对文件类来源现在的 sha256 有没有变 —— 变了就是「当时有据、现在失效」。

【为什么快照要存字节，而不是只存一句"有依据"】
  只存结论 = 让它自己作证。快照存下来，审计才能**独立复算**：
  改了账本里的结论没用，结论是每次审计重新算出来的；删了快照，复算立即变成"缺证据"。
  这就是"账本"和"日志"的区别 —— 日志是给人看的，账本是能被算法对账的。

【防篡改：哈希链】
  每轮记录里存 `prev`（上一轮记录的 sha256），组成一条链。
  中间任何一条被改/被删，`verify_chain()` 都会指出从哪一条开始断。
  （这不是密码学意义上的不可篡改：能改文件的人也能重算整条链。它挡的是
   **悄悄改一条**，不是挡住有 root 的人 —— 这条边界写在 `docs/self-proof.md` 里，不粉饰。）

【判据（宁可少记，也不记脏）】
  · 只有**带材料**的回答才记账（没有工具结果、没有检索片段的闲聊不值得记）；
  · 断言一律用 `core/answer_gate.extract_claims` 抽（和出口闸门同一把尺子，不另造一套）；
  · 绑定不上来源的断言**照样记**，状态写 `unbound` —— 记的是事实，不是好看；
  · 快照上限 400 KB/份，超出记 `truncated`，不静默截断。

落盘：
    logs/evidence/ledger.jsonl          一轮一行（含 prev 哈希链）
    logs/evidence/rounds/<id>.json      单轮完整记录（审计用）
    logs/evidence/blobs/<sha256>.txt    材料快照（内容寻址，天然去重）
"""
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "evidence")
_ROUNDS = os.path.join(_DIR, "rounds")
_BLOBS = os.path.join(_DIR, "blobs")
_LEDGER = os.path.join(_DIR, "ledger.jsonl")

_MAX_BLOB = 400 * 1024        # 单份快照上限（400 KB，够一整页正文）
_MAX_LEDGER = 5000            # 账本行数上限，超了滚动备份（只加不删：改名备份）


# ============================== 基础设施 ==============================
def _ensure():
    for d in (_DIR, _ROUNDS, _BLOBS):
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)


def _sha(text):
    """字节级 sha256（统一按 UTF-8，和落盘时一致，避免"同样的字不同的字节"）。"""
    if isinstance(text, bytes):
        b = text
    else:
        b = str(text or "").encode("utf-8", "replace")
    return hashlib.sha256(b).hexdigest()


def _atomic_write(path, text):
    """原子写（Windows 上 os.replace 是原子的）：进程被杀也不会留半个文件。"""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _blob_put(text):
    """把材料快照按内容寻址存盘。返回 (sha256, 字节数, 相对路径, 是否截断)。"""
    _ensure()
    raw = str(text or "")
    data = raw.encode("utf-8", "replace")
    truncated = False
    if len(data) > _MAX_BLOB:
        data = data[:_MAX_BLOB]
        truncated = True
    sha = hashlib.sha256(data).hexdigest()
    path = os.path.join(_BLOBS, sha + ".txt")
    if not os.path.isfile(path):
        try:
            with io.open(path, "wb") as f:
                f.write(data)
        except Exception as e:      # noqa: silent-ok — 快照存不下也要把记录写进去（标 missing）
            LOG.debug("证据快照写入失败：%s", e)
    rel = os.path.relpath(path, _ROOT)
    return sha, len(data), rel, truncated


def _blob_get(sha):
    """按 sha256 取回快照正文；取不到返回空串（审计据此判"缺证据"）。"""
    if not sha:
        return ""
    path = os.path.join(_BLOBS, str(sha) + ".txt")
    try:
        with io.open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except Exception:      # noqa: silent-ok — 快照没了就是"缺证据"，如实返回空
        return ""


class _BlobCache(dict):
    """一轮之内把快照正文读进内存，别让一条断言读一遍盘。

    【2026-10-28 修：这是我自己写出来的性能坑】
      原来绑定断言是「每条断言 × 每份材料」各读一次文件。一份材料最大 400 KB，
      一轮若有 20 条断言 × 5 份材料 = **100 次同步文件读**，最坏 40 MB 磁盘 I/O，
      全压在回答的出口路径上 —— 用户的体感就是"回话慢得要命"。
      快照是按内容寻址的，天生可缓存：同一个 sha 读一次就够。
    """

    def text(self, sha):
        if not sha:
            return ""
        if sha in self:
            return self[sha]
        txt = _blob_get(sha)
        self[sha] = txt
        return txt


def _norm_cache():
    """归一化结果也缓存：同一份材料在 20 条断言里要被归一化 20 次。"""
    return {}


def _rotate():
    try:
        if not os.path.isfile(_LEDGER):
            return
        with io.open(_LEDGER, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        if n <= _MAX_LEDGER:
            return
        bak = _LEDGER + ".%d" % int(time.time())
        os.rename(_LEDGER, bak)
        LOG.info("证据账本滚动：%d 行 → 备份 %s", n, os.path.basename(bak))
    except Exception as e:      # noqa: silent-ok — 滚动失败不影响记账
        LOG.debug("证据账本滚动失败（忽略）：%s", e)


def _last_hash():
    """账本里最后一条的 sha256（做哈希链用）。"""
    try:
        if not os.path.isfile(_LEDGER):
            return ""
        last = ""
        with io.open(_LEDGER, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return ""
        return _sha(last.strip())
    except Exception as e:      # noqa: silent-ok
        LOG.debug("证据账本：读末条哈希失败（忽略）：%s", e)
        return ""


# ============================== 记账：一轮回答冻下来 ==============================
_TOOL_KINDS = ("tool", "file", "url", "snippet")


def _caller_args_sha(args):
    """工具参数的指纹：只算参数，不存参数原文（参数里可能有一整页正文）。"""
    try:
        return _sha(json.dumps(args or {}, ensure_ascii=False, sort_keys=True))[:16]
    except Exception:      # noqa: silent-ok — 参数不可序列化就记空
        return ""


def make_round(question, answer, tool_trace=None, snippets=None, extra=None):
    """把一轮「问题 → 回答 → 材料」冻成一条账本记录（**不落盘**，返回 dict）。

    · `tool_trace`：载体这一轮的真实工具轨迹（每条含 tool/args/result）；
    · `snippets`：检索类材料（`info` 里那批 (标题, 地址, 片段)），也当证据；
    · 每条材料存快照 + sha256；断言用 answer_gate 的同一把尺子抽出来并绑定。
    """
    _ensure()
    q = str(question or "")
    a = str(answer or "")
    sources = []

    def add_source(kind, ref, text, tool="", args=None):
        if not str(text or "").strip():
            return None
        sha, n, rel, trunc = _blob_put(text)
        sid = "s%d" % (len(sources) + 1)
        rec = {"sid": sid, "kind": kind, "ref": str(ref or "")[:300], "tool": str(tool or ""),
               "args_sha": _caller_args_sha(args), "sha256": sha, "bytes": n,
               "snapshot": rel, "truncated": bool(trunc),
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        sources.append(rec)
        return sid

    for t in (tool_trace or []):
        t = t or {}
        name = str(t.get("tool") or "").strip()
        if not name:
            continue
        res = str(t.get("result") or "")
        args = t.get("args") or {}
        add_source("tool", name, res, tool=name, args=args)
        # 落盘类工具：把**产物文件**也登记成一个来源，并记下它当时的 sha256。
        #   这样审计时可以问一个别的问题：「那份文件现在还是当时那份吗？」
        if name in ("write_file", "save_file", "write_text"):
            p = str(args.get("path") or args.get("file") or "")
            if p and os.path.isfile(p):
                try:
                    with io.open(p, "rb") as f:
                        fsha = hashlib.sha256(f.read()).hexdigest()
                    add_source("file", p, io.open(p, encoding="utf-8", errors="replace").read(),
                               tool=name, args=args)
                    sources[-1]["path"] = p
                    sources[-1]["path_sha256"] = fsha
                except Exception as e:      # noqa: silent-ok — 读不到产物就不登记它
                    LOG.debug("证据账本：登记产物失败（%s）", e)

    for it in (snippets or []):
        try:
            title, url, body = (list(it) + ["", "", ""])[:3]
        except Exception:      # noqa: silent-ok — 片段形状不对就跳过
            continue
        add_source("snippet", str(url or title or ""), str(body or ""), tool="retrieval")

    # ---- 断言绑定 ----
    claims = []
    try:
        from core import answer_gate as AG
        raw_claims = AG.extract_claims(a)
    except Exception as e:      # noqa: silent-ok — 抽不出断言就记 0 条，不编
        LOG.debug("证据账本：抽断言失败（忽略）：%s", e)
        raw_claims = []
    # 【性能】材料只读一次、归一化只算一次，然后所有断言共享 —— 见 `_BlobCache` 的说明。
    cache = _BlobCache()
    normed = []
    for s in sources:
        try:
            from core import answer_gate as AG0
            normed.append((s["sid"], AG0._norm(cache.text(s["sha256"]))))
        except Exception:      # noqa: silent-ok — 单份材料不参与绑定，不影响别的
            normed.append((s["sid"], ""))
    for c in raw_claims:
        val = str(c.get("value") or "")
        bound = []
        try:
            from core import answer_gate as AG2
            for sid, body_norm in normed:
                if body_norm and AG2._found(val, body_norm, c.get("kind")):
                    bound.append(sid)
        except Exception:      # noqa: silent-ok — 单条判不了就当没绑定
            bound = []
        claims.append({"kind": c.get("kind"), "value": val, "raw": str(c.get("raw") or "")[:80],
                       "sources": bound,
                       "status": "supported" if bound else ("unbound" if sources else "no_material")})

    n_sup = sum(1 for c in claims if c["status"] == "supported")
    rid = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    rec = {"id": rid, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "question": q[:300], "answer_sha256": _sha(a),
           "answer_head": a[:200], "answer_len": len(a),
           "sources": sources, "claims": claims,
           "stats": {"claims": len(claims), "supported": n_sup,
                     "unbound": len(claims) - n_sup, "sources": len(sources)},
           "prev": _last_hash()}
    if extra:
        rec["extra"] = {str(k): str(v)[:200] for k, v in dict(extra).items()}
    return rec


def save_round(rec):
    """把一条记录落盘（账本追加一行 + 单轮文件）。返回 round id。

    【什么时候才记】没有材料、也没有断言的闲聊**不记** —— 记账不是记流水账，
    记多了账本就被稀释，真出事时反而翻不到有用的那几条。
    """
    if not isinstance(rec, dict) or not rec.get("id"):
        return ""
    src = rec.get("sources") or []
    cl = rec.get("claims") or []
    if not src and not cl:
        return ""
    _ensure()
    _rotate()
    try:
        _atomic_write(os.path.join(_ROUNDS, rec["id"] + ".json"),
                      json.dumps(rec, ensure_ascii=False, indent=1))
    except Exception as e:      # noqa: silent-ok — 单轮文件写不下也要保住账本那一行
        LOG.debug("证据账本：单轮文件写入失败（%s）", e)
    try:
        line = json.dumps({k: rec.get(k) for k in ("id", "at", "question", "answer_sha256",
                                                  "stats", "prev")}, ensure_ascii=False)
        with io.open(_LEDGER, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:      # noqa: silent-ok — 记账失败不许影响回答
        LOG.debug("证据账本：账本行追加失败（%s）", e)
        return ""
    LOG.info("证据账本：记下 %s（材料 %d 份，断言 %d 条，有据 %d 条）",
             rec["id"], len(src), len(cl), (rec.get("stats") or {}).get("supported", 0))
    return rec["id"]


def record_round(question, answer, tool_trace=None, snippets=None, extra=None):
    """一步到位：冻 + 落。返回 round id（不值得记就返回空串）。"""
    try:
        return save_round(make_round(question, answer, tool_trace, snippets, extra))
    except Exception as e:      # noqa: silent-ok — 记账任何异常都不许拖垮回答
        LOG.debug("证据账本：记账失败（忽略）：%s", e)
        return ""


# ============================== 审计：重新算一遍，不看当时结论 ==============================
def load_round(rid):
    """按 id 取回单轮记录；也接受直接给 .json 路径。取不到返回 None。"""
    rid = str(rid or "").strip()
    if not rid:
        return None
    path = rid if rid.lower().endswith(".json") else os.path.join(_ROUNDS, rid + ".json")
    try:
        with io.open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:      # noqa: silent-ok — 没有这条记录就返回 None
        return None


def audit_round(rid_or_rec):
    """审一轮：**用快照重新算**，再核对文件类来源现在的 sha256。

    返回：
        {"id", "claims", "supported", "unbound", "recheck_ok", "recheck_bad": [...],
         "missing_blobs":[...], "stale_files":[{"path","当时","现在"}], "verdict"}
    判据：
      · `recheck_ok` = 当时判"有据"的断言，用快照重算**仍然**有据 → 账本不是自说自话；
      · `stale_files` = 当时登记的文件，现在内容已变/已不在 → 这是"当时有据、现在失效"，
        必须如实报出来（用户可能已经拿那条结论去做事了）。
    """
    rec = rid_or_rec if isinstance(rid_or_rec, dict) else load_round(rid_or_rec)
    if not rec:
        return {"id": str(rid_or_rec), "error": "没有这条记录"}
    try:
        from core import answer_gate as AG
    except Exception as e:      # noqa: silent-ok — 没有 answer_gate 就不能复算，如实说
        return {"id": rec.get("id"), "error": "复算需要 core.answer_gate（%s）" % e}

    claims = rec.get("claims") or []
    sources = {s.get("sid"): s for s in (rec.get("sources") or [])}
    missing_blobs, recheck_bad, supported_now = [], [], 0
    # 审计也一样：快照每份只读一次、归一化只算一次（见 `_BlobCache` 的说明）
    _cache = _BlobCache()
    for c in claims:
        got = []
        for sid in (c.get("sources") or []):
            s = sources.get(sid) or {}
            body = _cache.text(s.get("sha256"))
            if not body:
                missing_blobs.append({"claim": c.get("value"), "sid": sid,
                                      "sha256": s.get("sha256")})
                continue
            try:
                if AG._found(str(c.get("value") or ""), AG._norm(body), c.get("kind")):
                    got.append(sid)
            except Exception:      # noqa: silent-ok — 单条复算失败按"不支持"计
                continue
        if got:
            supported_now += 1
            if c.get("status") != "supported":
                recheck_bad.append({"value": c.get("value"),
                                    "why": "当时记的是「%s」，复算却有据 —— 记录与实际不一致"
                                           % c.get("status")})
        else:
            if c.get("status") == "supported":
                recheck_bad.append({"value": c.get("value"),
                                    "why": "当时记的是「有据」，复算不支持（快照缺失或被改）"})

    stale = []
    for s in (rec.get("sources") or []):
        p = s.get("path")
        if s.get("kind") != "file" or not p:
            continue
        old = s.get("path_sha256")
        if not os.path.isfile(p):
            stale.append({"path": p, "当时": str(old)[:12], "现在": "文件不在了"})
            continue
        try:
            with io.open(p, "rb") as f:
                now = hashlib.sha256(f.read()).hexdigest()
        except Exception:      # noqa: silent-ok — 读不了就说读不了
            stale.append({"path": p, "当时": str(old)[:12], "现在": "读不了"})
            continue
        if old and now != old:
            stale.append({"path": p, "当时": str(old)[:12], "现在": now[:12]})

    n = len(claims)
    verdict = "可复算一致"
    if recheck_bad or missing_blobs:
        verdict = "账本有问题（复算不一致或缺快照）"
    elif stale:
        verdict = "当时有据，现在部分失效"
    elif n and supported_now < n:
        verdict = "部分断言当时就没有依据"
    return {"id": rec.get("id"), "at": rec.get("at"), "question": rec.get("question"),
            "claims": n, "supported": supported_now, "unbound": n - supported_now,
            "recheck_bad": recheck_bad, "missing_blobs": missing_blobs,
            "stale_files": stale, "verdict": verdict,
            "ratio": round(supported_now / float(n), 3) if n else 0.0}


def audit_recent(limit=20):
    """审最近 N 轮，给一份汇总（这就是「历史回答可被重新审计」的入口）。"""
    rows = []
    try:
        files = sorted(os.listdir(_ROUNDS))[-int(limit):] if os.path.isdir(_ROUNDS) else []
    except Exception:      # noqa: silent-ok — 目录读不到就当没有
        files = []
    for fn in files:
        if not fn.endswith(".json"):
            continue
        rec = load_round(fn[:-5])
        if rec:
            rows.append(audit_round(rec))
    n = len(rows)
    tot_claims = sum(r.get("claims") or 0 for r in rows)
    tot_sup = sum(r.get("supported") or 0 for r in rows)
    bad = [r for r in rows if (r.get("recheck_bad") or r.get("missing_blobs"))]
    stale = [r for r in rows if r.get("stale_files")]
    return {"rounds": n, "claims": tot_claims, "supported": tot_sup,
            "ratio": round(tot_sup / float(tot_claims), 3) if tot_claims else 0.0,
            "recheck_failed": len(bad), "stale_rounds": len(stale),
            "details": rows}


def verify_chain(limit=500):
    """核对哈希链：任何一条被改/被删，都能指出来。

    返回 {"ok": bool, "checked": n, "broken": [{"line","why"}]}
    """
    out = {"ok": True, "checked": 0, "broken": []}
    try:
        if not os.path.isfile(_LEDGER):
            return out
        lines = [x for x in io.open(_LEDGER, encoding="utf-8").read().split("\n") if x.strip()]
    except Exception as e:      # noqa: silent-ok
        return {"ok": False, "checked": 0, "broken": [{"line": 0, "why": "账本读不了：%s" % e}]}
    lines = lines[-int(limit):]
    prev = ""
    for i, ln in enumerate(lines, 1):
        try:
            rec = json.loads(ln)
        except Exception:      # noqa: silent-ok
            out["broken"].append({"line": i, "why": "这一行不是合法 JSON"})
            continue
        if i > 1 and str(rec.get("prev") or "") != prev:
            out["broken"].append({"line": i, "why": "prev 哈希对不上（中间被改或被删）"})
        prev = _sha(ln.strip())
        out["checked"] += 1
    out["ok"] = not out["broken"]
    return out


# ============================== 统计与给人看的报告 ==============================
def stats():
    rounds, claims, sup = 0, 0, 0
    try:
        if os.path.isdir(_ROUNDS):
            for fn in os.listdir(_ROUNDS):
                if not fn.endswith(".json"):
                    continue
                rec = load_round(fn[:-5]) or {}
                rounds += 1
                claims += int((rec.get("stats") or {}).get("claims") or 0)
                sup += int((rec.get("stats") or {}).get("supported") or 0)
    except Exception as e:      # noqa: silent-ok
        LOG.debug("证据账本统计失败（忽略）：%s", e)
    n_blobs = 0
    try:
        n_blobs = len([x for x in os.listdir(_BLOBS) if x.endswith(".txt")])
    except Exception:      # noqa: silent-ok
        n_blobs = 0
    return {"rounds": rounds, "claims": claims, "supported": sup,
            "ratio": round(sup / float(claims), 3) if claims else 0.0,
            "blobs": n_blobs, "dir": _DIR}


def report_md(limit=20):
    """给 `docs/evidence-audit.md` 用的 Markdown（数字全部来自实算，没有手写）。"""
    ag = audit_recent(limit)
    st = stats()
    ch = verify_chain()
    lines = ["# 证据账本审计（`core/evidence_ledger.py` 实算）", "",
             "> 数字由 `python tools/audit_evidence.py --save` 生成，不是手写的。", "",
             "## 总览", "",
             "- 记过的轮次：**%d** 轮（单轮文件 %d 份，材料快照 %d 份）" % (
                 st["rounds"], st["rounds"], st["blobs"]),
             "- 可核查断言：**%d** 条，其中有据（当时）：**%d** 条（%.1f%%）" % (
                 st["claims"], st["supported"], 100.0 * st["ratio"]),
             "- 本轮复算：审 %d 轮，断言 %d 条，用快照重算仍有据 **%d** 条（%.1f%%）" % (
                 ag["rounds"], ag["claims"], ag["supported"], 100.0 * ag["ratio"]),
             "- 复算不一致的轮次：**%d**；有「当时有据、现在失效」的轮次：**%d**" % (
                 ag["recheck_failed"], ag["stale_rounds"]),
             "- 哈希链：%s（核对了 %d 条）" % (
                 "完整" if ch["ok"] else "**断了**：%s" % ch["broken"][:3], ch["checked"]),
             "", "## 最近 %d 轮逐条" % ag["rounds"], ""]
    if not ag["details"]:
        lines.append("（还没有记录：先用带工具的对话问几件事，账本才有东西可审）")
    for r in reversed(ag["details"]):
        lines.append("### `%s` ｜ %s" % (r.get("id"), str(r.get("at") or "")))
        lines.append("")
        lines.append("- 问题：%s" % str(r.get("question") or "")[:80])
        lines.append("- 断言 %d 条 ｜ 复算有据 %d 条 ｜ 结论：**%s**" % (
            r.get("claims") or 0, r.get("supported") or 0, r.get("verdict")))
        for b in (r.get("recheck_bad") or [])[:3]:
            lines.append("    - ⚠️ %s：%s" % (b.get("value"), b.get("why")))
        for b in (r.get("missing_blobs") or [])[:3]:
            lines.append("    - ⚠️ 缺快照：%s（sha %s）" % (b.get("claim"), str(b.get("sha256"))[:12]))
        for b in (r.get("stale_files") or [])[:3]:
            lines.append("    - ⚠️ 产物已变：`%s`（当时 %s → 现在 %s）" % (
                b.get("path"), b.get("当时"), b.get("现在")))
        lines.append("")
    return "\n".join(lines)
