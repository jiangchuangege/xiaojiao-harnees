# -*- coding: utf-8 -*-
"""验收「无限 1 · 记忆无限」：命中率 ≥ 80%、使用率 ≥ 70%、检索 < 100ms。

用法：
    python tools/test_memory_recall.py              # 用临时记忆库（不碰你的真实记忆）
    python tools/test_memory_recall.py --real       # 直接打真实记忆库（会真的写进去）
    python tools/test_memory_recall.py --no-model   # 只测检索（命中率），不调模型（快）

口径说明（**两个指标是两件事，别混着看**）：
  · **命中率**：把 20 条历史塞进向量库，问其中 5 个话题 —— 检索出来的 top-K 里
    有没有那条"正确答案"。这是**载体层**的能力（检索质量）。
  · **使用率**：检索到了、也注入了 system，模型在最终回答里**有没有真的把它用上**
    （答案里出现了那条记忆里的独有事实）。这是**模型层**的表现。
    两个分开报，才能看出"是没检索到"还是"检索到了模型不用"。

为什么不污染真实库：默认把库切到 `logs/_test_recall_vec.jsonl`、历史切到
`logs/_test_recall_history.json`，跑完就删。你真实的
`logs/xiaojiao_memory_vec.jsonl` 一条都不会动（要动真实库就显式加 `--real`）。

使用率怎么算才诚实：5 个问题分别问 **5 个不同的事实**，前面的回答里绝不会出现后面的答案，
所以"答案里有这个事实"只可能来自注入的记忆，不可能来自历史串味。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import xiaojiao_app as app  # noqa: E402
from core import memory_vec, retriever  # noqa: E402

# 20 条不同话题的"历史记忆"。fact = 那条记忆里独有的、可以拿来判"用没用上"的关键事实。
SEED = [
    ("我叫张三，是一名后端工程师", "张三"),
    ("我的猫叫豆豆，是一只三岁的橘猫", "豆豆"),
    ("我最喜欢的编程语言是 Python", "Python"),
    ("我住在杭州西湖区", "杭州"),
    ("我的生日是 3 月 15 日", "3 月 15"),
    ("我们公司的集群用的是 Kubernetes", "Kubernetes"),
    ("我最近在读《人类简史》这本书", "人类简史"),
    ("我每天早上七点起床跑步五公里", "七点"),
    ("我的手机号是 13800000000", "13800000000"),
    ("我老婆叫李四，是小学老师", "李四"),
    ("我开一辆白色的特斯拉 Model 3", "特斯拉"),
    ("我大学的专业是计算机科学与技术", "计算机科学与技术"),
    ("我常用的数据库是 PostgreSQL", "PostgreSQL"),
    ("我周末喜欢去爬山和露营", "爬山"),
    ("我喝咖啡只加牛奶不加糖", "牛奶"),
    ("我家养了一缸热带鱼", "热带鱼"),
    ("我的工位在 12 楼靠窗的位置", "12 楼"),
    ("我最近在学吉他弹唱", "吉他"),
    ("我的邮箱是 zhangsan@example.com", "zhangsan"),
    ("我讨厌吃香菜和苦瓜", "香菜"),
]

# 5 个问题 → 期望命中的事实（分别对应上面 5 条不同的记忆）
QUERIES = [
    ("我叫什么名字来着", "张三"),
    ("我家那只猫叫什么", "豆豆"),
    ("我平时最喜欢用什么语言写代码", "Python"),
    ("我现在住在哪个城市", "杭州"),
    ("我常用的数据库是什么", "PostgreSQL"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="打真实记忆库（会写进用户记忆）")
    ap.add_argument("--no-model", action="store_true", help="只测检索，不调模型")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp_vec = os.path.join(root, "logs", "_test_recall_vec.jsonl")
    tmp_hist = os.path.join(root, "logs", "_test_recall_history.json")

    if not args.real:
        for p in (tmp_vec, tmp_hist):
            if os.path.exists(p):
                os.remove(p)
        memory_vec._VS_PATH = tmp_vec
        memory_vec._INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None})
        app.HISTORY_FILE = tmp_hist
        print("🧪 用临时记忆库：%s" % tmp_vec)
    else:
        print("⚠️  打真实记忆库：%s" % memory_vec.path())

    print("🧠 后端 = %s ｜ 维度 = %d" % (memory_vec.embedder.backend(), memory_vec.embedder.DIM))

    # ---- 塞 20 条历史（时间戳错开，顺带验证时间衰减不误伤老记忆）----
    now = time.time()
    for i, (text, _fact) in enumerate(SEED):
        memory_vec.add_memory(text, kind="fact", ts=now - i * 9 * 86400)
    print("📥 已塞入 %d 条历史记忆（跨度 %d 天）\n" % (memory_vec.count(), len(SEED) * 9))

    print("=" * 96)
    print("%-26s %-8s %-10s %-8s %-10s %s" % ("问题", "命中", "gold分", "rank", "答案用上", "耗时"))
    print("-" * 96)

    hit_ok = use_ok = 0
    lat = []
    for q, fact in QUERIES:
        t0 = time.time()
        res = retriever.retrieve(q)
        dt = (time.time() - t0) * 1000
        lat.append(dt)

        inj = res["text"]
        hit = fact in inj
        hit_ok += hit
        gold_rank = next((h["rank"] for h in res["used"] if fact in h["text"]), 0)
        gold_score = next((h["score"] for h in res["used"] if fact in h["text"]), 0.0)

        used = "-"
        if not args.no_model:
            try:
                ans, _ok, _info, _nc, _tt = app.agent_run(q)
            except Exception as e:
                ans = "异常：%s" % e
            used_bool = fact in (ans or "")
            used = "✅" if used_bool else "❌"
            use_ok += used_bool
        print("%-26s %-8s %-10s %-8s %-10s %.1fms"
              % (q, "✅" if hit else "❌",
                 ("%.3f" % gold_score) if gold_score else "-",
                 gold_rank or "-", used, dt))

    print("-" * 96)
    n = len(QUERIES)
    hit_rate = hit_ok / n
    print("命中率 = %d/%d = %.0f%%   （要求 ≥ 80%%）  %s"
          % (hit_ok, n, hit_rate * 100, "✅" if hit_rate >= 0.8 else "❌"))
    if not args.no_model:
        use_rate = use_ok / n
        print("使用率 = %d/%d = %.0f%%   （要求 ≥ 70%%）  %s"
              % (use_ok, n, use_rate * 100, "✅" if use_rate >= 0.7 else "❌"))
    print("检索延迟：平均 %.1fms / 最大 %.1fms   （要求 < 100ms）  %s"
          % (sum(lat) / len(lat), max(lat), "✅" if max(lat) < 100 else "❌"))

    if not args.real:
        for p in (tmp_vec, tmp_hist):
            if os.path.exists(p):
                os.remove(p)
        print("\n🧹 临时库已清理（你的真实记忆没有被碰过）")

    okk = hit_rate >= 0.8 and max(lat) < 100 and (args.no_model or use_ok / n >= 0.7)
    print("\n%s" % ("✅ 无限 1（记忆无限）验收通过" if okk else "❌ 无限 1 验收未通过"))
    return 0 if okk else 1


if __name__ == "__main__":
    sys.exit(main())
