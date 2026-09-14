# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 创造性（模块 10.5）

【这段为什么这么设计】
    4B 模型问它十个点子，十个都长一个样 —— 因为它默认走「训练里最常见的那条路」。
    这不是它懒，是它**没有能力主动换个角度看**：把温度调高只是让同一句话的用词
    抖一抖，视角还是那一个，所以「多样性」只体现在措辞上，不体现在思路上。
    真正的创造力来自两件事，而这两件事**不需要智力，只需要结构**：
      ① 换**视角** —— 同一件事，孩子 / 银行家 / 外星人眼里的重点完全不同；
      ② 换**算子** —— 反转、嫁接、夸张……强行把思路推出常规路径之外。
    结构属于载体，不属于模型。所以本模块维护三张表：
        PERSPECTIVES  视角表（≥10 个，每个视角带「它会先问的 3 个问题」）
        OPERATORS     算子表（≥11 个，每个算子带「怎么用」和一个中文小例子）
        SEED_POOL     种子池（「换个角度想」用的短中文短语）
    模型每次仍然只做**一小步**：站在这个视角、用这个算子、就着这条扰动，
    回答这一个问题。十条点子 = 十次一小步，而不是「请给我十个点子」。

【为什么必须可复现（种子绝不用内置 hash()）】
    如果「换十个角度」每次都不一样，这套能力就**没法调试、没法复现、没法对比**：
    用户说「上次那个角度挺好，再来一次」，系统却给不出同一个。
    所以本模块所有随机一律走 `random.Random(显式种子)`，
    种子由 `zlib.crc32`（纯算法、无盐、标准库）算出，而**不是**内置 `hash()` ——
    CPython 对 str 的 hash 带进程级随机盐（PYTHONHASHSEED），换个进程就变，
    自测会表现为「时好时坏的失败」，这是最难查的一类 bug（因为它有时是对的）。
    去掉这条：同一问题在不同进程里给出不同的视角与扰动，「再来一次」永远复现不出来。

【去掉这个模块会怎样】
    ① 没有视角表 → 又退回「给我 10 个点子」，10 个都是同一个口吻；
    ② 没有算子表 → 模型只会在原方案上换措辞，永远不动结构；
    ③ 没有显式种子 → 无法复现、无法 A/B、无法解释「这次为什么这么想」，
       载体层就从「可观察的系统」退化成一个不透明的黑箱。

【数据落盘（一律在 logs/boost/ 下，logs/ 已被 .gitignore 忽略，不脏仓库）】
    logs/boost/creative/samples.jsonl   每次采样/算子的明细（append-only，越用越大）
    logs/boost/creative_uses.json       每个视角/算子被用过几次（快路径计数）
    logs/boost/boost.jsonl              事件流水（由公共层 note() 统一写）
    为什么要两份：jsonl 是**证据**（可回溯、可分析），json 是**快路径**
    （统计时不用扫全表）。去掉 jsonl 只剩计数，就再也回答不了「它到底怎么想的」；
    去掉 json 只剩明细，每次统计都要扫一个不断变长的文件。

【绝不删除任何文件】
    本模块只用「追加 / 覆盖写」，全程没有 os.remove / unlink / rmtree。
    连带后果：统计文件永远是覆盖写（不搞 tmp+rename —— Windows 上 rename 覆盖
    语义接近删旧文件），写坏了下一次写会覆盖回来。
