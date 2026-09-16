# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
"""小焦 · 载体层 · **用户画像库**（关于用户是谁、在乎什么）

【它是什么 —— 第四个库，跟前面三个都不一样】
  · `core/memory_vec.py`    对话记忆：**发生过什么**（全存，原始记录）
  · `core/spirit_memory.py` 精神记忆：**想明白了什么**
  · `core/preference.py`    偏好：**它自己反复起的心**
  · **本模块**             用户画像：**关于用户的特征**（有选择地存）

  前三个都是"它的"，这一个**是关于用户的**。所以必须分开存：
  检索时的分工也不同 —— 问事实走对话记忆，问"我上次说的那个"走画像 + 对话记忆，
  问新问题则把画像当**背景**注入。

【最重要的一条：谁来判断"该记什么"】
  **判据由模型给，存储由载体执行。**
  载体**绝不许**自己去判断"用户喜欢体育" —— 那就是死模板（代码写"关键词含篮球/NBA/湖人
  就记体育"）。为什么不行：
    · 用户随口问一次 ≠ 长期关注
    · 用户帮别人问 ≠ 他自己关注
    · 关键词匹配一定会误判
  而模型能区分"随口问"和"真的关注"、能结合上下文、判断错了还能修正。
  **载体要做的是给它"判断的机会"**（每轮问一句"这一轮有没有关于用户、值得长期记住的"），
  而不是替它判断。

【记录格式（规格给定）】
    {
      "id": "…",
      "ts": 1789…,                       # 载体填
      "kind": "兴趣" | "事实" | "偏好" | "关系",
      "content": "用户关注 NBA 篮球赛事",   # 模型给的一句话
      "source": "模型自己判断",             # **如实标：这不是载体推的**
      "evidence": "用户问了湖人 vs 勇士",    # 模型给的依据（载体照抄，不改写）
      "hit_count": 0                      # 命中一次 +1：用得越多的兴趣越稳
    }

【载体在这一层做的全部事情】（不多做一件）
  1. 追加写盘（原子、只追加）
  2. 命中时把 `hit_count` +1
  3. 把画像作为**事实**渲染给模型（`render()`）—— 渲染时**不加任何结论句**
  4. **不判断、不推断、不补全**：模型说记什么就记什么；模型说不记就一个字都不写
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

__all__ = ["KINDS", "add", "all_records", "recent", "hit", "render", "stats",
           "count", "forget_all", "path", "parse_verdict"]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, "logs", "psyche")
_PATH = os.path.join(_DIR, "user_profile.jsonl")
_LOCK = threading.RLock()

# 规格给定的四个类别。**只有这四个**，模型给别的会被拒（宁可漏，不污染）。
KINDS = ("兴趣", "事实", "偏好", "关系")

# 单条内容长度上限：内容太长就不是"一句话的画像"了，那是对话记忆该干的事。
MAX_LEN = 200
# 条数上限：画像要有选择，不能变成第二个对话库
MAX_ROWS = 500


def path():
    return _PATH


def _all_raw():
    out = []
    if not os.path.exists(_PATH):
        return out
    with open(_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:      # noqa: silent-ok — 坏行跳过（不因为一行坏了丢掉整个库）
                continue
    return out


def all_records():
    with _LOCK:
        return _all_raw()


def recent(n=5):
    rows = all_records()
    rows.sort(key=lambda r: float(r.get("ts") or 0))
    return rows[-max(1, int(n)):]


def count():
    return len(all_records())


def add(kind, content, why="", evidence="", source="模型自己判断"):
    """**只做存储**：模型说要记什么就记什么；载体不判断内容对不对、该不该记。

    返回记录 id；`content` 为空、或 `kind` 不在四类里 → 返回 ""（**不写盘**）。
    """
    k = str(kind or "").strip()
    c = str(content or "").strip()
    if not c or k not in KINDS:
        return ""
    if len(c) > MAX_LEN:
        c = c[:MAX_LEN]
    rec = {
        "id": "%d-%s" % (int(time.time() * 1000), os.urandom(3).hex()),
        "ts": time.time(),
        "kind": k,
        "content": c,
        # `why` 与 `evidence` 都是**模型给的原文，载体照抄不改写** —— 改了就成了载体在替它解释
        "why": str(why or "")[:200],
        "evidence": str(evidence or "")[:200],
        "source": str(source or "模型自己判断"),
        "hit_count": 0,
    }
    with _LOCK:
        os.makedirs(_DIR, exist_ok=True)
        rows = _all_raw()
        # 上限保护：超了就丢掉最老的（画像要精，不是要全）
        if len(rows) >= MAX_ROWS:
            keep = rows[-MAX_ROWS + 1:]
            tmp = _PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for r in keep:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tmp, _PATH)
        with open(_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec["id"]


def hit(kind=None, keyword=None, ids=None):
    """命中一次 → `hit_count` +1（用得越多的兴趣越稳）。

    只给自测/调用方显式记账用 —— 载体**不会**自己判定"这次算不算命中"。
    """
    ids = set(ids or [])
    n = 0
    with _LOCK:
        rows = _all_raw()
        for r in rows:
            ok = False
            if ids and r.get("id") in ids:
                ok = True
            elif keyword and keyword in str(r.get("content") or ""):
                ok = (kind is None or r.get("kind") == kind)
            if ok:
                r["hit_count"] = int(r.get("hit_count") or 0) + 1
                n += 1
        if n:
            tmp = _PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            os.replace(tmp, _PATH)
    return n


def render(n=8):
    """把画像渲染成**事实**清单，给模型看。

    ⚠️ **这里一个字都不许加结论**：只列"它自己被记下来的那句话"，
       不写"所以用户喜欢体育"之类的推断 —— 那是模型该做的，不是载体。
    """
    rows = recent(n)
    if not rows:
        return ""
    lines = ["（下面这些是**之前它自己判断值得记住的、关于用户的事**，原样列着，不作推断）"]
    for r in rows:
        lines.append("- [%s] %s（依据：%s）"
                     % (r.get("kind"), r.get("content"), r.get("evidence") or "未给"))
    return "\n".join(lines)


def parse_verdict(text):
    """解析模型那句判断。返回 `dict`（解析不出来返回 `{"remember": False}`）。

    【判据必须宽容、取值必须严】
      · 模型可能包着 ```json 或带解释 → **宽容**地从中抠出第一个 JSON 对象
      · 但 `remember` 必须是真 true、`kind` 必须在四类里 → **严**，宁可漏记不污染
    """
    s = str(text or "")
    if not s.strip():
        return {"remember": False, "why": "空"}
    m = re.search(r"\{[\s\S]*\}", s)
    if not m:
        return {"remember": False, "why": "没有 JSON"}
    try:
        d = json.loads(m.group(0))
    except Exception:      # noqa: silent-ok — 解析不了就当"不记"
        return {"remember": False, "why": "JSON 解析失败"}
    if not isinstance(d, dict):
        return {"remember": False, "why": "不是对象"}
    if d.get("remember") is not True:
        return {"remember": False, "why": str(d.get("why") or "模型说不记")}
    kind = str(d.get("kind") or "").strip()
    content = str(d.get("content") or "").strip()
    if kind not in KINDS or not content:
        # ⚠️ 模型说"要记"但类别/内容不合格 → **不记**，并把原因带出去（可如实记账）
        return {"remember": False, "why": "类别或内容不合格（kind=%r）" % kind}
    return {"remember": True, "kind": kind, "content": content,
            "why": str(d.get("why") or ""), "evidence": str(d.get("evidence") or "")}


def stats():
    rows = all_records()
    by = {}
    for r in rows:
        by[r.get("kind")] = by.get(r.get("kind"), 0) + 1
    return {"count": len(rows), "by_kind": by, "path": _PATH,
            "max_rows": MAX_ROWS}


def forget_all():
    """清空（只给测试/用户显式重置用，日常没人会调它）。"""
    with _LOCK:
        if os.path.exists(_PATH):
            os.remove(_PATH)


if __name__ == "__main__":       # 自带的冒烟自测（写临时库，不动真库）
    import tempfile
    _real = _PATH
    _PATH = os.path.join(tempfile.gettempdir(), "_up_smoke.jsonl")
    if os.path.exists(_PATH):
        os.remove(_PATH)
    try:
        assert add("体育", "x") == "", "非四类必须拒收"
        assert add("兴趣", "") == "", "空内容必须拒收"
        i = add("兴趣", "用户关注 NBA 篮球赛事", why="主动问了湖人比赛",
                evidence="用户问了湖人 vs 勇士")
        assert i, "正常记录应当写入"
        assert count() == 1, count()
        assert "NBA" in render(), render()
        assert hit(keyword="NBA") == 1
        assert all_records()[0]["hit_count"] == 1, all_records()[0]
        v = parse_verdict('```json\n{"remember": true, "kind": "兴趣", '
                          '"content": "用户关注 NBA", "why": "问了湖人"}\n```')
        assert v["remember"] is True and v["kind"] == "兴趣", v
        assert parse_verdict('{"remember": false}')["remember"] is False
        assert parse_verdict('{"remember": true, "kind": "瞎写", "content": "x"}'
                             )["remember"] is False, "非法类别必须拒收"
        assert parse_verdict("随便一句话")["remember"] is False
        print("✅ 用户画像库 冒烟自测通过；stats=%s" % stats())
    finally:
        if os.path.exists(_PATH):
            os.remove(_PATH)
        _PATH = _real
