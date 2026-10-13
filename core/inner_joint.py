# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# core/inner_joint.py —— 「感知」和「元认知自评」这两次内部调用：合并成一次 / 并发跑
#
# 【为什么要有这个文件（2026-10-13 用户点名要的"并发 + 合并"）】
#   用户体感「他回复好慢」。量的结果是：一轮里**串行**的内部模型调用有 4~6 次，
#   其中「感知层」和「元认知自评」用的是**同一句话、同一个上下文**，
#   两次调用互不依赖（自评不看感知的结果，感知不看自评的档位）—— 串着跑纯粹是历史顺序。
#
# ⚠️ **实测结果不如预期，照实写在这里**（`tools/bench_inner_calls.py`，5 次、轮流先跑）：
#     串行 中位 3.05 秒 ｜ 并发 中位 2.80 秒（**只省 0.26 秒**，个别轮次还更慢）
#     合并 中位 4.56 秒（**比串行慢 1.51 秒**），且 5 次里有 4 次给出和单独问**不一样的档位**
#   原因不难看明白：这两次调用**不等长**（感知约 2 秒、自评约 1 秒），能重叠的只有短的那一次；
#   一次问两件事还会让 4B 对"我有没有把握"的判断跟着变。
#   所以：并发默认开（语义与原来一模一样，白捡一点是一点），**合并默认关**。
#   这一步**不是量级改善** —— 真要让"思考"明显变快，得减少调用次数或缩短提示词。
#
# 两种做法，都放在这里：
#   ① `joint()`   —— **合并**：一次请求同时问"这意味着什么"和"你有没有把握"，
#                    回答里感知那几行 + 最后一行档位，一次拿回两样（省一整个来回）；
#   ② `start()` / `finish()` —— **并发**：还是两次请求，但同时在飞（语义与原来一模一样）。
#
# 【铁的边界：宁可慢，也不许读错】
#   · 合并那条路**只在两边都真的解读出来时**才算成功（`ok=True`）；
#     只要感知那半没读出「我」、或档位没解析出来，就**明确失败**，由调用方退回原来那条路。
#     所以合并出错**只会慢，不会把感知/档位弄错**——这是它敢开的前提。
#   · 档位那一行是从回答里**切出来**再交给 `selfrate` 的解析器的：
#     不切的话，感知那半的散文（"我没把握"之类）会被当成自评档位——那正是这一层最容易出的错。
#   · 这里不查表、不猜：模型没写就是没写，如实失败。
import re
import threading

# 档位行的写法（模型可能写「档位：C」「自评：B」「把握：A」…）
_RATE_LABEL_RE = re.compile(r"(?:档位|自评|评级|把握|信心|程度)\s*[:：]\s*([ABCabc?])(?![A-Za-z])")


def joint_prompt(background, perception_task, event, question, rate_lines, rate_context=""):
    """拼"一次问两件事"的提示词。

    `background` / `perception_task` 来自 `core/perception.py`（自我背景 + 感知那几行），
    `rate_lines` 来自 `core/metacognition/selfrate.py::rate_rules()`（三档含义那几句）——
    都**由调用方原样传进来**，这个文件不复制它们的措辞：
    复制一份就等于埋了一个"以后改了提示词这边没跟着改"的坑。
    """
    lines = [
        str(background or "").rstrip(),
        "",
        "这一轮你要做两件事，一件做完接着做另一件，**都写在同一条回答里**。",
        "",
        "第一件（感知）：这件事对你意味着什么。",
        str(perception_task or "").rstrip(),
        "",
        "事：%s" % str(event or "")[:400],
        "",
        "第二件（自评）：你有没有把握把这件事答好。",
        "",
    ]
    lines += [str(x) for x in (rate_lines or [])]
    lines += ["", "这一轮要答的是：%s" % (str(question or "")[:400] or "（空问题）")]
    if rate_context:
        lines += ["你可以参考的已知信息：%s" % str(rate_context)[:1500]]
    lines += [
        "",
        "—— 最后**只多写一行**（别的什么都不要写）：",
        "档位：<A 或 B 或 C 里的一个字母>",
    ]
    return "\n".join(lines)


