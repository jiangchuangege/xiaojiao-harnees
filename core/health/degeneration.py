# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 健康系统 · 退化检测（复读 / 低多样性）＝ Bug 3 的地基

【为什么必须存在】（真实现象，用户实测）
    让它「写 3000 字产品介绍」，写到某处开始反复吐：
        「然后说：嗯。然后说：哦。然后说：好的。」
    循环二十几次，后面几千字全是这一句的变体。
    这不是"模型坏了"，是**退化**：小模型每个 token 都倾向选最高频的那个，
    一旦吐出重复片段，重复片段本身就成了"最高频"，自回归地自我强化 —— 出不来。

【为什么不能在合并期去重了事】
    `core/continuation.py` 里已经有 `drop_repeated_sentences` / `drop_repeated_paragraphs`，
    但它们是**合并期**去重：处理的是"段与段之间"的重复。
    而 Bug 3 的复读发生在**同一段内部**——那一段还没交给合并流程，
    模型已经在一个请求里把 2000 token 全烧在复读上了。
    等合并期再删，删掉的是**整段**（内容已经废了），等于这一轮白跑。
    所以必须在**模型正在吐字的时候**就发现、就截断 —— 这就是本模块的职责。

【去掉它会怎样】
    · 一旦退化，用户拿到的是几千字垃圾（现在就是）；
    · 更糟：这段垃圾会进历史、进向量库，下一轮又被当成"上下文"喂回去，
      退化的内容会**污染长期记忆**，越滚越坏。
    · 所以它不是一个"可选优化"，是防止退化扩散的**闸门**。

【三类判据（对应退化在文本上的三种形态）】
    ① `phrase_repeat`   连续串联重复：`(.{L})\1{2,}` —— "嗯。嗯。嗯。嗯。"
    ② `ngram_repeat`    非连续高频：短块**扎堆**出现 ——
                        用户那句「然后说：嗯/哦/好的」正是这一类：**共享骨架是"然后说："**，
                        中间的字每次不同，所以连续串联检测抓不到它，
                        只有"短块高频 + 密集 + 占满窗口"才抓得到。
    ③ `low_diversity`   **二元组多样性**塌陷：尾部窗口里去重后的相邻字对比例掉到阈值以下 ——
                        兜住"每次都不一样但都极短"的变体复读（"嗯。哦。好的。"这种）。

【为什么阈值必须比"直觉"保守得多（本轮实测踩到，写下来免复发）】
    ① 短块（≤3 字）要求 **5 次**以上：`好的好的好的`、`哈哈哈哈` 是**正常口语修辞**，
       不是退化 —— 第一版按"≥3 次"判，实测把这些正常回答也截断了。
       只有连说五遍以上才叫失控。
    ② 非连续高频光看"出现次数"不够：`在 A 的时候…在 B 的时候…在 C 的时候…` 这种
       **合法枚举**也会让"的时候"这种 3-gram 密集出现。所以还要看**密度**：
       重复片段必须占满它所在跨度的一大半（≥30%），枚举的密度只有两成。
    ③ 多样性判据第一版用**单字**去重比例 —— 英文 200 字里只有 26 个字母，
       比例天然就低到 0.2，会把正常英文段落判成退化。改成**二元组**（相邻两字/两词）
       多样性：正常文本里几乎每对都不同（≈0.9），复读时只剩十来个（≤0.1），
       这个指标与语言无关，中英都稳。
    —— 一句话：宁可漏判一次，也绝不能把正常回答截断。截断是**不可逆**的破坏。
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

try:                                    # 日志目录跟随仓库根，别写到 CWD 去
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
except Exception:                       # noqa: silent-ok — 取不到就用相对路径，不影响检测
    _ROOT = "."
_HEALTH_DIR = os.path.join(_ROOT, "logs", "health")

# 只认"有实义"的字符作为重复块的成分：纯标点重复（"。。。"）不算退化，
# 否则一段正经的省略号会被误判成复读。
_MEANINGFUL = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbfA-Za-z0-9]")
# 句末标点（回退用；与 continuation 的口径保持一致）
_SENT_END = "。！？!?；;…"


