# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 思维流（Mind Stream）· 状态定义

【这段为什么这么设计】
    用户实测：同一会话里连说两次"我叫张三，在济南做后端开发"，小焦两次回答几乎一样。
    说明它每轮都在**重新理解**，没有"思维的连续性"。人不是这样：
    人上一秒在想什么，会影响下一秒怎么想 —— 不是"重新处理这句话"，是"接着刚才那条线往下走"。

    小焦原来的做法：每轮 = 输入 → 读历史 → 独立处理 → 输出。
    历史只是"参考资料"，没有"我正在想什么"这个状态。
    这里补的就是那个缺失的东西：**一份活着的思维状态**。
        每轮：读状态 → 更新 → 注入 → 生成 → 再更新 → 存盘
    所以第二条输入进来时，起点不是空的，而是"我刚才在想什么"。

【去掉它会怎样】
    回到"每轮重读历史"：用户重复同一句话，系统就重复同一个回答 ——
    因为在它看来那两条输入**确实一样**（它没有"我已经说过这个了、而且我还在想这件事"）。
    用户感受到的是"它在重放"，而不是"它在跟我聊"。

【两条不可动摇的原则（来自需求约束，也是设计底线）】
    1. **载体只维护状态，不给固定话术。**
       状态里只放"事实与判断"（在聊什么、我在想什么、我还没说出口的是什么），
       **绝不放"该说什么"的句子**。措辞一律由模型自由生成 ——
       载体一旦给出成句的话术，回答就变成本地模板，换模型也救不回来。
    2. **注入要轻量**：只给"当前话题 + 对用户的理解 + 刚才在想什么"，
       总量控制在 500 token 以内（见 `inject.py`）。
       状态是"给模型的提示"，不是"替模型思考"。

【为什么落在 logs/ 下、每个会话一个文件】
    · 会话是天然的隔离边界（串台是这个项目反复踩过的坑）；
    · 放 `logs/` 是因为它是**运行状态**，不是源码资产（.gitignore 已忽略）；
    · 必须能**跨重启恢复**（验收测试 6），所以必须落盘、不能只在内存里。
