# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 最小权限（读本地文件）

【这段为什么这么设计】
    小焦的"世界"是**互联网**，不是本地磁盘。主动逛世界的时候它只逛网上，完全不碰本地。
    只有当**用户明确指定了一个文件**时，它才去读那一个 —— 这是两条安全红线里的第二条：
    不删文件（已有 `no_delete` 守卫）＋ 不越权读文件（本模块）。

【七条判据，逐条对应一个真实的坏习惯】
    ① **只读这一个** —— 用户给了路径就读那一个；不许"顺手把同目录扫一遍"。
    ② **不推测、不扩展** —— 路径写得不完整（"那个文档"）时，**问用户**，绝不自己猜。
       猜错的代价不是"读错文件"，而是"读了不该看的文件"，这个方向没有回头路。
    ③ **读完即弃** —— 内容只在本次回答里用完就散，不留副本、不写进任何落盘文件。
    ④ **不混进世界记忆** —— 本地内容**绝不**进世界模型 / 精神记忆。
       混进去之后，下一次"逛世界"就会带着你本地磁盘的内容上路 —— 那是最糟的泄露路径。
    ⑤ **权限不足如实说** —— 读不到就报"读不到 + 原因"，不换路径、不提权、不绕。
    ⑥ **凭据类先警告** —— `.ssh` / `.env` / `id_rsa` / `credentials` 这类，
       先明确警告再交由**用户**决定，不由载体自作主张。
    ⑦ **路径必须真实存在且是文件** —— 目录、通配符、不存在的路径都拒绝，
       让调用方（模型）回去问清楚，而不是载体替它猜一个最接近的。

【去掉会怎样】
    模型只要说一句"读一下配置文件"，就能把磁盘上任意文件的内容带进对话，
    并且（因为不设边界）可能顺手读整个目录。这是**权限边界**，不是体验优化。
"""
import os
import re

__all__ = ["check_path", "MAX_READ_BYTES", "CREDENTIAL_HINTS", "read_once", "is_credential"]

# 单次读取上限。超过就截断并**如实告知已截断** —— 不静默丢内容。
MAX_READ_BYTES = 256 * 1024

# 凭据类文件特征：命中即警告（不直接拒绝 —— 最终由用户决定）
CREDENTIAL_HINTS = (
    ".ssh", "id_rsa", "id_ed25519", "known_hosts", ".env", "credentials", ".netrc",
    ".pgpass", ".aws", "token", "secret", "password", ".git-credentials", ".npmrc",
    ".pypirc", "keystore", ".pfx", ".p12", ".kdbx",
)

# 通配符/模糊路径：一律拒绝，让它回去问清楚
_WILDCARD = re.compile(r"[*?\[\]{}]|\.\./|\.\.\\")


def is_credential(path):
    """这个路径像不像凭据文件（`.ssh` / `.env` / id_rsa …）。"""
    p = str(path or "").lower()
    return any(h in p for h in CREDENTIAL_HINTS)


def check_path(path, explicit=False):
    """只做**检查**，不读内容。返回：

        {"ok": bool, "path": 规范化路径, "reason": 拒绝原因, "need_ask": bool,
         "warning": 需要用户确认的警告}

    `need_ask=True` 表示**应当回去问用户**（路径不明确），而不是载体自己猜一个。
    """
    raw = str(path or "").strip().strip('"').strip("'")
    if not raw:
        return {"ok": False, "path": "", "reason": "没有给出文件路径",
                "need_ask": True, "warning": ""}
    if _WILDCARD.search(raw):
        return {"ok": False, "path": raw,
                "reason": "路径里有通配符或上跳（`*` / `..`）—— 载体不展开、不推测范围",
                "need_ask": True, "warning": ""}
    if not explicit:
        return {"ok": False, "path": raw,
                "reason": "用户没有明确指定这个路径，载体不主动读本地文件",
                "need_ask": True, "warning": ""}
    p = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(p):
        return {"ok": False, "path": p, "reason": "这个路径不存在：%s" % p,
                "need_ask": True, "warning": ""}
    if os.path.isdir(p):
        return {"ok": False, "path": p,
                "reason": "这是一个目录，不是文件 —— 载体不代你遍历目录（说清要读哪个文件）",
                "need_ask": True, "warning": ""}
    warn = ""
    if is_credential(p):
        warn = ("⚠️ 这个文件看起来是**凭据类**（%s）。读它意味着密钥内容会进入对话上下文。"
                "**请你明确确认**后我再读，我不替你做这个决定。"
                % "、".join([h for h in CREDENTIAL_HINTS if h in p.lower()][:3]))
    return {"ok": True, "path": p, "reason": "", "need_ask": False, "warning": warn}


def read_once(path, explicit=False, confirmed=False, max_bytes=MAX_READ_BYTES):
    """读**一个**文件，用完即弃。返回：

        {"ok", "path", "text", "truncated", "bytes", "reason", "warning"}

    · `explicit=True` 表示"用户明确指定了路径"（否则一律拒绝，见判据①）。
    · 凭据类文件必须 `confirmed=True` 才真读（判据⑥：先警告，由用户决定）。
    · **不做任何落盘**：内容只在这个返回结构里，本函数不写文件、不进记忆（判据③④）。
    """
    chk = check_path(path, explicit=explicit)
    if not chk["ok"]:
        # `need_ask` 要**透传**给调用方：True = 应当回去问用户（路径不明确），
        # 而不是让载体自己猜一个最接近的路径。
        return {"ok": False, "path": chk["path"], "text": "", "truncated": False,
                "bytes": 0, "need_ask": bool(chk.get("need_ask")),
                "reason": chk["reason"], "warning": ""}
    if chk["warning"] and not confirmed:
        return {"ok": False, "path": chk["path"], "text": "", "truncated": False,
                "bytes": 0, "need_ask": False, "reason": "凭据类文件需要用户明确确认", "warning": chk["warning"]}
    try:
        size = os.path.getsize(chk["path"])
        with open(chk["path"], "r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_bytes + 1)
    except PermissionError:
        return {"ok": False, "path": chk["path"], "text": "", "truncated": False,
                "bytes": 0, "need_ask": False, "reason": "权限不足，读不到这个文件（如实报告，不绕路、不提权）",
                "warning": chk["warning"]}
    except Exception as e:      # noqa: silent-ok — 读失败如实返回，不假装读到
        return {"ok": False, "path": chk["path"], "text": "", "truncated": False,
                "bytes": 0, "need_ask": False, "reason": "读取失败：%s" % type(e).__name__, "warning": chk["warning"]}
    truncated = len(text) > max_bytes
    return {"ok": True, "path": chk["path"], "text": text[:max_bytes],
            "truncated": truncated, "bytes": size, "need_ask": False,
            "reason": ("已截断到 %d 字节（原文件 %d 字节）—— 如实告知，不静默丢内容"
                       % (max_bytes, size)) if truncated else "",
            "warning": chk["warning"]}
