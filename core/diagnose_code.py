# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 代码治病（跑 → 载体诊断 → 模型改 → 再跑 → 通过）

【这段为什么这么设计】
    模型"一次写对可运行的代码"这件事**不可靠**，但"照着错误信息改一行"很可靠。
    所以载体把"能不能跑"这件事从模型手里拿走：
      1. 载体**真的跑一遍**（不是让模型想象跑起来会怎样）；
      2. 跑挂了就把错误**翻译成人能看懂的方向**（只给方向，**不给答案**）；
      3. 模型按方向改；
      4. 载体再跑一遍；通过就**直接输出结果**，不再走多余的流程。
    这是"精度叠加"在代码这件事上的落点：把不确定性收敛在"改一小步"里。

【为什么载体只给方向、不给答案】
    给了答案就等于载体写代码、模型当搬运工 —— 模型永远学不会，换个模型全废。
    而且用户的诉求是"让它把这段代码弄对"，不是"载体替它写"。
    判据：诊断输出里**只允许出现错误类型、位置、可能原因、检查方向**，
    绝不出现"把 X 改成 Y"这种成品代码。（自测有一条专门断言这一点。）

【红线】
    跑之前先过 `core/security/no_delete.py` 的命令拦截：
    「删所有文件」这类**在运行前就被拒绝**，连试都不试。这是与权限开关无关的硬拦截。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

__all__ = ["run_code", "diagnose", "diagnosis_text", "heal", "RUN_TIMEOUT",
           "health_path", "stats", "web_reference",
           "QUALITY_BATCH_SIZE", "quality_batch_size", "check_segment", "check_batch",
           "heal_batch", "quality_stats"]

RUN_TIMEOUT = 10           # 单次运行上限（秒）：死循环靠它拦，不靠模型自觉

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HEALTH = os.path.join(_ROOT, "logs", "code_health.jsonl")
_LOCK = threading.Lock()

# 错误类型 → 人能看懂的方向（**只有方向，没有改法**）
_PATTERNS = (
    (r"IndexError", "越界", "你访问的下标超出了序列长度。先确认长度是多少、你用的下标是多少，"
                        "再想清楚边界该取到哪。"),
    (r"KeyError", "键不存在", "你取的那个键在字典里没有。先列出字典到底有哪些键，再确认你要的是哪一个。"),
    (r"ZeroDivisionError", "除以零", "分母变成了 0。检查分母在什么情况下会是 0，那个情况该不该走这条路。"),
    (r"TypeError.*(?:not subscriptable|not iterable)", "类型不支持下标/迭代",
     "你对一个不是序列的东西用了下标或迭代。先确认这个变量此刻到底是什么类型。"),
    (r"TypeError.*argument", "参数不匹配", "调用时传的参数个数或类型和定义对不上。核对函数签名。"),
    (r"AttributeError", "属性不存在", "对象上没有你用的那个属性。确认对象类型，以及该属性名是否拼错。"),
    (r"NameError", "名字未定义", "用了一个还没定义的名字（变量名拼错，或定义在别的分支里）。"),
    (r"ValueError", "取值不合法", "传进去的值本身不合法（比如把非数字字符串转成数字）。"),
    (r"IndentationError|TabError", "缩进错误", "缩进不一致。同一个代码块必须用同一种缩进。"),
    (r"SyntaxError", "语法错误", "这一行不符合语法。看箭头指的位置往前一点。"),
    (r"RecursionError", "递归过深", "递归没有终止条件，或终止条件没被满足。"),
    (r"TimeoutExpired|超时", "运行超时", "程序没在限定时间内结束（多半是死循环）。检查循环的退出条件。"),
    (r"ModuleNotFoundError|ImportError", "模块缺失", "依赖没装或名字写错。"),
)
_LINE = re.compile(r'File "[^"]*", line (\d+)')