def split_rating_zone(raw):
    """把回答切成 (感知那段, 档位那段)。切不出来时档位那段为空。

    为什么必须切：感知那半是散文（"这句话让我有点慌"），**里面完全可能出现"没把握"**
    —— 不切就给 `parse_rating` 整段，它会把这句散文读成自评档位。
    """
    text = str(raw or "")
    hits = list(_RATE_LABEL_RE.finditer(text))
    if not hits:
        return text, ""
    h = hits[-1]                      # 取**最后**一处：模型可能先写一遍格式示例
    return text[:h.start()], text[h.start():]


def joint(llm_fn, background="", perception_task="", event="", question="",
          rate_lines=None, rate_context="", doing="", extra=""):
    """**合并**：一次模型调用，同时拿回感知和自评。

    返回 `{"ok", "perception", "selfrate", "raw", "why"}`。
    `ok=False` 的**唯一含义**是"这次合并没读全"，调用方应退回原来的两次调用 ——
    绝不在这里拿半截结果去凑（那就成了"载体替它编"）。
    """
    from core import perception as _PC
    from core.metacognition import selfrate as _SR
    out = {"ok": False, "perception": None, "selfrate": None, "raw": "", "why": ""}
    # 背景和感知提示词没传就自己拼（调用方一般会传，好让"doing/extra"与单独那条完全一致）
    if not background:
        try:
            background = _PC.self_background(doing, extra)
        except Exception:      # noqa: silent-ok — 没背景也要能跑
            background = ""
    if not perception_task:
        perception_task = "\n".join(_PC._TASK)      # noqa: SLF001 — 同一层的"那一份措辞"
    if not rate_lines:
        rate_lines = _SR.rate_rules()
    prompt = joint_prompt(background, perception_task, event, question, rate_lines, rate_context)
    try:
        raw = str(llm_fn(prompt) or "").strip()
    except Exception as e:      # noqa: silent-ok — 调用失败=合并失败, 交给调用方退回
        out["why"] = "合并调用失败：%s: %s" % (type(e).__name__, str(e)[:120])
        return out
    out["raw"] = raw[:800]
    if not raw:
        out["why"] = "合并调用没给任何内容"
        return out
    per_zone, rate_zone = split_rating_zone(raw)
    per = _PC.from_raw(per_zone)                     # 回声判定/解析规则与单独那条完全一致
    sr = _SR.from_raw(rate_zone, question=question)
    out["perception"], out["selfrate"] = per, sr
    if not per.get("ok"):
        out["why"] = "感知那半没读出来（%s）" % str(per.get("parsed_by") or "")[:40]
        return out
    if not sr.get("ok"):
        out["why"] = "档位没解析出来（%s）" % str(sr.get("why") or "")[:60]
        return out
    out["ok"] = True
    out["why"] = "合并成功：感知 + 自评一次拿回"
    return out


# ---------------- 并发：两次调用同时在飞（语义与原来完全一致） ----------------
_FUTURES = {}
_FUT_LOCK = threading.Lock()


def start(tag, fn):
    """把一次内部调用丢到后台线程上跑，返回一个句柄（给 `finish` 用）。

    `tag` 只是给日志看的名字。**失败不抛**：句柄里如实存下异常，
    由 `finish` 决定退回什么 —— 内部调用的失败从来不该把整轮对话带走。
    """
    box = {"tag": tag, "fn": fn, "done": False, "value": None, "err": None,
           "thread": None, "t0": None}

    def _run():
        import time as _t
        box["t0"] = _t.time()
        try:
            box["value"] = fn()
        except Exception as e:      # noqa: silent-ok — 存下来交给调用方判断
            box["err"] = e
        finally:
            box["done"] = True

    th = threading.Thread(target=_run, name="inner_%s" % tag, daemon=True)
    box["thread"] = th
    with _FUT_LOCK:
        _FUTURES[tag] = box
    th.start()
    return box


def finish(box, timeout=60.0):
    """等并发那次调用收工。返回 `(值, 出错信息)`；超时按"没拿到"处理（返回 None 值）。"""
    if not box:
        return None, "没有这个并发任务"
    try:
        box["thread"].join(timeout)
    except Exception:      # noqa: silent-ok — join 出错也只当没等到
        pass
    if not box["done"]:
        return None, "等超时(%.0f 秒)还没回来" % timeout
    if box["err"] is not None:
        return None, "%s: %s" % (type(box["err"]).__name__, str(box["err"])[:120])
    return box["value"], ""


def pending():
    """现在还有哪些并发调用在飞（给自测/诊断看）。"""
    with _FUT_LOCK:
        return [k for k, v in _FUTURES.items() if not v["done"]]
