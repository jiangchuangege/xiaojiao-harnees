# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 无缝续写（无限 3：输出无限）

问题：模型单次只能吐 2000 token。用户要"写 5 万字"，模型**物理上**做不到一次给完。
载体解法：多次请求 + 无缝合并，用户看到的是一段连续输出，**看不出是分了几次**。

载体负责的事（一样都不推给模型）：
  ① 定长度：从任务里解析「3000 字 / 5 万字 / 20000 words」→ 目标总字数
  ② 装上下文：第 1 次给完整任务；第 N 次给「任务 + 已写摘要 + 上段最后 200 字」让模型接着写
  ③ 去重：与已写正文末尾做**最长重叠**比对（后缀=前缀），重叠部分裁掉 —— 这是"无缝"的关键
  ④ 断句：段落结束必须是完整句子；半句回退到上一个句号，残句带入下一轮
  ⑤ 校验：空输出 / 重新开场 / 又短又零重合 → 丢弃重试（≤ max_retries 次）
  ⑥ 提速：**并发预取**下一段 + 缓冲池（段与段之间不留空档）
  ⑦ 停止：模型说「【完成】」/ 达到目标长度 / 用户叫停

模型只干一件事：**接着写下一小段**。它不知道自己在被循环调度。

── 并发预取为什么这么写（踩过就想明白了）────────────────────────────────
预取第 N+1 段，必须知道"第 N 段已经写了什么"（要拿它当衔接锚点、还要拿它做去重）。
所以**不能**让预取线程和主循环同时对着同一份状态写 —— 那样第 N+1 段拿到的锚点是残缺的，
去重也会算错，拼出来就会重句。
这里的做法：**只有一条生成线程**（预取线程），它自己维护一份"影子正文"
（= 已提交正文 + 池子里已生成但还没被取走的部分），一直把池子填到 buffer_size 为止。
主循环只从池子里取、只做合并（去重/断句），从不并发生成。
这样既拿到了预取的速度，又保证每段的锚点都是**确定**的。
"""
import re
import threading
import time

DONE_MARK = "【完成】"
_TAIL_CTX = 200            # 带上"上段最后 200 字"作为衔接锚点
_SENT_END = "。！？!?；;…"  # 句子结束符（不含逗号/顿号 —— 那些是半句）
_OVERLAP_WIN = 800         # 去重时比对的窗口（字符）
_MIN_OVERLAP = 8           # 小于这个长度的"重叠"多半是巧合，不裁

_NUM = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
        "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_num(s):
    """把「三」「十五」「二十」这类中文数字转成 int（够用即可）。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in _NUM:
        return _NUM[s]
    m = re.fullmatch(r"([一二两三四五六七八九])?十([一二三四五六七八九])?", s)
    if m:
        return _NUM.get(m.group(1) or "一", 1) * 10 + _NUM.get(m.group(2) or "", 0)
    return None


def parse_target_chars(task):
    """从任务里解析用户想要的**总字数**；解析不到返回 None（= 写到模型说完成）。

    支持：3000字 / 3千字 / 5万字 / 两万字 / 20 万字 / 20000 words / 2000 词
    """
    t = (task or "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*千\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d+)\s*(?:字|词|words?)", t, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二两三四五六七八九十]+)\s*万\s*(?:字|词)", t)
    if m:
        n = _cn_num(m.group(1))
        return n * 10000 if n else None
    m = re.search(r"([一二两三四五六七八九十]+)\s*(?:字|词)", t)
    if m:
        return _cn_num(m.group(1))
    return None


def overlap_len(a, b, win=_OVERLAP_WIN):
    """a 的后缀与 b 的前缀的**最长重叠长度** —— 无缝拼接就靠它。

    模型"接着写"时几乎总会把上段末尾又抄一遍
    （上段"……他走进房间。" → 本段"他走进房间。屋里很暗……"）。
    直接把两段接起来就出现重复句；这里找出重叠并把第二段的开头裁掉。
    """
    if not a or not b:
        return 0
    A, B = a[-win:], b[:win]
    for L in range(min(len(A), len(B)), 0, -1):
        if A[-L:] == B[:L]:
            return L
    return 0


def cut_at_sentence(text, min_ratio=0.5):
    """切成 (完整句子部分, 残留半句)。整段不成句时原样返回（切不出东西就别切）。"""
    if not text:
        return "", ""
    idx = max(text.rfind(ch) for ch in _SENT_END)
    if idx < 0:
        return "", text
    if (idx + 1) < len(text) * min_ratio:
        return "", text
    return text[:idx + 1], text[idx + 1:]


_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])")


def split_sentences(text):
    """按句末标点切句（保留标点）。"""
    return [s for s in _SENT_SPLIT.split(text or "") if s.strip()]