def _blocked_by_redline(code):
    """跑之前先过删除红线。返回拒绝原因（空串 = 放行）。

    【接口对齐 —— 这是一处真实事故的修复】
        `no_delete.check_command()` 的合约是**返回字符串**：空串 = 放行，非空 = 拒绝原因。
        这里曾经把它当 dict 用（`r.get("allowed", True)`）。`str` 没有 `.get`，会抛
        `AttributeError`，而异常被下面的 `except` 吞掉后返回了"放行" ——
        **红线在这条路上静默失效**，「删所有文件」会被直接执行。
        现在按字符串处理，并兼容历史 dict 形态（万一别处还在返回 dict）。

    【为什么取不到守卫时是"拒绝"而不是"放行"】
        删除**不可逆**。守卫取不到时无法证明这段代码安全：
        放行的代价是文件真的没了，拒绝的代价只是这次没跑成。只能选后者。
        这与"守卫拿不到就放行"的旧写法相反 —— 旧写法把"守卫坏了"变成了"禁区没了"。
    """
    try:
        from .security import no_delete as ND
        r = ND.check_command(code)
    except Exception as e:      # noqa: silent-ok — 但**不静默放行**：下面按拒绝处理
        return ("载体层没能加载删除守卫（%s）；删除不可逆，取不到守卫时拒绝执行"
                % type(e).__name__)
    if isinstance(r, str):
        return r.strip()
    if isinstance(r, dict) and not r.get("allowed", True):
        return str(r.get("reason") or "命中删除红线")
    return ""


def run_code(code, timeout=None):
    """真跑一遍。返回 {"ok","stdout","stderr","error_kind","seconds","blocked"}。

    `blocked` 非空 = **红线拒绝执行**，此时连子进程都不起。
    """
    t0 = time.time()
    code = str(code or "")
    if not code.strip():
        return {"ok": False, "stdout": "", "stderr": "代码是空的", "error_kind": "空代码",
                "seconds": 0.0, "blocked": ""}
    why = _blocked_by_redline(code)
    if why:
        return {"ok": False, "stdout": "", "stderr": "载体层拒绝执行：%s" % why,
                "error_kind": "红线拦截", "seconds": 0.0, "blocked": why}
    fd, path = tempfile.mkstemp(suffix=".py", prefix="xj_heal_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            p = subprocess.run([sys.executable, "-X", "utf8", path],
                               capture_output=True, timeout=(timeout or RUN_TIMEOUT))
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "执行超过 %d 秒仍未结束（多半是死循环）"
                    % (timeout or RUN_TIMEOUT), "error_kind": "运行超时",
                    "seconds": round(time.time() - t0, 2), "blocked": ""}
        so = (p.stdout or b"").decode("utf-8", "replace")
        se = (p.stderr or b"").decode("utf-8", "replace")
        return {"ok": p.returncode == 0, "stdout": so, "stderr": se,
                "error_kind": "" if p.returncode == 0 else (_kind_of(se) or "非零退出"),
                "seconds": round(time.time() - t0, 2), "blocked": ""}
    except Exception as e:      # noqa: silent-ok — 起不了子进程就如实返回，不当成"通过"
        return {"ok": False, "stdout": "", "stderr": "起不了执行环境：%s" % e,
                "error_kind": "环境错误", "seconds": round(time.time() - t0, 2), "blocked": ""}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _kind_of(err):
    for pat, kind, _hint in _PATTERNS:
        if re.search(pat, err, re.S):
            return kind
    return ""


def diagnose(err, code=""):
    """把错误翻译成**方向**（不是答案）。返回 {"kind","line","hint","raw"}。

    ⚠️ 这里**只允许**产出"错误类型 / 位置 / 可能原因 / 检查方向"。
    绝对不产出"把 X 改成 Y"这类成品代码 —— 那等于载体替模型写，模型永远学不会。
    """
    err = str(err or "")
    kind, hint = "", ""
    for pat, k, h in _PATTERNS:
        if re.search(pat, err, re.S):
            kind, hint = k, h
            break
    line = ""
    m = _LINE.search(err)
    if m:
        line = m.group(1)
    if not hint:
        hint = "先把错误原文看清楚：它说的是哪一行、哪一类问题。"
    return {"kind": kind or "未归类", "line": line, "hint": hint,
            "raw": err.strip().splitlines()[-1][:200] if err.strip() else ""}


