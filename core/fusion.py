# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 融合边界（2026-10-30，第二轮：死模板一律不许出现）

【用户原话】
  「我是说不止这一条是所有的都要AI不要模板直接，而且不只有对话，甚至插件，等等都不要直接模板
    都是通过AI，所有的，载体的所有都要融入到AI，AI也要融入到载体，这样就更强大了成为一体」
  「模型没起来时它替代不了模型…… 我说了宁愿牺牲一部分时间，我也不要死模板，明白？」
  → 定死：**不许因为"模型没应答"就把模板原样甩出去**。宁愿多花时间，甚至换一颗火种再说。

【这份文件解决什么】
  载体（工具/插件/规则）拿到的结果，出到用户眼前之前都要**变成人说的话**。
  以前各路由各拼一份模板（「🌐 …实测」+代码块、「🔧 …实测结果」+代码块、「最近的任务（N 条）」…），
  人看到的是机器排版。现在只有这一条边界，写法与账目都只有一份。

【模型这条链是怎么排的（一级一级退，退到最后也没有模板）】
  ① 当前火种（两次尝试 —— 本机 llama-swap 偶发 500）；
  ② **换火种**：旁边还有 coder / deepseek-v4 / qwopus… 就换一颗问（载体能换火，这是载体优先的应有之义）；
  ③ 还不行 → 载体**自己组织成人话**（`prose`）：按数据的结构说成句子，
     不是「标题 + 代码块」那种死模板，也不假装是模型说的。

【谁在说话，必须可查（"如实标注"的落点）】
  每次判定落 `logs/fusion.jsonl`，状态只有这几种，绝不混用：
    · clean   —— 本来就不是模板（模型自己说的话），不动
    · ai      —— 模型改述了（附模型名/耗时/字数）
    · prose   —— 所有火种都没应答 → 载体自己组织成人话（**不是死模板**），并如实标注
    · exempt  —— 按规矩不能改述（待确认 / 红线 / 禁区 / 工程类代码块）
    · kept    —— 已废弃（保留只为旧账兼容）；正常情况下不会再产生
  `stats()` 现算比例，`/proof` 页面直接显示。

【边界（不粉饰）】
  · 只改说法，不改事实：原文里的量一条不许改、不许少；缺的补一行「原始要点」。
  · 结构化面板数据（JSON 状态、图表数据）不走这条路：那不是"话"，硬转述只会失真。
  · 换火种会慢（每颗几秒），用户已明确接受这个代价 —— 慢比死模板好。
