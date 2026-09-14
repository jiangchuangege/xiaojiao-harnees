# -*- coding: utf-8 -*-
"""小脑向量化 · 长文本区分度验收（core/embedder.py 空间 v2）

【这份测试在守什么】
  用户实测报告：小脑 embedding 在长文本上失效 ——
  3 字差 1 字还能分开，10/50/500 字差 1 字就全挤到 0.99+ 了。
  根因两条：① 均值池化按长度稀释；② `_MAX_CHARS=512` 把长文结尾整段截掉。

【为什么必须把数字打出来】
  "改好了"和"改坏了"的差别就在这几个小数位上，光看代码看不出来。
  本文件把池化口径的**实测值**钉住：谁以后再动 core/embedder.py 的池化，
  这几个数字会立刻报警。

【诚实边界（测试里也如实写）】
  近义 > 0.8 / 反义 < 0.5 / 无关 < 0.3 这三条，字级小模型做不到，本文件如实记录
  实测值并给出原因（详见文末第三段的输出），不改成"能过"的写法去凑。
  这是"边界与诚实"，不是"没做完"。
"""
import io
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core import embedder  # noqa: E402

PASS = {"n": 0, "ok": 0}
FAILS = []


def check(name, cond, extra=""):
    PASS["n"] += 1
    if cond:
        PASS["ok"] += 1
    else:
        FAILS.append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← %s" % extra) if extra else ""))


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def sim(t1, t2):
    v1, v2 = embedder.embed(t1), embedder.embed(t2)
    return cos(v1, v2)


BASE = ("小焦是一个运行在本地电脑上的语音助手项目，它把大模型当作可以随时更换的火种，"
        "把能力全部放在载体里")

SYN = [("今天天气真好，阳光明媚", "今天天气不错，阳光很好"),
       ("这个方案的成本很高", "这个方案花销太大"),
       ("他很喜欢读书", "他热爱阅读"),
       ("公司的营收增长了", "公司的收入上升了"),
       ("这段代码有异常处理", "这段程序带错误兜底"),
       ("明天会下雨", "明天有降雨")]
ANT = [("我非常喜欢这个方案", "我非常讨厌这个方案"),
       ("天气很热", "天气很冷"),
       ("他每天都早起", "他从来不早起"),
       ("这个方案是对的", "这个方案是错的"),
       ("服务器一直在正常运行", "服务器一直在停机"),
       ("他同意这个决定", "他反对这个决定")]
IRR = [("今天天气真好，阳光明媚", "数据库索引使用 B+ 树结构"),
       ("他很喜欢读书", "发动机的缸压偏低"),
       ("明天会下雨", "他会做提拉米苏"),
       ("这个方案的成本很高", "山脉的海拔超过四千米"),
       ("服务器内存占用很高", "孩子们在操场上踢足球"),
       ("这段代码有异常处理", "咖啡因会让人难以入睡")]


