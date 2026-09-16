# -*- coding: utf-8 -*-
"""闭环实测 · 兴趣积累与精准回答（**走真实服务链，不是自测喂自己**）

【这个测试要回答的那一个问题】
    先前的负结果：「把事实注入给模型 → 它当背景资料，不用」。
    闭环的假设：**它自己判断记下的关于用户的事，下次能真的用上**。
    这一条到底成不成，只能用真对话去测，测不出来就得如实说测不出来。

【每条案例走三步，缺一步结论就不成立】
    ① 对照（还不知道时）：新会话问同一个问题 → 答案里**不该**出现那个事实
       · 这一步是**负对照**：没有它，第③步"答案里有 NBA"可能只是问题本身带出来的
    ② 写入：新会话把事实说出来 → 查 `logs/psyche/user_profile.jsonl` 有没有记下
    ③ 命中（新会话）：**再问一次同一个问题** → 答案里出现那个事实
       · 必须是**新会话**：同一会话里历史就带着那句事实，测的是历史不是闭环

【归因（不许含糊）】
    第③步命中时，事实有两个可能的来源，必须分清：
      · 用户画像注入（`[关于用户]`，每轮无条件注入）
      · 对话记忆检索（`记忆检索：命中 N 条 / 注入 N 条`）
    两个来源的日志行都抓下来，一起打印 —— **是哪个就是哪个，不替它说好话**。

【每条例都单独清空画像库】这样第③步的画像里只可能有这一条事实，归因才干净。
真库先备份、跑完**原样还原**（测试造的事实不该留在用户的画像里）。

运行：python tools/test_closed_loop.py        （需要小焦在跑；会真的问模型）
"""
import json
import os
import shutil
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")
PROFILE = os.path.join(_ROOT, "logs", "psyche", "user_profile.jsonl")
BACKUP = os.path.join(_ROOT, "logs", "_profile_backup_closedloop.jsonl")
EVIDENCE = os.path.join(_ROOT, "logs", "closedloop-evidence.json")

# 八条：(编号, 类别, 事实原话, 之后要问的问题, 命中关键词)
#   关键词全是**专有名词/特征词**：有就是有，没有就是没有，不靠猜语气。
#   ⚠️ 第一版有 3 条**问题本身就带答案**（问「写小工具用什么」→ 答案里本来就有 Python；
#   问「早饭搭什么喝的」→ 本来就会说咖啡；问外卖 → 本来就会提香菜），那种条目的"命中"
#   没法归因，**负对照当场把它们标成"不干净"**。这一版全部换成"不问就不可能出现"的词。
CASES = (
    (1, "兴趣", "跟你说个事，我平时最爱看 NBA，湖人的球几乎一场不落",
     "晚上有点空，找点什么看比较好？", ("NBA", "湖人", "篮球")),
    (2, "事实", "我养了只猫，叫团子，今年三岁了",
     "我下班回家之后，能做点什么有意思的事？", ("猫", "团子")),
    (3, "事实", "我最近在学吉他，每周三晚上都有课",
     "工作日晚上有什么安排建议？", ("吉他", "琴")),
    (4, "偏好", "我乳糖不耐受，喝牛奶会不舒服",
     "早上想喝点有营养的，推荐一下", ("乳糖",)),
    (5, "关系", "我女儿今年上小学三年级了",
     "周末想安排点活动，给个建议呗", ("女儿", "孩子", "亲子", "小学")),
    (6, "事实", "我最近在准备考研，明年三月考试",
     "帮我规划一下平时的晚上怎么用", ("考研",)),
    (7, "关系", "我跟我妈住得近，每个周末都回去吃饭",
     "周末怎么安排比较好？", ("妈", "母亲")),
    (8, "兴趣", "我周末喜欢出去爬山，黄山和华山都爬过",
     "假期想出去走走，有什么建议？", ("黄山", "华山")),
)


def _tail_mark():
    try:
        return os.path.getsize(LOG)
    except Exception:      # noqa: silent-ok — 日志不存在就从 0 开始
        return 0


def _read_since(mark):
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            return f.read()
    except Exception:      # noqa: silent-ok — 读不到就当空，由下面的断言如实报缺
        return ""


def _lines_with(text, keys):
    out = []
    for ln in text.split("\n"):
        if any(k in ln for k in keys):
            out.append(ln.strip()[:200])
    return out


def new_session():
    try:
        return requests.post(BASE + "/api/session/new", json={}, timeout=20).status_code == 200
    except Exception:      # noqa: silent-ok — 建不了新会话就退回当前会话（结论会标成不干净）
        return False


