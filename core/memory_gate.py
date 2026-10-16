# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 记忆口径闸门（把「绝假记忆」接到主对话链路上）

【这是什么】
    `core/memory_deep.py` 里那套判断（precise / fuzzy / none）本身是完整的，
    但在 2026-10-15 之前**只有自测脚本在调** —— `docs/modules/03-memory-depth.md`
    7.1 那张表里如实写着「设计，未落地」。
    本模块就是"落地"那一步：在**用户明确在问自己记忆里的事**时，
    把检索出口的口径**替它定死**，写进这一轮的 system。

【为什么必须由载体定，而不是留给模型】
    用户问一件从没说过的事（"我的车牌号是多少"），主链路要么什么都不注入、
    要么注入几条"像的"片段，然后由模型自己决定怎么答 ——
    而模型的默认行为是**顺着问句编一个像样的答案**。编造用户的经历是最严重的失信，
    而且用户很难当场发现（他只能凭印象觉得"我没说过这个啊"）。
    所以这一句必须由载体写死：**记得 / 只记得大概 / 没记过**，三选一。

【只加不删，三道保险（任何一道不成立就一个字都不加）】
    ① **只在"问自己记忆"的问题上说话**（`is_memory_question`）：正常聊天、
       写代码、查新闻一律不碰 —— 否则每轮都塞一句"你没说过"就成了神经病；
    ② **precise 一律不说话**：精确命中时注入文本原样，一个字不改（好用的地方不动）；
    ③ **别的记忆源已经知道答案就不说话**（`other_knows`）：用户原话直答
       （`_find_user_fact`）与画像召回能答的问题，绝不让这道闸门去唱反调 ——
       否则会出现"右边说有、左边说没说过"的自相矛盾，比不接还糟。

【诚实的边界】
    · 它判的是"**我记不记得**"，不是"这件事对不对"（记忆本身可能有错，那是检索与库的问题）；
    · 它不修检索排序：top-1 选错了一条（比如问猫答狗）它照样会判 precise ——
      那是 `retriever` 的活，本模块不越界；
    · 判据全是确定性的（余弦 + 表面重合），不调模型、不额外花钱、不额外等一次检索。
"""
from . import memory_deep as MD

# 问法标记：出现这些字，说明这句话**在问**（与 `xiaojiao_app._MY_Q_MARKS` 同一套口径；
# 核心层不 import 应用层，所以这里各写一份，改动时两边一起改）。
_ASK_MARKS = ("哪", "什么", "谁", "几", "多少", "吗", "呢", "？", "?")

# "关于我自己的事"的话题词：必须命中其中一个**才**认为用户在问记忆，
# 否则"我该学点什么""我今天穿什么"也会被当成记忆问题。
# 这份表和 `xiaojiao_app._MY_FACT_WORDS` 是同一批词（那边管"从库里取原话"，这边管"要不要判口径"）。
_SELF_TOPICS = (
    "记得", "记不记得", "说过", "提过", "告诉", "知道", "叫", "名字", "姓", "住", "生日",
    "岁", "年龄", "喜欢", "爱", "学", "工作", "职业", "上班", "公司", "单位", "学校", "大学",
    "养", "宠物", "狗", "猫", "吃", "喝", "过敏", "身体", "父母", "女儿", "儿子", "孩子",
    "伴侣", "老婆", "老公", "女朋友", "男朋友", "家乡", "老家", "城市", "地方",
    "手机", "电话", "微信", "邮箱", "电脑", "车",
)
# 实测补的这一批（2026-10-16，在真机上问出来的）：
#   「我在哪家公司上班」原来**判不出来**是记忆问题 —— 因为表里有「工作」却没有「上班/公司」。
#   漏判的后果是"闸门不介入"（回到旧行为，不算错但少了一层保护），
#   所以这里按"用户真会怎么问"补齐一组同义说法，而不是只留书面词。

_NOTE_HEAD = "【本轮口径 · 记忆闸门（载体定的，别改）】"


def is_memory_question(q):
    """这一轮用户是不是在问「我记忆里有没有这件事」。

    判据刻意**窄**（三条全中才算）：有第一人称 + 是个问句 + 问的是"关于我自己的话题"。
    宁可漏判（那只是不介入，回到原行为），也不要误判（误判会让正常聊天被塞进"你没说过"）。
    """
    s = str(q or "").strip()
    if not s or len(s) > 40:
        return False
    if "我" not in s and "咱" not in s:
        return False
    if not any(w in s for w in _ASK_MARKS):
        return False
    return any(w in s for w in _SELF_TOPICS)


def note_for(verdict):
    """口径 → 写进 system 的那句话（precise/empty 不说话，返回空串）。"""
    if verdict == "none":
        return (_NOTE_HEAD +
                "用户问的是**关于他自己**的事，而记忆里**一条都没记过** → "
                "必须如实说「你之前没跟我说过这事」，**不许**拿下面任何一条不相关的素材去顶，"
                "也**不许**替他补一个细节出来（数字、时间、地点、名字一律不许编）。")
    if verdict == "fuzzy":
        return (_NOTE_HEAD +
                "记忆里有**像的**，但证据只到「记得这件事」 → 可以说「我记得你提过…」，"
                "**不许补细节**（数字、时间、地点、名次一律不许填），要请用户提醒一句；"
                "细节以用户下一句为准，不要自己圆回来。")
    return ""


def judge(query, hits, cfg=None, other_knows=False):
    """判这一轮的口径，并给出"要不要往 system 里加一句"的结论。**绝不抛异常**。

    cfg（来自控制文件 `capabilities`，全部有默认值）：
      · `memory_gate`        总开关，默认 True（关掉就回到接之前的行为）
      · `memory_precise_overlap`  覆盖 precise 的表面重合门槛（默认 0.4，见 memory_deep）
    other_knows：**别的记忆源是不是已经知道答案**（用户原话直答 / 画像召回）。
                  True → 这道闸门不介入（避免"一处说有、一处说没说过"的自相矛盾）。

    返回 {"verdict", "note", "reason", "applied", "best"}：
      applied=True 表示 `note` 应当被追加进 system；其余情况 note 是空串、行为与接之前一致。
    """
    out = {"verdict": "", "note": "", "reason": "", "applied": False, "best": None}
    try:
        cfg = cfg or {}
        if cfg.get("on", True) is False:
            out["reason"] = "闸门被配置关掉了（capabilities.memory_gate=false）"
            return out
        q = str(query or "").strip()
        if not is_memory_question(q):
            out["reason"] = "不是「问自己记忆」的问题 → 不介入"
            return out
        d = MD.decide_hits(q, hits or [], overlap_min=cfg.get("overlap"))
        out["verdict"] = d["verdict"]
        out["reason"] = d["reason"]
        out["best"] = d["best"]
        if d["verdict"] in ("precise", "empty"):
            out["reason"] = "口径=%s：注入原样不动（%s）" % (d["verdict"], d["reason"])
            return out
        if other_knows:
            out["reason"] = ("口径=%s，但别的记忆源（用户原话/画像）已经知道 → "
                             "闸门不说话（免得两边唱反调）" % d["verdict"])
            return out
        out["note"] = note_for(d["verdict"])
        out["applied"] = bool(out["note"])
    except Exception as e:      # noqa: silent-ok — 闸门自己出错就当作"不介入"，绝不拖垮对话
        out["reason"] = "闸门自身出错，按不介入处理：%s" % e
        out["note"] = ""
        out["applied"] = False
    return out