def drop_repeated_sentences(chunk, seen, min_len=12):
    """把**整句复读**从本段去掉，返回 (清洗后的段落, 去掉的句数)。

    为什么"末尾重叠裁剪"不够：那只裁得掉**接缝处那一句**。而弱模型（4B）在"接着写"
    时常见的是**整句复读**——第二句、第三句又把同一句话抄一遍。只裁接缝，正文里照样
    会留下重复句，用户一眼就看出"这是拼的"。
    所以每段合并前再过滤一次：只要这个整句（≥ min_len 字）已经出现过，就丢掉。
    `seen` 是跨段累积的集合（调用方维护），段内重复同样会被这一遍挡住。
    """
    out, dropped = [], 0
    for s in split_sentences(chunk):
        t = s.strip()
        if len(t) >= min_len and t in seen:
            dropped += 1
            continue
        if len(t) >= min_len:
            seen.add(t)
        out.append(s)
    return "".join(out), dropped


_STOPWORDS = ("写一篇", "写一个", "写一份", "写一段", "写个", "帮我写", "给我写", "请写", "替我写",
              "帮我", "给我", "请你", "麻烦", "请", "写", "生成", "创作", "来一篇", "一篇", "一个",
              "一份", "一段", "关于", "有关", "左右", "以上", "不少于", "至少", "字", "词", "的",
              "介绍一下", "介绍", "我", "你", "要", "把", "用", "和", "与", "或", "在")


def _keywords(task, limit=12):
    """任务里的**主题**关键词（连续中文/英文片段），用于偏题校验。

    坑（第 3 步单测抓到）：直接把整句里的连续中文抠出来当关键词，抠到的是**指令措辞**
    而不是主题 —— 「写一篇 3000 字的产品介绍」会抠出「写一篇」「字的产品介绍」，
    模型正文里当然不会出现这些，于是每一段都被误判"跑题"、整篇生成不出来。
    现在先把数字与指令/助词剥掉，剩下的才是主题（这里 →「产品介绍」）。
    """
    t = re.sub(r"\d+", "", task or "")
    for w in _STOPWORDS:
        t = t.replace(w, " ")
    kws = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z]{3,}", t)
    out, seen = [], set()
    for k in kws:
        kl = k.lower()
        if kl in seen:
            continue
        seen.add(kl)
        out.append(k)
        if len(out) >= limit:
            break
    return out


_OPENERS = ("好的，我来", "好的，以下", "以下是", "下面我", "当然可以", "没问题，我",
            "我来为你写", "我将为你", "这是一篇", "《")


def looks_offtopic(chunk, kws):
    """偏题/空转判定（**保守**：只抓明显跑掉的，不误杀正常长文）。

    长文的后段不复述任务关键词是正常的，所以只在"又短、又与关键词零重合"时才判跑题。
    """
    c = (chunk or "").strip()
    if not c:
        return True, "空输出"
    head = c[:40].lstrip("#* \t")
    for p in _OPENERS:
        if head.startswith(p):
            return True, "重新开场（不是接着写）"
    if len(c) < 200 and kws and not any(k in c for k in kws):
        return True, "又短又与任务关键词零重合"
    return False, ""


def _brief(text, limit=180):
    """已写内容的极简梗概（给下一轮当"已经写到哪了"）。"""
    parts = [s for s in re.split(r"(?<=[。！？!?])", text or "") if s.strip()]
    if not parts:
        return (text or "")[-limit:]
    out = parts[0][:80]
    for p in parts[1:]:
        if len(out) + len(p) > limit:
            break
        out += p[:60]
    return out[-limit:]


def build_prompt(task, n, written, summary=""):
    """第 1 次给完整任务；第 N 次给「任务 + 已写摘要 + 上段最后 200 字」。"""
    if n == 1:
        return ("%s\n\n请直接开始写正文（不要解释、不要客套、不要复述我的要求）。"
                "写满就停下，我随后会让你接着写。" % task)
    body = written[-_TAIL_CTX:] if written else ""
    user = ("原任务：%s\n\n你已经写到（梗概）：%s\n\n"
            "你上一次写到的最后一段原文：\n……%s\n\n"
            "请**紧接着上面最后一句往下写**：不要重抄已写过的内容，不要另起标题，"
            "不要重新开场，不要总结前文。直接续写正文。" % (task, summary or _brief(written), body))
    return user


