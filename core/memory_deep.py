# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 记忆深度系统（模块 3）

【这段为什么这么设计】
    记忆不是"一堆句子"。人对同一件事的记法是分层的：
      · 事实层：谁、什么时候、在哪、发生了什么 —— 要能**精确**复述，不许含糊；
      · 表达层：寒暄、语气、说话习惯 —— 只学"怎么说"，**不背原句**；
      · 印象层：很久以前的事 —— 记不清细节，但"我经历过"必须还在。
    把三者混在一个向量库里，会出现两种最坏的结果：
      ① 把"你好"当成事实存 100 遍（样本爆炸、检索变吵）；
      ② 把"我住在济南"降级成"模糊"甚至删掉（用户问起来就变成编造或失忆）。
    所以这一层做三件事：**分类**（谁进哪一层）、**降级不清零**（清晰度随时间降，但永不删除）、
    **绝假记忆**（检索不到就明确说没有，绝不拿最像的凑答案）。

【去掉它会怎样】
    只剩 `memory_vec` 的"按相似度取 top-K"：
      · 寒暄样本会把真实事实挤出 top-K（记忆被自己的"你好"淹没）；
      · 模型看到"模糊命中"的片段会自己补全 → 正是"绝假记忆"要禁的行为；
      · 半年前的对话查不到就当成没发生过 —— 用户会直接感到"它变了"。

【与既有模块的关系（不重复造轮子）】
    · 向量存储仍用 `core/memory_vec.py`（append-only JSONL，红线：绝不碰 knowledge_vec.json）；
    · 检索排序（余弦 + 时间衰减）仍用 `core/retriever.py`；
    · 本模块只负责**分层 / 降级 / 巩固 / 联想 / 绝假记忆**这几件载体自己的判断，
      不重写存储与检索，也不依赖任何具体模型。