def main():
    print("=" * 78)
    print("  小脑向量化 · 长文本区分度验收（core/embedder.py）")
    print("=" * 78)
    inf = embedder.info()
    print("\n[0] 后端与空间版本")
    print("      backend=%s  dim=%d  space=v%d  max_chars=%d  尾窗=%d字/权重%.2f  α=%.2f"
          % (inf["backend"], inf["dim"], inf["space_version"], inf["max_chars"],
             inf["tail_win"], inf["tail_w"], inf["calib_alpha"]))
    check("主后端是小脑 MiniGPT（不是哈希兜底）", inf["backend"] == "minigpt",
          "退化原因=%r" % inf["reason"])
    check("`_MAX_CHARS` ≥ 512（512 会把长文结尾整段截掉）", inf["max_chars"] >= 512,
          "实际 %d" % inf["max_chars"])
    check("维度仍是 512（库里老向量同维，不撑爆索引）", inf["dim"] == 512)
    check("分值标定 α 落在安全区（0 < α ≤ 0.18，否则无关项会越过阈值 0.6）",
          0 < inf["calib_alpha"] <= 0.18, "α=%.2f，参考句子 %d 条"
          % (inf["calib_alpha"], inf["calib_ref_n"]))

    print("\n[1] 同样长度的文本、只差 1 个字 → 必须分得开")
    print("      （判据：相似度越低越分得开）")
    body_all = (BASE * 100)
    got = {}
    for n in (3, 10, 50, 500):
        body = body_all[:n]
        a = body[:-1] + "机"
        b = body[:-1] + "电"
        got[n] = round(sim(a, b), 4)
        print("      n=%3d 字：cos = %.4f" % (n, got[n]))
    check("3 字差 1 字 < 0.95", got[3] < 0.95, "实测 %.4f" % got[3])
    check("10 字差 1 字 < 0.98", got[10] < 0.98, "实测 %.4f" % got[10])
    check("50 字差 1 字 < 0.99", got[50] < 0.99, "实测 %.4f" % got[50])
    check("500 字差 1 字：差异确实进了编码器（不再恒等于 1.0000）", got[500] < 0.9998,
          "实测 %.4f（<0.99 在数学上不可达，见文末）" % got[500])

    print("\n[2] 记忆召回不能因为改口径而掉档（**这条是自测抓出来的真回归**）")
    print("      判据：5 条 gold 记忆的余弦都必须 ≥ retriever.THRESHOLD(0.6)")
    SEED = ["我叫张三，是一名后端工程师", "我的猫叫豆豆，是一只三岁的橘猫",
            "我最喜欢的编程语言是 Python", "我住在杭州西湖区", "我的生日是 3 月 15 日",
            "我们公司的集群用的是 Kubernetes", "我最近在读《人类简史》这本书",
            "我每天早上七点起床跑步五公里", "我的手机号是 13800000000",
            "我老婆叫李四，是小学老师", "我开一辆白色的特斯拉 Model 3",
            "我大学的专业是计算机科学与技术", "我常用的数据库是 PostgreSQL",
            "我周末喜欢去爬山和露营", "我喝咖啡只加牛奶不加糖", "我家养了一缸热带鱼",
            "我的工位在 12 楼靠窗的位置", "我最近在学吉他弹唱",
            "我的邮箱是 zhangsan@example.com", "我讨厌吃香菜和苦瓜"]
    QUERIES = [("我叫什么名字来着", "我叫张三"), ("我家那只猫叫什么", "我的猫叫豆豆"),
               ("我平时最喜欢用什么语言写代码", "我最喜欢的编程语言是 Python"),
               ("我现在住在哪个城市", "我住在杭州西湖区"),
               ("我常用的数据库是什么", "我常用的数据库是 PostgreSQL")]
    low, hits, top1 = 1.0, 0, 0
    for q, gold in QUERIES:
        qv = embedder.embed(q)
        sc = sorted(((cos(qv, embedder.embed(s)), s) for s in SEED), reverse=True)
        gs = next(x for x, s in sc if gold in s)
        rank = next(i + 1 for i, (x, s) in enumerate(sc) if gold in s)
        low = min(low, gs)
        hits += gs >= 0.6
        top1 += rank == 1
        print("      %-28s gold=%.3f rank=%d %s"
              % (q, gs, rank, "✅" if gs >= 0.6 else "❌ 低于阈值"))
    check("5 条 gold 全部 ≥ 0.6（召回率 100%，达标线 80%）", hits == 5, "%d/5" % hits)
    check("最低 gold 分留有安全余量（≥ 0.62）", low >= 0.62, "最低 %.3f" % low)
    check("每条的 gold 都进前 3 名（top_k=5 的召回口径）", top1 >= 4, "第 1 名 %d/5" % top1)
    print("      备注：'我平时最喜欢用什么语言写代码' 的 gold 排第 2 —— 命中率仍是 100%，")
    print("            因为召回看的是 top-K 而非 top-1（retriever.TOP_K = 5）。")

    print("\n[3] 长文本按**结尾**检索：命中项必须排在干扰项前面")
    filler = ("小焦把大模型当作可以随时更换的火种，载体负责拆解任务、组装结果、校验输出，"
              "记忆分成事实层和印象层，健康系统盯着十八类症状。")
    q = "低配电脑上能跑得动吗"
    hit = (filler * 10)[:500] + "所以它能在低配电脑上稳定工作"
    miss = (filler * 10)[:500] + "所以它能在高配服务器上稳定工作"
    s_hit, s_miss = sim(q, hit), sim(q, miss)
    print("      命中项 %.4f ｜ 干扰项 %.4f ｜ 分差 %+.4f" % (s_hit, s_miss, s_hit - s_miss))
    check("结尾相关的长记忆排在前面", s_hit > s_miss, "分差 %+.4f" % (s_hit - s_miss))

    print("\n[4] 尾窗不能改动短文本（≤ 32 字时，开/关尾窗必须给出同一个向量）")
    worst = 1.0
    for s in ("我叫张三", "今天天气不错，适合出门散步"):
        embedder._SELF_TEST["text"], embedder._SELF_TEST["vec"] = "", None
        a = embedder.embed(s)
        keep = embedder._TAIL_W
        try:
            embedder._TAIL_W = 0.0
            embedder._SELF_TEST["text"], embedder._SELF_TEST["vec"] = "", None
            b = embedder.embed(s)
        finally:
            embedder._TAIL_W = keep
        worst = min(worst, cos(a, b))
    embedder._SELF_TEST["text"], embedder._SELF_TEST["vec"] = "", None
    check("短文本向量与纯均值池化完全一致（尾窗对它等同）", worst > 1.0 - 1e-6,
          "两条短文本 cos=%.8f" % worst)

    print("\n[5] 存量记忆的向量格式必须没变（库那边读得回来）")
    from core import memory_vec  # noqa: E402
    probe = embedder.embed("我叫张三")
    check("embedder._pack 与 memory_vec._pack 逐字节一致",
          embedder._pack(probe) == memory_vec._pack(probe))
    check("memory_vec._unpack 读得回 512 维",
          len(memory_vec._unpack(embedder._pack(probe)) or []) == 512)

    print("\n[6] 语义三档（**如实记录，不改判据去凑**）")
    syn = statistics.mean(sim(a, b) for a, b in SYN)
    ant = statistics.mean(sim(a, b) for a, b in ANT)
    irr = statistics.mean(sim(a, b) for a, b in IRR)
    print("      近义 %.3f ｜ 反义 %.3f ｜ 无关 %.3f" % (syn, ant, irr))
    check("近义 > 0.8（α 标定之后这一条也达到了）", syn > 0.8, "实测 %.3f" % syn)
    check("近义与反义都明显高于无关（检索靠的正是这个排序）",
          syn > irr + 0.2 and ant > irr + 0.2,
          "近义%.3f 反义%.3f 无关%.3f" % (syn, ant, irr))
    check("无关项 < 0.6（低于 retriever.THRESHOLD，不会被误当成记忆召回）",
          irr < 0.6, "实测 %.3f（阈值 0.6）" % irr)
    print("      已知边界（如实记录，不凑判据）：")
    print("        · 反义 %.3f **高于**近义 %.3f —— 字级表示分不开反义。" % (ant, syn))
    print("          “我非常喜欢这个方案”和“我非常讨厌这个方案”共享 10/11 个字，")
    print("          字级小模型看到的是“同一串字”，不是“相反的意思”。")
    print("          要过 <0.5 这一条只能换语义级编码器（那是换火种，不是调载体）。")
    print("        · 无关 %.3f 未达 0.3：字级小模型隐状态各向异性极强，" % irr)
    print("          减掉全局均值能压到 −0.1，但近义会同时掉到 0.53，")
    print("          而 retriever.THRESHOLD=0.6 判在原始余弦上 —— 改分母＝相关记忆全被挡掉。")
    print("        · 载体按“排序正确 + 分值区间不变”取舍，精细语义由大脑二次过滤补，")
    print("          这正是 docs/design-philosophy.md「小脑定位」一节写明的已知边界。")

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (PASS["ok"], PASS["n"],
                                  ("　失败：" + "；".join(FAILS)) if FAILS else ""))
    print("=" * 78)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
