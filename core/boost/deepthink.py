# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 单次深度推理（模块 10.6）

【这段为什么这么设计】
    4B 模型一次前向只能走「一小步」的思考：它生成下一个词时，没有余量去
    先列已知、再试假设、再自我反驳。所以直接问它一个复杂问题，它给出的
    不是「想过的答案」，而是**读起来很流畅的答案** —— 流畅和正确在这里是两件事。
    载体没法给它更多算力（那是模型的事），但可以给它**脚手架**：
    把「想」这件事故意拆成若干步，每一步只让它做一小步，并在每步上焊一个
    必须回答的问题。这就是本模块的四套脚手架：

      cot_prompt   CoT    强制分步 + 每步必须写依据（不许跳步、不许最后才给理由）
      tot_branches ToT    一次开出 n 条互不相同的探索分支，每条必须先声明「这一步在赌什么」
      self_doubt  自我质疑 让它当自己答案的敌人，找最可能错的地方与第一个崩掉的步骤
      divide      分而治之 把大问题拆成 n 个**独立可答**的子问题，每个只答自己那一个

    plan() 按**纯规则**从这四套里选一套：问题类型决定脚手架的形态，
    而不是让模型自己决定（让它选，它永远选那个最省事的「直接回答」）。

【去掉这个模块会怎样】
    ① 复杂问题继续拿到「流畅但没思考过」的一整段，用户只能靠运气判断对错；
    ② 多候选择优只能靠输入顺序（第一段总是被当成最好的）；
    ③ 没有任何一条会让模型**自己指出**答案的薄弱处 —— 而人做重要判断时，
       最值钱的那一步恰恰是「如果我错了，会先崩在哪」。

【为什么选型规则本身要写死在这儿，而不是交给模型】
    「该用 CoT 还是 ToT」是一个**关于问题的判断**，不是关于内容的理解：
    句子里有没有「为什么」「哪个更好」「帮我看看对不对」，是字符串层面的确定事实。
    用规则判它，零成本、可解释、可复现；用模型判它，多一次调用、多一次幻觉机会，
    而且同一句话两次可能得到不同的脚手架 —— 用户会看到「同样的问法，这次它换了套路」。
    去掉规则：深度变成随机事件，出问题时无法解释「为什么这次没用 CoT」。

【evaluate 的诚实原则（本模块最重要的一条自律）】
    没有 llm_fn 时**绝不假装模型评过**：`scored_by` 老老实实写 "rule"，
    理由是「载体规则打分」而不是「模型认为」。给了 llm_fn 但没抽出编号、
    或者 llm_fn 抛了异常，一律**回退到规则打分并在 note 里说明原因**。
    去掉这条自律：日志里会留下「模型评过」的假记录，
    而这种假记录一旦进了长期记忆，就再也没人能分清哪些结论是真被试过的。

【数据落盘（一律在 logs/boost/ 下，logs/ 已被 .gitignore 忽略，不脏仓库）】
    logs/boost/deepthink/plans.jsonl   每次 plan / evaluate 的明细（append-only，越用越大）
    logs/boost/deepthink_counts.json   模式与评估次数的快路径计数
    logs/boost/boost.jsonl             事件流水（由公共层 note() 统一写）

【绝不删除任何文件】
    本模块只用「追加 / 覆盖写」，全程没有 os.remove / unlink / rmtree。
