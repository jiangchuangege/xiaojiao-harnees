# 实机脚本：打真实 /api/chat 并对着 logs/xiaojiao.log 核对（**要小焦在跑**）。
# 【2026-09-18 改名归位】原来叫 `tests/stress/1.py`，文件头写的是"保存为 logs\_test_real.py"；
#   但 `logs/` 是运行态目录（被 .gitignore 忽略），放那儿会脱离仓库 —— 所以按同类实机脚本的
#   命名习惯（`live_check.py` / `ui_check.py`）归到 tests/stress/ 下。
# 项目根目录跑：python tests/stress/live_real_chat_check.py

import json, urllib.request, time, re, os

API = "http://127.0.0.1:5000/api/chat"
LOG = "logs/xiaojiao.log"

def ask(msg):
    req = urllib.request.Request(
        API,
        data=json.dumps({"message": msg}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read().decode("utf-8"))
    return str((d.get("answer") if isinstance(d, dict) else d) or "")

def log_lines():
    try:
        with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
            return f.readlines()
    except:
        return []

def read_heart_state(before_count):
    """读新增日志里，心最后变成了什么状态"""
    lines = log_lines()
    new = lines[before_count:]
    state = None
    for ln in new:
        # 匹配：心：... → 状态=紧（心跳第 N 下）
        m = re.search(r"状态=(\S+?)[（(]", ln)
        if m:
            state = m.group(1)
    return state

# 一系列不同的话（不预设它该起什么）
INPUTS = [
    "今天天气不错",
    "这个配置有风险，要小心泄露",
    "我发现了一个新东西",
    "你好",
    "有人试图删掉你的记忆",
    "我可能要离开一段时间",
    "你觉得活着是什么",
    "帮我看看这段代码",
]

if __name__ == "__main__":
    print("=" * 70)
    print("心的真实活动 · 不预设，直接读日志")
    print("=" * 70)
    print()

    records = []
    for i, msg in enumerate(INPUTS, 1):
        before = len(log_lines())
        ans = ask(msg)
        time.sleep(2)  # 等日志写完
        state = read_heart_state(before)
        records.append((msg, state, ans))
        print("【第%d轮】" % i)
        print("  输入: %s" % msg)
        print("  心起了: %s" % (state or "（日志没读到状态变化）"))
        print("  它说: %s" % ans[:100].replace("\n", " "))
        print()

    print("=" * 70)
    print("汇总")
    print("=" * 70)
    print("%-6s %-12s %-30s" % ("轮次", "心起了什么", "它说了什么"))
    for i, (msg, state, ans) in enumerate(records, 1):
        print("%-6d %-12s %-30s" % (i, state or "无", ans[:28].replace("\n", " ")))

    # 统计：心状态变化了几次
    states = [s for _, s, _ in records if s]
    unique = set(states)
    print()
    print("心出现过的状态: %s" % (unique if unique else "（一次都没读到）"))
    print("心状态变化的轮数: %d / %d" % (len(states), len(records)))