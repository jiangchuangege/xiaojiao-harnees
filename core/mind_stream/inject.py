# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的器官（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 思维流 · 注入（轻量，≤500 token）+ 温度自适应

【这段为什么这么设计】
    状态维护好了，但**怎么给模型**才是成败关键。两种错误做法：
      ① 全量塞进去 → 挤占上下文（无限 6 有硬上限），而且模型会被一堆元信息带偏；
      ② 不给 → 那状态白维护了，回答还是"每轮重来"。
    这里只给三样（需求里点名的"关键的"）：
        当前话题 + 对用户的理解 + 刚才在想什么
    外加一条**行为指令**（"接着刚才那条线往下走"）——
    注意这条是"怎么说"的**方法**，不是"说什么"的**话术**（见下）。

【为什么绝不给成句话术（本项目的一条底线）】
    需求写得很明确："载体只维护思维状态，不给固定话术；模型自由生成，载体不干涉"。
    所以注入块里**只有事实与判断**，没有一句可以直接抄的成品句子。
    一旦载体给出成句的话术，回答就变成本地模板 —— 换个模型也救不回来，
    而且用户会明显感到"它在念稿"。

【温度为什么按意图给】
    事实类问题（"是多少/为什么/原理"）需要**稳**（0.2）——温度高会算错、会编数字；
    闲聊需要**多样**（0.8）——温度低会每次都回同一个腔调（正是用户抱怨的"两次回答一样"）；
    其余取 0.5。这不是"调参玄学"：两端的失败模式都很明确（见上）。
"""
import re

from .state import TONE_CN, TONES

# 注入预算：需求要求 ≤500 token。中文按 1.5 token/字估（与 app 里同一把尺子），
# 所以字数上限取 330 字 —— 留出标点与英文的余量，保证折算后不超 500 token。
MAX_CHARS = 330
MAX_TOKENS = 500

# 温度档位
TEMP_FACT = 0.2      # 事实/计算/解释：要准
TEMP_CHAT = 0.8      # 闲聊/情绪：要多样
TEMP_MID = 0.5       # 其余


def estimate_tokens(text):
    """与主程序一致的 token 估算（中文 ×1.5 + ASCII/3）。

    为什么自己算而不是 import app 的：mind_stream 要能**独立 import**
    （不依赖 Flask、不依赖 xiaojiao_app）—— 依赖主程序会让它无法单测。
    """
    t = str(text or "")
    if not t:
        return 0
    cjk = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 1.5 + (len(t) - cjk) / 3) + 1


def temperature_for(intent="chat", text="", tone="neutral"):
    """按意图/语气给温度。返回 float。

    判据顺序即优先级：
      ① 事实类（intent=query/shell，或句子里有"多少/为什么/原理"）→ 0.2
      ② 闲聊/情绪（intent=chat，或语气是 casual/playful/empathetic）→ 0.8
      ③ 其余 → 0.5
    为什么先判事实：把"多少"这种问题当闲聊给 0.8，温度高会**算错数**或编数字，
    而这个错误用户一眼能看出来（可信度直接崩）。
    """
    s = str(text or "")
    fact_like = intent in ("query", "shell", "full") or any(
        w in s for w in ("多少", "几", "为什么", "原理", "机制", "等于", "计算", "定义",
                         "区别", "是不是", "能不能"))
    if fact_like:
        return TEMP_FACT
    if intent in ("chat", "diagram") or tone in ("casual", "playful", "empathetic"):
        return TEMP_CHAT
    return TEMP_MID


def build_block(st, text="", intent="chat"):
    """把状态编成一段**只给事实**的轻量提示词。返回 `{"text","tokens","used","temp"}`。

    【2026-09-18 改（用户定的标准：模型自己感知 = 真；载体写好词句 = 假）】
      改之前这里是**载体命名的框架 + 一条行为指令**：
        「【你刚才在想什么（接着这条线往下说，不要重新开始）】」
        「· 当前在聊：… · 你对用户的了解：… · 你刚才在想：… · 你上次有没说完的话：…
         · 用户还悬着的问题：… · 当前语气：…」
        「（这是你自己的思路，不是要复述的内容；自然接着往下走就行，别把这些当答案念出来。）」
      —— 标题是载体起的、语气是载体命名的、连"该怎么用"都是载体交代的。
      现在只给事实：
        · **值里的载体句式一律剥掉**：`update.py` 存的是
          `聊到「X」时我回应了：Y` / `没说完：Y` —— 前半个是载体写的框，后半个才是它自己的话，
          这里只留后半（原样，不改写）。
        · **标题框 / 语气命名 / 行为指令全删**（"接着往下说"这类是载体教它怎么说话）。
    【保留的】预算裁剪、`temp` 的算法（那是数值，不是词句）、字段本身。
    【仍然只给事实与归属】每条事实都标明**是谁说的**（用户说过 / 它自己说过）——
      这个项目上一课就是"把工具给的、说成用户说的"，归属必须写清。
    """
    st = st or {}
    topic = str(st.get("current_topic") or "").strip()
    _frame = re.compile(r"^(?:聊到「[^」]*」时我回应了：|没说完：)")
    und = [_frame.sub("", str(x))[:40] for x in (st.get("user_understanding") or [])][-4:]
    thoughts = [_frame.sub("", str(x))[:70] for x in (st.get("recent_thoughts") or [])][-3:]
    unsaid = [_frame.sub("", str(x))[:50] for x in (st.get("unsaid") or [])][-2:]
    opens = [_frame.sub("", str(x))[:40] for x in (st.get("open_questions") or [])][-3:]
    tone = st.get("tone_state") if st.get("tone_state") in TONES else "neutral"
    temp = temperature_for(intent, text, tone)

    # 状态里**什么都没有**时不要硬塞一段空话（那只会让模型困惑、白吃 token）
    if not (topic or und or thoughts or unsaid):
        return {"text": "", "tokens": 0, "used": False, "temp": temp}

    def compose(t, u, th, un, op):
        lines = ["[此刻的事实]"]
        if t:
            lines.append("当前话题：%s" % t)
        if u:
            lines.append("用户说过：%s" % "；".join(u))
        if th:
            lines.append("它自己说过：%s" % "；".join(th))
        if un:
            lines.append("没说完的：%s" % "；".join(un))
        if op:
            lines.append("用户的问题：%s" % "；".join(op))
        return "\n".join(lines)

    text_out = compose(topic, und, thoughts, unsaid, opens)
    # 超预算 → 从后往前砍（先砍悬而未决、再砍没说出口、再砍思考）
    for cut in (lambda: compose(topic, und, thoughts, unsaid, []),
                lambda: compose(topic, und, thoughts, [], []),
                lambda: compose(topic, und, thoughts[-1:], [], []),
                lambda: compose(topic, und, [], [], [])):
        if len(text_out) <= MAX_CHARS:
            break
        text_out = cut()
    if len(text_out) > MAX_CHARS:
        text_out = text_out[:MAX_CHARS]
    return {"text": text_out, "tokens": estimate_tokens(text_out),
            "used": bool(text_out), "temp": temp}