"""
import math
import os
import random
import zlib

# 公共工具一律从包根拿，绝不在本模块重写一份 —— 重写的必然结局是
# 「视角采样认一种去重口径、别的模块认另一种」，同一句话在两个模块里两种结果。
# 为什么没取 has_any：本模块判断「是不是决策/情绪类问题」时要的不是布尔值，
# 而是**命中的那个词**（它要写进 why 与流水当证据），所以直接用 hits。
# 取一个用不上的名字，只会让下一个读代码的人以为这里真的在用它。
from . import boost_dir, boost_path, norm, cjk_count, hits, now, note
from . import append_jsonl, read_jsonl, read_json, write_json

# ------------------------------------------------------------------ 视角表
# 为什么是「视角 + 3 个问题」而不是只给一个视角名：
# 只给「工程师视角」这四个字，模型会把它理解成「用工程词汇把原答案包装一遍」；
# 给出「它会先问什么」，视角才**真的**变成一种注意力分配 —— 模型有了具体落点。
# 去掉 questions：视角会退化成形容词，采样出来的 n 条又会长得一样。
PERSPECTIVES = [
    {
        "id": "child", "name": "孩子",
        "lens": "只关心「好不好玩、我能不能自己搞定、会不会挨骂」，不关心任何大道理。",
        "questions": [
            "这个东西我第一眼想拿它干什么？",
            "我要不要大人帮忙才能玩得起来？",
            "它会不会让我觉得自己很笨？",
        ],
    },
    {
        "id": "engineer", "name": "工程师",
        "lens": "只关心「它到底怎么工作、哪里会坏、边界在什么条件下被越过」。",
        "questions": [
            "它的输入和输出到底是什么？",
            "哪个零件最可能先坏？",
            "在什么条件下它会彻底不工作？",
        ],
    },
    {
        "id": "poet", "name": "诗人",
        "lens": "只关心「它让人心里升起什么感觉、它像什么」，不关心可行不可行。",
        "questions": [
            "它像什么？（找一个具体的比喻，不要抽象词）",
            "它让人心里升起什么感觉？",
            "如果只准用一个词形容它，是哪个词？",
        ],
    },
    {
        "id": "pm", "name": "产品经理",
        "lens": "只关心「谁真的会用、值不值得做、拿什么数字说明它成了」。",
        "questions": [
            "到底是谁在用，他现在的土办法是什么？",
            "做完之后，用什么数字说明它成了？",
            "不做它，会损失掉什么？",
        ],
    },
    {
        "id": "hacker", "name": "黑客",
        "lens": "只关心「最省力的歪路在哪、哪儿没设防、怎么用最小动作拿最大效果」。",
        "questions": [
            "如果我要偷懒，最省事的那条歪路是什么？",
            "这个系统哪一扇门没锁？",
            "怎么用最小的动作拿到最大的效果？",
        ],
    },
    {
        "id": "elder", "name": "老人",
        "lens": "只关心「这件事搁十年二十年看还重要吗、以前的人是怎么处理的」。",
        "questions": [
            "这件事放到十年后回头看，还重要吗？",
            "我年轻的时候遇到这种事，是怎么处理的？",
            "有没有一种更慢但更稳的做法？",
        ],
    },
    {
        "id": "alien", "name": "外星人",
        "lens": "完全不懂人类的前提，一切「理所当然」在他眼里都是怪事。",
        "questions": [
            "如果我从没见过这件事，我会把它理解成什么？",
            "这里面哪个环节人类觉得理所当然，其实非常奇怪？",
            "如果这里的物理规则不同，它会变成什么样？",
        ],
    },
    {
        "id": "banker", "name": "银行家",
        "lens": "只关心「投入多少、回来多少、最坏赔多少、多久回本」。",
        "questions": [
            "这件事的投入和产出各是什么？",
            "最坏情况会赔掉什么？",
            "多久能回本？",
        ],
    },
    {
        "id": "teacher", "name": "老师",
        "lens": "只关心「怎么讲才能让人真的懂、学习者会卡在哪一步」。",
        "questions": [
            "如果要把这件事讲给一个外行，第一步讲什么？",
            "学习者最可能卡在哪一步？",
            "用什么例子能让人一下就懂？",
        ],
    },
    {
        "id": "doctor", "name": "医生",
        "lens": "只关心「症状是什么、病因藏在哪、如果只能先治一处先治哪」。",
        "questions": [
            "现在能观察到的症状是什么？",
            "真正的病因可能在哪个看不见的地方？",
            "如果只能先治一处，先治哪里？",
        ],
    },
    {
        "id": "chef", "name": "厨师",
        "lens": "只关心「火候在哪一步、顺序能不能换、原料本身够不够好」。",
        "questions": [
            "这件事的火候在哪一步（早了晚了都不行）？",
            "顺序能不能换？换了会怎样？",
            "原料本身够不够好？",
        ],
    },
    {
        "id": "detective", "name": "侦探",
        "lens": "只关心「手里真正的证据是什么、哪两个说法对不上、谁从现状里获益」。",
        "questions": [
            "我手里真正的证据是什么（不是猜测）？",
            "哪两个说法互相矛盾？",
            "谁从现状里获利？",
        ],
    },
]

# ------------------------------------------------------------------ 算子表
# 为什么算子要配「怎么用 + 中文小例子」：
# 「反转」这种两字名字，模型会自己解释成「说反话」；
# 而一句中文小例子能立刻把它钉在正确语义上（例子比解释省 token 且更准）。
# 去掉 example：同一个算子在不同问题下会被理解成不同的东西，采样不可比。
OPERATORS = [
    {"id": "invert", "name": "反转", "name_en": "Invert",
     "how": "把默认做法整个反过来：原来要加的改成减，原来先做的挪到最后，原来追求 A 的改成避免 A。",
     "example": "让用户填 20 项表格 → 改成只填 1 项，其余由系统猜。"},
    {"id": "graft", "name": "嫁接", "name_en": "Graft",
     "how": "把另一个完全不相干领域里已经成熟的做法，整棵搬过来套在这件事上。",
     "example": "把医院急诊的分诊制度搬到客服工单上：按严重度排队，不按到达顺序。"},
    {"id": "exaggerate", "name": "夸张", "name_en": "Exaggerate",
     "how": "把某个变量放大到荒谬的程度，看它在什么条件下才成立 —— 极端处往往藏着问题的本质。",
     "example": "如果有 1000 万个人同时用，这个功能会长成什么样？"},
    {"id": "shrink", "name": "缩小", "name_en": "Shrink",
     "how": "把对象瘦到极致：只能留一样东西的话留哪样？被砍掉的先记下来，它们可能就是噪音。",
     "example": "只能保留一个按钮，留哪个？"},
    {"id": "shift", "name": "移位", "name_en": "Shift",
     "how": "换场景、换时间、换使用者，同一个东西搬到别处再看：不适用的部分往往就是冗余。",
     "example": "把写周报搬到电梯里 30 秒说完的场景。"},
    {"id": "replace", "name": "替换", "name_en": "Replace",
     "how": "把其中一个部件换成完全不同的东西，其余全部不动，只看接缝处会冒出什么。",
     "example": "把人工客服换成一只鹦鹉，或者换成一段录音。"},
    {"id": "combine", "name": "组合", "name_en": "Combine",
     "how": "把两个本来没关系的东西硬拼在一起，然后只盯着拼缝 —— 新东西都长在缝上。",
     "example": "闹钟 + 社交 = 一群互相叫醒的早起的人。"},
    {"id": "borrow", "name": "借形", "name_en": "Borrow Form",
     "how": "只借形状和骨架、不借内容：照抄一个已经验证过的结构，把里面的东西换掉。",
     "example": "照抄菜谱的结构（材料 / 步骤 / 火候 / 失败了怎么救）写一份工作方案。"},
    {"id": "reduce_dim", "name": "降维", "name_en": "Reduce Dimension",
     "how": "把多维的选择压成一个数或一个标准，强迫排序 —— 压不下去，说明你还没想清最在意什么。",
     "example": "把要不要买压成一个数：三个月之后我的后悔概率。"},
    {"id": "raise_dim", "name": "升维", "name_en": "Raise Dimension",
     "how": "给问题加一个原来没有的维度（时间 / 谁来做 / 代价 / 可逆性），一维选择就变成多维设计。",
     "example": "吃什么加一维「和谁吃」，答案会完全不同。"},
    {"id": "random_constraint", "name": "随机约束", "name_en": "Random Constraint",
     "how": "随机加一条硬限制，堵死常规解，逼出非常规解 —— 限制越具体，产出越具体。",
     "example": "不许用键盘，只能说话 → 逼出一套全新的输入方式。"},
    {"id": "backcast", "name": "倒推", "name_en": "Backcast",
     "how": "从「已经成功 / 已经失败」的结果往回写步骤，倒推比正推更容易发现缺的那一环。",
     "example": "假设半年后已经成了，回过头写这半年每周做了什么。"},
]

# ------------------------------------------------------------------ 扰动池
# 为什么每个算子要挂 ≥4 条扰动，而不是一条：
# 只有一条扰动的话，「同一个算子换不同种子」给出的是同一个结果，
# 算子树就等于死了 —— 用户第二次用「反转」拿到的还是同一句，
# 而这正是本模块要消灭的「十个点子十个一样」。
# 去掉扰动池：算子表退化成 12 条固定的提示词模板。
OPERATOR_TWISTS = {
    "invert": [
        "把「必须做到」的那一条，改成「必须避免」的那一条",
        "把整条顺序倒过来做：先定最后一步，再从结果往回推第一步",
        "把对象反过来：本来是给人用的，改成给机器、或者给十年后的自己用",
        "把评价标准反过来：不比谁更好，比谁先坏",
        "把角色反过来：原来被服务的那一方，现在让它来提供服务",
    ],
    "graft": [
        "从一个最不像的行业里借（殡葬 / 婚庆 / 屠宰 / 消防，挑一个）",
        "从自然界的器官里借（根 / 翅膀 / 壳 / 鳃，挑一个）",
        "从一百年前的人处理同类事情的老办法里借",
        "从游戏机制里借（存档 / 复活 / 血条 / 副本，挑一个）",
        "从你每天都在用的一件小工具里借",
    ],
    "exaggerate": [
        "把规模放大一百万倍",
        "把时间压缩到 1 秒之内必须完成",
        "把要求提到必须 100% 不出错",
        "把预算放大到无限",
        "把用户放大到全世界每个人都在用",
    ],
    "shrink": [
        "砍到只剩一个功能",
        "砍到只剩一句话或者一张图",
        "砍到只剩 1 秒钟的使用时间",
        "砍到零预算、零新增人力",
        "砍到只有一个维护它的人",
    ],
    "shift": [
        "搬到一百年前",
        "搬到五十年后",
        "搬到一个完全没有网络的地方",
        "搬到半夜三点（人最没有耐心的时候）",
        "搬到竞争对手手里",
    ],
    "replace": [
        "把「人」换成「机器」",
        "把「文字」换成「声音」",
        "把「钱」换成「时间」",
        "把「免费」换成「很贵」",
        "把「专家」换成「完全的外行」",
    ],
    "combine": [
        "和它的反面拼在一起",
        "和一件完全无关的日用品拼在一起",
        "把你最讨厌的那件事拼进来",
        "和季节 / 天气拼在一起",
        "和「一次性、用完就扔」拼在一起",
    ],
    "borrow": [
        "借菜谱的结构",
        "借说明书的结构",
        "借病历的结构",
        "借剧本的结构（分幕 / 冲突 / 转折）",
        "借体检报告的结构（指标 + 正常范围 + 建议）",
    ],
    "reduce_dim": [
        "压成一个 0~10 的分",
        "压成是 / 否两个字",
        "压成「一年之后它还重要吗」",
        "压成只比一个指标（成本 / 速度 / 快乐，挑一个）",
        "压成一句话，多一个字都不许",
    ],
    "raise_dim": [
        "加一维时间：不同阶段各做哪一半",
        "加一维谁来用：换个人用，答案会不会翻过来",
        "加一维做错的代价",
        "加一维可逆性：能不能撤回",
        "加一维十年后",
    ],
    "random_constraint": [
        "不许花钱",
        "不许联网",
        "不许说话（只能写、或者只能画）",
        "只给你半天时间",
        "必须让一个十岁小孩也能独立完成",
        "必须能写在一张 A4 纸上",
    ],
    "backcast": [
        "假设一年后已经彻底失败，回看是哪一步崩的",
        "从终点倒着写三步",
        "假装已经做完了，先写复盘",
        "从最后一天倒回到今天该做什么",
        "先写庆功宴上的那段发言，再倒推做了什么才配得上它",
    ],
}

# 某算子万一没有扰动池（有人只加了算子、忘了加扰动）时的兜底池。
# 为什么宁可留一个通用兜底也不抛异常：加算子的人只是想加个提示词模板，
# 不该因为漏配扰动就让整个对话崩掉；兜底能让它降级可用，且一看就知道没配。
_TWIST_FALLBACK = (
    "把它整体反过来做",
    "换一个完全不同的对象",
    "把它缩小到只剩一样东西",
    "给它加一条硬限制",
)

# ------------------------------------------------------------------ 种子池
# 「换个角度想」用的短中文短语。为什么是短句而不是「随机数 42」：
# 种子要能**直接塞进提示词**并被人读懂；一个抽象数字对模型是噪音，
# 一句「把它当成人来设计」却能立刻改变它的注意力。
# 去掉种子池：random_seeds 只能返回数字，用户看到的是一串没有含义的编号。
SEED_POOL = [
    "把它当成人来设计",
    "假设预算为 0",
    "假设预算无限",
    "把它反过来做",
    "只保留一个功能",
    "让一个十岁小孩来用",
    "假设它要存在一千年",
    "搬到一百年前去解决",
    "把它当成一场游戏",
    "把它当成一种仪式",
    "去掉它最大的那个部件",
    "让最懒的那个人来用",
    "让最较真的人来检查",
    "把它写在一张明信片上",
    "假设只有一次机会",
    "假设可以无限重来",
    "先做最小的一半试试",
    "把它拆成两个人的活",
    "把它交给一个完全不懂的人",
    "用一个完全无关的行业来类比",
]
# 决策类问题专用的补充种子：决策的难处不在「想到什么」，而在「敢不敢选」，
# 所以这几条直接冲「选择」本身去。去掉它们：决策类问题拿到的种子跟闲聊一样泛。
_DECISION_POOL = [
    "先假设已经选了它，看哪里最难受",
    "假设必须今天决定，砍掉哪个选项",
    "假设三年后回头看，你希望当时怎么选",
    "把两个选项各自的最坏一天写出来比一比",
    "假设你有一票否决权，你会否决哪一个",
    "假设这个决定可以撤回，你还会犹豫吗",
]
# 情绪类问题专用的补充种子：人在情绪里要的不是方案，而是「先被理解」。
# 去掉它们：用户说「我最近很烦」，系统会一本正经地给他做一份 SWOT 分析。
_EMOTION_POOL = [
    "先把它当成一件可以放一放的事",
    "先假设这件事有一半不是你的责任",
    "先问：如果是我最好的朋友遇到，我会怎么劝他",
    "先把它说成一句抱怨，再把它说成一句请求",
    "先找出这件事里你唯一能控制的那一小块",
    "先假设最坏的结果已经发生了，然后看还剩什么",
]
# 命中这些词就说明是「要选一个」的问题（判据词表，不在函数里写死字符串）
_DECISION_WORDS = ("要不要", "该不该", "值不值", "划算", "二选一",
                   "纠结", "怎么选", "选一个", "决定")
# 命中这些词就说明是「心里不好受」的问题
_EMOTION_WORDS = ("烦", "累", "焦虑", "难受", "郁闷", "崩溃", "压力", "委屈",
                  "生气", "难过", "害怕", "慌")

# 通用种子（question 为空 / None 时用）。为什么给一个固定常量而不是随机：
# 用户没给问题，也应该拿到一批**稳定**的通用角度 —— 每次都不一样的话，
# 空输入就成了唯一不可复现的分支，自测无法覆盖它。
_GENERIC_SEED = 0x5A17


# ------------------------------------------------------------------ 稳定随机
def _stable_hash(text):
    """把任意文本映射成一个跨进程稳定的 32 位整数（本模块唯一的随机来源）。

    为什么用 `zlib.crc32` 而不是内置 `hash()`：CPython 对 str 的 hash 默认带
    **进程级随机盐**（PYTHONHASHSEED），同一个问题在两个进程里得到不同的数，
    于是「同一问题同一批视角」这条承诺直接失效，自测会呈现「时好时坏」的失败 ——
    这是最难查的一类 bug，因为它有时是对的。crc32 是纯算法、无盐、标准库。
    去掉它改用 hash()：用户说「上次那个角度再来一次」，系统永远给不出同一个。
    """
    try:
        return zlib.crc32(norm(text).encode("utf-8")) & 0xFFFFFFFF
    except Exception:      # noqa: silent-ok — 编码都失败（极端脏输入）时退化为 0：宁可全取第一批也不能抛
        return 0


def _stride(size):
    """给「轮转取样」挑一个与 size 互质的步长，保证绕一圈不重不漏。

    为什么必须互质：步长与 size 有公因数时，轮转只能覆盖 size/gcd 个位置 ——
    视角表 12 个，步长取 4 就只能取到 3 个不同视角，调用方要 5 条时会拿到重复的
    人（表面 5 条，其实是 3 条重复）。去掉它（步长写死成 5）：
    一旦有人往视角表里再加几个视角（例如加到 15 个），互质性被破坏，
    采样会悄悄退化成「重复的视角」，而且不报错。
    """
    if size <= 2:
        return 1
    for s in range(3, size + 1):
        if math.gcd(s, size) == 1:
            return s
    return 1


def _rotate(seq, offset, n, stride=None):
    """从 `seq` 里按「起点 + 互质步长」取出 n 个**互不相同**的元素。

    为什么不直接 `seq[:n]`：那样每个问题拿到的都是同一批视角，
    「不同问题取到不同视角」这条要求等于没做 —— 用户很快会发现
    「你翻来覆去就这几个人」。去掉轮转：视角表就成了摆设，退化成固定前 n 项。
    """
    size = len(seq)
    if size <= 0:
        return []
    try:
        nn = int(n)
    except Exception:      # noqa: silent-ok — n 是 None / 脏值时退回取 1 个，绝不因为参数脏就崩
        nn = 1
    nn = max(1, min(nn, size))
    st = int(stride) if stride else _stride(size)
    return [seq[(int(offset) + i * st) % size] for i in range(nn)]


def _count(n, default):
    """把任意输入转成一个整数（n 传 None / 空串 / 「三」都不抛）。

    为什么单独抽出来：本模块有 4 个函数都收 `n`，如果各自写 `int(n)`，
    那么「n=None 时谁崩谁不崩」就成了随机事件 —— 而载体层的规矩是
    **任何函数都不许因为输入脏而抛**。去掉它：random_seeds(n=None) 直接 TypeError。
    """
    try:
        return int(n)
    except Exception:      # noqa: silent-ok — 脏参数一律退回默认值，这比抛异常有用得多
        return int(default)


# ------------------------------------------------------------------ 落盘
def _samples_path():
    """采样明细的落盘路径：`logs/boost/creative/samples.jsonl`。

    为什么单独开一个子目录（而不是平铺在 logs/boost/ 下）：
    creative 的明细会随使用量不断变长，和别的模块的冻结快照混在一起时，
    清理与排查都会误伤；分目录是唯一能长期共处的办法。
    去掉 boost_dir() 改用 `__file__` 自己拼：早晚有人拼错一级，
    数据会散到仓库别处 —— 排查「怎么没存上」时你会发现它其实存在另一个目录。
    """
    return os.path.join(boost_dir("creative"), "samples.jsonl")


def _uses_path():
    """用量计数的落盘路径：`logs/boost/creative_uses.json`（快路径）。"""
    return boost_path("creative_uses.json")


def _ledger(kind, **kw):
    """把一次采样 / 算子调用追加进明细流水（append-only，越用越大）。

    为什么要留明细而不只留计数：本模块的卖点是「越用越大」，
    而「变大」必须能被**看见**，否则没人知道视角表到底有没有被用起来。
    同时它是唯一能回答「这次为什么是这几个视角」的东西。
    为什么写不进去也不抛：流水只是证据，不是功能；
    为了记一条日志让用户的对话失败，是明显不划算的交换。
    """
    rec = {"ts": now(), "kind": norm(kind)}
    try:
        rec.update(kw)
    except Exception:      # noqa: silent-ok — kw 里混进不可序列化对象也不能崩
        pass
    try:
        append_jsonl(_samples_path(), rec)
    except Exception:      # noqa: silent-ok — 流水写不进去绝不影响功能
        pass
    return rec


def _bump(kind, keys, inc=1):
    """给用法计数 +inc（keys 可以是单个 id，也可以是 id 列表）。

    为什么用「读小 JSON → 改 → 覆盖写」而不是自己维护内存计数：
    内存计数一重启就归零，「越用越大」就成了假话；写盘才能跨会话累加。
    为什么一次调用只写一次盘：每次采样要记 5 个视角，逐条写盘就是 5 次
    读 + 写同一个文件 —— 在对话热路径上这是白白浪费的时间。
    去掉它（不计数）：stats() 只能报告「表里有多少条」，报告不了「用过没有」，
    而后者才是判断载体有没有真的在工作。
    """
    try:
        ks = [norm(k) for k in (keys if isinstance(keys, (list, tuple, set)) else [keys])]
        ks = [k for k in ks if k]
        if not ks:
            return False
        p = _uses_path()
        data = read_json(p, {})
        if not isinstance(data, dict):
            data = {}
        bucket = data.get(norm(kind))
        if not isinstance(bucket, dict):
            bucket = {}
        for k in ks:
            bucket[k] = int(bucket.get(k) or 0) + int(inc)
        data[norm(kind)] = bucket
        data["last_used"] = now()
        write_json(p, data)
        return True
    except Exception:      # noqa: silent-ok — 统计写不上只是「少记一次用量」，绝不能让生成失败
        return False


# ------------------------------------------------------------------ 视角采样
def resample(question, n=5):
    """多视角采样：同一个问题，**稳定地**生出 n 个真正不同的角度。

    【两层稳定哈希，缺一不可】
      ① 选哪些视角：起点 = crc32(问题) % 视角总数，再按互质步长轮转取 n 个。
         这样「同一问题同一批」（可复现），且**不同问题取到不同的人**
         （不会永远只取前 n 个）。
      ② 每个视角先问哪一句：种子 = crc32(问题 + "|" + 视角 id)。
         视角固定，但挂着的 3 个问题要轮着问，否则「工程师」永远问同一句，
         采样在第二层上又退化成固定输出。
    去掉①：所有问题都拿到前 n 个视角；去掉②：每个视角永远只问第一句。

    【为什么 n 要先 clamp 再采样】
      调用方按 n 条渲染、按 n 条评估，条数少一条就会串位；
      所以 n 先夹到 [1, len(PERSPECTIVES)]，再由 _rotate 保证互不相同。
      去掉 clamp：n=50 时会把 12 个视角重复铺 4 遍，用户看到一堆重复的人，
      「多视角」这个卖点当场变成笑话。

    返回 list[dict]，每条含 perspective / name / lens / focus / prompt 五个键。
    question 传 None / 空串 / 超长串都不抛。
    """
    t = norm(question)
    size = len(PERSPECTIVES)
    nn = max(1, min(_count(n, 5), size))
    picks = _rotate(PERSPECTIVES, _stable_hash(t) % max(1, size), nn)

    # 问题太短时补一句「先把隐含目标补出来」：短问题（「怎么做面」）留给模型的
    # 空间太大，它会直接给一段通用答案。这一句是载体替它补的上下文。
    # 去掉它：所有短问题的多视角采样都会收敛成差不多的一段百科式回答。
    short_hint = ""
    if t and cjk_count(t) < 4:
        short_hint = ("\n【补充】你给的问题很短，请先把这个问题的隐含目标写出来"
                      "（你猜他真正想要什么），再回答。\n")

    out = []
    for p in picks:
        qs = p.get("questions") or [""]
        focus = qs[_stable_hash("%s|%s" % (t, p.get("id"))) % len(qs)]
        prompt = (
            "请**站在「%s」这个视角**回答下面的问题。\n\n"
            "【这个视角在看什么】%s\n"
            "【这个视角会先问】%s\n\n"
            "【问题】%s\n"
            "%s\n"
            "【回答要求】\n"
            "1. 只按这个视角的关注点回答，**不要写「综合来看」** —— "
            "那是把所有视角糊在一起，等于没有视角。\n"
            "2. 先正面回答上面那个问题，再给出具体做法或具体结论。\n"
            "3. 最后必须单独写一行「这个视角牺牲了什么：」，写明为了坚持这个视角，"
            "你丢掉了哪些别的视角会在意的东西。\n"
            "4. 如果这件事在这个视角下根本看不见，就直接说「这个视角看不到它」，"
            "并说清为什么。\n"
        ) % (p.get("name"), p.get("lens"), focus,
             t or "（你还没有把问题告诉我）", short_hint)
        out.append({
            "perspective": p.get("id"),
            "name": p.get("name"),
            "lens": p.get("lens"),
            "focus": focus,
            "prompt": prompt,
        })

    ids = [p.get("id") for p in picks]
    note("resample", chars=len(t), n=len(out), perspectives=ids)
    _bump("perspectives", ids)
    _ledger("resample", question=t[:200], n=len(out), perspectives=ids)
    return out


# ------------------------------------------------------------------ 算子 + 扰动
def _find_operator(op_id):
    """按 id / 中文名 / 英文名找算子（都找不到返回 None）。

    为什么允许按中文名和英文名找：调用方有两类 —— 代码里写 id 的，
    和从用户话里抠出「用夸张算子试试」的人。只认 id 的话，
    后一类必须自己维护一张中英对照表，早晚和这里不一致。
    去掉多路匹配：用户说「用一下嫁接」，系统会告诉他「没有这个算子」。
    """
    key = norm(op_id).lower()
    if not key:
        return None
    for op in OPERATORS:
        if key in (norm(op.get("id")).lower(), norm(op.get("name")).lower(),
                   norm(op.get("name_en")).lower()):
            return op
    return None


def apply_operator(op_id, seed=""):
    """把算子 + 一次随机扰动，拼成一段可直接交给模型的提示词。

    【为什么「算子」必须配「随机扰动」才完整】
      单说「用反转算子」，模型会挑最容易的那条反转路径（还是常规解）；
      加上一条**载体指定的**扰动（比如「把顺序整条倒过来做」），
      它就被逼到具体且非常规的那一格上。所以算子给方向、扰动给定点。
      去掉扰动：同一个算子的所有调用收敛成同一个答案。

    【为什么完全可复现】
      随机源是 `random.Random(norm(seed))` —— str 种子在 CPython 里走 sha512
      派生，**跨进程稳定**；绝不用内置 hash()（带进程盐，换个进程就变）。
      因此 `apply_operator("invert", seed="abc")` 两次调用、乃至两个不同的
      Python 进程，返回的 dict 用 `==` 比较都完全相等。
      去掉这条：自测会时过时不过，用户的「再来一次」也复现不出上次的扰动。

    【op_id 不存在时怎么办：退化到默认算子，而不是返回 {"ok": False}】
      两种做法规格都允许，这里选**退化**：调用方（渲染层）拿到的一定是一个
      形状完整、`prompt` 可用的 dict，不需要到处写「if not res.get('ok')」。
      返回里带 `fallback=True` 与 `requested=<原样输入>` 作为如实标记，
      所以「用错算子」照样能在日志里查出来，而不是被悄悄吞掉。
      去掉退化（改成返回 ok=False）：每一个调用点都得自己兜底，
      漏一个就会把 None 当成提示词发给模型 —— 那才是真正的静默失败。

    【prompt 里为什么是占位符，而不是真的原问题】
      规格给的签名是 `apply_operator(op_id, seed="")` —— 没有 question 参数。
      所以「原问题」只能以 `【问题】（把你要解决的问题原样粘到这里）` 的形式留位，
      由调用方拿到后自行填入（或直接把 prompt 追加在自己的问题前面）。
      去掉这个占位符：调用方得自己拼提示词，算子库又退化成「一句说明」。

    每次调用都会 `note("apply_operator", op=..., seed=...)` 记一条流水。
    """
    t_seed = norm(seed)
    op = _find_operator(op_id)
    fallback = op is None
    if fallback:
        op = _find_operator("invert")
    op = op or {"id": "invert", "name": "反转", "name_en": "Invert",
                "how": "把默认做法整个反过来。", "example": ""}

    pool = OPERATOR_TWISTS.get(norm(op.get("id"))) or list(_TWIST_FALLBACK)
    # 为什么只用「一次取样」：保证同一 seed 的随机数消耗序列稳定，
    # 将来即使有人在前面插一次取样，也不会让老 seed 的结果集体漂移。
    # 去掉这个克制：扰动会在改了无关代码之后悄悄变化，历史日志就无法解释。
    try:
        rng = random.Random(t_seed)
        twist = pool[rng.randrange(len(pool))]
    except Exception:      # noqa: silent-ok — 极端脏输入让取样失败时取首条扰动：宁可退化也不能抛
        twist = pool[0]

    prompt = (
        "请用「%s（%s）」这个创意算子来处理下面的问题。\n\n"
        "【这个算子怎么用】%s\n"
        "【一个例子】%s\n\n"
        "【本次扰动（载体随机指定，必须采纳）】%s\n"
        "  注意：扰动是本次生成的硬设定，**不许换成别的说法**，也不许只把它当建议。\n\n"
        "【问题】\n"
        "（把你要解决的问题原样粘到这里）\n\n"
        "【输出要求】\n"
        "1. 先写一行「我采纳的扰动是：」并把扰动抄一遍，确认没有跑偏。\n"
        "2. 然后给出被这个算子变形之后的方案 / 想法，3~5 条，每条一句话，要具体到能动手。\n"
        "3. 最后写一行「常规做法长什么样：」，把不加算子时会给出的那个平庸答案写出来，用来对比。\n"
        "4. 不要写「综上所述」这类总结废话。\n"
    ) % (op.get("name"), op.get("name_en"), op.get("how"), op.get("example"),
         twist)

    res = {
        "op": norm(op.get("id")),
        "name": op.get("name"),
        "name_en": op.get("name_en"),
        "seed": t_seed,
        "how": op.get("how"),
        "twist": twist,
        "prompt": prompt,
    }
    if fallback:
        # 只在退化时加这两个键：正常路径保持规格里那个最小形状，
        # 退化路径留下「你传错了」的证据。去掉它们，用错算子就无声无息了。
        res["fallback"] = True
        res["requested"] = norm(op_id)

    note("apply_operator", op=norm(op_id), seed=t_seed, fallback=fallback)
    _bump("operators", res["op"])
    _ledger("operator", op=res["op"], seed=t_seed, twist=twist, fallback=fallback)
    return res


# ------------------------------------------------------------------ 随机种子
def _flavor(question):
    """判断问题属于哪一类「味道」，以便挑对应的种子池。返回 (味道, 命中的词)。

    为什么要分味道：决策类问题和情绪类问题的「换个角度」根本不是一回事 ——
    前者缺的是敢下手的角度，后者缺的是先被理解的角度。用同一池种子打天下，
    用户说「我最近特别烦」会拿到「假设预算为 0」这种驴唇不对马嘴的角度。
    去掉它：random_seeds 退化成一个与问题内容无关的固定池。
    """
    t = norm(question)
    got = hits(t, _DECISION_WORDS)
    if got:
        return "decision", got[0]
    got = hits(t, _EMOTION_WORDS)
    if got:
        return "emotion", got[0]
    return "general", ""


def random_seeds(question, n=3):
    """给「换个角度想」用的一批随机种子（短中文短语，n 夹在 [1,8]）。

    【为什么必须确定性】
      同一 question → 同一结果（跨进程稳定）。种子是给用户看的：
      他看完觉得「第三个角度不错」，回头必须能再拿到同一批；
      每次都不同的话，这批种子就成了只能看一次的一次性噪音。
      随机源是 `random.Random(crc32(问题))`，绝不用内置 hash()（进程级盐，不可复现）。

    【为什么要先从池子里挑味道再抽样】
      通用池管「想得开」，决策池管「敢下手」，情绪池管「先被理解」。
      去掉按味道分池：给情绪类问题开出的是冷静的方案角度，
      用户会觉得「它根本没听懂我在说什么」。

    question=None / 空串 → 用固定常量做种子，给出**稳定的**通用种子，不抛。
    n=8 时池子至少 20 条（通用池），所以永远取得到 8 条互不相同的结果。
    去掉 n 的 clamp：n=0 会返回空列表（调用方以为「没角度可用」），
    n=999 则 sample 要的比池子多，直接抛异常。
    """
    t = norm(question)
    nn = max(1, min(_count(n, 3), 8))

    flavor, matched = ("generic", "") if not t else _flavor(t)
    pool = list(SEED_POOL)
    if flavor == "decision":
        pool += _DECISION_POOL
    elif flavor == "emotion":
        pool += _EMOTION_POOL

    base = _stable_hash(t) if t else _GENERIC_SEED
    try:
        rng = random.Random(base)
        got = rng.sample(pool, nn)
    except Exception:      # noqa: silent-ok — 抽样失败（池子被外部改短等）时退化为取前 n 条，不能抛
        got = pool[:nn]
    if not got:
        got = list(SEED_POOL[:nn])

    note("random_seeds", chars=len(t), n=len(got), flavor=flavor, matched=matched)
    _bump("seeds", flavor)
    return got


# ------------------------------------------------------------------ 统计
def stats():
    """报告三张表的规模与真实用量（**越用越大**必须能被看见）。

    为什么返回 int 而不是把整张表塞回来：stats() 是给日志和自检用的，
    把 12 个视角、12 个算子、20 条种子全塞进去，会污染每一行日志；
    具体清单另有 PERSPECTIVES / OPERATORS / SEED_POOL 供直接读取。
    为了照顾「想看明细」的用法，这里额外给了 seed_pool_list。
    去掉它：没人知道视角表和算子表有没有被真正用起来，
    「载体在变强」就只剩一句无法验证的口号。
    任何一步失败都只影响报告本身，绝不抛。
    """
    samples = 0
    try:
        samples = len(read_jsonl(_samples_path()))
    except Exception:      # noqa: silent-ok — 读不动明细就当 0 条：统计不该有能力搞崩调用方
        samples = 0

    uses = {}
    try:
        raw = read_json(_uses_path(), {})
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, dict):
                    uses[k] = sum(int(x or 0) for x in v.values())
    except Exception:      # noqa: silent-ok — 计数文件坏了不影响「表里有多少条」这类硬事实
        uses = {}

    return {
        "perspectives": len(PERSPECTIVES),
        "operators": len(OPERATORS),
        "seed_pool": len(SEED_POOL),
        "seed_pool_list": list(SEED_POOL),
        "perspective_ids": [p.get("id") for p in PERSPECTIVES],
        "operator_ids": [o.get("id") for o in OPERATORS],
        "twists": {o.get("id"): len(OPERATOR_TWISTS.get(o.get("id")) or _TWIST_FALLBACK)
                   for o in OPERATORS},
        "samples": samples,
        "uses": uses,
        "dir": boost_dir("creative"),
    }


# 便于「从外面看一眼这个模块长什么样」（自测与排查用，改不了任何东西）。
__all__ = ["PERSPECTIVES", "OPERATORS", "OPERATOR_TWISTS", "SEED_POOL",
           "resample", "apply_operator", "random_seeds", "stats"]