"""
import os
import re

# 公共工具一律从包根拿，绝不在本模块重写一份：
# 尤其 bigrams —— 评估里的「重复度」要和别的模块认同一个分词口径，
# 自己再切一份的结果是同一段文字在两个模块里得到两种重复度。
# 为什么没取 has_any：选型理由里要写出**命中哪个判据词**（那是给用户看的证据），
# 所以每个判据点都用 hits 拿具体词，而不是用布尔快路径。
from . import boost_dir, boost_path, norm, cjk_count, bigrams, hits, now, note
from . import append_jsonl, read_jsonl, read_json, write_json

# ------------------------------------------------------------------ 四种模式
MODE_COT = "cot"
MODE_TOT = "tot"
MODE_DOUBT = "doubt"
MODE_DIVIDE = "divide"
MODES = (MODE_COT, MODE_TOT, MODE_DOUBT, MODE_DIVIDE)

# 中文名只给日志和 why 用。为什么不让调用方传中文：
# 传中文就要维护一张对照表，早晚出现「'分步' 到底算不算 'cot'」的争论。
MODE_CN = {MODE_COT: "强制分步", MODE_TOT: "思维树",
           MODE_DOUBT: "自我质疑", MODE_DIVIDE: "分而治之"}

# 问题为空 / None 时的占位。为什么不直接发空提示词：空提示词会让模型开始
# 自由发挥（通常是复述系统提示），用户拿到一段完全跑题的输出；
# 一句占位能让它诚实地问回来「你要我思考什么」。
_EMPTY_Q = "（你还没有把问题告诉我）"

# ------------------------------------------------------------------ 选型判据词表
# 判据顺序 = 误判代价从大到小（和 memory_deep 的「事实优先」同一条思路）：
#   把「我有答案要挑错」误判成 CoT → 用户要的是挑错，拿到的是把原答案重讲一遍；
#   把「多诉求长问题」误判成 CoT → 一段话什么都谈、什么都不深，等于没答；
#   把「哪个更好」误判成 CoT → 拿到一段分析，却没有任何一个被选出来的结论；
#   反过来，把普通问题误判成别的脚手架，代价只是「答得比需要的更啰嗦」。
# 去掉顺序（随便先判哪个）：同一句话会因为命中顺序不同而换脚手架，无法解释。
_DOUBT_WORDS = ("我写的", "我的答案", "帮我看看", "对不对", "是不是错", "挑错",
                "检查一下", "有问题吗", "审一下", "评一下", "我的方案", "看对不对")
_DIVIDE_MULTI_WORDS = ("并且", "同时", "分别", "以及", "另外", "还要", "顺便",
                       "一方面", "另一方面", "两个问题", "三件事", "多个")
_TOT_WORDS = ("哪个更", "哪个好", "选一个", "怎么选", "二选一", "比较",
              "优缺点", "取舍", "方案", "设计", "规划", "要不要", "值不值")
_COT_WORDS = ("为什么", "解释", "原理", "原因", "怎么理解", "是什么",
              "讲讲", "说说", "分析一下", "怎么回事", "有啥区别")

# 长度判据：中文按汉字数（cjk_count），因为 "hello world" 和 "你好世界"
# 字符数一样但信息量差很远。阈值取 40 / 90 汉字：
#   40 汉字≈一句话里塞进了两个诉求，90 汉字≈一段话问了好几件事。
# 去掉长度判据：一段 300 字、含三个诉求的问题会被判成 CoT，
# 模型只能在一次分步里把三件事都草草带过。
_LONG_CJK = 40
_VERY_LONG_CJK = 90
_LONG_CHARS = 80


# ------------------------------------------------------------------ CoT
def cot_prompt(question):
    """强制分步：每一步都要写出「凭什么」，绝不许把理由堆到最后一步。

    【为什么要写死「不许跳步」和「不许最后才给理由」】
      4B 模型最典型的两种偷懒是：从第 1 步直接跳到结论（中间省了）、
      以及先给结论再补一段理由（先有答案后编依据）。
      第二种尤其危险 —— 它读起来像「有推导」，其实是事后补的，
      而人看不出来。这两条禁令就是冲它们去的。
      去掉这两条：模型会交出一段「先结论后理由」的漂亮文字，
      用户以为它推过，其实结论是拍脑袋的。

    【为什么要「不确定就写出来」】
      不确定性是**有用的输出**：它告诉用户该去哪里核对。让小模型含糊过去，
      等于把不确定性藏起来，最后以「很确定的错误」的形式暴露给用户。
      去掉这一条：模型会把自己编的假设当既定事实继续往下推。

    question=None / 空串 / 超长串都不抛（超长串原样放进提示词，由模型自己处理）。
    """
    t = norm(question)
    return (
        "你正在被要求回答下面的问题。**不要直接给结论**，一步一步来。\n\n"
        "【问题】%s\n\n"
        "【硬性规则】\n"
        "1. 把回答拆成编号步骤（建议 4~7 步），一步一步写，每步开头写「第 N 步：」。\n"
        "2. **每一步都必须写出「凭什么」**：这一步依据的是什么事实 / 假设 / 算式 / 常识。"
        "没有依据的那一步，删掉重写，不要留着凑数。\n"
        "3. **不许跳步**：不许从第 1 步直接跳到结论；也不许把理由堆在最后一步 —— "
        "理由必须在它对应的那一步当场给出，而不是结尾补一段。\n"
        "4. 如果某一步你自己也不确定，就在那一步后面写明「不确定，因为……」，"
        "并说清要去哪里核对。不许含糊带过。\n"
        "5. 最后单起一行写「结论：」，只写一句话。\n"
        "6. 如果走到一半发现方向错了，明确写「回到第 N 步重来」，然后重写那一步，"
        "不要假装前面没写错。\n\n"
        "现在开始，第 1 步：\n"
    ) % (t or _EMPTY_Q)


# ------------------------------------------------------------------ ToT
# 七条真正不同的探索策略。为什么必须七条、且每条带一个「赌注」：
# 「给三个方案」和「沿三个方向各探索一步」是两件不同的事 ——
# 前者产出三份成品，后者产出三个**试探**，而试探才能暴露方向本身是错的。
# 加「这一步在赌什么」，是逼模型把隐含假设摆到台面上：
# 说不清在赌什么的探索，就是没有方向的瞎猜。
# 去掉 bet：模型会给出三条同方向的、只换了措辞的「分支」。
_BRANCHES = [
    {"id": "best", "name": "最好情况优先",
     "how": "假设所有理想条件都成立，先看这条路能走多远。",
     "bet": "赌「最理想的那个前提会成立」"},
    {"id": "worst", "name": "最坏情况优先",
     "how": "假设最关键的某个前提不成立，先看这条路会怎么塌。",
     "bet": "赌「某个被当成理所当然的前提其实是会失效的」"},
    {"id": "opposite", "name": "反向假设",
     "how": "先假设你已经得出的那个结论是错的，从这个错结论往回找路。",
     "bet": "赌「真实答案和直觉感受是相反的」"},
    {"id": "analogy", "name": "借别的领域",
     "how": "找一个完全不相干但结构相似的领域，把那里现成的解法搬过来试。",
     "bet": "赌「这件事的结构和另一个领域的结构是同构的」"},
    {"id": "simplify", "name": "极端简化",
     "how": "去掉一个被认为「必须有」的约束，看问题是否直接消失或变形。",
     "bet": "赌「那个约束其实不是必需的，只是没人敢去掉」"},
    {"id": "user", "name": "换使用者",
     "how": "把主角换成另一类人（外行 / 小孩 / 最挑剔的客户），重新推一遍。",
     "bet": "赌「当前答案只对某一类人成立，换个人就不成立」"},
    {"id": "phases", "name": "拆成两个阶段",
     "how": "假设这其实是两个时间尺度上的两个问题，分别单独回答。",
     "bet": "赌「这个问题被当成一件事来问，其实是两件事粘在一起」"},
]


def _rotate(seq, offset, n, stride=3):
    """从 `seq` 里按「起点 + 互质步长」取 n 个互不相同的元素。

    为什么步长写死 3：本模块的序列长度是 7（分支表），3 与 7 互质，
    轮转一圈不重不漏。为什么不写成通用求法：这里只有一张固定长度的表，
    通用求法要多一个 math 依赖和一段循环，而它换不来任何东西。
    （去掉轮转：每个问题都从「最好情况优先」开始，分支表顺序就成了固定套路。）
    """
    size = len(seq)
    if size <= 0:
        return []
    nn = max(1, min(int(n), size))
    return [seq[(int(offset) + i * stride) % size] for i in range(nn)]


def tot_branches(question, n=3):
    """思维树：返回 n 条**互不相同**的探索分支提示词（n 夹在 [1,6]）。

    【为什么 n 条必须真的不同】
      「分支 1 / 分支 2 / 分支 3」只换编号的话，模型会给出三段同方向的答案 ——
      等于把一次回答切成三份，没有增加任何探索面。
      所以每条分支绑定一个**不同的策略 + 不同的赌注**，n 条就是 n 个方向。
      去掉策略绑定：ToT 退化成「请给我三个方案」。
    【为什么每条都要求写「这一步在赌什么」】
      分支的价值不在结论，而在**它押了什么假设**。把假设写出来，
      载体和用户才能一眼看出「这条路建立在什么之上」，
      进而判断要不要为它去核实 —— 这才是可执行的探索。
      去掉它：三条分支看起来都很合理，但没人知道它们各自怕什么。
    【为什么按问题轮转起点】
      不同问题从不同策略起步（有的先试最坏情况、有的先试极端简化），
      否则每次都是「最好情况打头」，用户会觉得它只会唱赞歌。
    question=None / 空串不抛。
    """
    t = norm(question)
    nn = max(1, min(_count(n, 3), 6))
    off = (_stable_hash(t) % len(_BRANCHES)) if _BRANCHES else 0
    picks = _rotate(_BRANCHES, off, nn)

    out = []
    for i, b in enumerate(picks, 1):
        out.append(
            "【思维树 · 分支 %d/%d：%s】\n\n"
            "【问题】%s\n\n"
            "【这条分支的探索策略】%s\n\n"
            "【第一步必须先写「这一步在赌什么」】把这条分支押上的那个假设单独写一行，"
            "格式是「这一步在赌：___」，并补一句：如果这个假设不成立，这条路会怎么塌。\n"
            "【然后】只沿这条分支往下走 2~3 步，走到能给出一个**试探性**结论为止。\n"
            "【禁止】不要把别的分支的答案写进来，也不要写「综合来看」「另一方面」—— "
            "这一条分支只负责一个方向。\n"
            "【收尾】写「这条分支如果成立，结论是：」加上一句话。\n"
            % (i, nn, b.get("name"), t or _EMPTY_Q, b.get("how"))
        )
    return out


# ------------------------------------------------------------------ 自我质疑
def self_doubt(answer):
    """自我质疑：让模型当自己答案的敌人，找出最可能错的地方和第一个崩掉的步骤。

    【为什么「第一个崩掉的步骤」比「哪里可能错」更值钱】
      「哪里可能错」是列举，模型会给出四五条泛泛的风险（数据可能有偏差之类），
      基本没用。而「按因果顺序找，如果错了第一个崩掉的是哪一步」是**排序题**：
      它逼模型在答案内部建立依赖关系，指出真正的承重点。
      承重点一旦被指出，用户只需要核对那一处，成本极低。
      去掉它：质疑环节退化成一段「答得总体不错，但建议进一步核实」的客套话。
    【为什么专门禁「客套」】
      小模型有强烈的讨好倾向，会说「整体不错，只是小地方可以更严谨」而不敢下判断。
      明确禁止客套，才拿得到真话。
    answer=None / 空串不抛。
    """
    t = norm(answer)
    return (
        "下面是一份**已经写好的答案**。你的任务不是重写它，也不是夸奖它，"
        "而是当它的敌人。\n\n"
        "【答案】%s\n\n"
        "【必须按顺序回答这四件事】\n"
        "1. 这份答案里**最可能错的地方是哪一处**？直接引用原句（照抄那几个字），"
        "然后说明为什么它可疑。\n"
        "2. 如果它真的错了，**第一个崩掉的会是哪一步**？按因果顺序找 —— "
        "不是挑措辞问题，而是找那个支撑着其它结论的承重点。\n"
        "3. 要推翻它，**最省力的办法是什么**？给一个具体的动作：一个反例、"
        "一次核对、或者一个该问但没问的问题。\n"
        "4. 最后写「修正版结论：」，只写修正之后的一句话；"
        "如果确实不需要修正，就写「不需要修正，因为……」。\n"
        "【禁止】不要客套，不要说「整体不错」，也不要为了显得友好而不敢指出错误；"
        "指出错误不会冒犯我，漏掉错误才会。\n"
    ) % (t or _EMPTY_Q)


# ------------------------------------------------------------------ 分而治之
# 八条固定子问题，**顺序有依赖**：先有事实，才谈得上目标和约束。
# 为什么顺序固定、不轮转：轮转会出现「先讲代价再讲目标」这种乱序子问题，
# 而乱序的子问题拼不回一个大问题（收集回来时用户根本串不起来）。
# 去掉固定顺序：分而治之产出的是一堆互不相干的片段。
_SUB_TOPICS = [
    {"id": "facts", "name": "现状与事实",
     "ask": "就这件事，现在**能确定的**事实有哪些？只写事实，凡是你猜的都要标出来。"},
    {"id": "goal", "name": "目标",
     "ask": "这件事要达成什么才算成功？给出一个**能验证**的成功标准。"},
    {"id": "constraints", "name": "约束条件",
     "ask": "有哪些硬约束（时间 / 钱 / 人力 / 不能碰的红线）？把它们列全。"},
    {"id": "variables", "name": "关键变量",
     "ask": "结果最依赖哪几个变量？按影响从大到小排，并说明为什么。"},
    {"id": "options", "name": "可选方案",
     "ask": "有哪几条可选路线？每条只写一句话，不要展开比较。"},
    {"id": "cost", "name": "代价与风险",
     "ask": "每条路线的代价和最坏结果是什么？只谈代价，不要谈好处。"},
    {"id": "steps", "name": "执行步骤",
     "ask": "如果现在就要动手，第一步具体做什么？只给步骤，不要给理由。"},
    {"id": "check", "name": "验证方式",
     "ask": "怎么判断做对了？给出一个可以在短期内检查的验证方法。"},
]


def divide(question, n=4):
    """分而治之：把问题拆成 n 个**独立可答**的子问题提示词（n 夹在 [2,8]）。

    【为什么每个子问题都要单开一条提示词，而不是一次列给模型】
      一次列给模型，它会把前几个草草带过、把最后一个写得很长 ——
      因为它的注意力被摊薄了。一条提示词只问一件事，
      它才有余量把这件事想清楚 —— 这就是「模型每次只做一小步」。
      去掉拆分：复杂问题回到「一段话什么都说、什么都不深」。
    【为什么要求「只回答这一个子问题，不要顺带回答别的」】
      小模型有强烈的补全倾向：问它约束，它会把方案也顺手答了，
      而顺手答的部分质量最差、却最容易被用户当成结论。
      把口子扎死，每一格的质量才是可比的。
    【为什么 n 下限是 2】
      n=1 的分而治之没有意义（那就是直接回答），而下限设成 2 能让调用方
      一眼看出「拆过头了」是参数写错，而不是模块坏了。
    question=None / 空串不抛。
    """
    t = norm(question)
    nn = max(2, min(_count(n, 4), 8))
    picks = _SUB_TOPICS[:nn]

    out = []
    for i, s in enumerate(picks, 1):
        out.append(
            "【分而治之 · 子问题 %d/%d：%s】\n\n"
            "【大问题】%s\n\n"
            "【你只需要回答这一个子问题】%s\n\n"
            "【规则】\n"
            "1. **只回答这一个子问题，不要顺带回答别的** —— 其它子问题由别人回答，"
            "你多答的部分会被丢掉，只会稀释你自己的答案。\n"
            "2. 回答必须**独立成立**：不要写「见上一问」「同上」「如前所述」，"
            "把必要的前提在这里重述一遍。\n"
            "3. 如果回答需要某个你还不知道的前提，就把这个前提明确写出来并标成「待确认」，"
            "不要自己替它编一个值继续往下答。\n"
            "4. 3~6 句话，不要写成文章，也不要分很多层标题。\n"
            % (i, nn, s.get("name"), t or _EMPTY_Q, s.get("ask"))
        )
    return out


# ------------------------------------------------------------------ 选型
def _auto_mode(t):
    """纯规则选脚手架，返回 (mode, 中文理由)。

    为什么理由必须**引用命中的判据词**：用户会问「为什么这次这么答」，
    答案必须是「因为你的问题里有『为什么』」，而不是「因为我觉得」。
    可解释性是载体层相对模型的唯一优势，理由不写清就等于放弃了它。
    去掉判据引用：日志里只剩一个 mode，事后无法复盘选型对不对。
    """
    if not t:
        return MODE_COT, ("问题为空，选「强制分步」：四套脚手架里只有它不预设问题形态，"
                          "先让模型把话说清楚，再谈别的。")

    got = hits(t, _DOUBT_WORDS)
    if got:
        return MODE_DOUBT, ("命中「%s」——这是「已经有一份答案、需要挑错」的信号，"
                            "「自我质疑」这套脚手架就是为它准备的（先找承重点，再谈对错）。"
                            % got[0])

    multi = hits(t, _DIVIDE_MULTI_WORDS)
    n_cjk = cjk_count(t)
    if (n_cjk >= _LONG_CJK and multi) or n_cjk >= _VERY_LONG_CJK or len(t) >= 2 * _LONG_CHARS:
        why = ("问题较长（%d 个汉字）" % n_cjk)
        if multi:
            why += "且命中并列诉求词「%s」" % multi[0]
        if n_cjk >= _VERY_LONG_CJK or len(t) >= 2 * _LONG_CHARS:
            why += "，已超过「一段话问了好几件事」的阈值"
        return MODE_DIVIDE, (why + " → 选「分而治之」：一次问这么多事，"
                             "模型只会每件都草草带过，拆成独立子问题才有深度。")

    got = hits(t, _TOT_WORDS)
    if got:
        return MODE_TOT, ("命中「%s」——这是「要在几条路里挑一条」的信号，"
                          "选「思维树」：先各开一条分支试探，把每条押的假设摆出来，"
                          "再决定走哪条。" % got[0])

    got = hits(t, _COT_WORDS)
    if got:
        return MODE_COT, ("命中「%s」——这是「要讲清因果 / 原理」的信号，"
                          "选「强制分步」：这类问题怕的不是答得短，是跳步。" % got[0])

    return MODE_COT, ("没有命中任何专门判据（没提为什么 / 原理，没提哪个更好 / 方案，"
                      "也不是「我有答案要挑错」，且不长）→ 默认「强制分步」："
                      "它是唯一对问题形态没有要求的脚手架，误判代价最低。")


def _prompts_for(mode, t):
    """按模式渲染提示词列表（集中在一处，避免 plan 里写四种分支）。

    为什么集中：调用方（包括自测和将来的调度层）要知道「每种模式输出几条提示词」，
    散在 plan 里的话，这条信息只能靠读代码；集中之后它就是这个函数的一行。
    去掉它：加第五种模式时要改两处（分支判断 + note），早晚漏一处。
    """
    if mode == MODE_TOT:
        return tot_branches(t, 3)
    if mode == MODE_DOUBT:
        return [self_doubt(t)]
    if mode == MODE_DIVIDE:
        return divide(t, 4)
    return [cot_prompt(t)]


def plan(question, mode="auto"):
    """按问题类型（或显式指定）选出脚手架，返回 mode / prompts / why。

    【为什么默认 auto，而不是让调用方每次自己选】
      调用方最不了解该用哪套（它只有一句用户原话），而判型只需要几个
      字符串命中判断。默认 auto 让「正确的脚手架」成为免费得到的默认行为，
      而不是每个调用点都要重新想一遍的负担。
      去掉 auto：所有问题都会走同一个脚手架，深度就成了一句空话。
    【mode 显式给了就照办】
      上层（比如用户手动点了「换个思路」）的判断优先于规则 ——
      规则是兜底，不是权威。
    【非法 mode 为什么不抛】
      一个拼错的 mode 不该让整轮对话失败；回退到 auto 并在 why 里
      写明「你传的 mode 不认识」，是把错误变成信息，而不是变成故障。
      去掉容错：mode="deepthink"（很像但不合法）会让用户拿到一个异常。
    【为什么 prompts 直接给出成品字符串，而不是让调用方再调一次函数】
      一次调用就拿到可以直接发给模型的完整提示词列表，
      调用方不需要知道「哪个 mode 对应哪个函数」—— 那层对应关系一旦外泄，
      就会出现在五个调用点里，其中必有一个是过期的。
    每次调用都会 note("plan", mode=..., chars=...) 记一条流水。
    """
    t = norm(question)
    raw = norm(mode)
    key = raw.lower()
    bad = bool(key) and key not in MODES and key != "auto"

    if bad:
        chosen, why = _auto_mode(t)
        why = ("传入的 mode「%s」不是 cot / tot / doubt / divide 之一，"
               "已回退按问题类型自动选型；" % raw) + why
    elif key in MODES:
        chosen = key
        # ⚠️ `mode=%s` 里的那个 `%` 必须转义成 `%%`：字符串里有 % 又要做 % 格式化时，
        #    漏转义就是 "not enough arguments for format string"（自测当场抓到）。
        why = ("调用方显式指定 mode=%s（%s），按指定执行，不做自动判型。"
               % (chosen, MODE_CN.get(chosen)))
    else:
        chosen, why = _auto_mode(t)

    prompts = _prompts_for(chosen, t)
    note("plan", mode=chosen, chars=len(t))
    _record(chosen, chars=len(t), n_prompts=len(prompts), asked=key or "auto", bad_mode=bad)
    return {"mode": chosen, "prompts": prompts, "why": why}


# ------------------------------------------------------------------ 多候选择优
# 评估用的判据词表。为什么这些词能当"有依据"的信号：
# 「因为 / 所以 / 例如」是**推理连接词**，它们出现说明句子之间有支撑关系；
# 没有连接词的长答案多半是并列的金句堆（读着好听，没有承重结构）。
_REASON_WORDS = ("因为", "所以", "由于", "因此", "例如", "比如", "依据", "说明",
                 "取决于", "第一", "第二", "则", "可见")
# 分点标志：行首的 - * •、1. 1、1)、一、一.、①…
_POINT_PAT = re.compile(r"(?:^|\n)\s*(?:[-*•]|\d+[.、)]|[一二三四五六七八九十]+[.、]|[①②③④⑤⑥⑦⑧⑨⑩])")
_NUM_PAT = re.compile(r"\d")
# 从模型回文里抽编号：先按"候选 / 编号 / 答案 / 第 N"这种明确写法抽，
# 抽不到再退回"文本里第一个数字"。为什么分两步：
# 模型常常回「候选 2 更具体」也偶尔回「2」，还可能回一段带年份的废话；
# 两步策略能让明确的回答稳拿，模糊的回答才退到兜底规则。
_STRICT_IDX = re.compile(r"(?:候选|编号|答案|选项|第|answer)\s*[是为：:\-]?\s*(\d+)")
_LOOSE_IDX = re.compile(r"\d+")


def _stable_hash(text):
    """跨进程稳定的 32 位整数（只用于给 tot_branches 挑轮转起点）。

    为什么不用内置 hash()：CPython 对 str 的 hash 带进程级随机盐，
    同一句话在两个进程里取到不同的分支起点 —— 自测会「时好时坏」。
    这里只需 crc32 的稳定性，不需要它均匀分布（只有 7 个分支）。
    去掉它改用 hash()：同一问题在不同进程里换分支顺序，无法复现。
    """
    try:
        import zlib
        return zlib.crc32(norm(text).encode("utf-8")) & 0xFFFFFFFF
    except Exception:      # noqa: silent-ok — 编码失败（极端脏输入）时退化为 0：宁可固定起点也不能抛
        return 0


def _count(n, default):
    """把任意输入转成整数（None / 空串 / 中文数字都不抛）。

    为什么要独立成函数：本模块有三个函数收 n，各自写 `int(n)` 的话，
    「n=None 时谁崩谁不崩」就成了随机事件，而规范要求任何函数都不许因为输入脏而抛。
    去掉它：tot_branches(n=None) 直接 TypeError。
    """
    try:
        return int(n)
    except Exception:      # noqa: silent-ok — 脏参数退回默认值，比抛异常有用得多
        return int(default)


def _score_one(text):
    """按载体规则给一条候选打分，返回 (分数, 中文打分理由)。

    【为什么是这几个判据，而不是"让模型打个分"】
      没有 llm_fn 时，评分必须由载体自己做（而且必须**如实**标注 scored_by="rule"）。
      挑这四个判据是冲着 4B 模型最常见的四种毛病去的：
        太短 → 什么都没说；太长 → 在用字数冒充深度（复读/车轱辘话）；
        没有分点 → 没有结构；没有依据词 → 只有结论没有支撑。
      去掉任一条都会留下一个能被"骗分"的空子：
        只算长度 → 交一段啰嗦的空话就赢；只算分点 → 罗列关键词就赢。
    【为什么理由是中文并且带上加了多少分】
      排序结果要给用户看，理由就是「为什么选它」的答案；
      不写清加减分，用户会觉得系统在瞎排，而无法判断要不要相信这个排序。
    """
    t = norm(text)
    L = len(t)
    if L == 0:
        return 0.0, "空候选，得 0 分"

    score = 0.0
    why = []

    # ① 长度：适中最优，过短说不出东西，过长多半在灌水。
    if L < 8:
        score += 0.2
        why.append("只有 %d 个字符，说不出什么（+0.2）" % L)
    elif L < 30:
        score += 0.8
        why.append("偏短（%d 字，+0.8）" % L)
    elif L <= 400:
        score += 1.5
        why.append("长度适中（%d 字，+1.5）" % L)
    elif L <= 1200:
        score += 0.9
        why.append("偏长（%d 字，+0.9）" % L)
    else:
        score += 0.4
        why.append("过长（%d 字，多半在用字数冒充深度，+0.4）" % L)

    # ② 结构：有分点说明它组织过内容；上限 1.0，防止靠堆编号刷分。
    pts = len(_POINT_PAT.findall(t))
    if pts:
        add = min(1.0, 0.4 * pts)
        score += add
        why.append("有 %d 处分点 / 编号（+%.1f）" % (pts, add))

    # ③ 依据：推理连接词越多，说明句子之间有支撑关系；上限 1.2 同理。
    got = hits(t, _REASON_WORDS)
    if got:
        add = min(1.2, 0.3 * len(got))
        score += add
        why.append("命中依据词「%s」（+%.1f）" % ("、".join(got[:3]), add))

    # ④ 具体：出现数字说明它敢给具体值（时间/数量/条件），通常不是空话。
    if _NUM_PAT.search(t):
        score += 0.4
        why.append("给出了具体数字（+0.4）")

    # ⑤ 重复度：用二元组去重率衡量。复读/车轱辘话是模型退化最典型的表现，
    #    不给它不是"没检查到"，而是把复读的候选排到了前面 —— 那是反向选择。
    bg = bigrams(t)
    if len(bg) >= 4:
        uniq = len(set(bg)) / float(len(bg))
        score += round(0.8 * uniq, 4)
        why.append("用字不重复度 %.2f（+%.2f）" % (uniq, 0.8 * uniq))
        if uniq < 0.55:
            score -= 0.3
            why.append("重复明显，疑似车轱辘话（-0.3）")

    # ⑥ 整段复读：前 20 字出现两次以上，基本可以确定它在原地打转。
    if L >= 60:
        head = t[:20]
        if head and t.count(head) > 1:
            score -= 0.5
            why.append("开头 20 字重复出现，判定为复读（-0.5）")

    return round(max(0.0, score), 2), "；".join(why)


def _rule_rank(texts):
    """对所有候选按规则打分并排序（分数降序，同分按原顺序 —— 保证确定性）。

    为什么同分要按原顺序而不是再引入随机：调用方可能反复调同一个 evaluate
    来做 A/B，「同分时名次会变」会让两次结果对不上，看起来像 bug。
    去掉这条 tie-break：分数相同的两条候选在两次调用里可能互换位置。
    """
    ranked = []
    for i, t in enumerate(texts):
        sc, why = _score_one(t)
        ranked.append({"index": i, "text": t, "score": sc, "why": why})
    ranked.sort(key=lambda r: (-r["score"], r["index"]))
    return ranked


def _judge_prompt(texts):
    """给 llm_fn 的判题提示词：只许回一个编号。

    为什么要求「只回复一个数字」并用正则抽：4B 模型回不了结构化 JSON
    （十次能坏八次），但回一个数字很稳；而"回一段带解释的话"我们也必须
    能容忍 —— 抽取逻辑就在 _parse_index 里。
    为什么候选要截断：候选取自生成结果，可能很长；把 5 段长文塞进去，
    小模型会直接在长度上失焦，判出来的编号基本是随机的。
    去掉截断：判题本身变成一次超长上下文测试，而不是一次比较。
    """
    blocks = []
    for i, t in enumerate(texts, 1):
        body = t if len(t) <= 300 else (t[:300] + "…（已截断）")
        blocks.append("候选 %d：\n%s" % (i, body))
    return (
        "下面有 %d 个候选答案。请只做一件事：挑出其中**最好**的那一个。\n\n"
        "%s\n\n"
        "【怎么算更好】说得更具体、有依据（有因为/所以/例如）、有结构、不啰嗦、不重复。\n"
        "【输出格式】**只回复一个数字**（1 到 %d 之间），不要写理由、不要写解释、"
        "不要写别的字。\n"
        % (len(texts), "\n\n".join(blocks), len(texts))
    )


def _parse_index(raw, n):
    """从模型回文里抽候选编号，返回 0 基下标；抽不到或不合法返回 None。

    为什么抽不到要返回 None（而不是猜一个）：猜的那一个会被记成
    「模型选的」，于是日志里留下一条假的模型判断 —— 本模块最重要的自律
    就是**绝不假装模型评过**。
    为什么越界也要当失败：模型说「第 7 个」而只有 3 个候选，说明它没看懂题目，
    此时它选的编号毫无信息量，退回规则打分比采信它更诚实。
    """
    s = norm(raw)
    if not s:
        return None
    m = _STRICT_IDX.search(s)
    if m is None:
        m = _LOOSE_IDX.search(s)
    if m is None:
        return None
    try:
        k = int(m.group(m.lastindex or 1) if m.re is _STRICT_IDX else m.group(0))
    except Exception:      # noqa: silent-ok — 抽出的串转不成数字就当作没抽到，绝不抛
        return None
    if 1 <= k <= int(n):
        return k - 1
    return None


def _rule_result(texts, note_text):
    """构造"规则打分"的返回体（空候选之外的统一出口）。

    为什么把返回体拼装集中在一处：evaluate 有五条出口（无 llm_fn、正常、
    异常回退、抽不到编号回退、空候选），各自手写一遍 dict，
    早晚出现某个出口少一个键 —— 而少键的返回体会在下游调用方那里炸掉。
    去掉它：五种返回形状慢慢分叉，而下游只测试过其中一种。
    """
    ranked = _rule_rank(texts)
    best = ranked[0] if ranked else None
    return {
        "best": best["text"] if best else None,
        "best_index": best["index"] if best else -1,
        "ranked": ranked,
        "scored_by": "rule",
        "note": note_text,
    }


def evaluate(candidates, llm_fn=None):
    """多候选择优：有模型就用模型挑，没有（或挑不出来）就按载体规则挑。

    【为什么必须同时支持两条路】
      llm_fn 是可选的：离线自测、模型不可用、用户关掉模型时，
      择优这件事**不能停** —— 否则整条生成流水线会因为"没有裁判"而卡死。
      规则打分不是"凑合"，它是最终兜底，所以判据要经得起看（见 _score_one）。
    【为什么宁可回退也绝不假装模型评过】
      见模块 docstring 的「诚实原则」：scored_by 只有 "rule" / "llm" 两种取值，
      任何没真正采信模型编号的路径都记 "rule"，并在 note 里写明原因。
      去掉这条：日志里会混入假的「模型判过」，长期记忆一旦吸收就再也分不清了。
    【为什么空列表要单独返回一个固定形状】
      调用方（比如"生成 3 个再选 1 个"）在极端情况下会传空列表，
      此时最好的行为是**明确说没有候选**（best=None、best_index=-1），
      而不是抛异常或者返回一个像"空字符串候选"的歧义结果。
      best_index=-1 与任何真实下标都不冲突，调用方一眼能看懂。
    【为什么 None 项不剔除】
      ranked 的下标必须与输入一一对应，否则 best_index 对不上原文。
      所以 None 项按空串处理（得 0 分）并保留在列表里。
      去掉这条：调用方拿 best_index 回查自己的列表时会拿到错的候选。

    llm_fn 约定签名 `llm_fn(prompt: str) -> str`；抛异常、返回 None、
    返回不含编号的文本，全部回退规则打分，**绝不向上抛**。
    llm_fn=None 时同一输入永远得到同一结果（纯规则、无随机）。
    """
    try:
        items = list(candidates) if candidates is not None else []
    except Exception:      # noqa: silent-ok — 传进来的"不是列表"（比如一个字符串）就当作没有候选，绝不抛
        items = []
    texts = [norm(c) for c in items]

    if not texts:
        return {"best": None, "best_index": -1, "ranked": [],
                "scored_by": "rule", "note": "没有候选"}

    if llm_fn is None:
        res = _rule_result(
            texts,
            "没有提供 llm_fn，全部按载体规则打分（长度 / 分点 / 依据词 / 数字 / 重复度），"
            "未假装模型评过。")
        _record("evaluate", n=len(texts), scored_by="rule", why="no_llm_fn")
        return res

    try:
        raw = llm_fn(_judge_prompt(texts))
    except Exception as e:      # noqa: silent-ok — 模型侧任何异常都只是"这一个裁判缺席"，不能拖垮生成
        res = _rule_result(
            texts,
            "llm_fn 调用抛了异常（%s），已回退规则打分；异常不向上抛，"
            "因为择优这件事不该因为裁判故障而失败。" % type(e).__name__)
        _record("evaluate", n=len(texts), scored_by="rule", why="llm_exc")
        return res

    picked = _parse_index(raw, len(texts))
    if picked is None:
        res = _rule_result(
            texts,
            "模型没给出可解析的编号，已回退规则打分（scored_by=rule）——"
            "宁可如实说没用上模型，也不假装它评过。")
        _record("evaluate", n=len(texts), scored_by="rule", why="unparsable")
        return res

    # 采信模型的编号：它排第一，其余按规则分排。
    # 为什么被选中那条的 score 仍然是**规则分**而不是模型给的分数：
    # 模型只回了一个编号，没给分数。自己编一个分数填上去，
    # 就等于把"载体算出来的数"和"模型的态度"混成同一个字段，日后无法区分。
    rule_ranked = _rule_rank(texts)
    rest = [r for r in rule_ranked if r["index"] != picked]
    head = [r for r in rule_ranked if r["index"] == picked][0]
    head = dict(head)
    head["why"] = ("%s；【模型选中】llm_fn 在 %d 个候选里回了编号 %d。"
                   "注意此处 score 仍是载体规则分，不代表模型给了分数。"
                   % (head.get("why"), len(texts), picked + 1))
    ranked = [head] + rest
    _record("evaluate", n=len(texts), scored_by="llm", why="llm_pick")
    return {
        "best": texts[picked],
        "best_index": picked,
        "ranked": ranked,
        "scored_by": "llm",
        "note": ("由 llm_fn 选出的编号 %d 得第一；其余候选取规则分排序。"
                 "llm_fn 返回的原文为：%s" % (picked + 1, norm(raw)[:120])),
    }


# ------------------------------------------------------------------ 落盘
def _plans_path():
    """明细落盘路径：`logs/boost/deepthink/plans.jsonl`。

    为什么单独开子目录：本模块的明细会随使用不断变长，和别的模块的
    冻结快照混在一起时，清理与排查都会误伤（同 creative 的处理）。
    去掉 boost_dir() 改用 `__file__` 自己拼：早晚有人拼错一级，
    数据散到仓库别处，排查"怎么没存上"时你会发现它就在另一个目录里。
    """
    return os.path.join(boost_dir("deepthink"), "plans.jsonl")


def _counts_path():
    """计数落盘路径：`logs/boost/deepthink_counts.json`（快路径）。"""
    return boost_path("deepthink_counts.json")


def _record(key, **kw):
    """把一次 plan / evaluate 记进明细流水 + 计数（越用越大）。

    为什么要明细 + 计数两份：明细是**证据**（能回答"当时选了什么、为什么"），
    计数是**快路径**（统计时不扫一个不断变长的文件）。
    为什么写不进去也不抛：流水只是证据，不是功能；
    为了记一条日志让用户的对话失败，是明显不划算的交换。
    """
    rec = {"ts": now(), "event": norm(key)}
    try:
        rec.update(kw)
    except Exception:      # noqa: silent-ok — kw 里混进不可序列化对象也不能崩
        pass
    try:
        append_jsonl(_plans_path(), rec)
    except Exception:      # noqa: silent-ok — 明细写不进去绝不影响功能
        pass
    try:
        p = _counts_path()
        data = read_json(p, {})
        if not isinstance(data, dict):
            data = {}
        k = norm(key)
        data[k] = int(data.get(k) or 0) + 1
        data["total"] = int(data.get("total") or 0) + 1
        data["last_at"] = now()
        write_json(p, data)
    except Exception:      # noqa: silent-ok — 计数写不上只是"少记一次"，绝不能让生成失败
        pass
    return rec


def stats():
    """报告选型分布（**越用越大**必须能被看见）。

    为什么只给分布、不给明细：明细在 plans.jsonl 里，已被 read_jsonl 可读；
    stats() 是给日志和自检用的一行摘要，塞明细会污染每一行日志。
    去掉它：没法回答「用户的问题里有多少走了 ToT」这种最基本的观察问题，
    也就无从判断选型规则是不是把大多数问题都判成了默认的 CoT。
    任何一步失败都只影响报告本身，绝不抛。
    """
    out = {"total": 0, "by_mode": {}, "modes": list(MODES), "dir": boost_dir("deepthink")}
    try:
        raw = read_json(_counts_path(), {})
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k != "total" and k != "last_at":
                    out["by_mode"][k] = int(v or 0)
            out["total"] = int(raw.get("total") or 0)
    except Exception:      # noqa: silent-ok — 计数文件坏了就退回"扫明细"这条慢路
        pass
    try:
        rows = read_jsonl(_plans_path())
        if not out["total"]:
            out["total"] = len(rows)
        for r in rows:
            m = norm(r.get("mode"))
            if m:
                out["by_mode"][m] = int(out["by_mode"].get(m) or 0) + 1
    except Exception:      # noqa: silent-ok — 明细读不动也不影响已有计数
        pass
    return out


# 便于「从外面看一眼这个模块长什么样」（自测与排查用，改不了任何东西）。
__all__ = ["MODE_COT", "MODE_TOT", "MODE_DOUBT", "MODE_DIVIDE", "MODES", "MODE_CN",
           "cot_prompt", "tot_branches", "self_doubt", "divide", "plan",
           "evaluate", "stats"]
