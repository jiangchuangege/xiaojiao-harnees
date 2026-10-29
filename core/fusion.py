# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 融合边界（2026-10-30）

【用户原话】
  「我是说不止这一条是所有的都要AI不要模板直接，而且不只有对话，甚至插件，等等都不要直接模板
    都是通过AI，所有的，载体的所有都要融入到AI，AI也要融入到载体，这样就更强大了成为一体」

【这份文件解决什么】
  载体（工具/插件/规则）拿到的**结果**，以前经常被拼成模板直接甩给用户：
  「🌐 **我的公网 IP（实测）** + 代码块」「🔧 xxx 实测结果 + 代码块」「最近的任务（8 条）」……
  人看到的是机器的排版，不是有人跟他说话。
  现在把这件事收成**一个边界**：载体出结果 → 融合层 → 模型用自己的话说给用户。
  所有出口（对话、流式、插件结果、功能交付）都过同一道边界，而不是各路由各拼一份。

【谁在说话，必须可查（这是"如实标注"的落点）】
  每一次判定都落 `logs/fusion.jsonl`，状态只有五种，绝不混用：
    · clean     —— 本来就不是模板（模型自己说的话），不动
    · ai        —— 原来是模板，模型改成了自己的话（附模型名/耗时/字数）
    · kept      —— 是模板，但模型这次没应答 → **保留载体原文**，不假装是模型说的
    · exempt    —— 按规矩不能改述（待确认 / 红线 / 禁区 / 工程类代码块）
    · budget    —— 这一轮已经太慢，不再多花一次模型调用（速度优先，保留原文并说明）
  `stats()` 把五种状态的比例算出来，`/proof` 页面直接显示 —— 不靠自我感觉。

【边界（不粉饰）】
  · 它只改**说法**，不改事实：原文里的数字/ID/路径/日期一个不许改、不许少；
    缺的补一行「原始要点」，让用户能核对。
  · 模型没起来时它替不了模型：那时候保留载体原文并如实标注 —— 这是能做到的最诚实的形态。
  · 结构化的面板数据（JSON 状态、图表数据）不走这条路：那不是"话"，硬转述只会失真。
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

_LLM = None          # 由 app 注入（llm_chat），注入一次即可
_LLM_NAME = ""

# 模板的三种长相（判据宁可窄：误改一回正常回答，比漏改十条更糟）
_EMOJI = ("🔧", "🌐", "💻", "📋", "🎯", "📈", "🧾", "🩺", "📊", "🧪", "🛠", "🚀", "📄", "🗂", "🔎")
_PHRASES = ("实测结果", "载体实取", "未经模型转述", "极快直通", "原始数据如下", "没能把数据讲成话")
_SKIP = ("〔待确认〕", "红线", "禁区", "已拦截")
_CODE_Q = re.compile(r"(写代码|代码|函数|脚本|实现|报错|bug|debug|sql|正则|html|css|json|yaml)", re.I)


def install(llm_fn, model_name=""):
    """app 启动时把模型调用注进来。重复调用无副作用。"""
    global _LLM, _LLM_NAME
    if llm_fn is not None:
        _LLM = llm_fn
    if model_name:
        _LLM_NAME = str(model_name)


def looks_templated(text, question=""):
    """这条输出是不是载体拼的模板（而不是模型说的话）？"""
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

    【为什么不只认"两位以上"】实测任务表里的关键量就是「8 条」这种一位数：
      模型把它说成"有几条任务完成了"，用户就核对不到。所以：
      · 两位以上或带小数的数字 → 一律算量；
      · 一位数但**带单位**（条/步/个/项/行/次/名/份/张/秒/分/时/%）→ 也算量；
      · 其余一位数（"第2步"这类序数、版本号里的数字）不算，否则会逼模型说废话。
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


def answer(question, text, label="", kind="", budget=None):
    """把载体输出变成"人说的话"。返回 (最终文本, 状态)。

    状态见模块说明：clean / ai / kept / exempt / budget。
    """
    src = str(text or "").strip()
    if not src:
        return "", "clean"
    if _exempt(src, question, kind):
        _record("exempt", kind, question, src, src, why="安全原文/代码块，按规矩不改述")
        return src, "exempt"
    if not looks_templated(src, question):
        return src, "clean"
    if budget is not None:
        try:
            if float(budget) <= 0:
                _record("budget", kind, question, src, src, why="这一轮已太慢，不再多花一次模型调用")
                return src, "budget"
        except Exception:      # noqa: silent-ok
            pass
    if _LLM is None:
        _record("kept", kind, question, src, src, why="没有可用的模型调用（融合层未注入）")
        return src, "kept"
    _sys = ("你在替一个本地助手，把载体刚取到的结果讲给用户听。要求：\n"
            "1. 用你自己的话，**不要复读原文的表格和代码块**；\n"
            "2. 原文里的数字、ID、路径、日期**一个都不能改、不能少**；\n"
            "3. 不要写「根据数据」「原始数据如下」「实测结果」这类机器腔；\n"
            "4. 三到六句，先说结论，再说关键细节；\n"
            "5. 原文是执行/查询结果时，说清做了什么、结果是什么；出错了就说错在哪、下一步怎么办。")
    _t0 = time.time()
    out = ""
    for _try in (1, 2):        # 本机 llama-swap 偶发 500，试两次再放弃
        try:
            out = str(_LLM([{"role": "system", "content": _sys},
                            {"role": "user", "content": "用户问：%s\n\n%s结果：\n%s" % (
                                str(question or "")[:200], (label or "载体"), src[:2000])}],
                           temperature=0.3) or "").strip()
        except Exception as e:      # noqa: silent-ok
            LOG.debug("融合改述第 %d 次失败：%s", _try, e)
            out = ""
        if len(out) >= 4:
            break
    if len(out) < 4:
        _record("kept", kind, question, src, src, why="模型这次没应答，保留载体原文（不假装是模型说的）")
        return src, "kept"
    _miss = [n for n in _numbers(src) if n not in out]
    if _miss:
        out += "\n\n> 原始要点：%s —— 这一行是载体从记录里直接摘的。" % "、".join(_miss[:6])
    _record("ai", kind, question, src, out,
            extra={"sec": round(time.time() - _t0, 2), "miss": _miss[:6]})
    return out, "ai"


def plugin_answer(question, plugin, text, budget=None):
    """插件结果的专用入口（plugin 名进记录，方便查"哪个插件的输出还在甩模板"）。"""
    return answer(question, text, label="%s 插件" % (plugin or "未知"), kind="plugin",
                  budget=budget)


def stats(limit_days=7):
    """融合账：五种状态各多少条，AI 复述占比。数字来自 logs/fusion.jsonl，不是估的。"""
    out = {"events": 0, "clean": 0, "ai": 0, "kept": 0, "exempt": 0, "budget": 0,
           "ai_ratio": 0.0, "kept_ratio": 0.0, "kinds": {}, "path": _LOG}
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
    _need = out["ai"] + out["kept"] + out["exempt"] + out["budget"]
    if _need:
        out["ai_ratio"] = round(out["ai"] / float(_need), 3)
        out["kept_ratio"] = round(out["kept"] / float(_need), 3)
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
