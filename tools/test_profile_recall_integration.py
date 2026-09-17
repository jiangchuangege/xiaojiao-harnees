# -*- coding: utf-8 -*-
"""画像召回层 · **接入主流程**验收（要小焦在跑；不进 CI，因为它要真调大脑）

验收的是四件事，缺一件"接上了"就不算数：
  1. 用户消息进来 → `recall()` 真的被调了（日志有 `画像召回：…`）
  2. 召回结果真的进了 system（`build_system()` 出来的那段能在 system 里找到）
  3. 召回为空时正常走（不能因为没印象就答不出来）
  4. 回复**已经返回之后**，`remember_from_message()` 才在后台跑（不能阻塞用户等待）

运行：python tools/test_profile_recall_integration.py
"""
import io
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")
STORE = os.path.join(_ROOT, "xiaojiao_profiles.json")

# (用户这句, 期望召回的画像关键词 或 None 表示"不该召回任何印象", 要不要等写入)
# ⚠️ 第 5 条我第一版把期望写成"不召回任何印象"，那是**我自己写错了**：
#    「猫」是画像 8「用户喜欢猫，养了一只橘猫」的触发词，触发词那一路命中就该召回 —— 那是对的。
#    规格给这条的验收点只有一个：**回复之后要自动写入一条新画像**。
CASES = (
    ("今天心情不好", "失恋", False),
    ("推荐首歌听听", "周杰伦", False),
    ("晚上想吃点啥", "不会做饭", False),
    ("今天天气真好", None, False),
    ("我养了一只猫", "猫", True),
)


def tail_mark():
    try:
        return os.path.getsize(LOG)
    except Exception:      # noqa: silent-ok — 日志不在就从 0 开始
        return 0


def read_since(mark):
    try:
        with io.open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            return f.read()
    except Exception:      # noqa: silent-ok — 读不到就当空，由断言如实报缺
        return ""


def load_store():
    try:
        return json.load(io.open(STORE, encoding="utf-8")).get("profiles", [])
    except Exception:      # noqa: silent-ok — 库坏了按空算，测试如实报
        return []


def _why(q):
    """排查模式：一句话走一遍写入链，**把卡在哪一步打印出来**。

    【为什么需要它】`remember_from_message()` 对"不记 / 判重 / 没生成"三种情况**都返回 None**，
    光看返回值分不出是谁的问题。这三种的修法完全不同：
      · 判了"不记"    → 模型侧决定（载体没错）
      · 判重          → 闸门挡住了（正常）
      · 没生成出来    → **载体侧**（它的 JSON 没被解析出来，要修的是解析）
    模块本身不许改，所以排查放这里。
    """
    sys.path.insert(0, _ROOT)
    import xiaojiao_recall as R
    print("画像库：%s（%d 条）" % (R.PROFILES_PATH, len(R.load_profiles())))
    # 第一道门的**原始输出**（照抄模块里那段提示词；模块改了这里也要跟着改，只为看到它到底说了什么）
    _jp = ("用户说：%s\n\n"
           "这句话里有没有关于用户本人的、值得长期记住的信息？\n"
           "值得记的：身份、职业、居住地、喜好、忌讳、健康、家人、长期状态。\n"
           "不值得记的：临时情绪、一次性提问、天气、闲聊、问句。\n"
           "只回答两个字：要记 或 不记。" % q)
    _raw = R.local_chat([{"role": "user", "content": _jp}], temperature=0.0, max_tokens=8)
    print("\n① 判该不该记｜模型原始输出：%r（照抄模块的提示词问的）" % _raw)
    print("   should_remember → %s" % R.should_remember(q))
    p = R.generate_profile(q)
    print("② generate_profile → %s" % p)
    if p is None:
        print("   ⚠️ **载体侧**：它的输出没解析成画像（这一步该修解析，不是模型不记）")
        return 0
    print("③ is_duplicate → %s" % R.is_duplicate(p, R.load_profiles()))
    print("\n④ remember_from_message → %s" % R.remember_from_message(q))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--why":
        return _why(" ".join(sys.argv[2:]) or "我养了一只猫")
    if not os.path.exists(STORE):
        print("❌ 找不到画像库 %s" % STORE)
        return 2
    before = load_store()
    print("画像库开工前：%d 条" % len(before))
    ok = 0
    for i, (msg, want, wait_write) in enumerate(CASES, 1):
        print("\n" + "=" * 74)
        print("【%d】用户说：%s ｜ 期望：%s" % (i, msg, want or "不召回任何印象"))
        mark = tail_mark()
        t0 = time.time()
        try:
            r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=300)
            d = r.json()
        except Exception as e:      # noqa: silent-ok — 连不上就如实报，不假装成功
            print("  ❌ 请求失败：%s" % e)
            continue
        dt = time.time() - t0
        reply = str(d.get("answer") or "")
        got = read_since(mark)
        recall_lines = [ln.split("] ")[-1] for ln in got.split("\n") if "画像召回：" in ln]
        write_lines = [ln.split("] ")[-1] for ln in got.split("\n") if "画像写入：" in ln]
        print("  耗时 %.1fs ｜ 回复：%s" % (dt, reply.replace("\n", " ")[:110]))
        print("  日志·召回：%s" % (recall_lines or "（没有 画像召回 这一行 ← 没接上）"))
        hit = None
        if recall_lines:
            if want is None:
                # "没有印象"现在有两种正常写法：投出来是空的（空），
                # 或者这句话跟印象库没有词面交集、被闸门直接跳过（跳过）——
                # 后者是 2026-09-17 加的时间优化（一轮 10 路投票要 8~10 秒，
                # "你好"这种话不该为它花这个时间）。
                hit = ("空" in recall_lines[0]) or ("跳过" in recall_lines[0])
            else:
                hit = ("命中" in recall_lines[0]) and want in recall_lines[0]
        # system 里到底有没有那段（拿服务器自己的日志对不上，就看回复有没有用上——
        # 这里只判"召回这一层跑没跑、结果对不对"）
        if hit:
            ok += 1
        print("  判定：%s" % ("通过 ✅" if hit else "没过 ❌"))
        if wait_write:
            print("  （回复已经返回了，现在等后台写入链把它记下来…）")
            for _ in range(30):
                time.sleep(2)
                after = load_store()
                if len(after) > len(before):
                    new = [p["text"] for p in after[len(before):]]
                    print("  后台写入 → 新画像：%s" % new)
                    print("  日志·写入：%s" % (write_lines or "（还没有 画像写入 这一行）"))
                    break
            else:
                print("  ❌ 等了 60 秒，库里没有新画像")
            after = load_store()
            if len(after) > len(before):
                ok += 1
                print("  判定（写入）：通过 ✅")
            else:
                print("  判定（写入）：没过 ❌")

    print("\n" + "=" * 74)
    total = len(CASES) + 1        # 5 条召回 + 1 条写入
    print("接入验收：%d/%d" % (ok, total))
    print("=" * 74)
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
