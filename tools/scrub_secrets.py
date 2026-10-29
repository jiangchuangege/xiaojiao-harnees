# -*- coding: utf-8 -*-
"""明文密钥清理 + 备份文件脱敏（2026-10-29）

【为什么要这个脚本】外部审计在这台机器上真找到了东西：
  `logs/` 下至少 5 份配置备份文件里存着明文 `api_key`（`sk-…`）。
  日志输出那条链是脱敏的（`xiaojiao_log.py` 会把 `sk-…` 打码），
  但**备份文件**是"把 control 原样拷一份"，走的是文件写入，没经过脱敏 —— 这就是漏的那条缝。

【它怎么处理"只加不删"这条红线】
  用户规矩是不能删数据。密钥不是数据，是**凭据**：它留在盘上一天，风险就多一天。
  所以这里的做法是：
    1. 先把**脱敏后的内容**写一份到 `logs/backup_secrets/<原路径>.redacted-<时间>`（保留结构，只把密钥串换成占位符）；
    2. 再就地脱敏原文件（把 `sk-…` 换成 `<<REDACTED-ROTATE-THIS-KEY>>`）；
    3. **不改任何其它字节**（缩进、注释、换行全保留）。
  换句话说：文件一个不少、结构一点不变，唯一消失的是那串密钥本身 —— 而它本来就该作废重发。

用法：
    python tools/scrub_secrets.py              # 只扫描，打印在哪（打码显示）
    python tools/scrub_secrets.py --apply      # 扫描 + 就地脱敏（先写脱敏备份）
    python tools/scrub_secrets.py --path logs  # 只扫某个目录
"""
import argparse
import io
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKUP = os.path.join(_ROOT, "logs", "backup_secrets")

