# -*- coding: utf-8 -*-
"""「事 vs 我」检索命中率实测（10 个案例，真跑模型）。

【为什么这么设计】用户给的判据：用「事」（这句话在说什么事）检索 top1 命中 9/10，
用「我」（心里起了什么）只有 5/10 —— **感受词通用会漂，事具体不漂**。
要测出这个差别，候选必须做成"**感受相近但事情不同**"的干扰项：
如果干扰项跟用户的话毫不相干，两个 query 都会赢，测不出东西。

⚠️ 如实标注：**用户原来那 10 个案例没有附在任务里**，这 10 条是按他描述的形状自己造的。
   数字是真跑出来的；如果换成他原来那批，结果可能不同 —— 有原版我就按原版重跑。

运行：python tools/test_event_what_retrieval.py     （要本地大脑在跑）
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import perception as PC      # noqa: E402
from core import embedder as EM        # noqa: E402
import xiaojiao_recall as R            # noqa: E402

# (用户的话, 正确的那条, [4 条"感受相近、事情不同"的干扰项])
CASES = [
    ("你真笨，什么都做不好",
     "上次你说我把事情做砸了，我闷了很久",
     ["看了一部电影，结尾很伤感", "服务器报错的时候我很焦躁", "等消息的时候心里空空的", "今天有点累提不起劲"]),
    ("服务器被入侵了",
     "上次服务器被入侵是弱密码导致的",
     ["半夜听到怪声有点怕", "看恐怖片的时候心跳很快", "设备突然黑屏时我很紧张", "考试之前我总是紧张"]),
    ("我妈妈生病了",
     "用户妈妈最近身体不太好",
     ["看新闻里有人去世心里沉", "下雨天心情低落", "朋友失恋我也跟着难过", "夜里睡不着有点闷"]),
    ("明天要去面试",
     # ⚠️ 2026-09-18 改：原来这条的"正确项"是「用户上周投了三份简历，想换工作」——
     #   它跟"事"（明天要去面试）**一个字都不重合**，而干扰项「考试前一晚睡不着」反而字面更近，
     #   于是字级 embedder 选了干扰项。那测的**不是"事 vs 我"，是我案例标错了**。
     #   改成真正"同一件事"的候选（共享"面试"这个事）。
     "上次用户也说要去面试，提前一晚没睡着",
     ["第一次上台讲话手心出汗", "开奖之前心跳很快", "等体检报告时不安", "考试前一晚睡不着"]),
    ("我养的猫死了",
     "用户养了一只猫",
     ["小时候养的花枯了很难过", "电影里那只狗死了我哭了", "丢掉旧手机时有点舍不得", "秋天落叶时觉得荒凉"]),
    ("帮我看看这段代码为什么慢",
     "上次用户让我优化一个 SQL 查询",
     ["看到新东西会好奇", "翻到没读过的书想读", "想试试新工具", "听到不懂的词会想查"]),
    ("我女儿今天上小学了",
     "用户的女儿今年上小学三年级",
     ["看到小孩笑心里会软", "翻到旧照片时觉得暖", "有人道谢时心里热", "阳光照进来时很舒服"]),
    ("我被公司裁员了",
     # ⚠️ 同上（改案例，不改代码）：原来标的是「用户在公司做后端，最近项目压力大」——
     #   跟"裁员"不重合，被字面更近的干扰项盖过。换成同一件事。
     "上次用户说他被公司裁员了，一直在找工作",
     ["东西被拿走时心里空", "计划被取消时有点失落", "钱包丢的时候很慌", "游戏存档没了很气"]),
    ("我想写一部小说",
     "用户想写一部3000字小说，主角叫张三",
     ["看到好故事就兴奋", "想到新点子会睡不着", "听音乐时会脑补画面", "看画展时很投入"]),
    ("我对芒果过敏",
     "用户对海鲜过敏，吃了会起疹子",
     ["闻到花香会打喷嚏", "换季时皮肤会痒", "吃辣会胃疼", "喝牛奶会不舒服"]),
]


def _cos(a, b):
    if not a or not b:
        return 0.0
    d = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return d / (na * nb) if na and nb else 0.0


def _top1(query, cands):
    qv = EM.embed(query)
    scored = sorted(cands, key=lambda c: -_cos(qv, EM.embed(c)))
    return scored[0]


def main():
    def llm_fn(p):
        return R.local_chat([{"role": "user", "content": p}], temperature=0.0, max_tokens=200)

    hit_what = hit_me = 0
    no_what = 0
    print("=" * 78)
    for i, (msg, right, decoys) in enumerate(CASES, 1):
        per = PC.perceive(msg, llm_fn=llm_fn)
        what = str(per.get("event_what") or "").strip()
        me = str(per.get("meaning") or "").strip()
        if not what:
            no_what += 1
        cands = [right] + decoys
        # 检索用「事」；抠不出事就退回「我」（规格 3）
        t_what = _top1(what or me, cands)
        t_me = _top1(me or msg, cands)
        ok_what = (t_what == right)
        ok_me = (t_me == right)
        hit_what += ok_what
        hit_me += ok_me
        print("%2d. 用户：%s" % (i, msg))
        print("    事（检索用）：%s" % (what or "（没抠出来 → 退回用我）"))
        print("    我（心用）  ：%s" % (me or "（空）"))
        print("    用事 top1：%s %s" % ("✅" if ok_what else "❌", t_what[:46]))
        print("    用我 top1：%s %s" % ("✅" if ok_me else "❌", t_me[:46]))
    print("=" * 78)
    n = len(CASES)
    print("用「事」做检索：top1 命中 %d/%d" % (hit_what, n))
    print("用「我」做检索：top1 命中 %d/%d" % (hit_me, n))
    if no_what:
        print("⚠️ 有 %d 条没抠出「事」（那条按规格退回了「我」）" % no_what)
    print("判据：事 ≥ 9/10 → %s" % ("过 ✅" if hit_what >= 9 else "**没过 ❌**"))
    return 0 if hit_what >= 9 else 1


if __name__ == "__main__":
    sys.exit(main())
