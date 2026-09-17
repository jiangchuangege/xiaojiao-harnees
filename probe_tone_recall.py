import sys
sys.path.insert(0, ".")
from xiaojiao_app import llm_chat
PROFILES = [
    ("用户对花生严重过敏，绝对不能吃花生", "花生"),
    ("用户平时最爱看 NBA", "NBA"),
    ("用户住在杭州", "杭州"),
    ("用户喜欢猫", "猫"),
    ("用户是后端工程师，平时用 Python", "Python"),
]
CASES = [
    ("推荐部电影看看", "猫"),      # 相关：猫
    ("晚上吃什么好？推荐几个菜", "花生"),  # 相关：花生
    ("最近有什么好看的比赛", "NBA"),   # 相关：NBA
    ("周末去哪玩", "杭州"),        # 相关：杭州
    ("我想学编程，从哪开始", "Python"),  # 相关：Python
    ("你好", None),              # 不相关
]
print("=" * 74)
print("  逐条给：看它对【相关那条】和【不相关那条】的反应")
print("=" * 74)
total_related = 0
total_unrelated = 0
for q, rel_kw in CASES:
    print()
    print("问：" + q)
    for prof, kw in PROFILES:
        msg = "（关于用户：" + prof + "）\n\n" + q
        try:
            a = (llm_chat([{"role": "user", "content": msg}], temperature=0.3) or "").strip()
        except Exception as e:
            print("  调用失败：" + str(e)[:40]); continue
        used = kw in a
        # 标记：相关那条 + 用上了 = 好；不相关那条 + 没用 = 好
        is_related = (rel_kw is not None and kw == rel_kw)
        if is_related:
            mark = "✅" if used else "❌"
            if used: total_related += 1
        else:
            mark = "✅" if not used else "❌(硬塞)"
            if not used: total_unrelated += 1
        print("  " + mark + " 给【" + prof[:16] + "】→ " + ("用了" if used else "没用"))
print()
print("=" * 74)
print("  相关那条：用上 %d 次" % total_related)
print("  不相关那条：没硬塞 %d 次（共 %d 次不相关测试）" % (total_unrelated, len(CASES) * (len(PROFILES) - 1)))
print("=" * 74)
