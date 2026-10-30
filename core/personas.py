# -*- coding: utf-8 -*-
"""小焦 · 人设（2026-10-30）

【为什么单独一个模块】用户要「给每个 AI 设置性格人设」，而人设会被两处用到：
朋友圈（发什么语气）和模型群组（怎么说话）。写两份必然打架，所以只有这一份。

存储：`logs/personas.json`
    {"小焦": {"name": "小焦", "persona": "……", "model": "", "enabled": true}, ...}
边界：只存文本，不做判断；谁在用就谁读。所有写入走同一把锁 + 原子替换。
"""
import io
import json
import logging
import os
import threading
import time

LOG = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "logs", "personas.json")
_LOCK = threading.Lock()

_DEFAULT = {
    "name": "小焦",
    "persona": ("我是小焦，住在你电脑里的 AI 助手。说话直接、不装、不糊弄；"
                "有不确定的就说不确定；会记住你的事，也会有自己的小心思。"),
    "relation": "",          # 你给它的关系/身份：女朋友、室友、搭档、后宫成员…（你自己定）
    "avatar": "",            # 头像文件名（logs/personas/avatars/<名字>.<ext>）
    "model": "",
    "enabled": True,
}

_AVDIR = os.path.join(_ROOT, "logs", "personas", "avatars")


def avatar_dir():
    os.makedirs(_AVDIR, exist_ok=True)
    return _AVDIR


def set_avatar(name, blob, ext="png"):
    """存这个 AI 的头像（只留一张，旧的删掉）。"""
    import re as _re
    safe = _re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fa5]", "_", str(name or "小焦"))[:40] or "xj"
    d = avatar_dir()
    try:
        for old in os.listdir(d):
            if old.startswith(safe + "."):
                try:
                    os.remove(os.path.join(d, old))
                except Exception:      # noqa: silent-ok
                    pass
        fn = "%s.%s" % (safe, str(ext or "png").lstrip("."))
        with open(os.path.join(d, fn), "wb") as f:
            f.write(blob or b"")
        return fn
    except Exception as e:      # noqa: silent-ok
        LOG.debug("存头像失败：%s", e)
        return ""


def avatar_path(name):
    """找这个 AI 的头像文件（没有返回空串）。"""
    import re as _re
    safe = _re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fa5]", "_", str(name or "小焦"))[:40] or "xj"
    try:
        d = avatar_dir()
        for old in os.listdir(d):
            if old.startswith(safe + "."):
                return os.path.join(d, old)
    except Exception:      # py: silent-ok
        pass
    return ""


def _load():
    try:
        with io.open(_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:      # noqa: silent-ok — 没有就是空库
        return {}


def _save(d):
    os.makedirs(os.path.dirname(_PATH), exist_ok=True)
    tmp = _PATH + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2))
    os.replace(tmp, _PATH)


def get(name="小焦"):
    """取某个人设（没有就用默认那份，不编）。"""
    d = _load()
    p = d.get(name) or d.get("小焦") or _DEFAULT
    out = dict(_DEFAULT)
    out.update(p or {})
    out["name"] = name or out.get("name") or "小焦"
    return out


def set_persona(name, persona, model="", enabled=True, relation=None, avatar=None):
    """设置人设。返回保存后的完整记录。"""
    name = str(name or "小焦").strip() or "小焦"
    with _LOCK:
        d = _load()
        cur = dict(d.get(name) or _DEFAULT)
        cur.update({"name": name, "persona": str(persona or "").strip(),
                    "model": str(model or "").strip(), "enabled": bool(enabled),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if relation is not None:
            cur["relation"] = str(relation or "").strip()[:40]
        if avatar is not None:
            cur["avatar"] = str(avatar or "").strip()
        d[name] = cur
        _save(d)
    LOG.info("人设已更新：%s（%d 字，模型=%s）", name, len(cur["persona"]), cur["model"] or "默认")
    return cur


def list_all():
    """所有人设（含默认那份）。"""
    d = _load()
    out = [dict(_DEFAULT, **{"name": "小焦"})]
    for k, v in (d or {}).items():
        row = dict(_DEFAULT)
        row.update(v or {})
        row["name"] = k
        out.append(row)
    # 去重（同名只留一条，后写的覆盖默认）
    seen, uniq = set(), []
    for r in out:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        uniq.append(r)
    return uniq


def names():
    return [r["name"] for r in list_all()]
