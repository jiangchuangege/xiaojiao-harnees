# -*- coding: utf-8 -*-
"""无限 2 · 输入无限 · 验收（确定性，不依赖模型、不依赖网络）

提示词的验收口径：
    贴 10 万字 → 完整总结；贴 50 万字 → 完整总结。
    （"总结"由真模型给，这里用**假模型**钉住**载体这一侧**的保证：
      切片不漏字、不切在句中、单片不超 token 上限、进度提示不泄露技术痕迹、
      产出能拼回完整结果、片有落盘可核对。）

为什么单独立这个验收：输入无限最容易出的错都是**静默**的 ——
    · 切成片时把段落边界吃掉半句话（用户看不出来，只看到"总结得不对"）；
    · 单片超了 token 上限（等到真模型那边报 ctx 错才暴露）；
    · 拼装时把重复段落带进结果（看着像模型啰嗦，其实是载体没去重）。
这些必须在**载体这一层**钉死，不能指望真模型兜。
"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import input_splitter as I   # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# ---------------- 造长文本：可读、可校验、可复现 ----------------
_TOPIC = "载体优先的意思是：把智力放在系统里，模型只处理当前这一小块，单次请求永远装得下。"
_SENT = ("第%05d段：小焦的记忆要外部化，历史全部落盘，用的时候按需检索注入；"
         "这样单次请求再小，用户感知到的知识量也是无限的。\n")


def make_text(chars):
    """造一段约 chars 字的中文文本（按段落组织，段内多句）。"""
    out, n, i = [], 0, 0
    while n < chars:
        para = _TOPIC + "".join(_SENT % (i + k) for k in range(4))
        out.append(para)
        n += len(para)
        i += 4
    return "\n\n".join(out)


def fake_llm(messages, max_tokens, **kw):
    """假模型：按这一片的**唯一编号**造出逐片不同、且**自身不重复**的产出。

    这里踩过两次坑，都记下来（都是"测试数据自己造的假象"，不是载体的问题）：
      ① 回显"这一片最后 40 字" → 我的测试文本高度重复，相邻片尾巴几乎一样，
         跨片整句去重把它们删了，拼装结果只剩几十字；
      ② 用 "句子×3" 造产出 → 同一片内就重复，`drop_repeated_sentences` 当然要去掉，
         结果同上。
    真实模型的产出是**逐片不同、片内不重复**的摘要 —— 这里就照这个造：
    每片用它的编号（00000/00004/…）拼出互不相同的句子。
    """
    u = messages[-1]["content"] if messages else ""
    import re as _re
    # ⚠️ 必须从"材料："**之后**找编号：提示词的前半段自己就写着
    #    "…不要写「以下是第几段」这类话" —— 不锚定就会抓到那句话里的"第几段"，
    #    于是每片判成同一个编号、产出全都一样、被去重删光（第三次踩同一个坑）。
    material = u.split("材料：", 1)[-1]
    m = _re.search(r"第(\d{5})段", material)
    ident = int(m.group(1)) if m else 0
    marker = "【本片收到 %d 字】" % len(u)
    body = "".join("第%05d片第%d句：载体把这一小块处理完了，结论编号 %05d-%d。\n"
                   % (ident, k, ident, k) for k in range(1, 7))
    return marker + "\n" + body


def main():
    print("=" * 70)
    print("  无限 2 · 输入无限（切片 → 逐片处理 → 落盘 → 拼装）")
    print("=" * 70)
    t0 = time.time()

    # ---------------- 一、切片：不漏字、不切句中 ----------------
    print("\n[一] 切片：不漏字、不切在句中、单片不超上限")
    for chars, label in ((100_000, "10 万字"), (500_000, "50 万字")):
        text = make_text(chars)
        chunks = I.split_input(text, max_chunk=I.DEFAULT_MAX_CHUNK)
        # ⚠️ 比较口径：拼装用的是 `\n\n` 连接、段落切分会把段间空白规范化，
        #    所以"一个字都没丢"要按**去掉所有空白后**比较 ——
        #    按原串逐字比较会把"段间空格规范化"误判成丢字（第一版就是这么误报的）。
        norm = lambda s: "".join(s.split())
        ck("%s → 切出多片" % label, len(chunks) > 1, "%d 片" % len(chunks))
        ck("%s → **内容一个字都没丢**" % label,
           norm("".join(chunks)) == norm(text),
           "原文 %d 字 / 拼回 %d 字" % (len(norm(text)), len(norm("".join(chunks)))))
        ck("%s → 每片都在 token 上限内" % label,
           all(len(c) <= I.DEFAULT_MAX_CHUNK * 3 for c in chunks),
           "最长片 %d 字" % max(len(c) for c in chunks))
        # 不切在句中：每片结尾必须是句末标点或段落结束（换行）
        bad_tail = [c[-6:] for c in chunks[:-1]
                    if c.rstrip() and c.rstrip()[-1] not in "。！？!?；;…」”\"\n"]
        ck("%s → **不切在句中**（片尾都是完整句）" % label, not bad_tail, bad_tail[:3])
        del text, chunks

    # ---------------- 二、边界情况 ----------------
    print("\n[二] 边界：空/极短/超长单段")
    ck("空文本 → 不崩、返回空或单片",
       I.split_input("", max_chunk=100) in ([], [""]), I.split_input("", max_chunk=100))
    ck("极短文本 → 原样单片（不做无谓切片）",
       I.split_input("你好", max_chunk=100) == ["你好"])
    big_one = "啊" * 5000          # 一个没有任何换行的超长段
    pieces = I.split_input(big_one, max_chunk=100)
    ck("**没有空行的超长单段也能切开**（否则会超 ctx）", len(pieces) > 1, len(pieces))
    ck("切开后不丢字", "".join(pieces) == big_one, len("".join(pieces)))

    # ---------------- 三、整条流水线 ----------------
    print("\n[三] 整条流水线：切片 → 逐片处理 → 落盘 → 拼装")
    text = make_text(120_000)
    seen = []
    r = I.process_long_input(text, "你是小焦。", max_chunk=3000,
                             on_progress=lambda d, t: seen.append((d, t)),
                             llm_fn=fake_llm)
    # 真接口（`inspect.getsource` 核过，不要再猜字段名）：
    #   {"answer", "slices", "tokens_in", "elapsed_s", "chunk_files"}
    final = r.get("answer") or ""
    ck("流水线返回结果（answer 非空）", bool(final), list(r.keys()))
    ck("片数如实（slices 与落盘文件数一致）",
       r.get("slices", 0) >= 2 and r.get("slices") == len(r.get("chunk_files") or []),
       (r.get("slices"), len(r.get("chunk_files") or [])))
    ck("**每片都真的送到了模型**（假模型逐片报了收到的字数）",
       final.count("【本片收到") >= 2, final.count("【本片收到"))
    ck("产出是**拼装**出来的（不是只有最后一片）",
       len(final) > 500 and "【本片收到" in final, len(final))
    ck("tokens_in 是真实估算（大于 0）", (r.get("tokens_in") or 0) > 0, r.get("tokens_in"))

    # ---------------- 四、落盘可核对 ----------------
    print("\n[四] 每片落盘：进度不丢、可核对、可续跑")
    chunk_dir = os.path.join(_ROOT, "logs", "_chunks")
    existed = os.path.isdir(chunk_dir)
    files = sorted(os.listdir(chunk_dir)) if existed else []
    ck("_chunks 目录存在（外部存储，logs 已 gitignore）", existed, chunk_dir)
    ck("**落盘片数 ≥ 2**（不是只在内存里过一遍就丢）", len(files) >= 2, len(files))
    if files:
        p = os.path.join(chunk_dir, files[-1])
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(120)
        ck("落盘文件可读且非空", bool(head.strip()), head[:40].replace("\n", " "))

    # ---------------- 五、拼装去重（感知无限的一部分） ----------------
    print("\n[五] 拼装：相邻片重复段落必须去掉（否则看着像模型啰嗦）")
    # ⚠️ 句长必须 ≥ `drop_repeated_sentences` 的 `min_len=12`：
    #    去重是**按整句**做的，太短的句子（比如 11 字的短结论）不在去重范围内 ——
    #    第一版拿 11 字的句子测，误判成"去重没生效"。这里用真正的长句测。
    long_sent = ("小焦的记忆必须外部化，历史全部落盘，用的时候按需检索注入，"
                 "这样单次请求再小，用户感知到的知识量也是无限的。")
    dup = [long_sent, long_sent + "第二片独有的结论：载体负责编排。"]
    merged = I.merge_outputs(dup)
    ck("**重复的长句只留一份**（去重真的生效）",
       merged.count(long_sent[:16]) == 1, merged.count(long_sent[:16]))
    ck("不同内容都保留", "第二片独有的结论" in merged, merged[:60])
    ck("空输入不崩", I.merge_outputs([]) == "", repr(I.merge_outputs([])))
    ck("全是空片时不产出空段落", I.merge_outputs(["", "  ", "\n"]) == "",
       repr(I.merge_outputs(["", "  ", "\n"])))

    # ---------------- 六、感知无限：进度提示不泄露技术痕迹 ----------------
    print("\n[六] 感知无限：用户只该看到「正在处理…」，不该看到技术痕迹")
    events = []
    _ = I.process_long_input(make_text(20_000), "你是小焦。", max_chunk=3000,
                             on_progress=lambda d, t: events.append((d, t)),
                             llm_fn=fake_llm)
    ck("进度回调发生了（界面能显示正在处理）", len(events) >= 1, len(events))
    forbidden = ("第 ", "片/共", "切片", "context", "token", "tokens", "chunk")
    leaked = [e for e in events if any(w in str(e) for w in forbidden)]
    ck("进度**只传数字**，不携带「第 X/Y 片」这类技术文案", not leaked, leaked[:2])

    # ---------------- 七、性能 ----------------
    print("\n[七] 性能：切片本身不能成为瓶颈")
    t = time.time()
    chunks = I.split_input(make_text(500_000), max_chunk=I.DEFAULT_MAX_CHUNK)
    el = time.time() - t
    ck("50 万字切片 < 5s", el < 5.0, "%.2fs / %d 片" % (el, len(chunks)))

    print("\n" + "=" * 70)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("  耗时 %.1fs" % (time.time() - t0))
    print("=" * 70)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