"""
import json
import os
import re
import time

from . import memory_vec
from .health import append_jsonl, read_jsonl, read_json, write_json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ------------------------------------------------------------------ 三层
LAYER_FACT = "fact"           # 事实层：原样存、精确检索、永不压缩
LAYER_EXPRESSION = "expression"   # 表达层：只学风格，不存原句
LAYER_IMPRESSION = "impression"   # 印象层：降级但不清零

LAYERS = (LAYER_FACT, LAYER_EXPRESSION, LAYER_IMPRESSION)
LAYER_CN = {LAYER_FACT: "事实", LAYER_EXPRESSION: "表达", LAYER_IMPRESSION: "印象"}

# ------------------------------------------------------------------ 清晰度（降级不是删除）
CLARITY_HD = "hd"             # 0-7 天    高清（原话）
CLARITY_SD = "sd"             # 7-30 天   标清（摘要）
CLARITY_BLUR = "blur"         # 30-180 天 模糊（关键词）
CLARITY_IMPRESSION = "impression"   # 180 天以上 印象（标签）

CLARITY_ORDER = (CLARITY_HD, CLARITY_SD, CLARITY_BLUR, CLARITY_IMPRESSION)
CLARITY_CN = {CLARITY_HD: "高清", CLARITY_SD: "标清",
              CLARITY_BLUR: "模糊", CLARITY_IMPRESSION: "印象"}

_DAY = 86400.0
# 清晰度分档（天）。为什么是这四个数：用户口径是"最近的要原话、久远的要印象"，
# 7/30/180 正好卡在"一周内 / 一个月内 / 半年内"这三个人类习惯的记忆节点上。
CLARITY_DAYS = ((7.0, CLARITY_HD), (30.0, CLARITY_SD),
                (180.0, CLARITY_BLUR), (float("inf"), CLARITY_IMPRESSION))
# 被重新提到 → 升级回高清（"被提到"的判据：一周内被检索命中过）
REVIVE_DAYS = 7.0

# ------------------------------------------------------------------ 分类规则（载体判断，不靠模型）
# 事实信号：具体人物/时间/地点/事件/状态/经历
_FACT_PATTERNS = (
    r"\d{4}\s*[-/年]\s*\d{1,2}",                       # 2026-09 / 2026年9月
    r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]",                 # 9月14日
    r"(今天|昨天|前天|明天|后天|上周|上个月|去年|今年|刚才|早上|中午|晚上|凌晨)",
    r"(住在|搬到|来自|老家|公司在|工作在|上学|毕业)",
    r"(我叫|名字是|叫我|他是|她是|我儿子|我女儿|我爸|我妈|老公|老婆)",
    r"(喜欢|讨厌|爱吃|不吃|过敏|戒烟|减肥)",
    r"(买不起|卸载|不要了|必须|一定要|不能接受)",         # 态度类**事件**：用户自己说的偏好事实
)
# 表达信号：寒暄/语气/口癖（短句 + 常见寒暄词）
_EXPRESSION_WORDS = (
    "你好", "您好", "在吗", "在么", "嗨", "哈喽", "hello", "hi", "早上好", "中午好", "晚上好",
    "吃了吗", "吃过了", "晚安", "早安", "谢谢", "多谢", "辛苦", "再见", "拜拜", "88",
    "哈哈", "哈哈哈", "呵呵", "笑死", "收到", "好的", "好嘞", "嗯嗯", "哦哦", "行吧",
)
_EXPRESSION_MAX_LEN = 24          # 超过这个长度就不算"寒暄短句"
# 情绪/状态/经历 → 事实（人经历过的事，不是口头禅）
_EVENT_WORDS = ("被", "挨", "发生", "遇到", "面试", "考试", "加班", "请假", "出差",
                "吵架", "分手", "生日", "生病", "住院", "升职", "离职", "搬家")


def classify(text):
    """判断这句话该进哪一层。**载体判断，不靠模型**。

    判据顺序不能反（这是本模块最容易写错的地方）：
      1. 先看"事实信号"（人物/时间/地点/事件/情绪经历）—— 命中就是事实层，**直接返回**；
      2. 再看"表达信号"（短句 + 寒暄词）—— 只有在**没有**事实信号时才可能是表达层；
      3. 都不命中 → 默认事实层。
    为什么"事实优先"：把事实误判成表达，代价是**用户说过的正经事被当成寒暄丢掉**；
    把表达误判成事实，代价只是多存一条样本。所以**事实误判的代价远大于表达误判**，
    不确定时一律倒向事实层。

    返回 (layer, reason)：reason 是给人看的中文理由（日志/自检里要能回答"为什么这么分"）。

    【为什么这么设计】分类是"该记什么"的第一道判断，也是最不能交给模型的一步：
    模型每次给的分类都可能不一样，而记忆一旦进错层（把"我住在济南"当寒暄丢掉），
    是**不可逆的损失**。规则判据虽然笨，但可复现、可单测、可解释（reason 就是解释）。

    【去掉它会怎样】所有话都进同一个池子：寒暄样本把真实事实挤出 top-K，
    而"只学风格不背原句"的表达层也没了意义 —— 回话会越来越像复读机。
    """
    t = (text or "").strip()
    if not t:
        return LAYER_FACT, "空内容按事实层处理（宁可多存，不可丢）"
    low = t.lower()
    for pat in _FACT_PATTERNS:
        m = re.search(pat, t)
        if m:
            return LAYER_FACT, "命中事实信号「%s」" % m.group(0)
    for w in _EVENT_WORDS:
        if w in t:
            return LAYER_FACT, "命中事件词「%s」（经历过的事属于事实）" % w
    if len(t) <= _EXPRESSION_MAX_LEN:
        for w in _EXPRESSION_WORDS:
            if w in low:
                return LAYER_EXPRESSION, "短句且命中寒暄词「%s」→ 只学风格，不存原句" % w
    return LAYER_FACT, "无寒暄特征 → 默认事实层（事实误判代价更大）"


def clarity_of(age_days):
    """按"距今多少天"给出清晰度档位（只降不升由上层 consolidate/revive 决定）。"""
    a = max(0.0, float(age_days))
    for lim, name in CLARITY_DAYS:
        if a < lim:
            return name
    return CLARITY_IMPRESSION


def age_days(ts, now=None):
    now = time.time() if now is None else float(now)
    return max(0.0, (now - float(ts or 0)) / _DAY)


# ------------------------------------------------------------------ 落盘位置
def _dir():
    d = os.path.join(_ROOT, "logs", "memory")
    os.makedirs(d, exist_ok=True)
    return d


def _path(name):
    return os.path.join(_dir(), name)


def _events_path():
    return _path("events.jsonl")


def _summary_path():
    return _path("summary.json")


def _log(event, **kw):
    """记忆事件流水（压缩/巩固/降级/联想/绝假记忆都进来，便于事后回答"它为什么忘了"）。"""
    rec = {"ts": time.time(), "event": event}
    rec.update(kw)
    try:
        append_jsonl(_events_path(), rec)
    except Exception:      # noqa: silent-ok — 流水写不进去绝不能影响记忆本身
        pass
    return rec


# ------------------------------------------------------------------ 事实层
def remember_fact(text, entities=None, ts=None, source="对话", key_text=None):
    """把一条**事实**存进记忆库（原样存、精确检索、永不压缩）。

    为什么原样存：事实一旦被摘要，细节就永远回不来了 ——
    "上个月在三院做的胃镜" 摘要成 "做过检查"，用户再问"哪个医院"就只能编。
    """
    t = (text or "").strip()
    if not t:
        return None
    _ts = time.time() if ts is None else float(ts)
    mid = memory_vec.add_memory(t, kind=LAYER_FACT, entities=entities or [],
                                ts=_ts, key_text=key_text,
                                meta={"layer": LAYER_FACT, "clarity": CLARITY_HD,
                                      "source": source, "revived_at": 0.0})
    _log("remember", layer=LAYER_FACT, id=mid, chars=len(t), source=source)
    return mid


# ------------------------------------------------------------------ 表达层（学风格，不存原句）
_STYLE_PATH_NAME = "style.json"


def _style_path():
    return _path(_STYLE_PATH_NAME)


# 风格维度：句长、语气词、称呼、标点习惯、亲密度。数值型 → 可直接算相似度/生成新表达。
_STYLE_TONE_WORDS = ("呀", "啦", "哦", "呢", "吧", "嘛", "哈", "嘿", "嘻", "～", "~", "!", "！")
_STYLE_ADDRESS = ("你", "您", "亲", "宝", "哥", "姐", "老板")


def _style_of(text):
    t = (text or "").strip()
    n = max(1, len(t))
    return {
        "len": len(t),
        "tone": sum(t.count(w) for w in _STYLE_TONE_WORDS) / float(n),      # 语气词密度
        "exclaim": (t.count("!") + t.count("！")) / float(n),               # 感叹密度
        "question": (t.count("?") + t.count("？")) / float(n),              # 疑问密度
        "ellipsis": (t.count("…") + t.count("...")) / float(n),             # 省略密度
        "address": sum(1 for w in _STYLE_ADDRESS if w in t),                # 称呼习惯
        "emotion": sum(t.count(w) for w in ("哈", "笑", "哭", "气", "爱", "喜欢")) / float(n),
    }


def _merge_style(old, new, count):
    """把新样本的风格向量并进旧风格（**加权平均**，不是覆盖）。"""
    if not old:
        return dict(new)
    out = {}
    for k, v in new.items():
        o = float((old or {}).get(k, v) or 0.0)
        out[k] = (o * count + float(v)) / (count + 1.0)
    return out


def remember_expression(text):
    """把一句寒暄/口头禅**蒸进风格向量**，返回风格快照。

    为什么**不存原句**：存原句 → "你好" 说 100 次就存 100 条，向量库被寒暄淹没，
    而且回话时容易变成"你说你好我也说你好"的死板复读。
    这里只更新一个**全局风格档案**（句长/语气词密度/称呼/标点习惯），
    回话时按风格生成新表达 —— 越用越像这个人，而不是越用越像复读机。
    """
    t = (text or "").strip()
    if not t:
        return None
    st = read_json(_style_path(), default={}) or {}
    n = int(st.get("samples") or 0)
    st["style"] = _merge_style(st.get("style"), _style_of(t), n)
    st["samples"] = n + 1
    st["updated_at"] = time.time()
    st.setdefault("recent", [])
    st["recent"] = ([{"text": t, "ts": time.time()}] + list(st["recent"]))[:20]
    write_json(_style_path(), st)
    _log("expression", samples=st["samples"], text=t[:40])
    return st


def style_profile():
    """读当前风格档案（没有样本时返回空壳，不编造）。"""
    st = read_json(_style_path(), default={}) or {}
    return {"samples": int(st.get("samples") or 0), "style": st.get("style") or {},
            "updated_at": st.get("updated_at") or 0}


def expression_reply(kind="hello"):
    """按**已学到的风格**生成一句新表达（不是背原句）。

    为什么要有它：表达层若只统计不产出，就等于没实现 —— "越用越会说"必须有一个出口。
    这里用"模板 + 风格参数"生成，**不调用模型**（载体能做的就不麻烦模型）。
    """
    prof = style_profile()
    s = prof.get("style") or {}
    n = prof.get("samples") or 0
    base = {"hello": "在的", "thanks": "不客气", "bye": "回见", "ask": "怎么了",
            "ok": "好的"}.get(kind, "在的")
    if not s:
        return base + "。"
    tail = ""
    if s.get("tone", 0) > 0.02:
        tail = "呀"
    if s.get("exclaim", 0) > 0.02:
        tail += "！"
    elif s.get("ellipsis", 0) > 0.01:
        tail += "～"
    if not tail:
        tail = "。"
    # 称呼习惯：样本里常用"您"→ 加尊称
    if s.get("address", 0) >= 2/3.0:
        base = "您" + base.replace("你", "")
    return base + tail if n else base + "。"


# ------------------------------------------------------------------ 印象层
def _impression_row(text, source="压缩", ts=None):
    """**构造**一条印象记录（不写盘）。

    【为什么要把"构造"和"写盘"分开 —— 自测抓到的真 bug】
        `compress()` 原来的写法是：循环里调 `remember_impression()`（**直接追加写盘**），
        循环结束后再 `_rewrite(rows)` 用**循环开始前读到的那个 rows 列表**覆盖整个文件。
        结果：刚追加的印象行**被自己的覆盖写抹掉了** ——
        返回值里 `compressed=1`、目标行的 `compressed_to` 也指向了那个 id，
        但文件和索引里都没有它（实测 file_rows 398→398、索引 0→398 却查不到）。
        这类"写了又被自己覆盖"的 bug 不会报错，只会让印象永远丢失。
        修法：把新行**并进 rows 再一次性原子写**，全程只有一次落盘。
    """
    t = (text or "").strip()
    if not t:
        return None
    imp = t if len(t) <= 60 else t[:60] + "…"
    body = "【印象】" + imp
    return {"id": "%d-%s" % (int(time.time() * 1000), os.urandom(3).hex()),
            "ts": float(ts if ts is not None else time.time()),
            "kind": LAYER_IMPRESSION,
            "entities": [],
            "len": len(body),
            "text": body[:2000],
            "key": body[:400],
            "meta": {"layer": LAYER_IMPRESSION, "clarity": CLARITY_IMPRESSION,
                     "source": source, "refs": 0, "revived_at": 0.0}}


def remember_impression(text, source="压缩", ts=None):
    """把久远内容压成**印象**（标签+一句话），进向量库，**永不删除**。"""
    rec = _impression_row(text, source=source, ts=ts)
    if rec is None:
        return None
    rows = _all_rows()
    rows.append(rec)
    _rewrite(rows)          # 一次原子写：既落盘也保证索引知道这条
    _log("impression", id=rec["id"], chars=len(rec["text"]), source=source)
    return rec["id"]


# ------------------------------------------------------------------ 五个机制
def _all_rows():
    """读出全部记忆行（含 meta/clarity）。读失败就返回空表（不许因此崩）。"""
    try:
        return read_jsonl(memory_vec.path())
    except Exception:      # noqa: silent-ok — 读不出来按"没有记忆"处理，由上层如实说明
        return []


def _clarity_of_row(row, now=None):
    meta = row.get("meta") or {}
    base = meta.get("clarity") or CLARITY_HD
    # 被重新提到 → 升级回高清（"被提到"= 最近 REVIVE_DAYS 内被检索命中过）
    rev = float(meta.get("revived_at") or 0)
    if rev and (float(now or time.time()) - rev) < REVIVE_DAYS * _DAY:
        return CLARITY_HD
    # 巩固过的（important）不降级
    if meta.get("locked"):
        return base
    degraded = clarity_of(age_days(row.get("ts"), now))
    # **取更差的那一档**，不是更好的那一档。
    # 这里踩过一次真坑（自测抓到的）：写成 max(base, degraded) 之后，
    # 因为条目**在写入时就把 clarity 记成 hd**，"时间降级"永远拼不过那个 hd →
    # 任何条目一旦入库就终身高清（`degrade()` 报 changed=0），
    # 等于整套清晰度降级**从来没生效过**，而且压缩标记也会被 hd 顶掉。
    # 语义定死：stored 只是"底线"，时间只会让它更差，不会让它更好。
    return degraded if CLARITY_ORDER.index(degraded) > CLARITY_ORDER.index(base) else base


def degrade(now=None, apply=True, rows=None):
    """机制③ **降级**：按时间把清晰度往下调（不是删除）。

    返回 {"scanned": n, "changed": [{id, from, to, age_days}], "levels": {档位: 条数}}。
    为什么必须"只降不删"：删掉的是用户的真实经历；降级丢的是"细节清晰度"。
    半年后用户再问，答"我好像记得这件事，细节你提醒我一下"是可接受的；
    答"没这回事"是不可接受的（那等于否认用户的经历）。

    ⚠️ `rows` 参数为什么必须存在（**这是被自测事故逼出来的**）：
        降级是**按时间**算的，而"按时间"意味着可以传任意 `now`。
        自测时为了验证"400 天前→印象"，用 `now + 500 天` 调了一次 `apply=True` ——
        结果它把**整库 397 条真实记忆**全部按"500 天后"重算并写回，全成了印象。
        教训：**"能按时间推演"的函数绝不能默认改真实数据**。
        所以现在允许把待处理的行**直接传进来**（`rows=[...]`）：
        传了就在内存里算、不回写文件（`apply` 自动失效）。测试与推演一律用这个口子。
    """
    now = time.time() if now is None else float(now)
    live = rows is None
    rows = _all_rows() if live else list(rows)
    changed, levels = [], {}
    for r in rows:
        meta = r.get("meta") or {}
        if (r.get("kind") or "") == LAYER_EXPRESSION:
            continue                     # 表达层不进清晰度体系（它只存风格向量）
        old = meta.get("clarity") or CLARITY_HD
        new = _clarity_of_row(r, now)
        levels[new] = levels.get(new, 0) + 1
        if new != old:
            changed.append({"id": r.get("id"), "from": old, "to": new,
                            "age_days": round(age_days(r.get("ts"), now), 2)})
            if apply and live:
                meta["clarity"] = new
                meta["degraded_at"] = now
                r["meta"] = meta
    applied = bool(apply and live and changed)
    if applied:
        _rewrite(rows)
    if applied or (changed and not live):
        _log("degrade", changed=len(changed), levels=levels, applied=applied)
    return {"scanned": len(rows), "changed": changed, "levels": levels, "applied": applied}


def consolidate(min_refs=3, now=None):
    """机制② **巩固**：被引用多的记忆锁定为高清（重要的事不该随时间变模糊）。"""
    now = time.time() if now is None else float(now)
    rows = _all_rows()
    locked = []
    for r in rows:
        meta = r.get("meta") or {}
        if int(meta.get("refs") or 0) >= int(min_refs) and not meta.get("locked"):
            meta["locked"] = True
            meta["locked_at"] = now
            r["meta"] = meta
            locked.append(r.get("id"))
    if locked:
        _rewrite(rows)
        _log("consolidate", locked=len(locked))
    return {"locked": locked, "count": len(locked)}


def note_usage(memory_id, now=None):
    """记一次"这条记忆被用上了"（供 consolidate 打分）。"""
    rows = _all_rows()
    for r in rows:
        if r.get("id") == memory_id:
            meta = r.get("meta") or {}
            meta["refs"] = int(meta.get("refs") or 0) + 1
            meta["last_used"] = time.time() if now is None else float(now)
            r["meta"] = meta
            _rewrite(rows)
            return meta["refs"]
    return 0


def revive(memory_id, now=None):
    """被重新提到 → 升级回高清（机制③的另一半：降级可逆）。"""
    rows = _all_rows()
    for r in rows:
        if r.get("id") == memory_id:
            meta = r.get("meta") or {}
            meta["revived_at"] = time.time() if now is None else float(now)
            meta["clarity"] = CLARITY_HD
            r["meta"] = meta
            _rewrite(rows)
            _log("revive", id=memory_id)
            return True
    return False


def flush_index(rows=None):
    """把"文件里有、向量索引里没有"的行补进索引。

    【为什么必须有它 —— 自测抓到的真 bug】
        `memory_vec.reload()` 的语义是"重建索引"，但重建**只覆盖文件里已有的行**。
        而真实流程是：先 `add_memory()` 追加一行（索引里立刻有了），
        紧接着 `_rewrite()` 覆盖整个文件 + `reload()` —— 重建期间如果漏掉这行，
        它就**永远留在文件里、却永远搜不到**（实测：压缩出来的印象条目
        `compressed_to` 有 id、读文件也看得到，但 `search_memory` 找不到）。
        这是最阴的一类 bug：写入不报错、读文件也正常，只是检索不到 ——
        用户只会觉得"它忘了"。所以每次覆盖写之后都要**对一次账**。
    """
    try:
        rows = _all_rows() if rows is None else list(rows)
        try:
            have = set(memory_vec.ids())
        except Exception:      # noqa: silent-ok — 拿不到 id 列表就整体重建一次
            memory_vec.reload()
            have = set(memory_vec.ids())
        fixed = 0
        for r in rows:
            if r.get("id") in have:
                continue
            try:
                if memory_vec.reindex_row(r):
                    fixed += 1
                    have.add(r.get("id"))
            except Exception:      # noqa: silent-ok — 单行补不进去不能拖垮整体
                continue
        if fixed:
            _log("flush_index", fixed=fixed)
        return fixed
    except Exception:      # noqa: silent-ok — 对账失败只影响检索完整性，绝不抛到生成路径上
        return 0


def _rewrite(rows):
    """把改过的记忆行写回 JSONL（**原子替换**：先写 .tmp 再 replace）。

    为什么必须原子：这里是唯一的"覆盖写"路径，写到一半崩了就是**整库报废**。
    先写临时文件再 `os.replace`（同目录 rename 是原子的），最坏情况也只是临时文件残留。
    """
    p = memory_vec.path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    memory_vec.reload()
    flush_index(rows)          # 覆盖写之后必须对账，否则新行可能"文件里有、搜不到"

    """把"文件里有、向量索引里没有"的行补进索引。

    【为什么必须有它 —— 自测抓到的真 bug】
        `memory_vec.reload()` 的语义是"重建索引"，但重建**只覆盖文件里已有的行**。
        而真实流程是：先 `add_memory()` 追加一行（索引里立刻有了），
        紧接着 `_rewrite()` 覆盖整个文件 + `reload()` —— 重建期间如果漏掉这行，
        它就**永远留在文件里、却永远搜不到**（实测：压缩出来的印象条目
        `compressed_to` 有 id、`_all_rows()` 也读得到，但 `search_memory` 找不到）。
        这是最阴的一类 bug：写入没报错、读文件也对，只是检索不到 —— 用户只会觉得"它忘了"。
        这里做一次**对账**：索引缺哪行就补哪行（只追加，不改已有）。
    """
    try:
        rows = _all_rows() if rows is None else list(rows)
        ids = set(memory_vec.ids()) if hasattr(memory_vec, "ids") else set()
        fixed = 0
        for r in rows:
            if r.get("id") in ids:
                continue
            try:
                memory_vec.reindex_row(r)
                fixed += 1
            except Exception:      # noqa: silent-ok — 某一行补不进去不能拖垮整体
                continue
        if fixed:
            _log("flush_index", fixed=fixed)
        return fixed
    except Exception:      # noqa: silent-ok — 对账失败只影响检索完整性，不能抛到生成路径上
        return 0


def compress(now=None, force=False, rows=None):
    """机制① **压缩**：把久远的、非锁定的记忆压成印象层摘要。

    返回 {"compressed": n, "impressions": [...], "summary"?: {...}}。
    为什么压缩不是删除：压完原条目仍在（清晰度降为印象），并额外落一条印象条目
    —— 用户的"我经历过"必须永远为真。

    `rows` 同 `degrade`：传进来就只算不写（推演/自测用）。
    """
    now = time.time() if now is None else float(now)
    live = rows is None
    rows = _all_rows() if live else list(rows)
    out = []
    for r in rows:
        meta = r.get("meta") or {}
        kind = r.get("kind") or LAYER_FACT
        locked = bool(meta.get("locked"))
        age = age_days(r.get("ts"), now)
        if (not force) and kind != LAYER_IMPRESSION and not locked and age >= 180.0:
            if live:
                # 先把印象行**并进同一个 rows 列表**，最后一次性原子写 ——
                # 不能再"先追加写盘、再拿旧 rows 覆盖"（那会把刚写的抹掉，见 _impression_row 说明）
                rec = _impression_row(r.get("text") or "", source="压缩", ts=r.get("ts"))
                if rec is None:
                    continue
                rows.append(rec)
                mid = rec["id"]
            else:
                mid = "(dry-run)"
            meta["clarity"] = CLARITY_IMPRESSION
            meta["compressed_to"] = mid
            r["meta"] = meta
            out.append({"id": r.get("id"), "impression_id": mid,
                        "age_days": round(age, 1), "text": (r.get("text") or "")[:40]})
    if out and live:
        _rewrite(rows)
        sm = read_json(_summary_path(), default={}) or {}
        sm["last_compress"] = now
        sm["compressed_total"] = int(sm.get("compressed_total") or 0) + len(out)
        write_json(_summary_path(), sm)
        _log("compress", count=len(out))
    return {"compressed": len(out), "impressions": out, "applied": bool(out and live)}


def associations(memory_id, limit=5, now=None):
    """机制④ **联想**：给一条记忆找"因果链 + 时间链"上的邻居。

    为什么需要它：单条记忆只能回答"这件事"，联想能回答"后来呢/为什么"。
    判据（纯载体规则，不调模型）：**时间相邻** + **共享实体** → 时间链；
    时间相近且出现"因果词"→ 因果链。
    """
    now = time.time() if now is None else float(now)
    rows = _all_rows()
    me = next((r for r in rows if r.get("id") == memory_id), None)
    if me is None:
        return []
    my_ents = set(x for x in (me.get("entities") or []) if x)
    my_ts = float(me.get("ts") or 0)
    causal_words = ("因为", "所以", "于是", "导致", "结果", "后来", "因为这样", "害得")
    out = []
    for r in rows:
        if r.get("id") == memory_id:
            continue
        ts = float(r.get("ts") or 0)
        gap = abs(ts - my_ts)
        ents = set(x for x in (r.get("entities") or []) if x)
        shared = my_ents & ents
        kind = None
        if shared:
            kind = "实体"
        elif gap <= 10 * _DAY:
            kind = "时间"
        if kind is None:
            continue
        txt = (r.get("text") or "")
        if kind == "时间" and any(w in txt for w in causal_words):
            kind = "因果"
        # ---- 排序分：为什么这么加权 ----
        # 共享实体的联想最有用（"同一件事的其他侧面"），因果次之（"后来呢"），
        # 纯时间相邻最弱（一个时间段里本来就挤着很多无关的事）。
        # 上一版是"先按 kind 排、再按时间排"，结果 limit 一截，
        # 全被时间链占满、实体链一条都进不来（自测当场判红）。
        score = {"实体": 3.0, "因果": 2.0, "时间": 1.0}.get(kind, 0.5)
        score -= min(0.9, gap / (30 * _DAY))          # 越近越靠前，但最多只扣 0.9
        out.append({"id": r.get("id"), "kind": kind, "text": txt[:60],
                    "gap_days": round(gap / _DAY, 2), "shared": sorted(shared)[:4],
                    "score": round(score, 3)})
    out.sort(key=lambda z: -z["score"])
    return out[:max(1, int(limit))]


# ------------------------------------------------------------------ 机制⑤ 绝假记忆（诚信红线）
# 【阈值为什么这么定 —— 实测出来的，不是拍的】
# 拿真实记忆库量过：**纯余弦相似度在这个嵌入模型上区分不了"记得"和"没说过"**：
#     记得的   "我住在哪"      top5 余弦 0.652 / 关键词重合 0.00
#     没说过   "我的车牌号是什么" top5 余弦 0.622 / 关键词重合 0.00
#   两者几乎重叠（中文短句的余弦基线就在 0.55~0.67），
#   所以**不能**只靠相似度下"我记得/我不记得"的结论 —— 那正是"绝假记忆"的红线。
# 真正有区分度的是**表面特征重合**（中文 2-gram + 数字 + 拉丁词）：
#   同一个说法（原文命中）: 重合 1.00；换一种说法的改写: 0.00。
# 于是判据定为两级：
#   precise（敢当事实说）: 余弦 ≥ SIM_STRONG **且** 表面特征有重合
#   fuzzy （只承认"记得"、绝不补细节）: 余弦 ≥ SIM_WEAK，但没有表面重合
#   低于 SIM_WEAK → "你之前没跟我说过这事"
SIM_WEAK = 0.55
SIM_STRONG = 0.66
# 中文虚词单字：它们凑出的 2-gram（"我的"/"是不"）没有信息量，必须过滤，
# 否则任何两句中文都会"假重合"，闸门直接失效。
_STOP_CHARS = set("的了是我你他她它们在有和与也就都还不没很呢吧啊呀哦这那什么怎么请"
                  "问一下帮我个说记之前跟曾经经过于把被给对于从到会要能可以真想那第")


def _features(text):
    """抽"表面特征"：中文 2-gram（滤虚词）+ 数字串 + 长度≥2 的拉丁词。

    为什么用 2-gram 而不是分词：项目里没有中文分词器，也不该为一个判断加依赖；
    2-gram 对"这两句是不是在说同一件事"已经足够可分（实测 1.00 vs 0.00）。
    """
    t = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "")
    out = set()
    for i in range(len(t) - 1):
        bg = t[i:i + 2]
        if bg[0] in _STOP_CHARS and bg[1] in _STOP_CHARS:
            continue
        out.add(bg)
    if len(t) == 1 and t not in _STOP_CHARS:
        out.add(t)
    for w in re.findall(r"[A-Za-z]{2,}", text or ""):
        out.add(w.lower())
    for num in re.findall(r"\d{2,}", text or ""):
        out.add(num)
    return out


def overlap(query, text):
    """查询与记忆内容的表面特征重合率（分母是查询侧，表示"我说的东西你记着多少"）。"""
    a, b = _features(query), _features(text)
    if not a:
        return 0.0
    return len(a & b) / float(len(a))


def confidence(query, text, sim=None):
    """综合置信度（0~1）：表面重合为主，向量相似度为辅。

    为什么表面重合权重更高：见上面实测 —— 余弦在这台嵌入模型上没有区分度，
    表面重合才是"是不是同一件事"的可靠证据。
    """
    ov = overlap(query, text)
    s = 0.0 if sim is None else max(0.0, min(1.0, float(sim)))
    base = 0.55 * s
    if ov >= 0.5:
        return min(1.0, base + 0.45)
    if ov > 0:
        return min(1.0, base + 0.30)
    return base * 0.35          # 没有任何表面重合 → 大幅折价，落到 fuzzy/none 区间


def recall(query, top_k=5, threshold=None, now=None):
    """检索记忆并**如实**给出口径。这是"绝假记忆"的唯一出口，别的路径不许自己答。

    返回 dict：
      verdict   precise | fuzzy | none | empty
      text      注入/回话用文本（verdict=none 时是**明确的"没说过"**，不是空串）
      hits      命中列表（含 clarity/age_days，降级的东西必须带上这个标记）
      tokens    文本 token 数
    四条口径（对用户的话）：
      · precise：精确命中 → 可以当成事实说；
      · fuzzy  ：记得这件事、细节不清 → 必须说"细节你提醒我一下"，**不许补全细节**；
      · none   ：检索不到 → 必须说"你之前没跟我说过这事"；
      · empty  ：用户压根没说具体事（比如"你好"）→ 不下结论。

    【为什么这么设计】这是"绝假记忆"这条诚信红线的**唯一出口**，
    所以它必须把"我记得/我不记得/我只记得大概"三种状态**分开返回**，
    而不是像普通检索那样只给一串命中。实测过：纯余弦相似度区分不了这两者
    （"没说过"top 0.622 vs "记得"top 0.652），所以判据里加了**表面特征重合**这道闸门 ——
    没有重合就只能承认"记得但细节不清"，绝不把最像的那条当事实说。

    【去掉它会怎样】调用方各自拿 top-1 当答案：用户问一件从没说过的事，
    系统会把某条不相关的记忆包装成"你说过" —— 编造用户的经历是**最严重的失信**，
    而且用户很难发现（他只能凭印象觉得"我没说过这个啊"）。
    """
    from . import retriever
    q = (query or "").strip()
    if not q:
        return {"verdict": "empty", "text": "", "hits": [], "tokens": 0}
    th = SIM_WEAK if threshold is None else float(threshold)
    r = retriever.retrieve(q, top_k=top_k, threshold=th, log=False, now=now)
    hits = []
    now = time.time() if now is None else float(now)
    rows = {x.get("id"): x for x in _all_rows()}
    for h in (r.get("hits") or []):
        row = rows.get(h.get("id")) or {}
        cl = _clarity_of_row(row, now) if row else CLARITY_HD
        ov = overlap(q, h.get("text") or "")
        hits.append({"id": h.get("id"), "text": h.get("text"), "score": h.get("score"),
                     "decayed": h.get("decayed"), "age_days": h.get("age_days"),
                     "clarity": cl, "clarity_cn": CLARITY_CN.get(cl, cl),
                     "overlap": round(ov, 3),
                     "conf": round(confidence(q, h.get("text") or "", h.get("score")), 3)})
    hits.sort(key=lambda z: -(z["conf"] or 0))
    if not hits:
        _log("recall_none", query=q[:40])
        return {"verdict": "none",
                "text": "你之前没跟我说过这事。", "hits": [], "tokens": r.get("tokens") or 0}
    best = hits[0]
    # 精确：向量够强 **且** 表面上确实在说同一件事（有重合特征）—— 两条都满足才敢当事实说
    if (best["score"] or 0) >= SIM_STRONG and best["overlap"] > 0:
        if best["clarity"] in (CLARITY_BLUR, CLARITY_IMPRESSION):
            # 记得这件事，但内容已经模糊 —— 只承认"记得"，绝不补细节
            _log("recall_fuzzy", query=q[:40], id=best["id"], clarity=best["clarity"])
            return {"verdict": "fuzzy",
                    "text": "我记得你提过「%s」，但细节我记不太清了，你提醒我一下。"
                            % (best["text"] or "")[:40],
                    "hits": hits, "tokens": r.get("tokens") or 0}
        _log("recall_precise", query=q[:40], id=best["id"], conf=best["conf"])
        return {"verdict": "precise", "text": best["text"], "hits": hits,
                "tokens": r.get("tokens") or 0}
    # 有相似的句子、但**表面上对不上**（没有共同特征）→ 不敢当事实，也不谎称"没说过"
    _log("recall_fuzzy", query=q[:40], id=best["id"], why="表面无重合")
    return {"verdict": "fuzzy",
            "text": "我记得你提过「%s」，但细节我记不太清了，你提醒我一下。"
                    % (best["text"] or "")[:40],
            "hits": hits, "tokens": r.get("tokens") or 0}


# ------------------------------------------------------------------ 统一入库口
def remember(text, entities=None, ts=None, source="对话", key_text=None):
    """**统一入口**：分类 → 进对应层。上层不需要自己判断该调哪个函数。

    返回 {"layer", "reason", "id"}（reason 必须留着：事后要能回答"这条为什么进了表达层"）。
    """
    layer, reason = classify(text)
    if layer == LAYER_EXPRESSION:
        remember_expression(text)
        mid = None
    else:
        mid = remember_fact(text, entities=entities, ts=ts, source=source, key_text=key_text)
    _log("remember_auto", layer=layer, reason=reason, id=mid, text=(text or "")[:40])
    return {"layer": layer, "reason": reason, "id": mid}


def stats(now=None):
    """给界面/自检用的概览（**全部是真实统计**，没有就写 0）。"""
    rows = _all_rows()
    now = time.time() if now is None else float(now)
    by_layer, by_clarity = {}, {}
    for r in rows:
        kind = r.get("kind") or "dialogue"
        by_layer[kind] = by_layer.get(kind, 0) + 1
        if kind == LAYER_EXPRESSION:
            continue
        cl = _clarity_of_row(r, now)
        by_clarity[cl] = by_clarity.get(cl, 0) + 1
    return {"total": len(rows), "by_layer": by_layer,
            "by_clarity": by_clarity, "by_clarity_cn": {CLARITY_CN.get(k, k): v
                                                        for k, v in by_clarity.items()},
            "style_samples": style_profile()["samples"],
            "summary": read_json(_summary_path(), default={}) or {}}