def diagnosis_text(d):
    """给模型看的诊断文本（只给方向）。"""
    parts = ["【载体诊断 · 只给方向，不给答案】",
             "错误类型：%s" % d.get("kind")]
    if d.get("line"):
        parts.append("出错位置：第 %s 行" % d["line"])
    if d.get("raw"):
        parts.append("原始报错：%s" % d["raw"])
    parts.append("检查方向：%s" % d.get("hint"))
    parts.append("请你自己按这个方向改代码，把**完整代码**重新给我（不要只给改动片段）。")
    return "\n".join(parts)


def health_path():
    """病历路径：`logs/code_health.jsonl`。"""
    return _HEALTH


def record_case(**kw):
    """往病历追加一条。返回这条记录（写不进去也返回，只是没落盘）。

    【病历与精神记忆的分工】
        病历记的是**这一次发生了什么**（原始证据：错了几轮、错在哪几类、是不是被红线拦的）。
        精神记忆记的是**提炼出来的经验**（"编辑吃掉 def 行要用 ruff F821 兜"）。
        原始证据可以粗、可以多；提炼后的经验必须是一句话。两者不混。
    **只追加，不覆盖** —— 病历被改写就失去了取证价值。
    """
    rec = {"ts": time.time(), "kind": "code_heal"}
    rec.update(kw)
    try:
        os.makedirs(os.path.dirname(_HEALTH), exist_ok=True)
        with _LOCK:
            with open(_HEALTH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:      # noqa: silent-ok — 记不上病历只影响复盘，不影响这一轮回答
        pass
    return rec


def stats():
    """病历统计：总条数、成功/失败、被红线拦下的条数、最常见的错误类型。"""
    rows = []
    if os.path.exists(_HEALTH):
        try:
            with open(_HEALTH, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception:      # noqa: silent-ok — 坏行跳过
                        continue
        except Exception:      # noqa: silent-ok — 读不到就当还没病历
            rows = []
    kinds = {}
    for r in rows:
        for k in (r.get("kinds") or []):
            kinds[k] = kinds.get(k, 0) + 1
    return {"total": len(rows),
            "ok": sum(1 for r in rows if r.get("ok")),
            "blocked": sum(1 for r in rows if r.get("blocked")),
            "used_web": sum(1 for r in rows if r.get("used_web")),
            "kinds": kinds, "path": _HEALTH}


def web_reference(err, code="", web_fn=None, max_chars=1200):
    """改到第 N 轮还不过时，上网查一段**参考**。

    【为什么是"参考"而不是"答案"】
        网上搜到的往往是**别人针对别人的问题**写的完整代码。直接拿来用有两个问题：
        它可能根本不适用（问题不同），而且一旦照抄，模型就没在解决问题，
        只是当了搬运工 —— 换个问题又不会了。所以这里的用法是：
        把检索结果作为**思路参考**交给模型，明确要求它理解之后**自己重写**。

    返回 `{"ok","text","query","why"}`。`web_fn(query) -> str` 由调用方注入
    （载体已有的联网能力）；没给或查不到时如实返回 ok=False，**不编造参考内容**。
    """
    if not callable(web_fn):
        return {"ok": False, "text": "", "query": "", "why": "没有可用的联网入口"}
    d = diagnose(err, code)
    # 检索词用"错误类型 + 报错原文"，不用整段代码 —— 代码里的细节会污染检索
    query = ("%s %s" % (d.get("kind") or "", d.get("raw") or "")).strip()[:120]
    if not query:
        return {"ok": False, "text": "", "query": "", "why": "提炼不出检索词"}
    try:
        text = web_fn(query) or ""
    except Exception as e:      # noqa: silent-ok — 联网失败不该中断治病，如实记下
        return {"ok": False, "text": "", "query": query, "why": "联网失败：%s" % type(e).__name__}
    text = str(text).strip()
    if not text:
        return {"ok": False, "text": "", "query": query, "why": "联网没查到内容"}
    return {"ok": True, "text": text[:max_chars], "query": query, "why": "查到一段参考"}


def _round(code, timeout, on_step, i, phase):
    res = run_code(code, timeout=timeout)
    if on_step:
        try:
            on_step(i, res)
        except Exception:      # noqa: silent-ok — 回调是锦上添花
            pass
    return res


def heal(code, llm_fn, max_rounds=3, timeout=None, on_step=None,
         web_fn=None, web_rounds=1):
    """跑 → 诊断 → 模型改 → 再跑。通过就停。

    `llm_fn(messages) -> str`：调大脑要一段新代码（返回里允许带 ``` 围栏，会自动剥）。
    `web_fn(query) -> str`：**自己改的机会用尽后**，用它上网查一段**参考**
    （明确标注是参考，并要求模型理解后自己重写，不照抄）。

    【升级规则】`max_rounds` 就是"自己改的机会数"，默认 3（规格值：三轮不行再查网络）。
    用尽之后才升级到联网参考；调用方把它调小（比如 1），就是主动要求更早去查资料。
    **红线被拦时不升级也不重试** —— 删文件不是"查查资料就能过"的错误。

    返回 {"ok","code","rounds","trace","final"}；`trace` 是每一轮的实际记录（自测取证用）。
    被红线拦下时额外带 `blocked`，且**不再重试**。
    """
    trace = []
    kinds = []
    cur = str(code or "")
    total = 0
    blocked = ""
    used_web = False

    # ---- 第一段：自己改，最多 max_rounds 轮 ----
    for i in range(1, max(1, int(max_rounds)) + 1):
        total = i
        res = _round(cur, timeout, on_step, i, "自改")
        trace.append({"round": i, "phase": "自改", "ok": res["ok"],
                      "error_kind": res["error_kind"], "blocked": res["blocked"],
                      "seconds": res["seconds"],
                      "stdout": res["stdout"][:400], "stderr": res["stderr"][:400]})
        if res["ok"]:
            return _finish(True, cur, trace, res["stdout"].strip(), blocked, kinds, used_web)
        if res["blocked"]:
            # 红线拒绝：**不许重试**。这不是"改一改就能跑"的错误，查网络也没用。
            return _finish(False, cur, trace, "", res["blocked"], kinds, used_web)
        if res["error_kind"]:
            kinds.append(res["error_kind"])
        d = diagnose(res["stderr"], cur)
        try:
            out = llm_fn([{"role": "user", "content":
                           "下面这段 Python 跑不起来。\n\n```python\n%s\n```\n\n%s"
                           % (cur, diagnosis_text(d))}]) or ""
        except Exception as e:      # noqa: silent-ok — 模型调不通就如实停下
            trace.append({"round": i, "phase": "自改", "note": "模型调用失败：%s" % e})
            break
        new = _strip_fence(out)
        if not new.strip() or new.strip() == cur.strip():
            trace.append({"round": i, "phase": "自改", "note": "模型没给出不同的代码，停止"})
            break
        cur = new

    # ---- 第二段：改满还不过 → 上网查**参考**，再给 web_rounds 轮 ----
    last_err = ""
    for t in reversed(trace):
        if t.get("stderr"):
            last_err = t["stderr"]
            break
    if callable(web_fn) and int(web_rounds) > 0 and last_err:
        ref = web_reference(last_err, cur, web_fn=web_fn)
        trace.append({"phase": "查网络参考", "ok": None, "query": ref.get("query", ""),
                      "reference_ok": ref["ok"], "note": ref["why"]})
        if ref["ok"]:
            used_web = True
            for j in range(1, int(web_rounds) + 1):
                total += 1
                prompt = (
                    "下面这段 Python 跑不起来，已经自己改了几轮都没过。\n\n"
                    "```python\n%s\n```\n\n%s\n\n"
                    "【网上查到的参考资料（**只是参考**）】\n%s\n\n"
                    "**要求**：理解这段参考的思路之后，**自己重写代码**。"
                    "不要照抄 —— 它可能是在回答别人的问题，直接搬过来多半不适用。"
                    "改写后的目标仍然是解决我原本的问题。请给出**完整代码**。"
                    % (cur, diagnosis_text(diagnose(last_err, cur)), ref["text"]))
                try:
                    out = llm_fn([{"role": "user", "content": prompt}]) or ""
                except Exception as e:      # noqa: silent-ok
                    trace.append({"round": total, "phase": "参考改", "note": "模型调用失败：%s" % e})
                    break
                new = _strip_fence(out)
                if not new.strip() or new.strip() == cur.strip():
                    trace.append({"round": total, "phase": "参考改", "note": "模型没给出不同的代码，停止"})
                    break
                cur = new
                res = _round(cur, timeout, on_step, total, "参考改")
                trace.append({"round": total, "phase": "参考改", "ok": res["ok"],
                              "error_kind": res["error_kind"], "blocked": res["blocked"],
                              "seconds": res["seconds"],
                              "stdout": res["stdout"][:400], "stderr": res["stderr"][:400]})
                if res["ok"]:
                    return _finish(True, cur, trace, res["stdout"].strip(), blocked, kinds, used_web)
                if res["blocked"]:
                    return _finish(False, cur, trace, "", res["blocked"], kinds, used_web)
                if res["error_kind"]:
                    kinds.append(res["error_kind"])
                last_err = res["stderr"]

    return _finish(False, cur, trace, "", blocked, kinds, used_web)


def _finish(ok, code, trace, final, blocked, kinds, used_web):
    """收尾：写病历 + 返回统一结构。**病历落盘失败不影响返回结果**。"""
    outcome = {"ok": ok, "code": code, "rounds": len([t for t in trace if t.get("ok") is not None]),
               "trace": trace, "final": final, "kinds": kinds, "used_web": used_web}
    if blocked:
        outcome["blocked"] = blocked
    record_case(ok=ok, blocked=blocked, kinds=kinds, used_web=used_web,
                rounds=outcome["rounds"],
                seconds=round(sum(float(t.get("seconds") or 0) for t in trace), 2),
                code_head=str(code or "")[:300],
                error_head=(trace[-1].get("stderr") or "")[:200] if trace else "")
    return outcome


def _strip_fence(s):
    s = str(s or "").strip()
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", s, re.S)
    return m.group(1) if m else s


# ================== 批处理流式质检（防抄）==================
# 【为什么还需要这一层】`_blocked_by_redline` 拦的是"整段照抄代码"，拦不住
#   **"你把 range(n) 改成 range(n-1)"** 这种**具体改法** —— 它是文字、不是代码，
#   红线看不见它，但它同样是"载体替模型把答案说出来了"，模型照样学不会。
#
# 【为什么是"批处理 + 流式"】逐段质检会让用户看到一顿一顿的输出（每段都要等医生）；
#   整轮生成完再质检又会让用户白等一大段然后被打回重来。
#   折中：攒够一批（默认 10 段）就**先流式给用户**，用户看得到进展；这批输出完**暂停**，
#   医生查这 10 段：没问题就放行、继续下一批；有问题就**截断、修好、重发**，再继续。
#   批大小是用户可调的旋钮：
#     · 调小 → 用户更流畅（暂停更频繁但每次更短），医生更累（检查次数多）
#     · 调大 → 用户会卡顿（等一批攒满），医生更省
QUALITY_BATCH_SIZE = 10

# "给具体改法"的典型句式。**只认祈使式的具体替换**，不认"检查一下/确认一下"这类方向性说法
# ——后者正是载体诊断该给的东西，不能一起拦掉。
_SPECIFIC_FIX = re.compile(
    r"把\s*[^\s，。；]{1,40}\s*(?:改成|改为|换成|替换为|写成)"
    r"|将\s*[^\s，。；]{1,40}\s*(?:改成|改为|换成|替换为|写成)"
    r"|(?:改成|改为|替换为)\s*[^\s，。；]{1,30}")
# "编造事实"的代理判据：**给了具体版本号/日期，却没有任何来源标记**
_VERSION = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
_DATE = re.compile(r"\d{4}\s*[-/年]\s*\d{1,2}")
_SOURCE_MARK = ("http://", "https://", "来源", "据", "官方", "文档", "引用", "参考")
# "工具该调没调"：整段在讲**会变的外部事实**，而这一轮一个工具都没调
_NEEDS_TOOL = ("最新", "当前版本", "官网", "刚刚发布", "实时", "现在的价格", "今年")


def quality_batch_size(default=QUALITY_BATCH_SIZE):
    """批大小：优先读控制文件 `quality_check_batch_size`，读不到用默认 10。"""
    try:
        cfg_path = os.path.join(_ROOT, "xiaojiao_control.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8", errors="replace") as f:
                cfg = json.load(f) or {}
            v = cfg.get("quality_check_batch_size")
            if isinstance(v, int) and 1 <= v <= 200:
                return v
            if isinstance(v, str) and v.strip().isdigit():
                n = int(v.strip())
                if 1 <= n <= 200:
                    return n
    except Exception:      # noqa: silent-ok — 配置坏了就用默认值
        pass
    return default


def _copied(text, tool_texts):
    """这一段是不是**抄了工具返回的原文**（连续 24 字以上一模一样）。"""
    t = str(text or "")
    if len(t) < 24:
        return False
    for src in (tool_texts or []):
        s = str(src or "")
        if len(s) < 24:
            continue
        for i in range(0, len(t) - 24 + 1):
            if t[i:i + 24] in s:
                return True
    return False


def check_segment(text, tool_texts=(), tool_used=False):
    """查一段**有问题没有**。返回 `(是否通过, 原因)`。

    四类问题（用户规格）与各自的判据：
      ① **抄工具原文** —— 与工具返回文本有 ≥24 字连续重合。抄原文等于把"检索"冒充成"理解"。
      ② **给具体改法** —— 命中"把 X 改成 Y"这类**祈使式替换**。载体只给方向，
         给了具体改法就等于载体替模型把答案说了，模型学不会、换模型全废。
      ③ **编造事实** —— 给了具体版本号/日期，却**一个来源标记都没有**。
         这是代理判据（判不了"真伪"），但"给具体数字却不给出处"是可判的。
      ④ **工具该调没调** —— 整段在讲会变的外部事实（最新/官网/实时…），而这一轮没调任何工具。

    ⚠️ 边界：这是**启发式**，不是事实核查。它抓的是"表述形态上的毛病"，
    抓不了"说得像真的但其实是编的"。所以它是**拦截器**，不是判真伪的法官。
    """
    t = str(text or "").strip()
    if not t:
        return True, ""
    if _copied(t, tool_texts):
        return False, "抄了工具返回的原文（连续 24 字以上重合）—— 要把资料读进去再自己说，不是搬运"
    m = _SPECIFIC_FIX.search(t)
    if m:
        return False, "给了具体改法（「%s」）—— 只许给方向（错在哪、往哪查），不许替模型把改法写出来" % m.group(0)[:30]
    if (_VERSION.search(t) or _DATE.search(t)) and not any(s in t for s in _SOURCE_MARK):
        return False, "给了具体版本号/日期却没有任何来源标记 —— 这多半是编的，要给不出处就别给数字"
    if not tool_used and any(w in t for w in _NEEDS_TOOL):
        return False, "在讲会变的外部事实（最新/官网/实时…）却一个工具都没调 —— 该查就去查"
    return True, ""


def check_batch(segments, tool_texts=(), tool_used=False):
    """查一批。返回 `{"ok", "bad": [{"i", "reason", "text"}], "checked"}`。

    `i` 是**批内序号**（从 1 开始），调用方据此决定截断到哪一段。
    """
    bad = []
    segs = list(segments or [])
    for i, s in enumerate(segs, 1):
        ok, why = check_segment(s, tool_texts=tool_texts, tool_used=tool_used)
        if not ok:
            bad.append({"i": i, "reason": why, "text": str(s)[:120]})
    return {"ok": not bad, "bad": bad, "checked": len(segs)}


def heal_batch(generate_fn, llm_fn, total_segments, batch_size=None,
               tool_texts=(), tool_used=False, context_tail="", on_batch=None):
    """批处理流式质检的主循环：**生成一批 → 质检 → 有问题就截断修好重发 → 再下一批**。

    `generate_fn(n, tail) -> [段落...]`：生成 n 段；`tail` 是**前一批末尾**，
    传给它才能保证衔接（不然第 2 批开头会跟第 1 批结尾接不上，读起来是断裂的）。
    `llm_fn(messages) -> str`：修那一段时调模型（"这句不行，重新说"）。

    返回 `{"segments", "batches", "fixed", "rejected", "blocked_at"}`：
      · `segments` 是**最终通过质检**的段落序列；
      · `batches` 是每一批的真实记录（自测取证用）；
      · `blocked_at` 非空表示某段修了也没过、停在那里（**如实停下，不硬凑**）。
    """
    size = int(batch_size or quality_batch_size())
    size = max(1, size)
    out, batch_records = [], []
    n_batches = 0
    fixed = rejected = 0
    tail = str(context_tail or "")
    done = 0
    while done < int(total_segments):
        n = min(size, int(total_segments) - done)
        try:
            segs = list(generate_fn(n, tail) or [])
        except Exception as e:      # noqa: silent-ok — 生成失败就如实停，不假装产出
            return {"segments": out, "batches": batch_records, "fixed": fixed,
                    "rejected": rejected, "blocked_at": "生成失败：%s" % type(e).__name__}
        if not segs:
            return {"segments": out, "batches": batch_records, "fixed": fixed,
                    "rejected": rejected, "blocked_at": "生成器没有产出内容"}
        n_batches += 1
        batch_records.append({"n": n_batches, "segments": len(segs),
                               "ok": None})
        # ---- 这批先"流式给出"（on_batch 回调即用户的可见进度），再暂停质检 ----
        if on_batch:
            try:
                on_batch(n_batches, list(segs))
            except Exception:      # noqa: silent-ok — 回调是锦上添花
                pass
        chk = check_batch(segs, tool_texts=tool_texts, tool_used=tool_used)
        batch_records[-1]["ok"] = chk["ok"]
        batch_records[-1]["bad"] = len(chk["bad"])
        if chk["ok"]:
            out.extend(segs)
            done += len(segs)
            tail = segs[-1]
            continue
        # ---- 有问题：截断到第一处问题之前，修好、重发 ----
        first = chk["bad"][0]
        keep = segs[:first["i"] - 1]
        bad_text = segs[first["i"] - 1]
        out.extend(keep)
        done += len(keep)
        _prev = (keep[-1] if keep else tail)
        try:
            _msg = ("下面这一句不行：%s\n原句：%s\n请**重新说这一句**：只给重写后的那一句，"
                    "不要解释。" % (first["reason"], str(bad_text)[:300]))
            new = str(llm_fn([{"role": "user", "content": _msg}]) or "").strip()
        except Exception:      # noqa: silent-ok — 修不动就停在这一段
            new = ""
        ok2, why2 = check_segment(new, tool_texts=tool_texts, tool_used=tool_used) if new else (False, "模型没有给出重写")
        if ok2:
            out.append(new)
            done += 1
            fixed += 1
            tail = new
            continue
        rejected += 1
        return {"segments": out, "batches": batch_records, "fixed": fixed, "rejected": rejected,
                "blocked_at": "第 %d 批第 %d 段修了仍未过：%s" % (n_batches, first["i"], why2)}
    return {"segments": out, "batches": batch_records, "fixed": fixed,
            "rejected": rejected, "blocked_at": ""}


def quality_stats():
    """质检自检信息：当前批大小与它来自哪里（配置还是默认）。"""
    cfg_path = os.path.join(_ROOT, "xiaojiao_control.json")
    src = "默认"
    try:
        if os.path.exists(cfg_path):
            with open(cfg_path, encoding="utf-8", errors="replace") as f:
                if "quality_check_batch_size" in (json.load(f) or {}):
                    src = "配置"
    except Exception:      # noqa: silent-ok
        pass
    return {"batch_size": quality_batch_size(), "source": src, "path": cfg_path}