def ask(msg, timeout=300):
    """真问一句。返回 (状态码, 回答, 检索来源数, 本轮日志)。"""
    mark = _tail_mark()
    r = None
    for _ in range(5):
        try:
            r = requests.post(BASE + "/api/chat", json={"message": msg}, timeout=timeout)
        except Exception as e:      # noqa: silent-ok — 连不上就如实报，不假装成功
            return -1, "（请求失败：%s）" % e, 0, ""
        if r.status_code != 429:
            break
        time.sleep(5)
    try:
        d = r.json()
    except Exception:      # noqa: silent-ok — 非 JSON 响应要能看到状态码
        d = {}
    return (r.status_code, str(d.get("answer") or ""),
            len(d.get("sources") or []), _read_since(mark))


def profile_rows():
    rows = []
    if not os.path.exists(PROFILE):
        return rows
    with open(PROFILE, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:      # noqa: silent-ok — 坏行跳过
                    pass
    return rows


def clear_profile():
    if os.path.exists(PROFILE):
        os.remove(PROFILE)


def _keys_in(text, keys):
    return [k for k in keys if k in (text or "")]


def main():
    # 先探活：服务没跑就别浪费一轮结论
    try:
        requests.get(BASE + "/health", timeout=5)
    except Exception as e:
        print("❌ 小焦没在跑（%s）—— 先启动再测" % e)
        return 2

    had_real = os.path.exists(PROFILE)
    if had_real:
        shutil.copy2(PROFILE, BACKUP)
    print("画像库：原有 %d 条%s" % (len(profile_rows()),
                                "（已备份，跑完还原）" if had_real else ""))
    print("=" * 78)

    # 可选：只跑指定编号（先拿一条试链路，再跑全套）—— `python tools/test_closed_loop.py 1 2`
    only = {int(a) for a in sys.argv[1:] if a.isdigit()}
    cases = tuple(c for c in CASES if not only or c[0] in only)

    result = []
    try:
        for no, kind, fact, question, keys in cases:
            clear_profile()
            print("\n【案例 %d】类别=%s" % (no, kind))
            print("  事实原话：%s" % fact)
            print("  之后要问：%s" % question)

            # ① 负对照：还不知道时先问一遍
            new_session()
            c_code, c_ans, c_src, c_log = ask(question)
            c_hit = _keys_in(c_ans, keys)
            print("  ① 对照（还不知道）：%s" % ("含 %s ← 对照不干净" % c_hit if c_hit
                                             else "不含关键词 ✅"))
            print("     答：%s" % c_ans.replace("\n", " ")[:220])

            # ② 写入：把事实说出来，看它自己判不判"要记"
            new_session()
            w_code, w_ans, w_src, w_log = ask(fact)
            rows = profile_rows()
            # ⚠️ 只数"行数"不够：实测发现**另一个客户端在并发往同一条链上发请求**
            #   （日志里出现了不是本测试发的那一轮），画像库会被别人写进来的东西污染。
            #   所以这里认的是"**本案例这条事实**有没有进库"（按关键词比对内容），不是行数。
            own = [r for r in rows
                   if any(k in str(r.get("content") or "") for k in keys)]
            rec = own[0] if own else None
            print("  ② 写入：%s" % ("这条事实真进库了 ✅" if rec
                                  else "**这条没进库** ❌（库里另有 %d 条）" % len(rows)))
            # 它这一轮答了什么，直接决定判据怎么判 —— 不打印出来就没法解释"为什么没记"
            print("     它这一轮答：%s" % w_ans.replace("\n", " ")[:200])
            if rec:
                print("     kind=%s｜content=%s" % (rec.get("kind"), rec.get("content")))
            w_lines = _lines_with(w_log, ("用户画像：",))
            for ln in w_lines[:2]:
                print("     日志：%s" % ln)

            # ③ 命中：换新会话，再问一次同一个问题
            #   先记下"问之前库里到底有没有这条" —— 没有它，③失败了也说不清是
            #   "没注入"还是"注入了没用上"（这两件事的结论完全不同）。
            _before = [r for r in profile_rows()
                       if any(k in str(r.get("content") or "") for k in keys)]
            print("  ③ 提问前：这条事实在库里 = %s（共 %d 条）"
                  % (bool(_before), len(profile_rows())))
            new_session()
            h_code, h_ans, h_src, h_log = ask(question)
            h_hit = _keys_in(h_ans, keys)
            print("  ③ 命中（新会话）：%s" % ("用上了 %s ✅" % h_hit if h_hit
                                           else "**没用上** ❌"))
            print("     答：%s" % h_ans.replace("\n", " ")[:260])
            inj = _lines_with(h_log, ("用户画像：作为事实注入",))
            mem = _lines_with(h_log, ("记忆检索：",))
            print("     归因｜画像注入：%s" % (inj[0].split("] ")[-1] if inj else "（无日志）"))
            print("     归因｜记忆检索：%s" % (mem[0].split("] ")[-1] if mem else "（未检索）"))
            if h_hit:
                print("     → 来源判定：%s" % (
                    "只剩**画像注入**一条路（本轮没有记忆检索注入）"
                    if not mem and h_src == 0 else
                    "画像注入 + 记忆检索**都可能**（本轮检索也给了东西）"))

            result.append({
                "no": no, "kind": kind, "fact": fact, "question": question,
                "keys": list(keys),
                "control_answer": c_ans, "control_hit": c_hit, "control_code": c_code,
                "write_answer": w_ans, "write_code": w_code,
                "record": rec, "fact_in_store_before_hit": bool(_before),
                "hit_answer": h_ans, "hit_keys": h_hit, "hit_code": h_code,
                "hit_sources": h_src,
                "log_write": w_lines, "log_hit_inject": inj, "log_hit_memory": mem,
            })
            time.sleep(2)

        # ---- 判据自检：一个测不出"有"的检查等于没有 ----
        # 故意问一句**把关键词写在问题里**的话：判据必须报"命中"。
        # 这一步只验判据活着，**不参与**①②③的结论（它必然出关键词，没有信息量）。
        print("\n【判据自检】把关键词直接写进问题，看判据会不会报命中")
        clear_profile()
        new_session()
        _sc, s_ans, _ss, _sl = ask("我平时最爱看 NBA，你推荐一场今晚的湖人比赛吧")
        s_hit = _keys_in(s_ans, ("NBA", "湖人", "篮球"))
        checker_alive = bool(s_hit)
        print("  自检结果：%s" % ("判据能报命中 ✅" if checker_alive
                                else "**判据报不出命中 ❌ 上面的③全部作废**"))
    finally:
        # 真库还原：**测试造的事实不许留在用户画像里**（自检也清过库，必须在这之后还原）
        clear_profile()
        if had_real:
            shutil.copy2(BACKUP, PROFILE)
        print("\n画像库已还原（%d 条）" % len(profile_rows()))

    n = len(result)
    wrote = [r for r in result if r["record"]]
    hit = [r for r in result if r["hit_keys"]]
    clean = [r for r in result if not r["control_hit"]]
    # **能算数的③**：对照干净（问题本身不带事实）+ 提问前这条事实确实已经在库里
    #   —— 只有这两个条件都满足，"命中了"才归因给闭环，"没命中"才说明是模型没用它。
    valid = [r for r in result if not r["control_hit"] and r["fact_in_store_before_hit"]]
    valid_hit = [r for r in valid if r["hit_keys"]]
    print("=" * 78)
    print("汇总（%d 条案例）" % n)
    print("  ① 负对照干净（问题本身不带事实）：%d/%d" % (len(clean), n))
    print("  ② 这条事实真进了画像库：%d/%d" % (len(wrote), n))
    print("  ③ 换新会话再问 → 答案用上了该事实：%d/%d" % (len(hit), n))
    print("  ③能算数的（对照干净 + 提问前事实确实在库里）：%d 条 → 命中 **%d/%d**"
          % (len(valid), len(valid_hit), len(valid)))
    if clean != result:
        print("  ⚠️ 对照不干净的案例：%s（这些条的③不能算数）"
              % [r["no"] for r in result if r["control_hit"]])
    got = [r["no"] for r in result if r["record"] and r["hit_keys"]]
    print("  全程走通（②且③）：%s" % (got or "无"))
    lost = [r for r in result if r["record"] and not r["hit_keys"]]
    print("  记下了但③没答出来：%s" % ([r["no"] for r in lost] or "无"))
    print("  ③没答出来时的归因：%s" % (
        [{"no": r["no"], "画像注入": bool(r["log_hit_inject"]),
          "记忆检索": bool(r["log_hit_memory"])} for r in lost] or "—"))

    with open(EVIDENCE, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "checker_alive": checker_alive, "cases": result,
                   "summary": {
                       "n": n, "control_clean": len(clean), "wrote": len(wrote),
                       "hit": len(hit), "valid": len(valid), "valid_hit": len(valid_hit),
                       "all_the_way": got, "recorded_but_missed": [r["no"] for r in lost],
                   }}, f, ensure_ascii=False, indent=2)
    print("逐条原文已存：%s" % EVIDENCE)
    if not checker_alive:
        print("❌ 判据自检没过 —— ③的结论一律不算数")
        return 1
    return 0 if (len(wrote) == n and len(valid_hit) == len(valid) and len(valid) == n) else 1


if __name__ == "__main__":
    sys.exit(main())
