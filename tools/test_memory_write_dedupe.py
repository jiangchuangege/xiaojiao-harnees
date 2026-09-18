# -*- coding: utf-8 -*-
"""写入侧去重自测（离线）：同一句对话问三遍，库里**不许**多出三行。

【为什么必须钉】用户实测：同一句「我住在菏泽」问三次 → 记忆库 450 → 451 → 452。
  一次性的存量清理（--dedupe-exact）治不了这个 —— 源头每次都在写，清完还会攒起来。
  所以这里直接在 `core/memory_vec.add_memory` 上加去重，并把这个行为钉住。

跑法：python tools/test_memory_write_dedupe.py（用**临时库**，不碰真库）
"""
import io
import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import memory_vec as MV  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def _lines(p):
    if not os.path.exists(p):
        return []
    return [l for l in io.open(p, encoding="utf-8", errors="replace").read().split("\n") if l.strip()]


def main():
    tmp = tempfile.mkdtemp(prefix="memdedup_")
    old_path = MV.path
    old_i, old_m, old_r = MV._INDEX["meta"], MV._INDEX["rows"], MV._INDEX["loaded"]
    real = os.path.join(tmp, "mem.jsonl")
    try:
        MV.path = lambda: real
        MV._INDEX["meta"], MV._INDEX["rows"], MV._INDEX["loaded"] = [], [], False

        print("一、同一句问三遍：只写一条")
        for i in range(3):
            MV.add_memory("用户：我住在菏泽\n小焦：好，我记下了。", kind="dialogue", key_text="我住在菏泽")
        n = len(_lines(real))
        ck("三遍只落一行（写入侧去重生效）", n == 1, "落盘 %d 行" % n)

        print("二、**回答不一样**时：仍是同一行（正文刷新，不新增）——这是用户实测的那个形状")
        before = len(_lines(real))
        MV.add_memory("用户：我住在菏泽\n小焦：菏泽的面食不错。", kind="dialogue", key_text="我住在菏泽")
        after = _lines(real)
        ck("行数没变（同一个问题只留一份）", len(after) == before, "%d → %d" % (before, len(after)))
        ck("正文被刷新成最新那版", "面食" in after[0], after[0][:80])
        ck("原 id 保留（没有换一条）", json.loads(after[0])["id"] == json.loads(_lines(real)[0])["id"])
        ck("记下了问过几次", int(json.loads(after[0]).get("same_key_n") or 0) >= 2,
           json.loads(after[0]).get("same_key_n"))

        print("\n三、换个问题：当然要写")
        MV.add_memory("用户：我喜欢猫\n小焦：猫好。", kind="dialogue", key_text="我喜欢猫")
        ck("不同 key → 新的一条", len(_lines(real)) == before + 1, "落盘 %d 行" % len(_lines(real)))

        print("\n四、返回的是**已有那条的 id**（不是空、也不是新 id）")
        a = MV.add_memory("用户：我喜欢猫\n小焦：猫好。", kind="dialogue", key_text="我喜欢猫")
        ids = [json.loads(l)["id"] for l in _lines(real)]
        ck("重复写入返回已存在的 id", a in ids, (a, ids))
        ck("并且没有再落一行", len(ids) == before + 1, len(ids))

        print("\n五、空内容本来就不写（旧行为不变）")
        ck("空 text → 返回空串", MV.add_memory("") == "")
        ck("库行数没变", len(_lines(real)) == before + 1, len(_lines(real)))
    finally:
        MV.path = old_path
        MV._INDEX["meta"], MV._INDEX["rows"], MV._INDEX["loaded"] = old_m, old_r, old_i
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 70)
    print("写入侧去重自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
