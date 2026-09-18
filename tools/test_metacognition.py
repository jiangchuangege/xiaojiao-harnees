# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""元认知自测 —— 真跑，不模拟（离线、秒级、不调任何模型）

运行：python tools/test_metacognition.py

为什么这个自测必须离线、必须能用假模型跑：
    元认知层最危险的失败模式是"**它以为自己检查过了**" ——
    llm_fn=None 时假装检查过、只拿到 1 个样本就宣布"一致"、解析不出档位就默认成"有把握"。
    这些在功能测试里全都看不出来（它照样返回一个 dict，字段还齐全）。
    所以这里逐条钉住"判据本身"，而且模型一律换成**记账用的假函数**：
    我们要验的是"载体判断得对不对"，而不是"某个模型答得好不好"（后者换火种就该变，
    载体判断换火种必须不变 —— 这正是"模型平等"的验收方式）。

覆盖（9 组）：
    A 解析容错（A/B/C/大小写/全角/脏回复/空回复/抄提示词 → 认不出必须 "?"）
    B 没有模型时不报错（None / 抛异常 / 空回复 / 非字符串，一律如实 ok=False）
    C 三档路由（含 "?" → use_tool：拿不准就走更稳的那条路）
    D 交叉检查（角度生成 / 相似度 / 一致性判据 / 单样本必须 unknown）
    E 边界档案落盘（真的写进 logs/metacognition/boundary.jsonl，stats 与行数对得上）
    F should_use_tool 样本不足**不误判**（必须 False）
    G should_use_tool 同类连续没把握 / 自评有把握却答错 → **必须 True**（真造数据）
    H summary 的数字与 stats 完全一致（不许自己另编一套）
    I 健壮性（脏参数 / 半截 JSONL / 不依赖 Flask 与主程序 —— 一律不崩）

【自测数据怎么清：只删带标记的行，**绝不删除任何文件**】
    本项目的红线是"绝不删除任何文件"，所以这里不去删档案文件，
    而是给自测写入的每一行都在 note 里带上标记 `【MC自测】`，跑完把**带标记的行**去掉，
    其余行按原样写回（连字节都不动别人的行）。
    为什么不用"整文件还原快照"：万一跑自测的时候主程序也在往同一个档案里写，
    还原快照会把**别人刚写的记录**一起抹掉 —— 那是更严重的问题（等于丢用户数据）。

【两个刻意的写法，都是为了断言不被自己污染】
    ① 标记只放在 `note` 里，**不放问题正文**：放正文会被 2-gram 当成"同类特征"，
       于是两个不相干的测试问题会被判成同一类，"样本不足"那组当场变成假失败。
    ② 每条问题都带一段**本次调用唯一的随机号**：上一次自测如果中途崩了，
       残留行会留在档案里；随机号保证这一轮的"同类问题"只可能匹配到这一轮自己写的行。

