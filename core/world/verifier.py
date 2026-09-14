# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 世界层 · 校验器（model verifier）

【一句话定位】给世界模型做**年检**：我上次对那个站的判断，事后看准不准？

【为什么必须有它（没有它，世界模型会"一次判断用到死"）】
自主探索每天都在往世界地图里写判断（这是科技媒体、那站不可信……）。
可**判断本身也会错**：域名换了主人、内容质量变了、当初的"广告站"后来认真做内容了。
没有校验器，第一个判断就永久生效 —— 地图会越来越偏离现实，
而小焦会拿着一张过期地图在世界里走。
这一层做三件事：
  ① **回看**：拿后来的快照/内容跟当初的判断比对；
  ② **修正**：不准 → 改判断 + 记录（`verification.jsonl`，可复盘"为什么改"）；
  ③ **降权/归档**：长时间不访问 → 交给 `WorldModel.decay_unused()`（不是删除，是降权）。

【去掉它会怎样】世界的"可信度/类型"永远停在第一次的猜测上；
用户看到的报告里有数字、但那些数字不再对应现实 —— 比没有数字更危险。
"""
import json
import os
import sys
import time

try:
    from .model import WorldModel
except Exception:                       # noqa: BLE001 — 允许作为脚本直接跑
    from model import WorldModel        # type: ignore

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORLD_DIR = os.path.join(_REPO_ROOT, "logs", "world")

try:
    import logging
    logger = logging.getLogger(__name__)
except Exception:                       # noqa: BLE001
    logger = None


def _log(msg, *a):
    if logger is not None:
        try:
            logger.info(msg, *a)
        except Exception:               # noqa: BLE001
            pass


def _append(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        return True
    except Exception:                   # noqa: BLE001 — 记不上不能中断校验
        return False


def _read_jsonl(path, limit=2000):
    out = []
    try:
        if not os.path.exists(path):
            return out
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:       # noqa: BLE001 — 半截行跳过
                    continue
    except Exception:                   # noqa: BLE001 — 读不动当没有
        return out
    return out[-limit:]


class WorldVerifier:
    """定期回看世界模型的判断，准的增强、不准的修正、久不访问的降权。"""

    def __init__(self, model=None, perception=None, judge=None, state_dir=None):
        self.state_dir = state_dir or WORLD_DIR
        self.model = model if model is not None else WorldModel(os.path.join(self.state_dir, "model.json"))
        self.perception = perception
        self.judge = judge
        self.log_path = os.path.join(self.state_dir, "verification.jsonl")

    # ---------------- 单个站点的复核 ----------------
    def verify_one(self, domain):
        """复核一个站：拿"最近看到的实际内容"跟"当初的判断"比，给结论。"""
        dom = str(domain or "").strip().lower()
        before = {}
        try:
            before = self.model.judgment_of(dom) or {}
        except Exception:               # noqa: BLE001 — 拿不到旧判断就当没有
            before = {}
        if not before:
            return {"domain": dom, "verdict": "unknown", "why": "世界模型里没有这个站的判断"}
        # 用"最近快照的字数"当作"它还在不在产出"的证据（不联网也能复核一半）
        chars = 0
        try:
            snaps = _read_jsonl(os.path.join(self.state_dir, "snapshots.jsonl"), limit=400)
            mine = [s for s in snaps if (s.get("domain") or "") == dom]
            if mine:
                chars = int(mine[-1].get("chars") or 0)
        except Exception:               # noqa: BLE001 — 快照读不到就只按时间判
            chars = 0
        last_seen = float(before.get("last_seen") or 0)
        idle_days = (time.time() - last_seen) / 86400.0 if last_seen else 999
        conf = float(before.get("confidence") or 0.5)
        trust = float(before.get("judged_trust") or before.get("trust") or 0.5)

        after, verdict, why = dict(before), "keep", ""
        if idle_days > 30:
            # 久不访问 → **降权**（不是删掉）：地图里保留这个站，只是不再那么信它
            after["judged_trust"] = round(max(0.1, trust * 0.9), 3)
            after["confidence"] = round(max(0.1, conf * 0.9), 3)
            verdict, why = "decay", "已有 %.0f 天没访问过这个站 → 可信度降到 %.2f" % (
                idle_days, after["judged_trust"])
        elif chars and chars < 200:
            after["confidence"] = round(max(0.1, conf - 0.2), 3)
            after["quality"] = after.get("quality") or "unknown"
            verdict, why = "revise", "最近一次抓到的正文只有 %d 字（不像正常页面）→ 降置信度" % chars
        elif chars >= 2000:
            after["confidence"] = round(min(1.0, conf + 0.1), 3)
            verdict, why = "boost", "最近抓到的正文 %d 字，内容充实的证据 → 提高置信度" % chars
        else:
            why = "没有新证据，维持原判断"
        rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%d %H:%M:%S"), "domain": dom,
               "before": before, "after": after, "verdict": verdict, "reason": why,
               "idle_days": round(idle_days, 1), "chars": chars}
        _append(self.log_path, rec)
        if verdict in ("decay", "revise", "boost"):
            try:
                # 写回地图：**改判断、不改历史**（verification.jsonl 里留着 before/after 对照）
                self.model.remember_judgment(dom, after)
            except Exception as e:      # noqa: BLE001 — 写不回也不影响这次复核的结论
                _log("校验器：写回判断失败(%s)：%s", dom, e)
        return rec

    def review(self, days=7, limit=50):
        """批量复核：按"最久没被复核过"的顺序挑，避免每次都查同样的几个。"""
        sites = {}
        try:
            sites = dict(self.model.snapshot().get("sites") or {})
        except Exception:               # noqa: BLE001
            sites = {}
        recent = {}
        for r in _read_jsonl(self.log_path, limit=500):
            recent[r.get("domain")] = max(recent.get(r.get("domain"), 0), float(r.get("ts") or 0))
        order = sorted(sites, key=lambda d: recent.get(d, 0))
        out = []
        for dom in order[:max(1, int(limit))]:
            try:
                out.append(self.verify_one(dom))
            except Exception as e:      # noqa: BLE001 — 单个站出错不能中断整批复核
                out.append({"domain": dom, "verdict": "error", "why": str(e)[:120]})
        try:
            dec = self.model.decay_unused()
        except Exception:               # noqa: BLE001 — 降权失败不影响复核结论
            dec = 0
        stat = {"ts": time.time(), "reviewed": len(out), "decayed": dec,
                "by_verdict": {}}
        for r in out:
            v = r.get("verdict") or "?"
            stat["by_verdict"][v] = stat["by_verdict"].get(v, 0) + 1
        _append(os.path.join(self.state_dir, "verification_runs.jsonl"), stat)
        return {"reviewed": len(out), "decayed": dec, "results": out, "summary": stat["by_verdict"]}

    def report(self, days=7):
        """给用户看的中文报告：**必须带真实数字**（没有数字的报告等于没说）。"""
        rows = [r for r in _read_jsonl(self.log_path, limit=2000)
                if float(r.get("ts") or 0) >= time.time() - days * 86400]
        if not rows:
            return "最近 %d 天还没做过世界模型复核。" % days
        cnt = {}
        for r in rows:
            v = r.get("verdict") or "?"
            cnt[v] = cnt.get(v, 0) + 1
        lines = ["最近 %d 天复核了 %d 个站：" % (days, len(rows))]
        cn = {"keep": "维持原判断", "boost": "提高置信度", "revise": "修正（降置信度）",
              "decay": "长时间没访问 → 降权", "unknown": "没有判断可复核", "error": "复核出错"}
        for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
            lines.append("  · %s：%d 个" % (cn.get(k, k), v))
        ex = [r for r in rows if r.get("verdict") in ("revise", "decay")][:2]
        for r in ex:
            lines.append("  · 例：%s —— %s" % (r.get("domain"), r.get("reason")))
        return "\n".join(lines)


# ---------------- 单例 ----------------
_SINGLETON = {"obj": None}


def get_verifier(**kw):
    if _SINGLETON["obj"] is None:
        _SINGLETON["obj"] = WorldVerifier(**kw)
    return _SINGLETON["obj"]


def review(days=7, **kw):
    """宿主/后台任务直接调这个即可。"""
    return get_verifier(**kw).review(days=days)