# 句读类标点**一律豁免**单字符洪水判定：100 字里 10 个逗号是标准中文行文，
# 把它们算成"刷屏"会让每一段正常文字都被判成退化（那这条判据就成了纯误报源）。
_FLOOD_EXEMPT = frozenset("。！？，、；：…—～·「」『』“”‘’（）《》〈〉【】\"'`")
# 符号/ASCII 标点：正常行文里不可能 100 字挤 10 个，门槛低
_SYMBOL_CHARS = frozenset("/\\|*+=#~^<>$%&@_-")


def _is_symbol(ch):
    """这个字符算不算"符号类"（→ 用低门槛）。中文/字母/数字用高门槛。"""
    if ch in _SYMBOL_CHARS:
        return True
    o = ord(ch)
    return 33 <= o <= 47 or 58 <= o <= 64 or 91 <= o <= 96 or 123 <= o <= 126


@dataclass
class DegenerationHit:
    """一次退化命中的完整证据（要能落进病历，也能拿来截断）。"""
    kind: str                 # phrase_repeat / ngram_repeat / low_diversity
    phrase: str               # 重复的那个片段
    count: int                # 重复次数
    at: int                   # 第一次出现的位置（字符下标）
    keep_until: int           # 截断点：保留 text[:keep_until]
    detail: str = ""
    where: str = ""            # 哪里发现的（stream / final / single …）
    ts: float = field(default_factory=time.time)

    def to_dict(self):
        return {"ts": self.ts, "where": self.where, "kind": self.kind, "phrase": self.phrase,
                "count": self.count, "at": self.at, "keep_until": self.keep_until,
                "detail": self.detail}

    def __str__(self):
        return "[%s] %r ×%d @%d（%s）" % (self.kind, self.phrase, self.count, self.at, self.detail)


def _find_keep_until(text, phrase, keep, start=0, max_gap=None):
    """找到 phrase 在 text 里的第 (keep+1) 次「密集出现」的起点 —— 那就是截断点。

    为什么要 `max_gap`：慢速复读（同一句话隔 500 字出现一次）是**正常写作**，不能截。
    只有"扎堆出现"才是退化。`max_gap=None` 表示不限间隔（连续串联重复用）。
    返回 -1 表示凑不够 keep+1 次。
    """
    if not phrase or keep < 1:
        return -1
    occ, i = [], start
    while True:
        j = text.find(phrase, i)
        if j < 0:
            break
        occ.append(j)
        i = j + len(phrase)
        if len(occ) > keep:                # 只需要前 keep+1 个
            break
    if len(occ) <= keep:
        return -1
    if max_gap is not None:
        for k in range(1, keep + 1):       # 密集性：相邻两次的间隔必须够小
            if occ[k] - occ[k - 1] > max_gap:
                return -1
    return occ[keep]


