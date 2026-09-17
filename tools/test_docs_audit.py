# -*- coding: utf-8 -*-
"""阶段 E · 文档逐项核对（README 顶部九条 + design-philosophy 十三节）

提示词要求：
    · README 顶部（15 行内）：小焦是载体/模型是零件、智力来自系统协作、换模型不换小焦、
      互联网是世界观、不能删文件、能力不封顶、健康系统自愈、方向是能力无上限、
      指向 design-philosophy.md；
    · design-philosophy.md（900 行内）：总纲 + 13 节（变形金刚整体/无限扩展/世界/自主/
      健康/能力无上限/一次算完/记忆深度/元认知/人格/通用vs专用/发布/协同）。

为什么要做成可跑的核对：文档最容易"写着写着少一节"，而这种缺失**没有任何报错**。

【2026-09-18 判据跟着口径改】原来这里要求的是"目标：4B 在载体里超越 360B"（关键词 `360B`）。
  用户明确说：**不要把终极目标写成"超过某个型号"，写成"无上限"**。
  —— "超过 X" 是把上限钉在另一个模型身上；"无上限"才是这一层的形状。
  所以判据关键词从 `360B` 换成 `无上限`（**判据跟着口径走，不是把口径改回去迁就判据**）。
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# README 顶部九条 → 判据关键词（任一命中即算写到）
README_POINTS = (
    ("小焦是载体、模型是零件", ("载体", "零件")),
    ("智力来自系统协作，不来自模型", ("智力来自", "系统协作")),
    ("换模型不换小焦", ("换模型不换小焦", "火种换了")),
    ("互联网是小焦的世界（不是工具箱）", ("互联网是小焦的世界", "互联网", "世界")),
    ("可以自主做事，但不能删任何文件", ("不能删任何文件", "不能删")),
    ("能力不封顶（用户加插件即长能力）", ("能力不封顶", "不封顶")),
    ("模型会退化，有健康系统能自愈", ("健康系统", "自愈")),
    ("方向：能力无上限（不封在模型规模里）", ("无上限",)),
    ("指向 docs/design-philosophy.md", ("design-philosophy",)),
)

# design-philosophy 的 13 节（按标题关键词核对，不要求字面完全一致）
PHIL_SECTIONS = (
    ("总纲", ("总纲",)),
    ("一 · 变形金刚整体（十一大器官）", ("变形金刚整体",)),
    ("二 · 能力的无限扩展", ("无限扩展", "能力的无限")),
    ("三 · 世界是互联网", ("世界是互联网", "互联网")),
    ("四 · 自主性", ("自主性",)),
    ("五 · 模型健康系统", ("健康系统",)),
    ("六 · 能力无上限", ("无上限",)),
    ("七 · 能一次算完就一次算完", ("一次算完",)),
    ("八 · 记忆深度", ("记忆深度",)),
    ("九 · 元认知", ("元认知",)),
    ("十 · 人格层", ("人格层", "人格")),
    ("十一 · 通用 vs 专用", ("通用", "专用")),
    ("十二 · 发布原则", ("发布原则", "发布即成品")),
    ("十三 · 协同网络", ("协同网络",)),
)

# 后半篇八节（第十四至二十二节）：spec 追加，同样按标题关键词核对。
# 【为什么单独一组而不是并进 PHIL_SECTIONS】两组分开报，才看得出"是哪一批缺了"——
#   前十三节是 v1.0 首发就有的，后半篇是本次追加的；失败信息要能直接指向该补哪一批。
PHIL_SECTIONS_PART2 = (
    ("十四 · 精度叠加", ("精度叠加", "存量精度")),
    ("十五 · 速度优化", ("速度优化", "无损加速")),
    ("十七 · 自我改进", ("自我改进",)),
    ("十八 · 全局工作空间", ("全局工作空间", "公共黑板")),
    ("十九 · 小脑定位", ("小脑定位", "记忆索引")),
    ("二十 · 意图理解交给模型", ("意图理解交给模型", "不做规则分流")),
    ("二十一 · 并发与状态一致性", ("并发与状态一致性", "状态一致性")),
    ("二十二 · 可观测性", ("可观测性",)),
)

# 行数上限。**【为什么从 300 抬到 800 —— 是 spec 变了，不是测试放宽】**
#   原上限 300 对应"总纲 + 13 节"那一版 spec。本次 spec 明确要求往同一个文件**追加八节**
#   （第十四至二十二节），13 节就 283 行，加上八节必然超过 300 —— 上限不改就是拿旧 spec 卡新需求。
#   留一个上限仍然有意义：它防的是"文档无限膨胀、没人读得完"，而不是"必须正好 300 行"。
DP_MAX_LINES = 900


def main():
    print("=" * 78)
    print("  阶段 E · 文档逐项核对")
    print("=" * 78)

    print("\n[一] README 的定位块（九条要义齐全；位置不限定在文件顶部）")
    rp = os.path.join(_ROOT, "README.md")
    ck("README.md 存在", os.path.exists(rp))
    if os.path.exists(rp):
        with open(rp, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        lines = raw.split("\n")
        # 【为什么不再只查"前 24 行"—— spec 变了】
        #   原判据要求九条要义写在一个**文件顶部**的引用块里（"前 15 行内说清硬指标"）。
        #   现在要求改成：定位块放在「## 这是什么」一节**之后**，先讲清"这是什么"，
        #   再列要点。位置一变，只扫前 24 行就必然扫不到 —— 那是判据的坐标过期，不是内容缺失。
        #   所以改成：① 先找到那个引用块（不管它在第几行）；② 块本身仍要求 ≤15 行；
        #   ③ 再逐条核对九条要义。位置约束从"必须在顶部"放宽为"必须在正文里且连续成块"。
        blocks, cur = [], []
        for l in lines:
            if l.startswith(">"):
                cur.append(l)
            else:
                if cur:
                    blocks.append(cur)
                    cur = []
        if cur:
            blocks.append(cur)
        top = max(blocks, key=len, default=[])
        blob = "\n".join(top)
        ck("正文里有连续的引用块（不是散落各处的单行引用）", bool(top), len(top))
        ck("定位块在 15 行内（实测 %d 行）" % len(top), len(top) <= 15, len(top))
        for name, kws in README_POINTS:
            ck("定位块含：%s" % name, any(k in blob for k in kws))
        ck("定位块不在文件最顶部（先讲「这是什么」，再列要点）",
           not lines[0].startswith(">"), lines[0][:40] if lines else "")

    print("\n[二] design-philosophy.md（要求 %d 行内 + 前十三节 + 后半篇八节）" % DP_MAX_LINES)
    dp = os.path.join(_ROOT, "docs", "design-philosophy.md")
    ck("design-philosophy.md 存在", os.path.exists(dp))
    if os.path.exists(dp):
        with open(dp, "r", encoding="utf-8", errors="replace") as f:
            d = f.read()
        n_lines = d.count("\n") + 1
        ck("行数在 %d 行内（实测 %d）" % (DP_MAX_LINES, n_lines),
           n_lines <= DP_MAX_LINES, n_lines)
        for name, kws in PHIL_SECTIONS:
            ck("含 %s" % name, any(k in d for k in kws),
               "" if any(k in d for k in kws) else "缺关键词 %s" % (kws,))
        secs = re.findall(r"^##\s*(第[一二三四五六七八九十]+节|总纲)", d, re.M)
        ck("小节标题数 ≥ 13 节 + 总纲（实测 %d）" % len(secs), len(secs) >= 13, secs)
        for name, kws in PHIL_SECTIONS_PART2:
            ck("含 %s" % name, any(k in d for k in kws),
               "" if any(k in d for k in kws) else "缺关键词 %s" % (kws,))
        ck("小节标题数 ≥ 21 节 + 总纲（后半篇八节齐全，实测 %d）" % len(secs),
           len(secs) >= 22, secs)

    print("\n[三] 交叉引用：文档之间互相指得到")
    if os.path.exists(rp):
        with open(rp, "r", encoding="utf-8", errors="replace") as f:
            rt = f.read()
        ck("README 指向 design-philosophy.md", "design-philosophy" in rt)
    if os.path.exists(dp):
        with open(dp, "r", encoding="utf-8", errors="replace") as f:
            dt = f.read()
        ck("design-philosophy 指向图册 architecture-diagrams.md",
           "architecture-diagrams" in dt)
    ck("图册文件存在", os.path.exists(os.path.join(_ROOT, "docs",
                                                 "architecture-diagrams.md")))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