def _default_call(messages, max_tokens, temperature=0.8):
    """默认模型调用：复用 xiaojiao_app 的 `_llm_targets` + `_llm_post`
    （自带重试 + 云端被拒自动兜到本地大脑，不另起一套）。"""
    try:
        import sys
        app = sys.modules.get("xiaojiao_app")
        if app is None:
            import xiaojiao_app as app
    except Exception:
        return ""
    for t in app._llm_targets():
        r, code, _body = app._llm_post(t, {"model": t["model"], "messages": messages,
                                           "temperature": temperature,
                                           "max_tokens": int(max_tokens)}, timeout=180, tries=2)
        if code == 200 and r is not None:
            try:
                return (r.json()["choices"][0]["message"]["content"] or "").strip()
            except Exception:
                continue
    return ""


def generate_unlimited(task, system="", max_per_chunk=2000, max_total=None,
                       max_retries=3, summary_interval=5, buffer_size=3,
                       parallel_prefetch=True, llm_fn=None, on_chunk=None,
                       should_stop=None, cfg=None):
    """按需生成任意长度的文本，段与段之间**无缝**。

      max_per_chunk   单次请求的输出上限（token）
      max_total       目标总**字符数**；None 时自动从 task 解析（"5 万字" → 50000）
      on_chunk(chunk, n, total_chars)  每通过一段回调一次 —— SSE 就靠它
      should_stop()   返回 True 立刻停（用户叫停）
    返回 dict：text/chunks/chars/stopped/elapsed_s/dedup_chars/retries/seams
    """
    llm_fn = llm_fn or _default_call
    if cfg:
        max_per_chunk = int(cfg.get("chunk_size") or max_per_chunk)
        max_retries = int(cfg.get("max_retries") or max_retries)
        summary_interval = int(cfg.get("summary_interval") or summary_interval)
        buffer_size = int(cfg.get("buffer_size") or buffer_size)
        if cfg.get("parallel_prefetch") is not None:
            parallel_prefetch = bool(cfg["parallel_prefetch"])
    if max_total is None:
        max_total = parse_target_chars(task)

    kws = _keywords(task)
    written = ""                     # 已提交正文（只在主线程改）
    carry = ""                       # 上一段切下来的半句
    summary = ""
    seen_sents = set()               # 已经出现过的整句（跨段累积，专治"整句复读"）
    chunks = []
    dedup_chars = 0
    t0 = time.time()
    buffer_size = max(1, int(buffer_size))

    lock = threading.Lock()
    cond = threading.Condition(lock)
    pool = []                        # [(n, raw, done)] 已生成待取
    shadow = ""                      # 池子里那些段落接上去之后的正文（预取线程自己维护）
    next_n = 1
    inflight = [0]                   # 正在生成第几段（0 = 没人在生成）
    stop_flag = threading.Event()
    stop_reason = [""]

    def _generate_raw(n, upto_text, upto_summary):
        """调模型拿一段**原始**输出（不做去重/断句 —— 那是合并时的事）。

        返回 (正文, 失败原因, 是否声明完成)
        `【完成】` 必须在偏题校验**之前**处理：模型说完结了就是完结了，
        不能让"风格校验"把它的收尾句当成跑题丢掉（第 3 步单测抓到的第二只虫子）。
        """
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": build_prompt(task, n, upto_text, upto_summary)})
        raw = (llm_fn(msgs, max_per_chunk) or "").strip()
        done = DONE_MARK in raw
        if done:
            raw = raw.replace(DONE_MARK, "").strip()
            if not raw:
                return "", "模型声明完成", True
            return raw, "", True          # 收尾句照样收下，由调用方决定停止
        off, why = looks_offtopic(raw, kws)
        if off:
            return "", why, False
        return raw, "", False

    retry_ctr = [0]

    def _gen_one(n, upto, summ, attempts):
        """带重试地生成第 n 段的原始输出。返回 (raw, done, why)。

        `done=True` 表示模型这一轮声明了【完成】—— 此时哪怕 raw 为空也算"正常结束"，
        不能被当成"校验不通过"。
        """
        why = ""
        for _ in range(max(1, attempts)):
            raw, w, done = _generate_raw(n, upto, summ)
            if done:
                return raw, True, ""
            if raw:
                return raw, False, ""
            why = w
            retry_ctr[0] += 1
        return "", False, why

    def _prefetch():
        """唯一的预取线程：把池子填到 buffer_size。影子正文只有它动。

        **必须认领 inflight**：否则主循环等不到池子就自己生成一段，两边同时产出同一个 n，
        后到的那段锚点是过期的（不知道前一段已经存在）→ 接缝会错位、还会白烧一次模型调用。
        第 3 步实测就撞上了：chunk 编号出现 [1,2,2]。
        """
        nonlocal shadow, next_n
        while not stop_flag.is_set():
            with cond:
                if len(pool) >= buffer_size or inflight[0]:
                    return
                n = next_n
                inflight[0] = n
                upto = shadow or written
                summ = summary
            raw, done, why = _gen_one(n, upto, summ, max_retries)
            with cond:
                inflight[0] = 0
                if stop_flag.is_set():
                    cond.notify_all()
                    return
                if done:
                    pool.append((n, raw, True))          # 收尾段（可能为空）
                    next_n = n + 1
                    cond.notify_all()
                    return
                if not raw:
                    stop_reason[0] = why or "预取失败"
                    cond.notify_all()
                    return
                pool.append((n, raw, False))
                # 影子正文 = 已提交 + 池内全部：下一段的锚点/去重基准才是对的
                shadow = (written + "".join(p for _, p, _ in pool))
                next_n = n + 1
                cond.notify_all()

    def _merge(raw):
        """去重 + 断句。返回 (可提交片段, 残留半句, 说明)。片段为空时说明里给原因。"""
        nonlocal dedup_chars
        body = raw
        if written:
            ov = overlap_len(written, body)
            if ov >= _MIN_OVERLAP:
                body = body[ov:]
                dedup_chars += ov
        # 再过滤"整句复读"（接缝裁剪管不到段中间/段尾的复读）
        body, dropped = drop_repeated_sentences(body, seen_sents)
        dedup_chars += dropped * 20      # 按句粗估裁掉的字符量，只用于汇报
        if not body.strip():
            return "", "", "整段都是重复内容"
        complete, rest = cut_at_sentence(body)
        if not complete:
            complete, rest = body, ""     # 整段不成句 → 原样用，别丢内容
        return complete, rest, ""

    while True:
        if should_stop and should_stop():
            stop_reason[0] = "用户叫停"
            break

        # ---- 取一段：优先缓冲池；池空但有人在预取就等它（绝不重复生成同一个 n）----
        item = None
        if parallel_prefetch:
            with cond:
                if pool:
                    item = pool.pop(0)
                elif inflight[0]:
                    deadline = time.time() + 300
                    while not pool and inflight[0] and time.time() < deadline:
                        cond.wait(timeout=0.2)
                    if pool:
                        item = pool.pop(0)
        if item is None:
            with cond:
                n_try = next_n
                inflight[0] = n_try          # 认领，免得预取线程同时产出同一个 n
            raw, done, why = _gen_one(n_try, written, summary, max_retries)
            with cond:
                inflight[0] = 0
                cond.notify_all()
            if not raw and not done:
                stop_reason[0] = why or ("校验不通过（连续 %d 次）" % max_retries)
                break
            item = (n_try, raw, done)
            with cond:
                next_n = n_try + 1
                shadow = written + "".join(p for _, p, _ in pool)

        n, raw, done = item
        if not raw:
            stop_reason[0] = "模型声明完成"
            break

        # ---- 合并（去重 + 断句）----
        piece, rest, mwhy = _merge(raw)
        if not piece:
            retry_ctr[0] += 1
            if retry_ctr[0] >= max(1, max_retries) * 3:
                stop_reason[0] = mwhy or "连续产出重复内容"
                break
            continue

        written += piece
        carry = rest
        chunks.append({"n": n, "chars": len(piece)})
        if summary_interval and (n % summary_interval == 0):
            summary = _brief(written, 300)
        if on_chunk:
            try:
                on_chunk(piece, n, len(written))
            except Exception:
                pass                       # 推流失败不能中断生成

        if done:
            stop_reason[0] = "模型声明完成"
            break
        if max_total and len(written) + len(carry) >= int(max_total):
            stop_reason[0] = "达到目标长度（%d 字）" % int(max_total)
            break
        if n >= 2000:                      # 兜底：真要一直写也不会无限循环
            stop_reason[0] = "达到单段数上限（2000 段）"
            break

        # ---- 把下一段预取起来（占住"客户端正在渲染本段"的这段时间）----
        if parallel_prefetch:
            with cond:
                shadow = written + "".join(p for _, p, _ in pool)
            threading.Thread(target=_prefetch, daemon=True).start()

    stop_flag.set()
    text = written + carry
    return {"text": text, "chunks": chunks, "chars": len(text),
            "stopped": stop_reason[0] or "未知", "elapsed_s": round(time.time() - t0, 2),
            "dedup_chars": dedup_chars, "retries": retry_ctr[0],
            "target_chars": max_total, "seams": max(0, len(chunks) - 1)}


def needs_continuation(task, cfg=None):
    """这一轮要不要走续写？—— 只有用户**明确要长文**才走，短回答一律不触发（用户无感）。

    判据：① 任务里写明了目标字数（"写 3000 字…"）；或 ② capabilities 里打开 always。
    """
    cfg = cfg or {}
    if cfg.get("enabled") is False:
        return False
    if cfg.get("always"):
        return True
    t = parse_target_chars(task)
    return bool(t and t >= int(cfg.get("min_chars", 800) or 800))
