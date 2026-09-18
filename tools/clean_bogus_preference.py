# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""清掉偏好库里的**假偏好**（把它们挪进隔离区，不是抹掉）。

**清的是哪一类**：`kind == "formed"` 里那些「根本不是偏好」的条目 ——
把当时那一下**心象照抄一遍**的、或者**没有素材**（`from_heart` 为空）的。
判据**不是这里新写的**，用的是 `core.preference.looks_like_preference()` ——
**新闸门挡什么，这个工具就清什么**（同一把尺子），所以清完不会马上又长回来。

**为什么是"挪"不是"删"**：那些条目是**它当时说过的话**。删掉等于改写历史，
所以整份备份 + 清掉的行进 `logs/quarantine/`，随时能翻回去看。

用法：
    python tools/clean_bogus_preference.py            # 只报（dry-run，默认）
    python tools/clean_bogus_preference.py --apply    # 真清（先备份，再重写文件）
退出码：0 = 看/清完了；1 = 读不出来。

⚠️ 本工具把 `preference._vec` 换成 `None` → `looks_like_preference` 里的 `_sim` **走字面退路**
  （不加载向量模型）。理由：清库要**快且可复现**，判据本身不依赖模型；
  代价也要说清楚：**"跟素材太像"这一条在这里是按字面重合算的**，跟线上（向量余弦）可能有个别出入。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:      # noqa: silent-ok
        pass


def _load(pf):
    path = pf.path()
    rows, raw = [], []
    if not os.path.exists(path):
        return rows, raw
    for ln in io.open(path, encoding="utf-8", errors="replace").read().split("\n"):
        raw.append(ln)
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:      # noqa: silent-ok — 坏行原样留着，不碰
            rows.append(None)
    return rows, raw


def main() -> int:
    apply = "--apply" in sys.argv
    from core import preference as pf

    # 判据不依赖模型：把向量换掉，`_sim` 走字面退路（理由见文件头）
    pf._vec = lambda t: None

    path = pf.path()
    rows, raw = _load(pf)
    if not rows:
        print("偏好库是空的（或读不出来）：%s" % path)
        return 0

    fs = [(i, r) for i, r in enumerate(rows) if r and r.get("kind") == "formed"]
    bad = [(i, r, pf.looks_like_preference(r.get("pref"), r.get("from_heart"))) for i, r in fs]
    bad = [(i, r, why) for i, r, why in bad if why]
    keep = [(i, r) for i, r in fs if not pf.looks_like_preference(r.get("pref"), r.get("from_heart"))]

    print("=" * 84)
    print("  偏好库体检（清的是「假偏好」，判据 = `core.preference.looks_like_preference`）")
    print("=" * 84)
    print("文件：%s" % path)
    print("总条数 %d ｜ 其中 formed（它自己回看出来的）%d ｜ 要清 %d ｜ 留下 %d"
          % (len([r for r in rows if r]), len(fs), len(bad), len(keep)))
    print("-" * 84)
    if bad:
        print("【要清掉的】")
        for i, r, why in bad:
            print("  行%-5d %s" % (i + 1, str(r.get("pref"))[:64]))
            print("          理由：%s" % why)
            print("          素材：%s" % (str(r.get("from_heart"))[:64] or "（空）"))
    else:
        print("【要清掉的】没有 —— 库里没有假偏好")
    print("-" * 84)
    print("【留下的 formed（真偏好）】")
    for i, r in keep:
        print("  行%-5d %s" % (i + 1, str(r.get("pref"))[:64]))
    if not keep:
        print("  （一条都没有 —— 那 `render()/top()` 就是空的，如实为空，不许硬凑）")

    if not bad:
        print("\n不用清。")
        return 0
    if not apply:
        print("\n这是 **dry-run**（一个字都没改）。要真清：加 `--apply`")
        return 0

    ts = time.strftime("%Y%m%d_%H%M%S")
    bakdir = os.path.join(ROOT, "logs", "backup_before_pref_clean", ts)
    os.makedirs(bakdir, exist_ok=True)
    shutil.copy2(path, os.path.join(bakdir, "preference.jsonl"))
    qdir = os.path.join(ROOT, "logs", "quarantine")
    os.makedirs(qdir, exist_ok=True)
    qpath = os.path.join(qdir, "bogus_preference_%s.jsonl" % ts)
    with io.open(qpath, "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "_note",
                            "why": "从 logs/psyche/preference.jsonl 挪出来的假偏好（判据=looks_like_preference）",
                            "ts": time.time(), "n": len(bad)}, ensure_ascii=False) + "\n")
        for i, r, why in bad:
            f.write(json.dumps({**r, "_cleaned_why": why, "_was_line": i + 1},
                               ensure_ascii=False) + "\n")

    bad_idx = {i for i, _r, _w in bad}
    keep_lines = [ln for i, ln in enumerate(raw) if i not in bad_idx and ln.strip()]
    # 【并发保护】小焦可能正在跑（每起一次心就 append 一行）。重写是整个文件覆盖，
    #   所以**重写前再看一眼**：把"我读完之后它新写进来的行"原样接在后面，别把刚写的弄丢。
    extra = []
    try:
        now_raw = io.open(path, encoding="utf-8", errors="replace").read().split("\n")
        tail_from = len(raw) - 1 if (raw and not raw[-1].strip()) else len(raw)
        extra = [ln for ln in now_raw[tail_from:] if ln.strip()]
    except Exception as e:      # noqa: silent-ok — 看不到就按没有新增处理
        print("（并发保护：重读失败，按没有新增处理：%s）" % e)
    if extra:
        print("（并发保护：读完之后它又写了 %d 行，原样保留）" % len(extra))
    out = keep_lines + extra
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, path)

    after = pf.preferences()
    print("\n✅ 已清：挪走 %d 条 ｜ 现在 formed = %d 条" % (len(bad), len(after)))
    print("   整份备份：%s" % os.path.relpath(os.path.join(bakdir, "preference.jsonl"), ROOT))
    print("   挪走的行：%s" % os.path.relpath(qpath, ROOT))
    print("   剩下的偏好：%s" % ("；".join(str(r.get("pref")) for r in after) or "（没有）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
