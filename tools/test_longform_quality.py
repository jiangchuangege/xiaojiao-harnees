# -*- coding: utf-8 -*-
"""问题 3 回归测试：长文的四项质检（字数 / 章节 / 引号 / 人名）。

运行：python tools/test_longform_quality.py

用户实测："要 10000 字，实际约 2500-3000 字就结束；只 5 章但结尾编造『共 24 章』；
           引号大量未闭合；内容跳戏；人名打错（沈清清舟）；结尾把『目录说明』当正文。"

这四件事**没有一件该指望模型自己做到** —— 全是机械校验，属于载体的活。
本测试用假模型复现这四种病症，逐项验证载体把它们治住了，并且**不许把正常文本改坏**。
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import core.continuation as C  # noqa: E402

PASS, FAIL = [], []


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))


_POOL = [
    "灯芯爆了一下，屋里忽然亮了一瞬，又暗回去",
    "雨敲在瓦上，声音又密又急，像是要把这间屋子从夜里摘出去",
    "他把账本翻到最后一页，那里夹着一张折过三次的纸",
    "街对面的铺子已经上了板，只有一盏灯还亮着",
    "老人没有再说话，只是把茶碗往他面前推了推",
    "远处传来更夫的梆子声，一下，两下，停在第三下",
    "他忽然想起很多年前的一个下午，那天也是这样阴着",
    "柜台上落了一层薄灰，指头划过去，留下一道清晰的痕",
    "门轴响了一声，风从外面挤进来，把灯苗压得贴住了油面",
    "他数了数抽屉里的铜钱，数目对不上，少了两串",
    "巷口有人在低声说话，说到一半就停了，像是被人按住",
    "他把那把钥匙在掌心里攥了攥，凉得像块石头",
    "窗纸破了一个洞，从洞里能看见对面屋檐下站着个人",
    "堂屋的钟摆停在了寅时，谁也没有去拨它",
    "她把手炉放在桌上，铜盖上的纹路已经被磨得发亮",
    "纸页边缘起毛，翻动的时候发出很轻的沙沙声",
    "他抬头看了一眼梁上，那里挂着一只落了灰的灯笼",
    "外面的车马声渐渐远了，院子里只剩下水滴的声音",
    "他把那封信折好，塞回袖子里，站起身要走",
    "门槛很高，跨过去的时候他扶了一下门框",
]
_VERB = ["看见", "听见", "想起", "摸到", "记起"]


def make_model(declare_at=5, name_variants=True, meta_ending=True):
    """造一个"写得出新内容、但会犯那四种病"的假模型。"""
    st = {"n": 0}

    def seg(i):
        who = (["沈清", "沈清清", "沈清舟"][i % 3]) if name_variants else "沈清"
        return "".join("%s%s，%s。\n" % (who, _VERB[k % 5], _POOL[(i * 7 + k * 3) % len(_POOL)])
                       for k in range(24))

    def llm(messages, max_tokens, **kw):
        st["n"] += 1
        u = messages[-1]["content"]
        if "自然的结尾" in u:
            end = "“这个故事到这里就结束了，他抬起头看着天。"       # 引号不闭合
            if meta_ending:
                end = "沈清清舟合上书。全书共 24 章，前五章讲了铺子与账本，后续章节将展开……" + end
            return end
        body = seg(st["n"])
        if st["n"] >= declare_at:
            return body + "\n【完成】\n"        # 提前喊完成
        return body
    return llm, st


def main():
    print("=" * 68)
    print("  问题 3 回归：长文四项质检")
    print("=" * 68)

    # ===== A 字数：目标 10000，不许只写 2500-3000 =====
    print("\n[A] 字数 · 要 10000 字就不许只给 2500")
    llm, st = make_model()
    res = C.generate_unlimited("写一本 10000 字的小说，主角叫沈清", "你是小焦。",
                               max_per_chunk=2000, llm_fn=llm, buffer_size=1)
    text = res["text"]
    ck("A", "实际字数 ≥ 目标 80%%（实测 %d / 10000 = %.0f%%）"
       % (res["chars"], 100.0 * res["chars"] / 10000), res["chars"] >= 8000,
       "%d 字" % res["chars"])
    ck("A", "没有超过目标 1.2 倍（不许硬撑篇幅）", res["chars"] <= 12000, res["chars"])
    ck("A", "模型第 5 段就喊完成 → 载体忽略了它并继续写",
       res.get("done_ignored", 0) >= 3, "忽略 %d 次" % res.get("done_ignored"))
    ck("A", "结果是完整的（结尾落在句末）", text.rstrip()[-1] in "。！？!?；;…", repr(text[-16:]))

    # ===== B 章节：不许编造"共 X 章" =====
    print("\n[B] 章节 · 不许编造『全书共 24 章』这类目录说明")
    meta = re.findall(r"全书共\s*[\d一二三四五六七八九十]+\s*章", text)
    ck("B", "成稿里没有『全书共 X 章』", not meta, meta or "无")
    ck("B", "没有『后续章节将展开』这类说明句", "后续章节将展开" not in text)
    ck("B", "质检结果里记了清掉几处", "meta_removed" in (res.get("quality") or {}),
       (res.get("quality") or {}).get("meta_removed"))
    # 章节编号单调递增（已有的重排能力，回归确认没被破坏）
    nums = [C._cn_to_int(m) for m in re.findall(r"第([零一二三四五六七八九十百\d]+)章", text)]
    nums = [n for n in nums if n]
    ck("B", "章节编号单调递增", all(nums[i] < nums[i + 1] for i in range(len(nums) - 1)),
       nums[:10])

    # ===== C 引号：必须全部闭合 =====
    print("\n[C] 引号 · 每个引号都必须闭合")
    for op, cl in C._QUOTE_PAIRS:
        ck("C", "『%s%s』配对" % (op, cl), text.count(op) == text.count(cl),
           "%d / %d" % (text.count(op), text.count(cl)))
    ck("C", "质检结果里记了修补几处", (res.get("quality") or {}).get("quotes_fixed") is not None,
       (res.get("quality") or {}).get("quotes_fixed"))

    # ===== D 人名：同一人前后必须一致 =====
    print("\n[D] 人名 · 同一人前后必须一致")
    ck("D", "三种写法被归一成一种",
       text.count("沈清清") == 0 and text.count("沈清舟") == 0 and text.count("沈清") > 0,
       {"沈清": text.count("沈清"), "沈清清": text.count("沈清清"), "沈清舟": text.count("沈清舟")})
    ck("D", "质检结果里记了归一了什么", bool((res.get("quality") or {}).get("names_unified")),
       (res.get("quality") or {}).get("names_unified"))

    # ===== E 关键：不许把正常文本改坏（第一版就是在这里翻车的）=====
    print("\n[E] 安全 · 归一不许误伤普通词句")
    # 这些句子里"忽然/忽然亮"、"时候/时候发"在**统计上**和人名走样一模一样
    normal = "".join("他忽然亮了一瞬，声音又密又急，时候发出沙沙的响。"
                     "外面挤进来一股风，已经上了板的铺子晃了晃。" * 8)
    out, notes = C.unify_names(normal)
    ck("E", "正常文本一个字都没被改", out == normal, notes or "无改动")
    ck("E", "也没有误报人名", not notes, notes)
    # 用**同一批动词**的假人名才该被归一（语法角色一致）
    same = "".join("沈清走进屋子。沈清听见雨声。沈清舟走进屋子。沈清舟听见雨声。" * 12)
    o2, n2 = C.unify_names(same)
    ck("E", "语法角色一致的人名走样才归一", "沈清舟" not in o2 and bool(n2), n2)
    # 势均力敌（可能是两个人）→ 不许动
    two = "".join("沈清走进屋子。沈清舟走进屋子。" * 8)
    o3, n3 = C.unify_names(two)
    ck("E", "两个名字势均力敌时不动它们（可能是两个人）", o3 == two, n3)

    # ===== F 复读：成稿里不许留短句循环 =====
    print("\n[F] 复读 · 成稿里不许留下短句循环")
    llm2, st2 = make_model(declare_at=3)

    def llm3(messages, max_tokens, **kw):
        u = messages[-1]["content"]
        if "自然的结尾" in u:
            return "这件事就这样结束了。"
        if st2["n"] >= 3:
            # 短句循环（"”老人说。" 5 个字，去重判据 min_len=12 压根管不到它）
            return "".join("他把手按在柜面上。”老人说。" for _ in range(30))
        return llm2(messages, max_tokens, **kw)
    res3 = C.generate_unlimited("写一本 5000 字的小说", "你是小焦。",
                                max_per_chunk=2000, llm_fn=llm3, buffer_size=1)
    t3 = res3["text"]
    runs = re.findall(r"(”老人说。)(?:”老人说。){2,}", t3)
    ck("F", "短句循环没有留在成稿里", not runs, "连续出现 %d 处" % len(runs))
    # 报告字段：这条循环可能在**生成中**就被源头闸门拦掉了（那就不走成稿复读），
    # 所以这里断言"查过"（checked / final_repeat_cut 都在），而不是断言"一定在成稿阶段查到"。
    ck("F", "质检报告注明查过成稿复读",
       (res3.get("quality") or {}).get("checked") is True
       and "final_repeat_cut" in (res3.get("quality") or {}),
       (res3.get("quality") or {}))
    # 单元级：成稿复读这条判据本身必须管用（直接喂给它）
    _cut, _n, _hit = C.drop_final_repeat("正常开头。" + "”老人说。" * 30)
    ck("F", "drop_final_repeat 本身能管住短句循环", _hit is not None and _n > 0,
       "%s 砍 %d 字" % (_hit.kind if _hit else "没检出", _n))

    # ===== G 如实报告：没写到目标就说没写到 =====
    print("\n[G] 诚实 · 篇幅不达标必须如实报告")

    def stuck(messages, max_tokens, **kw):
        u = messages[-1]["content"]
        if "自然的结尾" in u:
            return "结束。"
        return "短的。" + "\n【完成】\n"           # 一直喊完成、几乎不产出
    res4 = C.generate_unlimited("写一本 10000 字的小说", "你是小焦。",
                                max_per_chunk=2000, llm_fn=stuck, buffer_size=1)
    ck("G", "没达标时如实标注（不谎称完成）",
       "只写到目标篇幅" in res4["stopped"] or (res4.get("quality") or {}).get("under_target"),
       res4["stopped"][:80])
    ck("G", "空转时**主动认输**并如实说明（不无限烧算力）",
       (res4.get("quality") or {}).get("gave_up") is True and "空转" in res4["stopped"],
       res4["stopped"][:90])
    ck("G", "段数有界（没有跑飞）", len(res4["chunks"]) < 400, "%d 段" % len(res4["chunks"]))
    ck("G", "质检报告字段齐全（查过就写 0，不省略）",
       all(k in (res.get("quality") or {}) for k in
           ("checked", "meta_removed", "quotes_fixed", "final_repeat_cut")),
       sorted((res.get("quality") or {}).keys()))

    print("\n" + "=" * 68)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