退出码：全绿 0，有失败 1（可以直接挂进 CI）。
"""
import os
import sys
import tempfile
import time
import uuid

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.metacognition import selfrate as SR       # noqa: E402
from core.metacognition import crosscheck as CC     # noqa: E402
from core.metacognition import boundary as BD       # noqa: E402

PASS = []
FAIL = []

TAG = "【MC自测】"        # 只进 note，用来跑完清场（见文件头的说明①）
TMP_DIR = tempfile.mkdtemp(prefix="xj_metacognition_selftest_")
TMP_PATH = os.path.join(TMP_DIR, "boundary.jsonl")     # 数字必须完全确定的几组用
REAL_PATH = BD.boundary_path()                         # 落盘那组必须打真实档案才算数


def ck(group, name, cond, info=""):
    (PASS if cond else FAIL).append("%s/%s" % (group, name))
    print("  %s [%s] %s%s" % ("✅" if cond else "❌", group, name,
                              ("  ← " + str(info)) if info else ""))
    return bool(cond)


def q(text):
    """造一个问题：带**本次调用唯一**的随机号（理由见文件头说明②）。"""
    return "MC%s %s" % (uuid.uuid4().hex[:8], text)


def count_lines(path, tag=None):
    """数行数（不给 tag）或数"不带标记的行数"（给 tag）。读不到一律算 0，绝不抛。"""
    try:
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for line in f if tag is None or tag not in line)
    except OSError:      # noqa: silent-ok — 读不动按 0 处理，后面会如实报出来
        return 0


def cleanup_tagged(path, tag=TAG):
    """只删**带自测标记**的行，其余行原样写回；**绝不删除文件本身**。

    返回清掉的行数。文件如果原来不存在，清完留一个空文件（文件也留着 —— 红线）。
    """
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    keep, dropped = [], 0
    for line in lines:
        if tag in line:
            dropped += 1
            continue
        keep.append(line)
    if keep and not keep[-1].endswith("\n"):
        keep[-1] += "\n"        # 末行缺换行时补上，免得下次追加把两行粘成一行
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(keep)
    return dropped


def raises(fn):
    """fn() 是否抛异常（用于验"取不到的名字如实报错"）。"""
    try:
        fn()
        return False
    except Exception:      # noqa: silent-ok — 这里的"抛异常"就是期望结果
        return True


def main():
    print("=" * 74)
    print("  小焦元认知自测（答前自评 / 答后交叉检查 / 能力边界档案）")
    print("=" * 74)
    print("  真实档案：%s" % REAL_PATH)
    print("  临时目录：%s" % TMP_DIR)
    real_existed = os.path.exists(REAL_PATH)
    untagged_before = count_lines(REAL_PATH, TAG)

    # ---------------------------------------------------------------- A
    print("\n[A] 解析容错：模型回什么都要落在正确的档位上")
    ck("A", "只回 A → A", SR.parse_rating("A") == "A")
    ck("A", "带句号 A。 → A", SR.parse_rating("A。") == "A")
    ck("A", "小写 b → B（模型大小写不讲究）", SR.parse_rating("b") == "B")
    ck("A", "全角 Ｂ → B（不归一就会把明确的 B 谎报成没把握）", SR.parse_rating("Ｂ") == "B")
    ck("A", "我认为是B → B", SR.parse_rating("我认为是B") == "B")
    ck("A", "把握C → C", SR.parse_rating("把握C") == "C")
    ck("A", "答案是 B，因为上次说过 → B", SR.parse_rating("答案是 B，因为上次说过") == "B")
    ck("A", "B档 → B", SR.parse_rating("B档") == "B")
    ck("A", "空回复 '' → ?（**不许猜成 A**）", SR.parse_rating("") == "?")
    ck("A", "全空白 '   ' → ?", SR.parse_rating("   ") == "?")
    ck("A", "None → ? 且不崩", SR.parse_rating(None) == "?")
    ck("A", "脏回复「好的没问题」→ ?", SR.parse_rating("好的没问题") == "?")
    ck("A", "把提示词抄回来（三档全念一遍）→ ?（**不许挑开头的 A 当答案**）",
       SR.parse_rating("A 有把握 → 直接答；B 有点 → 带标注；C 没把握 → 走工具") == "?")
    ck("A", "「我不太确定」→ C（不许把否定听成肯定）", SR.parse_rating("我不太确定") == "C")
    ck("A", "「我不确定」→ C", SR.parse_rating("我不确定") == "C")
    ck("A", "「有点印象」→ B", SR.parse_rating("有点印象") == "B")
    ck("A", "「很有把握」→ A", SR.parse_rating("很有把握") == "A")
    ck("A", "「不是A」→ ?（排除性提及不算它给的档位）", SR.parse_rating("不是A") == "?")
    ck("A", "「我认为是B，不是A也不是C」→ B（先剔掉排除性提及）",
       SR.parse_rating("我认为是B，不是A也不是C") == "B")
    fuzz = ["", " ", None, 0, 12.5, "不知道", "??", "选D", "我选A档", "B或C", "可能吧",
            "aaaa", "。。。", "答案", "AAA", "把握", "1", "True", "\n", "ＡＢ"]
    bad = [(x, SR.parse_rating(x)) for x in fuzz if SR.parse_rating(x) not in SR.ALL_RATINGS]
    ck("A", "脏输入模糊测试（%d 例）：结果必定落在 A/B/C/? 之内" % len(fuzz), not bad, bad)
    ck("A", "parse_rating 永远返回字符串", all(isinstance(SR.parse_rating(x), str) for x in fuzz))

    # ---------------------------------------------------------------- B
    print("\n[B] 没有模型时**不报错**，如实说没把握")
    r = SR.self_rate("小焦的记忆存在哪")
    ck("B", "llm_fn=None 返回 dict 且不报错", isinstance(r, dict), type(r).__name__)
    ck("B", "llm_fn=None → rating '?'", r.get("rating") == "?", r)
    ck("B", "llm_fn=None → ok=False（没自评就是没自评）", r.get("ok") is False, r.get("ok"))
    ck("B", "llm_fn=None → why='没有可用的模型'（原文）",
       r.get("why") == "没有可用的模型", r.get("why"))
    ck("B", "llm_fn=None → raw 为空串（不编造原文）", r.get("raw") == "", repr(r.get("raw")))
    ck("B", "返回的键正好是 rating/raw/ok/why", set(r) == {"rating", "raw", "ok", "why"}, sorted(r))
    ck("B", "llm_fn 不是可调用对象 → 同样按'没有模型'处理，不报错",
       SR.self_rate("x", llm_fn="我不是函数").get("ok") is False)
    r2 = SR.self_rate("随便问问", llm_fn=lambda p: "B")
    ck("B", "模型回 B → ok=True 且 rating=B", r2.get("ok") is True and r2.get("rating") == "B", r2)
    ck("B", "raw 保留模型原话", r2.get("raw") == "B", repr(r2.get("raw")))
    r3 = SR.self_rate("随便问问", llm_fn=lambda p: 1 / 0)
    ck("B", "模型抛异常 → 不崩、ok=False、rating='?'",
       r3.get("ok") is False and r3.get("rating") == "?", r3.get("why"))
    r4 = SR.self_rate("随便问问", llm_fn=lambda p: None)
    ck("B", "模型回 None → 不崩且 ok=False", r4.get("ok") is False, r4.get("why"))
    r5 = SR.self_rate("随便问问", llm_fn=lambda p: "")
    ck("B", "模型回空串 → ok=False（不当成有把握）", r5.get("ok") is False, r5.get("why"))
    ck("B", "self_rate 的提示词里写了三档含义 + 只回一个字母",
       "A = " in SR.rate_prompt("x") and "只回一个字母" in SR.rate_prompt("x"))
    ck("B", "rate_prompt 带着问题原文", "天为什么是蓝的" in SR.rate_prompt("天为什么是蓝的"))
    ck("B", "有上下文才出现「已知信息」段",
       "已知信息" in SR.rate_prompt("x", "用户住在济南") and "已知信息" not in SR.rate_prompt("x"))
    ck("B", "B 档答案被加上'不太确定'标注", SR.CAVEAT in SR.apply_route("答案是 42。", "B"))
    ck("B", "A 档答案原样返回（不加标注、不改内容）", SR.apply_route("答案是 42。", "A") == "答案是 42。")
    ck("B", "空答案不会被硬加上标注（不产生一条只有标注的垃圾）",
       SR.apply_route("   ", "B").strip() == "")

    # ---------------------------------------------------------------- C
    print("\n[C] 三档路由（含 ? → 走更稳的那条路）")
    ck("C", "A → direct", SR.route("A") == "direct", SR.route("A"))
    ck("C", "B → answer_with_caveat", SR.route("B") == "answer_with_caveat", SR.route("B"))
    ck("C", "C → use_tool", SR.route("C") == "use_tool", SR.route("C"))
    ck("C", "? → use_tool（拿不准就当没把握）", SR.route("?") == "use_tool", SR.route("?"))
    ck("C", "小写 a → direct（大小写不讲究）", SR.route("a") == "direct", SR.route("a"))
    ck("C", "None → use_tool（不崩）", SR.route(None) == "use_tool", SR.route(None))
    ck("C", "认不出的档位 'X' → use_tool", SR.route("X") == "use_tool", SR.route("X"))
    ck("C", "四档路由表齐全、三条出口互不相同",
       set(SR.ROUTES) == set(SR.ALL_RATINGS) and len(set(SR.ROUTES.values())) == 3, SR.ROUTES)
    ck("C", "自评 C 之后 self_rate 的 why 指向 use_tool",
       "use_tool" in SR.self_rate("x", llm_fn=lambda p: "C")["why"])

    # ---------------------------------------------------------------- D
    print("\n[D] 交叉检查（角度 / 相似度 / 一致性判据）")
    a3 = CC.angles("小焦的记忆怎么存", 3)
    ck("D", "angles(q,3) 正好 3 个角度", len(a3) == 3, len(a3))
    ck("D", "3 个角度互不相同（同一个问法问三遍等于没检查）", len(set(a3)) == 3)
    ck("D", "角度里带着原问题（问的是同一件事）", all("小焦的记忆怎么存" in x for x in a3))
    ck("D", "angles(q,2) 正好 2 个；angles(q,1) 正好 1 个",
       len(CC.angles("q", 2)) == 2 and len(CC.angles("q", 1)) == 1)
    ck("D", "angles 上限就是模板数（n=99 被夹住，不会瞎编角度）",
       len(CC.angles("q", 99)) == len(CC.ANGLES), len(CC.angles("q", 99)))
    ck("D", "空问题/None → 空列表（不拿空问题去问模型）",
       CC.angles("") == [] and CC.angles(None) == [])
    ck("D", "角度生成是纯规则：不调模型也生成得出来",
       all(isinstance(x, str) and x for x in a3))

    ck("D", "完全相同（只差标点）→ 1.0",
       CC.similarity("北京是中国的首都。", "北京是中国的首都") == 1.0,
       CC.similarity("北京是中国的首都。", "北京是中国的首都"))
    ck("D", "完全无关 → 0.0", CC.similarity("北京是中国的首都", "今天天气不错") == 0.0,
       CC.similarity("北京是中国的首都", "今天天气不错"))
    ck("D", "同一件事换个说法 → ≥0.6（判一致）",
       CC.similarity("北京是中国的首都", "中国的首都是北京") >= CC.CONSISTENT_MIN,
       CC.similarity("北京是中国的首都", "中国的首都是北京"))
    ck("D", "空文本 → 0.0（两个空答案不许算'完全一致'）",
       CC.similarity("", "") == 0.0 and CC.similarity(None, "x") == 0.0)
    ck("D", "相似度永远落在 0~1",
       all(0.0 <= CC.similarity(x, y) <= 1.0
           for x, y in (("a", "b"), ("北京", "北京"), ("", "x"), (None, None))))

    same = lambda p: "北京是中国的首都。"                                   # noqa: E731
    diff = lambda p: ("北京是中国的首都。" if "直接" in p else               # noqa: E731
                      ("xyzzy" if "事实" in p else "qwerty"))
    para = lambda p: "北京是中国的首都" if "直接" in p else "中国的首都是北京"  # noqa: E731
    one = lambda p: "只有一个角度的答案" if "直接" in p else ""               # noqa: E731

    r = CC.cross_check("首都是哪", llm_fn=same)
    ck("D", "三个角度答案相同 → consistent", r["verdict"] == "consistent" and r["agree"] == 1.0,
       r["detail"])
    ck("D", "consistent → prefer=output", CC.prefer(r["verdict"]) == "output")
    ck("D", "answers 条数 == 角度数（3）", len(r["answers"]) == 3, len(r["answers"]))
    ck("D", "返回的键正好是 answers/agree/verdict/detail",
       set(r) == {"answers", "agree", "verdict", "detail"}, sorted(r))
    ck("D", "detail 里带真算出来的数字", "1.000" in r["detail"], r["detail"])

    r = CC.cross_check("首都是哪", llm_fn=diff)
    ck("D", "三个角度答案完全无关 → conflict（agree≤0.3）",
       r["verdict"] == "conflict" and r["agree"] <= CC.CONFLICT_MAX, "%s | %s" % (r["agree"], r["detail"]))
    ck("D", "conflict → prefer=reanswer_with_caveat",
       CC.prefer(r["verdict"]) == "reanswer_with_caveat")

    r = CC.cross_check("首都是哪", llm_fn=para)
    ck("D", "同一件事的不同说法 → consistent（不是所有改写都算矛盾）",
       r["verdict"] == "consistent", "%s | %s" % (r["agree"], r["detail"]))

    # 中间地带（0.3 < agree < 0.6）必须判矛盾 —— 宁严不宽。
    # 这一对是**实测**出来的：两条答案讲的是同一件事的不同侧面，字面重合 0.356。
    mid_a = "小焦的记忆分层存：事实层原样存，表达层只学风格，印象层降级不删。"
    mid_b = "小焦把记忆分成三层：事实、表达、印象，降级但不删除。"
    mid_sim = CC.similarity(mid_a, mid_b)
    ck("D", "构造出真的落在中间地带的一对（0.3<sim<0.6）",
       CC.CONFLICT_MAX < mid_sim < CC.CONSISTENT_MIN, mid_sim)
    two = lambda p: mid_a if "直接" in p else mid_b                          # noqa: E731
    rm = CC.cross_check("记忆怎么存", llm_fn=two, n=2)
    ck("D", "中间地带**也判矛盾**（宁严不宽：矛盾比不确定更危险）",
       rm["verdict"] == "conflict", "%s | %s" % (rm["agree"], rm["detail"]))

    r = CC.cross_check("首都是哪", llm_fn=one)
    ck("D", "只有 1 个可用答案 → unknown（**绝不 consistent**）",
       r["verdict"] == "unknown" and len(r["answers"]) == 1, r["detail"])
    ck("D", "单样本时 agree=0.0（不拿一个样本算'完全一致'）", r["agree"] == 0.0, r["agree"])
    ck("D", "unknown → prefer=output_with_caveat", CC.prefer(r["verdict"]) == "output_with_caveat")
    ck("D", "detail 明说'1 个样本不能说一致'", "1 个样本" in r["detail"], r["detail"])

    r = CC.cross_check("首都是哪", llm_fn=None)
    ck("D", "llm_fn=None → unknown 且不报错",
       r["verdict"] == "unknown" and r["answers"] == [], r["detail"])
    r = CC.cross_check("首都是哪", llm_fn=lambda p: 1 / 0)
    ck("D", "所有角度都抛异常 → unknown（不崩、不谎报一致）",
       r["verdict"] == "unknown" and r["answers"] == [], r["detail"])
    r = CC.cross_check(None, llm_fn=same)
    ck("D", "空问题 → unknown（没有问题就没有检查）", r["verdict"] == "unknown", r["detail"])
    ck("D", "verdict 永远落在 consistent/conflict/unknown 之内",
       all(CC.cross_check(x, llm_fn=f)["verdict"] in CC.VERDICTS
           for x in ("a", "", None) for f in (same, diff, one, None)))
    ck("D", "prefer 认不出 verdict 时退到 output_with_caveat（不替没做过的检查背书）",
       CC.prefer("xxx") == "output_with_caveat" and CC.prefer(None) == "output_with_caveat")

    # ---------------------------------------------------------------- E
    print("\n[E] 边界档案：真的落盘（%s）" % REAL_PATH)
    before = count_lines(REAL_PATH)
    qe = q("落盘验证：小焦的记忆存在哪")
    row = BD.record(qe, "C", correct=None, note=TAG + " 落盘自测", source="自测")
    row2 = BD.record(qe, "A", correct=True, note=TAG + " 落盘自测2", source="自测")
    after = count_lines(REAL_PATH)
    ck("E", "record 返回 written=True（真写进去了）", row.get("written") is True, row.get("written"))
    ck("E", "真实档案行数正好 +2", after - before == 2, "%d → %d" % (before, after))
    ck("E", "写的就是 logs/metacognition/ 下的 boundary.jsonl",
       REAL_PATH.replace("\\", "/").endswith("logs/metacognition/boundary.jsonl"), REAL_PATH)
    ck("E", "返回的 dict 里带着写盘结果与路径（调用方不用猜）",
       "written" in row and "path" in row, sorted(row))
    need = ("ts", "iso_time", "question", "topic", "rating", "rating_raw",
            "correct", "note", "source")
    rows_real = BD._rows(days=None)
    last = rows_real[-1] if rows_real else {}
    ck("E", "读回来的行字段齐全", all(k in last for k in need),
       [k for k in need if k not in last])
    ck("E", "correct=None 被保留成 None（不许折成 False 撒谎）", row.get("correct") is None,
       row.get("correct"))
    ck("E", "note/source 原样落盘",
       last.get("note") == TAG + " 落盘自测2" and last.get("source") == "自测",
       (last.get("note"), last.get("source")))
    ck("E", "topic 被算出来了（不是空串）", bool(last.get("topic")), last.get("topic"))
    ck("E", "档案里的 correct 是独立字段（C 档那条 None、A 档那条 True）",
       row.get("correct") is None and row2.get("correct") is True,
       (row.get("correct"), row2.get("correct")))
    st_real = BD.stats(30)
    ck("E", "stats(days=30) 统计到了刚写的 2 条", st_real["total"] >= 2, st_real["total"])
    if not real_existed:
        ck("E", "档案原本不存在 → stats.total 与文件行数**完全一致**",
           st_real["total"] == count_lines(REAL_PATH),
           "%d vs %d" % (st_real["total"], count_lines(REAL_PATH)))
    else:
        ck("E", "档案原本就有真实数据 → 至少统计到刚写的 2 条",
           st_real["total"] >= 2, st_real["total"])
    ck("E", "by_rating 四档加起来 == total",
       sum(st_real["by_rating"].values()) == st_real["total"], st_real["by_rating"])

    print("\n  -- 数字必须完全确定的那几组：写进临时档案 --")
    qm = "小焦的记忆是怎么存的"
    BD.record(qm, "A", correct=True, path=TMP_PATH)
    BD.record(qm, "A", correct=False, path=TMP_PATH, note="自评有把握却答错了")
    BD.record(qm, "B", path=TMP_PATH)
    BD.record(qm, "C", path=TMP_PATH)
    BD.record(qm, "C", path=TMP_PATH)
    BD.record("明天的天气怎么样", "A", correct=True, path=TMP_PATH)
    st = BD.stats(30, path=TMP_PATH)
    ck("E", "临时档案：stats.total == 6 == 文件行数",
       st["total"] == 6 == count_lines(TMP_PATH),
       "%s vs %s" % (st["total"], count_lines(TMP_PATH)))
    ck("E", "临时档案：by_rating = A3/B1/C2/?0",
       st["by_rating"] == {"A": 3, "B": 1, "C": 2, "?": 0}, st["by_rating"])
    ck("E", "false_confidence = 1（自评 A 却答错的那一条）", st["false_confidence"] == 1,
       st["false_confidence"])
    ck("E", "3 条 A 档里只有 1 条答错 → false_confidence 只数答错的那条（不数答对的）",
       st["by_rating"]["A"] == 3 and st["false_confidence"] == 1,
       "%d 条 A / %d 条答错" % (st["by_rating"]["A"], st["false_confidence"]))
    ck("E", "correct 缺省（None）的 B 档没被算进 false_confidence", st["false_confidence"] == 1)
    ck("E", "low_conf_topics 只列样本≥2 且有过 C 的话题",
       bool(st["low_conf_topics"])
       and all(t["samples"] >= 2 and t["c"] >= 1 for t in st["low_conf_topics"]),
       st["low_conf_topics"])
    ck("E", "low_conf_topics 第一项是「小焦」（5 条里 2 条 C）",
       bool(st["low_conf_topics"]) and st["low_conf_topics"][0]["topic"] == "小焦"
       and st["low_conf_topics"][0]["samples"] == 5 and st["low_conf_topics"][0]["c"] == 2,
       st["low_conf_topics"][:1])
    ck("E", "只有 1 条的「明天」不进话题统计（一条不叫一类问题）",
       all(t["topic"] != "明天" for t in st["low_conf_topics"]), st["low_conf_topics"])
    ck("E", "rating 归一：传模型原话「我认为是C」也记成 C",
       BD.record("归一测试", "我认为是C", path=TMP_PATH).get("rating") == "C")
    ck("E", "rating_raw 留了模型原话（以后改了规则还能重审旧记录）",
       BD.record("归一测试2", "我认为是C", path=TMP_PATH).get("rating_raw") == "我认为是C")

    # ---------------------------------------------------------------- F
    print("\n[F] should_use_tool：样本不足时**不许误判**")
    # 【2026-09-19 修：判据不许读**真实档案**】不传 `path` 时读的是
    #   `logs/metacognition/boundary.jsonl` —— 那是**用户跑出来的数据**（本机 2850 行，还在长）。
    #   于是同一组判据的结论会随"小焦跑了多少轮"变来变去：实测同一条自测在全量跑里红的是
    #   「2 条时 samples==2」、单独跑时红的是「样本 0 条」——**而且上一轮失败没清干净的行会污染下一轮**（自毒）。
    #   所以这里的断言一律走**临时档案**；真实档案那边只留一条打标记的行，专供最后「[清理]」那组验。
    r = BD.should_use_tool(q("全新话题：样本不足"), path=TMP_PATH)
    ck("F", "一条样本都没有 → use_tool=False", r["use_tool"] is False, r)
    ck("F", "样本 0 条时 samples=0（如实报数）", r["samples"] == 0, r["samples"])
    ck("F", "样本不足的 why 明说'样本不足'", "样本不足" in r["why"], r["why"])
    ck("F", "返回的键正好是 use_tool/why/samples", set(r) == {"use_tool", "why", "samples"},
       sorted(r))
    ck("F", "why 是人话（中文 + 真实数字）",
       any("\u4e00" <= ch <= "\u9fff" for ch in r["why"]) and any(ch.isdigit() for ch in r["why"]),
       r["why"])
    qs = q("样本不足验证：这个新话题")
    BD.record(qs, "C", path=TMP_PATH, note=TAG, source="自测")
    BD.record(qs, "C", path=TMP_PATH, note=TAG, source="自测")
    BD.record(q("真实档案也要能清干净"), "C", path=REAL_PATH, note=TAG, source="自测")
    r = BD.should_use_tool(qs, path=TMP_PATH)
    ck("F", "同类只有 2 条 C → 仍然 False（不到 3 条底线）",
       r["use_tool"] is False and r["samples"] == 2, r)
    ck("F", "2 条时 why 里带真实条数与门槛（2 条 / 不到 3 条）",
       "2 条" in r["why"] and "不到 3 条" in r["why"], r["why"])
    ck("F", "不同话题的历史不会误伤（问别的事 → 不误判成该走工具）",
       BD.should_use_tool(q("完全另一个话题：晚饭吃什么"), path=TMP_PATH)["use_tool"] is False)
    ck("F", "问题为空 → 不误判",
       BD.should_use_tool(None, path=TMP_PATH)["use_tool"] is False
       and BD.should_use_tool("", path=TMP_PATH)["use_tool"] is False)

    # ---------------------------------------------------------------- G
    print("\n[G] should_use_tool：同类连续没把握 / 自评有把握却答错 → **必须 True**")
    qc = q("连续没把握验证：这类问题")
    for i in range(3):
        BD.record(qc, "C", path=TMP_PATH, source="自测", note="%s 第%d条" % (TAG, i + 1))
    r = BD.should_use_tool(qc, path=TMP_PATH)
    ck("G", "同类连续 3 条 C 档 → use_tool=True", r["use_tool"] is True, r)
    ck("G", "samples 如实等于 3", r["samples"] == 3, r["samples"])
    ck("G", "why 里带真实比例（占 100%）与理由",
       "没把握" in r["why"] and "100%" in r["why"], r["why"])
    ck("G", "换个说法的同类问题也被认出来（不然历史永远攒不起来）",
       BD.should_use_tool(qc.replace("这类问题", "这种问题"), path=TMP_PATH)["use_tool"] is True)

    qf = q("自评有把握却答错验证：这类问题")
    BD.record(qf, "A", correct=True, source="自测", note=TAG)
    BD.record(qf, "A", correct=True, source="自测", note=TAG)
    BD.record(qf, "A", correct=False, source="自测", note=TAG + " 自评有把握但答错了")
    r = BD.should_use_tool(qf)
    ck("G", "出现过'自评 A 却答错' → use_tool=True（本账最值钱的一条）",
       r["use_tool"] is True, r)
    ck("G", "该 why 明说'自评「有把握」却答错'", "答错" in r["why"], r["why"])

    qok = q("一直答对验证：这类问题")
    for _ in range(3):
        BD.record(qok, "A", correct=True, source="自测", note=TAG)
    r = BD.should_use_tool(qok)
    ck("G", "同类 3 条全 A 且都答对 → False（历史靠得住就别乱改行为）",
       r["use_tool"] is False and r["samples"] == 3, r)
    ck("G", "靠得住时 why 也如实说明看过几条", "3 条" in r["why"], r["why"])

    # ---------------------------------------------------------------- H
    print("\n[H] summary：数字必须与 stats 一致（不许自己另编一套）")
    st = BD.stats(30, path=TMP_PATH)
    s = BD.summary(30, path=TMP_PATH)
    ck("H", "summary 非空且是中文", bool(s.strip())
       and any("\u4e00" <= ch <= "\u9fff" for ch in s), len(s))
    nums = [st["total"], st["by_rating"]["A"], st["by_rating"]["B"], st["by_rating"]["C"],
            st["by_rating"]["?"], st["false_confidence"]]
    miss = [v for v in nums if str(v) not in s]
    ck("H", "stats 里的每个数字都在 summary 里出现", not miss, "%s ｜ 缺 %s" % (s, miss))
    ck("H", "summary 明说 total（%d 条自评）" % st["total"], "%d 条自评" % st["total"] in s, s)
    ck("H", "summary 明说 false_confidence（%d 条自评「有把握」却答错）" % st["false_confidence"],
       "%d 条自评「有把握」却答错了" % st["false_confidence"] in s, s)
    t0 = st["low_conf_topics"][0]
    ck("H", "summary 明说 C 档最集中的话题与其条数（%s %d/%d）"
       % (t0["topic"], t0["c"], t0["samples"]),
       t0["topic"] in s and "%d 条里 %d 条没把握" % (t0["samples"], t0["c"]) in s, s)
    ck("H", "summary 带窗口天数（最近 30 天）", "最近 30 天" in s, s[:16])
    empty = BD.summary(30, path=os.path.join(TMP_DIR, "从来不存在.jsonl"))
    ck("H", "没有数据时如实说没有，不编数字", "没有一条边界记录" in empty, empty)
    ck("H", "没有数据时不出现编造的统计词", "A 档" not in empty and "条自评" not in empty, empty)

    # ---------------------------------------------------------------- I
    print("\n[I] 健壮性：一律不崩，且不依赖 Flask / 主程序")
    ok = True
    try:
        BD.record(None, None, path=TMP_PATH)
        BD.record("", "", path=TMP_PATH)
        BD.record("x", "不认识的档位", correct="不是布尔", path=TMP_PATH)
    except Exception as e:      # noqa: BLE001 — 崩了就是测试失败
        ok = False
        print("     异常：%r" % (e,))
    ck("I", "record(None / 空串 / 怪参数) 不崩", ok)
    ck("I", "record 传怪档位 → 记成 '?'（不凭空造一个档位出来）",
       BD.record("x", "不认识", path=TMP_PATH).get("rating") == "?")
    weird = BD.record("x", "A", correct="不是布尔", path=TMP_PATH)
    ck("I", "record 传怪 correct 不崩，且归一成布尔", isinstance(weird.get("correct"), bool),
       weird.get("correct"))
    ck("I", "stats(days='abc') 不崩（脏参数当作没有数据）",
       BD.stats("abc", path=TMP_PATH)["total"] == 0)
    ck("I", "summary(days='abc') 不崩", isinstance(BD.summary("abc", path=TMP_PATH), str))
    ck("I", "stats 读一个不存在的档案 → 全 0，不崩",
       BD.stats(30, path=os.path.join(TMP_DIR, "没有这个文件.jsonl"))["total"] == 0)
    half = os.path.join(TMP_DIR, "half.jsonl")
    with open(half, "w", encoding="utf-8") as f:
        f.write('{"ts": %f, "question": "小焦的记忆", "rating": "C", "topic": "小焦"}\n'
                % time.time())
        f.write('{"ts": 1.0, "question": "半截')      # 故意写半截（模拟被 kill 时写到一半）
    ck("I", "半截 JSONL → stats 不崩且只数好行", BD.stats(30, path=half)["total"] == 1,
       BD.stats(30, path=half)["total"])
    ck("I", "半截 JSONL → summary 不崩", isinstance(BD.summary(30, path=half), str))
    ck("I", "meta_dir 就是 logs/metacognition",
       BD.meta_dir().replace("\\", "/").endswith("logs/metacognition"), BD.meta_dir())
    import core.metacognition as MC      # noqa: E402 — 验"能独立 import"
    ck("I", "core.metacognition 顶层惰性取函数可用（PEP 562）",
       MC.parse_rating("B") == "B" and MC.route("?") == "use_tool"
       and MC.similarity("北京", "北京") == 1.0)
    ck("I", "取不到的名字如实 AttributeError（不瞎猜一个出来）",
       raises(lambda: MC.根本没有这个名字))
    ck("I", "三个模块独立 import 时**没有**顺带拉起 Flask / 主程序",
       "flask" not in sys.modules and "xiaojiao_app" not in sys.modules,
       sorted(k for k in sys.modules if k in ("flask", "xiaojiao_app")))
    ck("I", "配置容错：cfg() 一定能拿到关键键",
       all(k in MC.cfg() for k in ("enabled", "min_samples", "cross_check_n")), sorted(MC.cfg()))

    # ---------------------------------------------------------------- 清场
    print("\n[清理] 只删带 %s 标记的行（**绝不删除文件**）" % TAG)
    dropped = cleanup_tagged(REAL_PATH)
    leftover = BD._rows(days=None)
    ck("清理", "真实档案里的自测行已清干净（删了 %d 行）" % dropped, dropped > 0, dropped)
    ck("清理", "真实档案文件仍然存在（红线：绝不删文件）", os.path.exists(REAL_PATH))
    ck("清理", "清完之后档案里再没有一行带自测标记",
       all(TAG not in (x.get("note") or "") for x in leftover), len(leftover))
    ck("清理", "原本就有的行一条都没少（不动别人的数据）",
       count_lines(REAL_PATH, TAG) == untagged_before,
       "%d → %d" % (untagged_before, count_lines(REAL_PATH, TAG)))

    print("\n" + "=" * 74)
    total = len(PASS) + len(FAIL)
    print("  通过 %d / 共 %d%s" % (len(PASS), total,
                                   ("（失败：%s）" % ", ".join(FAIL)) if FAIL else ""))
    print("  临时数据目录：%s" % TMP_DIR)
    print("  本脚本从不删除任何文件（只删自己写的、带标记的行）")
    print("=" * 74)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