"""
import json
import os
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 思维状态的**全部字段**。加字段必须同时在这里登记 ——
# 这样"状态里到底有什么"永远是一份可读的清单，而不是散落在各处的隐含约定。
FIELDS = ("current_topic", "user_understanding", "recent_thoughts", "open_questions",
          "tone_state", "unsaid", "turn_count", "last_updated")

# 语气状态取值（不放开成自由文本：它要参与"温度自适应"的判定，必须是有限集合）
TONES = ("neutral", "casual", "empathetic", "serious", "playful", "focused")
TONE_CN = {"neutral": "平常", "casual": "轻松", "empathetic": "共情",
           "serious": "严肃", "playful": "俏皮", "focused": "专注"}

# 各字段最多留几条（状态是"正在想的"，不是"全部说过的话"——
# 留太多会挤占注入预算，也会让模型把注意力摊薄）
MAX_THOUGHTS = 4
MAX_OPEN_QUESTIONS = 3
MAX_UNSAID = 2
MAX_UNDERSTANDING = 6


def state_dir(sub=None):
    """思维状态的落盘目录：`logs/mind_stream/`（建不出来也不抛，写入点会兜）。"""
    d = os.path.join(_ROOT, "logs", "mind_stream")
    if sub:
        d = os.path.join(d, sub)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:      # noqa: silent-ok — 目录建不出来时各写入点自己再兜一层
        pass
    return d


def _safe_sid(sid):
    """会话 id → 安全的文件名（只保留字母数字与短横线）。

    为什么要过滤：会话 id 来自前端/URL，直接拼进路径会有目录穿越风险
    （`../../x` 这种）。这里只允许白名单字符，别的统统换成下划线。
    """
    s = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(sid or ""))
    return (s or "default")[:64]


def path_for(sid):
    """某个会话的状态文件路径。"""
    return os.path.join(state_dir(), "%s.json" % _safe_sid(sid))


def blank(sid=""):
    """全新的空状态（**每轮未命中任何信号时也要有它**，不能返回 None）。

    为什么要给 `schema` 字段：文件格式将来一定会变（加字段/改语义），
    没有版本号时"老文件被新代码读"只能靠猜。带上它，将来能显式迁移。
    """
    return {
        "schema": 1,
        "session_id": str(sid or ""),
        "current_topic": "",          # 当前在聊什么（语义级话题，不是关键词）
        "user_understanding": [],     # 此刻对用户的判断（当下的理解，不是长期画像）
        "recent_thoughts": [],        # 刚才在想什么（最近 2~3 轮的思考过程）
        "open_questions": [],         # 悬而未决的问题（想问但没问的）
        "tone_state": "neutral",      # 当前语气状态
        "unsaid": [],                 # 想说的没说的话（被截断/被跳过的）
        "turn_count": 0,              # 本会话轮数
        "last_updated": 0.0,
    }


def load(sid):
    """读某会话的思维状态；文件不存在/读坏/格式不对 → 返回**空状态**（绝不抛）。

    为什么读坏要给空状态而不是报错：状态是"锦上添花"（缺了只是这一轮从零开始），
    而它读在**每轮对话的入口**上 —— 在这里抛异常等于因为"记不住思路"而答不了话。
    """
    p = path_for(sid)
    if not os.path.exists(p):
        return blank(sid)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return blank(sid)
        st = blank(sid)
        st.update({k: v for k, v in d.items() if k in FIELDS or k in ("schema", "session_id")})
        # 类型兜底：文件可能被人手改过（"我看你不顺眼"），列表字段必须还是列表
        for k in ("user_understanding", "recent_thoughts", "open_questions", "unsaid"):
            if not isinstance(st.get(k), list):
                st[k] = []
        if not isinstance(st.get("current_topic"), str):
            st["current_topic"] = ""
        if st.get("tone_state") not in TONES:
            st["tone_state"] = "neutral"
        try:
            st["turn_count"] = int(st.get("turn_count") or 0)
        except Exception:      # noqa: silent-ok — 轮数坏了就当 0，不值得为此报错
            st["turn_count"] = 0
        return st
    except Exception:      # noqa: silent-ok — 读坏按"没有状态"处理，下一轮重新长出来
        return blank(sid)


def save(sid, st):
    """把状态写回磁盘（**只写不删**，见项目红线）。

    为什么直接覆写不做 tmp+rename：Windows 上 rename 覆盖目标等价于"删旧文件"，
    而本项目的硬约束是绝不删除任何文件；这里写的是自己的状态文件，
    内容是内存里算好的，写坏了下一次写会覆盖回来。
    """
    try:
        st = dict(st or {})
        st["last_updated"] = time.time()
        st["session_id"] = str(sid or "")
        # 二次裁剪：即使上游忘了截断，落盘也不会无限膨胀
        for key, lim in (("recent_thoughts", MAX_THOUGHTS),
                         ("open_questions", MAX_OPEN_QUESTIONS),
                         ("unsaid", MAX_UNSAID),
                         ("user_understanding", MAX_UNDERSTANDING)):
            v = st.get(key)
            st[key] = list(v)[-lim:] if isinstance(v, list) else []
        with open(path_for(sid), "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        return True
    except Exception:      # noqa: silent-ok — 存不上只影响下一轮的连续性，不能影响本轮回答
        return False


def summary(st, max_len=120):
    """一行中文摘要（给日志/界面看）。**没有内容就说没有，不编。**"""
    st = st or blank()
    topic = str(st.get("current_topic") or "").strip()
    parts = []
    parts.append("话题=%s" % (topic or "（还没定）"))
    parts.append("轮数=%s" % st.get("turn_count") or 0)
    u = st.get("user_understanding") or []
    if u:
        parts.append("了解=%s" % "、".join(str(x)[:12] for x in u[:3]))
    t = st.get("tone_state")
    if t and t != "neutral":
        parts.append("语气=%s" % TONE_CN.get(t, t))
    return ("｜".join(parts))[:max_len]