class DegenerationDetector:
    """增量式退化检测器：流式每来一小片就 `feed()` 一次，命中立刻返回并**锁存**。

    为什么是"锁存"（一旦命中就不再改判）：
      上层拿到命中就要终止生成、回退、补结尾。若下一次 feed 又返回 None，
      上层会以为"没事了"继续流 —— 复读会继续长出来。锁存让判定**单向不可逆**。

    为什么要 `min_chars`：开头的几十个字本来就短，任何"重复"都是统计噪声
      （比如第一句就是"你好。你好。"），过早触发会把正常回答截掉。
    """

    def __init__(self, phrase_min_repeat=3, phrase_short_repeat=5, phrase_short_len=3,
                 phrase_min_len=2, phrase_max_len=12,
                 ngram_n=3, ngram_min_repeat=4, ngram_window=300, ngram_max_gap=30,
                 ngram_min_density=0.30, ngram_scan=4000,
                 flood_window=100, flood_symbol_repeat=10, flood_char_repeat=25,
                 flood_min_share=0.35,
                 div_window=200, div_threshold=0.35, min_chars=60, check_every=10):
        self.phrase_min_repeat = int(phrase_min_repeat)
        self.phrase_short_repeat = int(phrase_short_repeat)
        self.phrase_short_len = int(phrase_short_len)
        self.phrase_min_len = int(phrase_min_len)
        self.phrase_max_len = int(phrase_max_len)
        self.ngram_n = int(ngram_n)
        self.ngram_min_repeat = int(ngram_min_repeat)
        self.ngram_window = int(ngram_window)
        self.ngram_max_gap = int(ngram_max_gap)
        self.ngram_min_density = float(ngram_min_density)
        self.ngram_scan = int(ngram_scan)
        self.flood_window = int(flood_window)
        self.flood_symbol_repeat = int(flood_symbol_repeat)
        self.flood_char_repeat = int(flood_char_repeat)
        self.flood_min_share = float(flood_min_share)
        self.div_window = int(div_window)
        self.div_threshold = float(div_threshold)
        self.min_chars = int(min_chars)
        self.check_every = max(1, int(check_every))
        # 默认跑的**强判据**；弱判据（多样性塌陷）单独放，只在体检时按需启用。
        self._probes = (self._probe_phrase, self._probe_ngram, self._probe_char_flood)
        self._weak_probes = (self._probe_diversity,)
        self.reset()

    # ---------- 生命周期 ----------
    def reset(self):
        self._text = ""
        self._hit: Optional[DegenerationHit] = None
        self._n_feed = 0
        self._checked_at = 0

    @property
    def text(self):
        return self._text

    @property
    def hit(self) -> Optional[DegenerationHit]:
        return self._hit

    # ---------- 增量入口（流式用）----------
    def feed(self, text) -> Optional[DegenerationHit]:
        """喂一小片；只在每 `check_every` 片、或新增长度够多时真跑检测（省 CPU）。

        流式每个 delta 都跑一遍全量检测代价不小（尾部窗口 + 多周期扫描），
        而退化是"重复几十次"才成灾的，隔十几片查一次完全来得及 —— 这就是 check_every 的意义。

        两个触发条件取**先到者**：
          · 片数（每 `check_every` 片）—— 对应需求里的"SSE 每 10~20 chunk 跑一次"；
          · 字数（累计新增 ≥60 字）—— 片很小时不至于"攒到十几片才查"。
        两句都要，是因为片的大小不确定（模型快时一片几十字，慢时一片三五字）。
        这里从 15/120 收紧到 10/60 是**实测调出来的**：原来从复读开始到掐断要读掉
        ~240 字（十几遍复读已经推给前端了），收紧后只读 ~60 字就掐断。
        代价是检测次数翻倍，但整段检测只要 0.003s/万字 —— 相对于省下的复读流量，完全划算。
        """
        if not text:
            return self._hit
        self._text += text
        self._n_feed += 1
        if self._hit is not None:
            return self._hit
        if len(self._text) < self.min_chars:
            return None
        if (self._n_feed % self.check_every) == 0 or (len(self._text) - self._checked_at) >= 60:
            self._checked_at = len(self._text)
            return self.check(self._text)
        return None

    # ---------- 一次性整段检测 ----------
    def check(self, text, where="", weak=False) -> Optional[DegenerationHit]:
        """对整段文本跑判据，返回第一个命中（同时锁存）。

        `self._text` 一并记住这段文本：命中点在**这段文本**上的坐标才有意义，
        调用方随后 `truncated()` 时不必再把原文递一遍（流式路径里原文就是它）。

        `weak=False`（默认）：只跑 `phrase_repeat` + `ngram_repeat` 两个**强判据**。
        `weak=True`：额外跑 `low_diversity`（**多样性塌陷**）。
        —— 为什么默认不跑它（本轮实测踩到的坑）：它是"弱判据"，会误杀**模板化的正常文本**。
        续写单测里那个假模型每句都套同一个句式（"第 N 段的产品介绍讲到这里，小焦把上下文…"），
        二元组多样性掉到 0.23，被当成退化截断了 —— 可那是**合法写作**（列举/编号列表都长这样）。
        截断是不可逆的破坏，所以宁可把它降级成"只在健康体检里当弱信号"，也不放进默认链路。
        """
        t = text if text is not None else self._text
        if text is not None:
            self._text = t                      # 让 keep_until 的坐标系与 _text 对齐
        if len(t) < self.min_chars:
            return self._hit
        probes = list(self._probes)
        if weak:                               # 弱判据只在需要时启用（默认不启用，见下）
            probes += list(self._weak_probes)
        for probe in probes:
            hit = probe(t)
            if hit:
                hit.where = where
                self._hit = hit
                log_hit(hit)
                return hit
        return None

    # ---------- ① 连续串联重复 ----------
    def _probe_phrase(self, t):
        best = None
        for L in range(self.phrase_min_len, self.phrase_max_len + 1):
            # 只要周期为 L 的串联重复：`(.{L})\1{2,}`（Python 的 `.` 不匹配换行，正好避开跨段误判）
            for m in re.finditer(r"(.{%d})\1{2,}" % L, t, re.S):
                blk = m.group(1)
                if not _MEANINGFUL.search(blk):        # 纯标点/空白不算
                    continue
                reps = len(m.group(0)) // L
                # 短块（≤3 字）门槛更高：'好的好的好的' / '哈哈哈哈' 是正常口语修辞，不是退化。
                # 这是本轮实测抓到的**误杀**（第一版按 ≥3 判，把正常回答也截了）。
                need = self.phrase_short_repeat if L <= self.phrase_short_len else self.phrase_min_repeat
                if reps < need:
                    continue
                keep = need - 1                        # 「保留前 2 次」（短块则保留前 4 次）
                keep_until = m.start() + keep * L
                cand = DegenerationHit(
                    kind="phrase_repeat", phrase=blk, count=reps, at=m.start(),
                    keep_until=keep_until,
                    detail="短语连续重复 %d 次（阈值 %d，块长 %d）" % (reps, need, L))
                if best is None or cand.count > best.count:
                    best = cand
        return best

    # ---------- ② 非连续高频短块（用户那句"然后说：…"就是这一类）----------
    def _probe_ngram(self, t):
        tail = t[-self.ngram_window:]
        base = len(t) - len(tail)
        n = self.ngram_n
        if len(tail) < n * self.ngram_min_repeat:
            return None
        freq = {}
        for i in range(0, len(tail) - n + 1):
            g = tail[i:i + n]
            if not _MEANINGFUL.search(g):
                continue
            if len(set(g)) == 1:        # 全同一个字（"哈哈哈哈"）：那是笑声，不是退化
                continue
            freq.setdefault(g, []).append(i)
        best = None
        for g, poss in freq.items():
            if len(poss) < self.ngram_min_repeat:
                continue
            # 把"扎堆"的连续段切出来：相邻两次间隔 > ngram_max_gap 就算断档。
            runs, start = [], 0
            for k in range(1, len(poss)):
                if poss[k] - poss[k - 1] > self.ngram_max_gap:
                    runs.append((start, k))
                    start = k
            runs.append((start, len(poss)))
            a, b = max(runs, key=lambda r: r[1] - r[0])
            seg = poss[a:b]                            # 最长的一段密集重复
            if len(seg) < self.ngram_min_repeat:
                continue
            span = seg[-1] - seg[0]
            # 重叠匹配会**虚增**次数："哈哈哈哈" 会算成 6 个"哈哈哈"（位置 0~5，跨度只有 5）。
            # 所以要求跨度至少装得下 min_repeat 个**不重叠**的片段 —— 这个下限把重叠噪声挡掉。
            if span < n * (self.ngram_min_repeat - 1):
                continue
            # 密度：重复片段本身必须占满这段跨度的一大半。
            # 没有它，"在 A 的时候…在 B 的时候…"这种**合法枚举**会被误判（实测）。
            density = (len(seg) * n) / float(span + n)
            if density < self.ngram_min_density:
                continue
            # ---- 截断点：必须落在**失控的起点**，不是"窗口里第 4 次" ----
            # 只在尾部窗口里找，会得到一个很靠后的位置：一篇 3000 字的正文从第 2800 字开始复读，
            # 窗口里第 4 次重复可能已经在第 2900 字，那样会**把前面 100 字的垃圾也留下**（实测）。
            # 所以判定成立之后，回到全文（最多回溯 ngram_scan 字）找出这段密集重复真正的起点。
            run = self._dense_run(t, g, target=base + seg[-1])
            if len(run) >= self.ngram_min_repeat:
                keep = self.ngram_min_repeat - 1       # 保留前 3 次
                cut = run[keep] if len(run) > keep else run[-1]
                run_len, run_span = len(run), run[-1] - run[0]
            else:
                keep = self.ngram_min_repeat - 1
                cut = base + seg[keep]
                run_len, run_span = len(seg), span
            cand = DegenerationHit(
                kind="ngram_repeat", phrase=g, count=run_len,
                at=run[0] if len(run) >= self.ngram_min_repeat else base + seg[0],
                keep_until=cut,
                detail="短块 %r 扎堆重复 %d 次（跨度 %d 字，密度 %.0f%%）"
                       % (g, run_len, run_span, density * 100))
            if best is None or cand.count > best.count:
                best = cand
        return best

    def _dense_run(self, t, g, target, limit=None):
        """在全文里找包含 `target` 位置的那一段"密集重复"的全部出现位置。

        为什么不能只看尾部窗口：窗口只有 300 字，而一次退化可能连着重复 2000 字。
        只看窗口 → 拿到的是窗口里第 4 次重复的位置 → 前面那一大段复读**留在正文里**。
        回溯范围受 `ngram_scan` 限制（默认 4000 字），既够用又不会在大文本上拖慢。
        """
        lo = max(0, len(t) - int(limit or self.ngram_scan))
        seg_text = t[lo:]
        pos = [lo + m.start() for m in re.finditer(re.escape(g), seg_text)]
        if not pos:
            return []
        # 找到 target 所属的密集段（相邻间隔 <= max_gap 视为同一段）
        runs, start = [], 0
        for k in range(1, len(pos)):
            if pos[k] - pos[k - 1] > self.ngram_max_gap:
                runs.append((start, k))
                start = k
        runs.append((start, len(pos)))
        hitrun = None
        for a, b in runs:
            if pos[a] <= target <= pos[b - 1] + len(g):
                hitrun = (a, b)
                break
        if hitrun is None:
            return []
        # 再往后延伸（尾部窗口之外的后续出现也该算进同一段）
        a, b = hitrun
        return pos[a:b]

    # ---------- ③ 单字符洪水（问题 1 实测：整屏「/」或整屏「预算」）----------
    def _probe_char_flood(self, t):
        """同一个字符在很近的距离里刷屏 → 触发。

        为什么必须单独有这一条（用户实测抓到的漏检）：
        前面两条判据都要求"**片段**重复"，而实测里最刺眼的退化形态是**同一个字符刷屏** ——
        表格被 "预算" 填满、分隔符被 "/" 刷几十遍。这类文本里：
          · `phrase_repeat` 可能因为整段没有形成"周期块"而抓不到；
          · `ngram_repeat` 要求块里**有实义字**，一整行 "//////" 直接被它跳过。
        于是"整屏都是同一个符号"这种最明显的退化，反而是三条判据里唯一漏掉的一类。

        阈值分两档，是因为不同字符"正常出现"的频率差了几个数量级：
          · **符号类**（/ | * - = # + 等）：100 字里出现 ≥10 次就不正常了 ——
            正常文章里不可能有 10 个斜杠挤在 100 字内。
          · **中文/字母/数字**：正常行文里"的"在 100 字里出现 8~12 次是很正常的，
            所以门槛必须高得多 —— 用 ≥25 次（占该窗口 1/4），那已经不是行文，是刷屏。
        句读类标点（。！？，、；：）**一律豁免**：100 字里 10 个逗号是标准中文。

        【光看次数会误杀 markdown 表格（实测当场抓到）】
        第一版只看"次数 ≥10" —— 一张**完全正常**的 4 行表格里 `|` 就出现 21 次，
        于是每一张正常表格都会被判成刷屏。次数根本不是"刷屏"的判据，
        **占满窗口的比例**才是：
          · `/` ×60 在 69 字里 → 占 87%（刷屏，该拦）
          · 正常表格的 `|` 21 次在 113 字里 → 占 18%（是格式，不该拦）
        所以最终判据是"次数够多 **且** 该字符占这个窗口的 35% 以上"。
        表格、编号列表、分隔线的占用率都远低于这条线，只有真正的刷屏才过得去。
        """
        window = t[-self.flood_window:]
        if len(window) < 60:
            return None
        counts = {}
        for ch in window:
            if ch.isspace():
                continue
            if ch in _FLOOD_EXEMPT:
                continue
            counts[ch] = counts.get(ch, 0) + 1
        best = None
        for ch, n in counts.items():
            limit = self.flood_symbol_repeat if _is_symbol(ch) else self.flood_char_repeat
            if n < limit:
                continue
            if (n / float(len(window))) < self.flood_min_share:
                continue                      # 次数够但没占满窗口 → 是格式（表格/列表），不是刷屏
            if best is None or n > best.count:
                best = (ch, n)
        if best is None:
            return None
        ch, n = best
        # 截断点：保留到"洪水"开始之前的那一段（前面正常内容一个字不动）
        cut = self._flood_start(t, ch)
        share = n / float(len(window))
        return DegenerationHit(
            kind="char_flood", phrase=ch, count=n, at=max(0, cut),
            keep_until=max(0, cut),
            detail="字符 %r 在 %d 字里刷了 %d 次（占 %.0f%%，阈值 次数≥%d 且占比≥%.0f%%）"
                   "→ 单个字符刷屏式复读"
                   % (ch, len(window), n, share * 100,
                      self.flood_symbol_repeat if _is_symbol(ch) else self.flood_char_repeat,
                      self.flood_min_share * 100))

    def _flood_start(self, t, ch):
        """洪水从哪儿开始的：从后往前扫，跳过密集区，停在"还正常"的位置。

        判据：以该字符的平均间隔的两倍为界 —— 一段里间隔一旦超过它，就不属于这次刷屏。
        找不到就退到"最后 120 字之前"，宁可多砍一点也不能把刷屏留在正文里。
        """
        try:
            pos = [i for i, c in enumerate(t) if c == ch]
            if len(pos) < 2:
                return max(0, len(t) - 120)
            span = pos[-1] - pos[0]
            gap = max(2, int(span / max(1, len(pos) - 1)) * 2)
            start = pos[-1]
            for i in range(len(pos) - 2, -1, -1):
                if pos[i + 1] - pos[i] > gap:
                    break
                start = pos[i]
            return max(0, start - 1)
        except Exception:      # noqa: silent-ok — 算不出来就退到保守位置
            return max(0, len(t) - 120)

    # ---------- ④ 二元组多样性塌陷（弱判据，默认不跑） ----------
    def _probe_diversity(self, t):
        tail = t[-self.div_window:]
        if len(tail) < self.div_window:
            return None
        pairs = [tail[i:i + 2] for i in range(len(tail) - 1)]
        if not pairs:
            return None
        ratio = len(set(pairs)) / float(len(pairs))
        if ratio >= self.div_threshold:
            return None
        return DegenerationHit(
            kind="low_diversity", phrase=tail[-20:], count=len(tail),
            at=len(t) - len(tail), keep_until=max(0, len(t) - len(tail)),
            detail="尾部 %d 字的相邻字对只用了 %.0f%% 种（阈值 %.0f%%）→ 词汇多样性塌陷"
                   % (len(tail), ratio * 100, self.div_threshold * 100))

    # ---------- 截断 ----------
    def truncated(self, text=None, hit=None):
        """按命中点截断：保留复读**之前**的内容 + 前 2 次重复，返回 (文本, 砍掉字数)。

        为什么要"保留前 2 次"而不是直接砍到复读起点之前：那两遍往往还读得通
        （"然后说：嗯。然后说：哦。"），一刀切到起点会让上下文断得很生硬；
        保留两遍再由 `repair_tail` 回退到完整句，读起来最自然。
        """
        t = self._text if text is None else text
        h = hit or self._hit
        if h is None or not t:
            return t, 0
        # 命中点可能在**旧文本**上算出来（流式边收边判），而调用方给的是新文本 ——
        # 所以一律夹到当前长度之内，绝不越界，也绝不因为"位置过期"而整段丢掉。
        cut = max(0, min(int(h.keep_until), len(t)))
        return t[:cut].rstrip(), len(t) - cut