# 认得出来的凭据（宁少不滥：只认有明确前缀或明确结构的）
_PATTERNS = [
    ("OpenAI 风格 key", re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("百度/阿里等长 key 字段", re.compile(r'"(?:api_key|apikey|access_key|secret_key|token)"'
                                        r'\s*:\s*"([A-Za-z0-9_\-\.]{16,})"')),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
_MASK = "<<REDACTED-ROTATE-THIS-KEY>>"

# 扫哪些后缀（二进制/大文件跳过：不读进内存，也不在二进制里瞎改）
_EXT_OK = (".json", ".jsonl", ".log", ".txt", ".md", ".py", ".yaml", ".yml", ".ini", ".env",
           ".bak", ".old", ".backup", ".cfg", ".conf")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", "backup_secrets", "quarantine"}
# 【别把"该放密钥的地方"也治了】`xiaojiao_control.json` 是**唯一合法的配置入口**，
#   密钥放在那里是正常的事（就像 `.env`）。真正的问题是"它被顺手复制进 logs/ 的十份备份里"。
#   所以默认**跳过**这个活跃配置文件，只清散落在各处的副本；确实要连它也清，加 `--include-config`。
_ACTIVE_CONFIG = "xiaojiao_control.json"


def _mask(s):
    """打码显示：只留前 4 后 4，中间用 * 填。"""
    s = str(s)
    if len(s) <= 10:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


def _scan_text(text):
    """返回 [(类型, 命中的原串)]（去重）。"""
    hits = []
    seen = set()
    for name, rx in _PATTERNS:
        for m in rx.finditer(text):
            raw = m.group(1) if (m.groups() and name.endswith("长 key 字段")) else m.group(0)
            key = (name, raw)
            if key in seen:
                continue
            seen.add(key)
            hits.append((name, raw))
    return hits


def scan(path=None, max_files=4000, include_config=False):
    """扫一遍，返回 [(文件, 类型, 打码后的样子)]（不打印、不改动）。"""
    root = os.path.abspath(path or _ROOT)
    out = []
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(_EXT_OK):
                continue
            fp = os.path.join(dirpath, fn)
            if (not include_config) and fn == _ACTIVE_CONFIG and os.path.dirname(
                    os.path.abspath(fp)) == _ROOT:
                continue        # 活跃配置是密钥合法的家，不清它（见 _ACTIVE_CONFIG 的说明）
            try:
                if os.path.getsize(fp) > 20 * 1024 * 1024:      # 跳过超大文件（日志动辄几百 MB）
                    continue
                text = io.open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:      # noqa: silent-ok — 读不了就跳过（权限/占用）
                continue
            for name, raw in _scan_text(text):
                out.append((os.path.relpath(fp, _ROOT), name, _mask(raw)))
            n += 1
            if n >= max_files:
                return out
    return out


def apply(path=None, include_config=False):
    """就地脱敏（先写一份脱敏备份）。返回 (改了几个文件, 抹了几处)。"""
    root = os.path.abspath(path or _ROOT)
    changed, n_hits = 0, 0
    if not os.path.isdir(_BACKUP):
        os.makedirs(_BACKUP, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith(_EXT_OK):
                continue
            fp = os.path.join(dirpath, fn)
            if (not include_config) and fn == _ACTIVE_CONFIG and os.path.dirname(
                    os.path.abspath(fp)) == _ROOT:
                continue        # 活跃配置是密钥合法的家，不清它（见 _ACTIVE_CONFIG 的说明）
            try:
                if os.path.getsize(fp) > 20 * 1024 * 1024:
                    continue
                text = io.open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:      # noqa: silent-ok
                continue
            hits = _scan_text(text)
            if not hits:
                continue
            red = text
            for name, raw in hits:
                red = red.replace(raw, _MASK)
                n_hits += 1
            # ① 先写"脱敏备份"（保留结构，方便日后排查当时是什么形状的配置）
            try:
                rel = os.path.relpath(fp, _ROOT).replace("\\", "__").replace("/", "__")
                bak = os.path.join(_BACKUP, rel + ".redacted-%d"
                                   % int(time.time()))
                io.open(bak, "w", encoding="utf-8", newline="").write(red)
            except Exception as e:      # noqa: silent-ok — 备份写不下也要把原文件治好
                print("  （脱敏备份写入失败：%s）" % e)
            # ② 再就地脱敏原文件
            try:
                io.open(fp, "w", encoding="utf-8", newline="").write(red)
                changed += 1
                print("  已脱敏：%s（%d 处）" % (os.path.relpath(fp, _ROOT), len(hits)))
            except Exception as e:      # noqa: silent-ok
                print("  脱敏失败：%s（%s）" % (os.path.relpath(fp, _ROOT), e))
    return changed, n_hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-config", action="store_true", dest="include_config",
                    help="连活跃的 xiaojiao_control.json 一起清（默认不清：那是密钥该待的地方）")
    args = ap.parse_args(argv)
    hits = scan(args.path or None, include_config=args.include_config)
    print("=" * 80)
    print("  明文密钥扫描（只打码显示，不打印原文）")
    print("=" * 80)
    if not hits:
        print("  ✅ 没找到明文凭据。")
        return 0
    cur = None
    for rel, name, masked in hits:
        if rel != cur:
            print("  %s" % rel)
            cur = rel
        print("      %-16s %s" % (name, masked))
    print("\n  合计 %d 处（%d 个不同的密钥串）"
          % (len(hits), len({h[2] for h in hits})))
    if not args.apply:
        print("\n  ⚠️ 这些是**真凭据**：建议先轮换（作废重发），再跑一次 `--apply` 就地脱敏。")
        return 1
    print("\n  开始就地脱敏（先写脱敏备份到 logs/backup_secrets/）…")
    changed, n = apply(args.path or None, include_config=args.include_config)
    print("\n  完成：%d 个文件、%d 处。" % (changed, n))
    left = scan(args.path or None, include_config=args.include_config)
    if left:
        print("  ⚠️ 还有 %d 处未清（可能是二进制/超大文件，需人工看）" % len(left))
        return 1
    print("  ✅ 现在扫不到了。记得**去服务商那边把旧 key 作废**——脱敏只是止血，不作废它仍然有效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