"""
import io
import json
import logging
import os
import re
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG = os.path.join(_ROOT, "logs", "fusion.jsonl")

_LLM = None          # 当前火种（app 注入 llm_chat）
_ALT = None          # 换火种的调用器（app 注入；签名为 alt(messages, temperature) -> text）
_LLM_NAME = ""

# 模板的三种长相（判据宁可窄：误改一回正常回答，比漏改十条更糟）
_EMOJI = ("🔧", "🌐", "💻", "📋", "🎯", "📈", "🧾", "🩺", "📊", "🧪", "🛠", "🚀", "📄", "🗂", "🔎")
_PHRASES = ("实测结果", "载体实取", "未经模型转述", "极快直通", "原始数据如下", "没能把数据讲成话")
_SKIP = ("〔待确认〕", "红线", "禁区", "已拦截")
_CODE_Q = re.compile(r"(写代码|代码|函数|脚本|实现|报错|bug|debug|sql|正则|html|css|json|yaml)", re.I)


def install(llm_fn=None, model_name="", alt_fn=None):
    """app 启动时注入火种。重复调用无副作用（None 不会覆盖已有值）。"""
    global _LLM, _ALT, _LLM_NAME
    if llm_fn is not None:
        _LLM = llm_fn
    if alt_fn is not None:
        _ALT = alt_fn
    if model_name:
        _LLM_NAME = str(model_name)


def looks_templated(text, question=""):
    """这条输出是不是载体拼的死模板（而不是人说的话）？"""
    a = str(text or "").strip()
    q = str(question or "")
    if not a or len(a) < 12:
        return False
    if any(w in a[:160] for w in _SKIP):
        return False
    if "```" in a and _CODE_Q.search(q):
        return False          # 工程类提问：代码块就是用户要的东西
    if a.startswith(_EMOJI):
        return True
    if any(p in a for p in _PHRASES):
        return True
    if re.match(r"^[^\n]{0,60}\n+\s*```[\s\S]*```\s*$", a):
        return True
    return False


def _exempt(text, question="", kind=""):
    """按规矩不能改述的：安全原文、工程类代码块、以及显式声明的 kind。"""
    a = str(text or "")
    if str(kind or "") in ("confirm", "redline", "safety", "code", "raw_data"):
        return True
    if any(w in a[:160] for w in _SKIP):
        return True
    if "```" in a and _CODE_Q.search(str(question or "")):
        return True
    return False


def _record(state, kind, question, src, out, why="", extra=None):
    """落一条可查的记录：谁说的、改了多少字、为什么。"""
    try:
        os.makedirs(os.path.dirname(_LOG), exist_ok=True)
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "state": state,
               "kind": str(kind or ""), "q": str(question or "")[:80],
               "src_chars": len(str(src or "")), "out_chars": len(str(out or "")),
               "model": _LLM_NAME, "why": str(why or "")}
        if extra:
            row.update(extra)
        with io.open(_LOG, "a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:      # noqa: silent-ok — 记账失败绝不影响回答
        LOG.debug("融合记账失败（忽略）：%s", e)


def _numbers(text):
    """要保真的量。

    · 两位以上或带小数的数字 → 一律算量；
    · 一位数但**带单位**（条/步/个/项/行/次/名/份/张/秒/分/时/%）→ 也算量
      （实测任务表的关键量就是「8 条」这种一位数）；
    · 其余一位数（"第2步"这类序数）不算，否则会逼模型说废话。
    """
    t = str(text or "")
    out = []
    for n in dict.fromkeys(re.findall(r"\d+(?:\.\d+)?", t)):
        if "." in n or len(n) >= 2:
            out.append(n)
    for n in re.findall(r"(\d+)\s*(?:条|步|个|项|行|次|名|份|张|秒|分钟|小时|天|人|%)", t):
        if n not in out:
            out.append(n)
    return out


# ---------------- 退到底：载体自己组织成人话（不是死模板） ----------------
def _prose_from(text, label=""):
    """把结构化记录说成句子（载体自己说，不调模型）。

    只在**所有火种都没应答**时用。原则：只说记录里有的；按状态归类；
    绝不产出「emoji 标题 + 代码块」这种死模板 —— 那是用户明确不要的东西。
    """
    raw = str(text or "").strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    body = [l for l in lines if not l.startswith(("📋", "```", "|--"))]
    rows = [l for l in body if l.startswith(("-", "*", "·"))]
    if not rows:
        rows = [l for l in body if len(l) > 6][:10]
    what = (label or "记录").replace("（载体实取）", "").strip()

    def _clean(r):
        # 表格里的竖线在口语里是停顿，不是分隔符 —— 换成顿号，读起来才像人话
        t = re.sub(r"^[-*·\s`]+", "", r)
        t = re.sub(r"[`]", "", t)
        t = re.sub(r"\s*[|\uff5c]\s*", "、", t)
        return t.strip()

    # 一、看起来是"键: 值"的单行（IP/时钟这类）
    pairs = []
    for r in body[:8]:
        m = re.match(r"^([\u4e00-\u9fa5A-Za-z ]{1,8})\s*[:：]\s*(.+)$", _clean(r))
        if m:
            pairs.append((m.group(1).strip(), m.group(2).strip()))
    if pairs and len(pairs) >= 2:
        head = "、".join("%s是%s" % (k, v) for k, v in pairs[:4])
        return ("%s：%s。" % (what, head)).replace("：是", "是")

    # 二、有状态的行（任务/项目这种）
    st = {"完成": 0, "失败": 0, "在跑": 0, "待": 0}
    for r in rows:
        if "完成" in r:
            st["完成"] += 1
        elif "失败" in r:
            st["失败"] += 1
        elif "进行" in r or "跑" in r:
            st["在跑"] += 1
        elif "待" in r or "pending" in r.lower():
            st["待"] += 1
    out = []
    if rows:
        out.append("%s一共 %d 条。" % (what, len(rows)))
        bits = ["%s %d 条" % (k, v) for k, v in st.items() if v]
        if bits:
            out.append("按状态分：%s。" % "、".join(bits))
        out.append("最近一条是：%s" % _clean(rows[0])[:120])
        if len(rows) > 1:
            out.append("更早的还有：%s" % _clean(rows[-1])[:120])
    # 三、什么都没有：把原文说成一句（仍不是模板形状）
    if not out:
        flat = re.sub(r"\s+", " ", re.sub(r"```", "", raw))[:260]
        out = ["%s是这样的：%s" % (what, flat)]
    return "\n".join(out)


def _ask_model(messages, temperature=0.3):
    """一级一级问：当前火种两次 → 换火种。返回 (文本, 用了谁)。"""
    for _try in (1, 2):
        try:
            t = str(_LLM(messages, temperature=temperature) or "").strip() if _LLM else ""
        except Exception as e:      # noqa: silent-ok
            LOG.debug("融合改述第 %d 次失败：%s", _try, e)
            t = ""
        if len(t) >= 4:
            return t, (_LLM_NAME or "当前火种")
    if _ALT is not None:
        try:
            t, who = _ALT(messages, temperature)
        except Exception as e:      # noqa: silent-ok
            LOG.debug("换火种失败：%s", e)
            t, who = "", ""
        if len(t) >= 4:
            return t, (who or "备用火种")
    return "", ""


def answer(question, text, label="", kind=""):
    """把载体输出变成"人说的话"。返回 (最终文本, 状态)。

    状态：clean / ai / prose / exempt。**永远不会把死模板原样返回。**
    """
    src = str(text or "").strip()
    if not src:
        return "", "clean"
    if _exempt(src, question, kind):
        _record("exempt", kind, question, src, src, why="安全原文/代码块，按规矩不改述")
        return src, "exempt"
    if not looks_templated(src, question):
        return src, "clean"
    _sys = ("你在替一个本地助手，把载体刚取到的结果讲给用户听。要求：\n"
            "1. 用你自己的话，**不要复读原文的表格和代码块**；\n"
            "2. 原文里的数字、ID、路径、日期**一个都不能改、不能少**；\n"
            "3. 不要写「根据数据」「原始数据如下」「实测结果」这类机器腔；\n"
            "4. 三到六句，先说结论，再说关键细节；\n"
            "5. 原文是执行/查询结果时，说清做了什么、结果是什么；出错了就说错在哪、下一步怎么办。")
    _msgs = [{"role": "system", "content": _sys},
             {"role": "user", "content": "用户问：%s\n\n%s结果：\n%s" % (
                 str(question or "")[:200], (label or "载体"), src[:2000])}]
    _t0 = time.time()
    out, who = _ask_model(_msgs)
    if len(out) < 4:
        # 【退到最后也不是模板】载体自己组织成人话，并如实标注是谁说的
        out = _prose_from(src, label)
        out = out.rstrip() + "\n\n> （这句是载体自己按记录说的：这一轮所有火种都没有应答。）"
        _record("prose", kind, question, src, out,
                why="所有火种都没应答 → 载体组织成人话（不是死模板）")
        return out, "prose"
    miss = [n for n in _numbers(src) if n not in out]
    if miss:
        out += "\n\n> 原始要点：%s —— 这一行是载体从记录里直接摘的。" % "、".join(miss[:6])
    _record("ai", kind, question, src, out,
            extra={"sec": round(time.time() - _t0, 2), "miss": miss[:6], "by": who})
    return out, "ai"


def plugin_answer(question, plugin, text):
    """插件结果的专用入口（plugin 名进账，方便查"哪个插件的输出还在甩模板"）。"""
    return answer(question, text, label="%s 插件" % (plugin or "未知"), kind="plugin")


def stats(limit_days=7):
    """融合账：各状态条数与占比。数字来自 logs/fusion.jsonl，不是估的。"""
    out = {"events": 0, "clean": 0, "ai": 0, "prose": 0, "kept": 0, "exempt": 0,
           "ai_ratio": 0.0, "prose_ratio": 0.0, "kinds": {}, "path": _LOG}
    try:
        if not os.path.isfile(_LOG):
            return out
        with io.open(_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:      # noqa: silent-ok — 坏行跳过
                    continue
                st = str(r.get("state") or "")
                if st in out:
                    out[st] += 1
                out["events"] += 1
                k = str(r.get("kind") or "") or "-"
                out["kinds"][k] = out["kinds"].get(k, 0) + 1
    except Exception as e:      # noqa: silent-ok
        LOG.debug("融合账读取失败：%s", e)
    _need = out["ai"] + out["prose"] + out["kept"] + out["exempt"]
    if _need:
        out["ai_ratio"] = round(out["ai"] / float(_need), 3)
        out["prose_ratio"] = round(out["prose"] / float(_need), 3)
    return out


def tail(n=8):
    """最近几条判定（给 /proof 页面展示"刚才那句话是谁说的"）。"""
    rows = []
    try:
        if os.path.isfile(_LOG):
            with io.open(_LOG, encoding="utf-8") as f:
                lines = f.readlines()[-int(n or 8):]
            for line in lines:
                try:
                    rows.append(json.loads(line))
                except Exception:      # noqa: silent-ok
                    continue
    except Exception as e:      # noqa: silent-ok
        LOG.debug("融合记录读取失败：%s", e)
    return rows
