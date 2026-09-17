# 保存到项目根目录：checkup.py
# 跑法：python checkup.py

import json
import os
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(ROOT, "logs")

def read_jsonl(path):
    """读 jsonl，返回 list；坏行跳过并计数。"""
    rows = []
    bad = 0
    if not os.path.exists(path):
        return rows, bad
    for ln in open(path, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            bad += 1
    return rows, bad

def count_lines(path):
    if not os.path.exists(path):
        return 0
    n = 0
    for ln in open(path, encoding="utf-8", errors="replace"):
        if ln.strip():
            n += 1
    return n

def ts_fmt(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)[:16]

# ============ 污染特征 ============
TOOL_SIGNS = ("检索到 ", "HTTP 200", '"content":', '"status":', '"items":',
              '"url":', '"error":')
BAD_REPLY = ("__pending__", "<think>", "<thinking>", "</think>")

def has_tool_return(text):
    t = str(text)
    return sum(1 for s in TOOL_SIGNS if s in t) >= 2

def has_bad_reply(text):
    t = str(text)
    return any(s in t for s in BAD_REPLY)

def is_too_short(text):
    t = str(text).strip()
    return len(t) < 8

def is_half_sentence(text):
    t = str(text).strip()
    return len(t) < 30 and t.endswith(("，", "、", ",", "…", "——"))

print("=" * 60)
print("  小焦 · 全系统体检报告")
print("  时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 60)

# ============ 一、记忆库 ============
print("\n【一、记忆库 memory_vec.jsonl】")
path = os.path.join(LOGS, "xiaojiao_memory_vec.jsonl")
rows, bad_lines = read_jsonl(path)
total = len(rows)
print("  总条数：%d" % total)
if bad_lines:
    print("  坏行（读不出 JSON）：%d" % bad_lines)

if rows:
    # 时间跨度
    tss = [r.get("ts", 0) for r in rows if isinstance(r.get("ts"), (int, float))]
    if tss:
        print("  时间跨度：%s ～ %s" % (ts_fmt(min(tss)), ts_fmt(max(tss))))

    # 各类污染
    tool_polluted = [r for r in rows if has_tool_return(r.get("text", ""))]
    bad_reply_polluted = [r for r in rows if has_bad_reply(r.get("text", ""))]
    short_polluted = [r for r in rows if is_too_short(r.get("text", ""))]
    half_polluted = [r for r in rows if is_half_sentence(r.get("text", ""))]
    no_who = [r for r in rows if "who" not in r]

    print("\n  污染统计：")
    print("    ① 含工具返回特征：%d 条" % len(tool_polluted))
    print("    ② 含坏回复（占位符/think）：%d 条" % len(bad_reply_polluted))
    print("    ③ 太短（<8字）：%d 条" % len(short_polluted))
    print("    ④ 疑似半截话：%d 条" % len(half_polluted))
    print("    ⑤ 没有 who 字段（来源未标）：%d 条" % len(no_who))

    # 各类样本
    print("\n  各类样本（各1条）：")
    for name, lst in [("工具污染", tool_polluted), ("坏回复", bad_reply_polluted),
                      ("太短", short_polluted), ("半截话", half_polluted)]:
        if lst:
            r = lst[0]
            print("    【%s】%s | %s" % (name, ts_fmt(r.get("ts", "")),
                                        str(r.get("text", ""))[:80]))
        else:
            print("    【%s】无" % name)

# ============ 二、聊天历史 ============
print("\n【二、聊天历史 chat_history.jsonl】")
path2 = os.path.join(LOGS, "chat_history.jsonl")
rows2, bad2 = read_jsonl(path2)
total2 = len(rows2)
print("  总条数：%d" % total2)
if bad2:
    print("  坏行：%d" % bad2)

if rows2:
    tss2 = []
    for r in rows2:
        t = r.get("time", "")
        if t:
            try:
                tss2.append(time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")))
            except Exception:
                pass
    if tss2:
        print("  时间跨度：%s ～ %s" % (ts_fmt(min(tss2)), ts_fmt(max(tss2))))

    pending2 = [r for r in rows2 if "__pending__" in str(r.get("final_reply", ""))]
    think2 = [r for r in rows2 if "<think" in str(r.get("final_reply", ""))]
    empty2 = [r for r in rows2 if not str(r.get("final_reply", "")).strip()]
    tool2 = [r for r in rows2 if has_tool_return(str(r.get("tool_trace", "")))]

    print("\n  污染统计：")
    print("    ① final_reply 含 __pending__：%d 条" % len(pending2))
    print("    ② final_reply 含 <think>：%d 条" % len(think2))
    print("    ③ final_reply 为空：%d 条" % len(empty2))
    print("    ④ tool_trace 含工具返回：%d 条（正常，不算污染）" % len(tool2))

# ============ 三、两库比例 ============
print("\n【三、两库差异】")
print("  chat_history：%d 条" % total2)
print("  memory_vec：%d 条" % total)
if total2 and total:
    ratio = total / total2
    print("  比例：memory_vec / chat_history = %.2f" % ratio)
    if ratio > 1.5:
        print("  ⚠️ 记忆库比聊天历史多很多 —— 可能有重复写入或污染累积")
    elif ratio < 0.3:
        print("  ⚠️ 记忆库比聊天历史少很多 —— 可能有写漏")
    else:
        print("  ✅ 比例正常（约 1:1）")

# ============ 四、精神记忆 ============
print("\n【四、精神记忆 spirit_memory/】")
for name in ("knowledge.jsonl", "method.jsonl", "diagnosis.jsonl"):
    p = os.path.join(LOGS, "spirit_memory", name)
    rows3, bad3 = read_jsonl(p)
    print("  %s：%d 条" % (name, len(rows3)))
    if rows3:
        # 找可疑的（超长 / 带问号 / 带"我"很多）
        suspect = []
        for r in rows3:
            t = str(r.get("text", ""))
            if len(t) > 200 or t.count("?") + t.count("？") >= 3:
                suspect.append(r)
        if suspect:
            print("    可疑（超长/多问号）：%d 条" % len(suspect))
            print("    样本：%s" % str(suspect[0].get("text", ""))[:100])

# ============ 五、心 / 印象 / 偏好 ============
print("\n【五、心 / 印象 / 偏好】")
for name, path in [
    ("impressions.jsonl", "psyche/impressions.jsonl"),
    ("preference.jsonl", "psyche/preference.jsonl"),
    ("narrative.jsonl", "psyche/narrative.jsonl"),
    ("unfinished.jsonl", "psyche/unfinished.jsonl"),
]:
    p = os.path.join(LOGS, path)
    rows4, _ = read_jsonl(p)
    print("  %s：%d 条" % (name, len(rows4)))

# ============ 六、内里状态 ============
print("\n【六、内里状态 inner/state.json】")
p = os.path.join(LOGS, "inner", "state.json")
if os.path.exists(p):
    try:
        d = json.load(open(p, encoding="utf-8"))
        print("  孤独：%s | 低沉：%s | 抑郁：%s | 内疚：%s | 骄傲：%s | 意义：%s"
              % (d.get("lonely"), d.get("low"), d.get("depress"),
                 d.get("guilt"), d.get("pride"), d.get("meaning")))
    except Exception as e:
        print("  读取失败：%s" % e)
else:
    print("  文件不存在")

# ============ 七、总表 ============
print("\n" + "=" * 60)
print("  总表")
print("=" * 60)
print("""
  库                              总数    污染
  ─────────────────────────────────────────────
""")
if rows:
    print("  memory_vec.jsonl              %5d   %d 条（工具/坏回复/太短）"
          % (total, len(set(id(r) for r in tool_polluted + bad_reply_polluted
                           + short_polluted + half_polluted))))
if rows2:
    print("  chat_history.jsonl            %5d   %d 条（pending/think/空）"
          % (total2, len(pending2) + len(think2) + len(empty2)))

print("\n" + "=" * 60)
print("  体检完成。只读，未改任何文件。")
print("=" * 60 + "\n")