# -*- coding: utf-8 -*-
"""**路由表**：任何一句话走哪条路 —— 离线自测（不调模型、不联网）。

【为什么要这张表（用户提的策略）】原来"该不该联网、拿什么词去搜、要不要卡来源"散在
四五个地方，于是**每冒出一个新说法就漏一次**：问「今天有什么重大新闻」搜回查日历的站、
问「最近国家收入」跑去讲一首歌、问「今天几号」却很好。现在判定收在 `_route_of` 一处，
**这张表就是策略本身**：新发现一个坏例子 → 往下面加一行（不是现场打补丁）。

跑法：python tools/test_route_table.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as A  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


# (输入, 期望 kind, 要不要联网, 期望来源约束)
TABLE = [
    ("今天有什么重大新闻呢", "news", True, "news"),
    ("今天的头条是什么", "news", True, "news"),
    ("最近有什么时事", "news", True, "news"),
    ("今天几月几号啊", "chat", False, ""),
    ("现在几点了", "chat", False, ""),
    ("最近国家收入", "fresh_data", True, ""),
    ("最近的财政收入数据", "fresh_data", True, ""),
    ("今年 GDP 增速多少", "fresh_data", True, ""),
    ("最新的人口统计", "fresh_data", True, ""),
    ("2026年世界杯谁是冠军", "realtime", True, ""),
    ("现在谁是世界首富", "realtime", True, ""),
    ("谁是鲁迅", "chat", False, ""),
    ("你好呀", "chat", False, ""),
    ("帮我写个函数", "chat", False, ""),
    ("抓一下 https://example.com", "scrape", True, ""),
    ("我住在哪", "fact_user", False, ""),
    ("我最喜欢什么动物", "fact_user", False, ""),
    ("我养的狗叫什么", "fact_user", False, ""),
]


def main():
    print("=" * 78)
    print("  路由表：一句话走哪条路（策略的可执行形式）")
    print("=" * 78)
    for text, kind, net, source in TABLE:
        r = A._route_of(text)
        ck("「%s」→ %s" % (text, kind), r["kind"] == kind, r)
        ck("「%s」→ 联网=%s" % (text, net), bool(r["need_net"]) is net, r["need_net"])
        if source:
            ck("「%s」→ 来源约束=%s" % (text, source), r["source"] == source, r["source"])

    print("\n【附】这几条的实际检索词（人要能看懂它拿什么去搜）")
    for text in ("今天有什么重大新闻呢", "最近国家收入", "2026年世界杯谁是冠军", "抓一下 https://example.com"):
        r = A._route_of(text)
        print("   %-22s → %r" % (text, r["search_query"][:60]))

    print("\n" + "=" * 78)
    print("路由表自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