def repair_tail(text):
    """回退到最后一个完整句，保证不把半句留给用户（返回 (新文本, 砍掉字数)）。

    为什么必须做：截断点落在句中时，正文会以"……然后说：嗯。然后说："收尾 ——
    用户看到的就是"像断网一样突然断了"。宁可少几字，也要落在句号上。
    """
    t = text or ""
    if not t.strip():
        return t, 0
    if t.rstrip()[-1] in _SENT_END or t.rstrip().endswith(("\n", "”", "\"", "）", ")")):
        return t, 0
    idx = max(t.rfind(ch) for ch in _SENT_END)
    if idx < 0:
        return t, 0
    return t[:idx + 1], len(t) - (idx + 1)


def detect(text, where="", weak=False, **kw) -> Optional[DegenerationHit]:
    """一次性检测（不锁存、不带状态）—— 给"事后体检"和单测用。"""
    d = DegenerationDetector(**kw)
    return d.check(text, where=where, weak=weak)


def truncate_repeat(text, hit=None, **kw):
    """一步到位：检测 → 截断 → 回退完整句。返回 (文本, hit, 砍掉字数)。

    这是给**非流式**路径（普通回答、续写的非流式分支）用的入口：
    它们拿到的已经是完整文本，没有"边收边判"的机会，只能在事后补一刀。
    """
    t = text or ""
    if hit is None:
        hit = detect(t, where="final", **kw)
    if hit is None:
        return t, None, 0
    cut = max(0, min(int(hit.keep_until), len(t)))
    t2, _ = repair_tail(t[:cut].rstrip())
    return t2, hit, len(t) - len(t2)


def log_hit(hit, extra=None):
    """把一次退化写进 `logs/health/degeneration.jsonl`（病历的原料）。

    为什么要落盘：退化的**分布**比单次更重要 —— 一天触发 40 次说明这个火种
    在当前上下文长度下不稳定，该降级/该换火种；只触发 1 次就是偶发，不用管。
    没有这份流水，"该不该干预"就只能靠猜。
    """
    try:
        os.makedirs(_HEALTH_DIR, exist_ok=True)
        row = hit.to_dict() if isinstance(hit, DegenerationHit) else dict(hit or {})
        if extra:
            row.update(extra)
        with open(os.path.join(_HEALTH_DIR, "degeneration.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上病历也绝不能影响对话
        pass


def summary(days=7):
    """统计最近 N 天的退化情况：次数 / 类型分布 / 高频短语（给体检报告用）。"""
    import datetime
    path = os.path.join(_HEALTH_DIR, "degeneration.jsonl")
    out = {"total": 0, "by_kind": {}, "top_phrases": [], "days": days}
    if not os.path.exists(path):
        return out
    since = time.time() - days * 86400
    phrases = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if float(r.get("ts") or 0) < since:
                    continue
                out["total"] += 1
                k = r.get("kind") or "?"
                out["by_kind"][k] = out["by_kind"].get(k, 0) + 1
                p = (r.get("phrase") or "")[:24]
                if p:
                    phrases[p] = phrases.get(p, 0) + 1
    except Exception:      # noqa: silent-ok — 病历读不动就当空的
        return out
    out["top_phrases"] = sorted(phrases.items(), key=lambda x: -x[1])[:10]
    out["since"] = datetime.datetime.fromtimestamp(since).strftime("%Y-%m-%d %H:%M")
    return out
