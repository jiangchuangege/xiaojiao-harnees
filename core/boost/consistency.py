# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 超长一致性（模块 10.7）

【这段为什么这么设计】
    小模型写长文会**换名字**：第三段还叫"沈清"，第五段成了"沈青"；
    前面说"住在济南"，第十二段变成"住在青岛"。
    这不是智力问题 —— 8000 字里同一个人的写法要同时压在注意力里，
    对任何模型都是硬负担，4B 只是先垮，70B 垮得晚一点而已。
    单靠"请你自己盯住"是提示词工程，改不动地基。

    所以把这件事从**模型脑子里**搬到**载体结构里**，做成两件具体的东西：
      · 实体表 EntityTable —— 谁在这篇文章/这段会话里出现过，规范名是什么，
        别的写法（别名）算同一个。同类不同名 → 归一；同名不同类 → 冲突。
      · 关系图 RelationGraph —— 谁和谁之间有什么边（是/住在/喜欢…）。
        同一条边重复出现只是 count+1；同一对实体上出现互斥的边 → 矛盾。
    再加两个动作把它们接进生成流程：
      · inject()  生成**前**把实体表写成提示词（防它换名字）；
      · check()   生成**后**把成果跟表和图对一遍（换名字/新实体/关系矛盾）。

【去掉它会怎样】
    只剩"让模型自己注意一致性"：长文一旦超过它能同时记住的长度，
    换名字和前后矛盾就是必然，而且**没有任何一处代码能发现它**。
    更糟的是错误会被写进长期记忆 —— 表和图不做，就等于让幻觉直接落地。

【它遵守本包的共同公式】
    ① 结构化：一段散文本 → 一张实体表 + 一张关系图；
    ② 结构由载体维护：抽取规则、归一规则、互斥表全在 Python 里，不调模型；
    ③ 模型每次只做一小步：这里只管"名字和边对不对"，不管文笔、不管事实真伪；
    ④ 结果存回结构：save() 落 logs/boost/consistency.json，下次 load() 接着长。
    去掉④：表只在这一次回答里活着，"同一个用户昨天叫沈清今天叫沈青"永远查不出来。

【为什么抽取必须用纯规则，绝不许调模型】
    这是本模块唯一不能妥协的一条。一致性检查的**可信度来自确定性**：
    同一段文字今天抽出来是这 5 个实体，明天还得是这 5 个，
    否则"上次和这次不一致"这个判据本身就是随机的，会把正常文本报成矛盾。
    用模型抽取 = 用一个会犯错的东西去检查另一个会犯错的东西，
    且错误不可复现 —— 那还不如不查。规则粗糙但**稳定**，
    粗糙的代价是漏检（可接受），随机的代价是误报（把用户文本冤枉成错的，不可接受）。
    去掉这条自律会怎样：自测无法复现、bug 无法定位、
    而且每一次检查都要花一次模型调用（本模块的定位恰恰是"模型能省就省"）。

【为什么别名用"先出现的那个"当规范名，而不是"更长的那个"】
    规范名要能被**追溯**：用户/上游第一次写下"沈清"，后面的"沈清舟"是后来才出现的
    写法，把规范名改成"沈清舟"会让**之前所有已落盘的记录都要改**。
    取"先出现者"则永远只是追加，不改历史 —— 这与本包"绝不删除"是同一条纪律。
    去掉它（随便挑一个或挑更长的）：同一个实体在不同时间点产出不同规范名，
    表越长越乱，最后没人知道哪一个是它对的名字。

【为什么 __init__ 里一个字逻辑都不放（同 core/boost 的做法）】
    本模块被 core.boost 用 PEP 562 惰性 import，自己**只**依赖 core 公共工具层。
    不 import Flask / xiaojiao_app / 任何模型客户端：这样它能在纯 Python 环境里
    单独 `import core.boost.consistency` 并跑完全部自测。
    去掉这条自律：一致性检查会被强行绑在应用启动链上，
    离线自测、批量回放历史文本这些用法全部不可用。

【数据落盘】logs/boost/consistency.json（格式见 save/load）
    本模块**只写不删**：save() 直写（不做 tmp+rename，Windows 上 rename 覆盖接近删文件），
    全程没有任何 os.remove / unlink / rmtree / 截断。
"""
import os
import re

# 为什么从公共层拿这些工具，而不是各写一份（同 core/boost 其余模块的做法）：
#   norm / cjk_count / hits / has_any 是**全包统一的文本口径**。一致性检查与
#   模板选型、领域打分如果各写一份"命中了哪些词"，同一句话在两处会得到不同结论，
#   而用户只看到最终答案 —— 表现为"它一会儿记得住一会儿记不住"，这是最难查的一类 bug。
#   now / boost_path / read_json / write_json 同理：时间与落盘位置只有一个出口，
#   将来换精度或换目录时不会漏掉某个模块。
# 说明（为什么不调用 note / append_jsonl / read_jsonl）：
#   本模块的持久化**只有一个出口** consistency.json（save/load 就是一整张表 + 一整张图）。
#   再往 logs/boost/boost.jsonl 追加流水，会让"谁动了这份数据"多出一个说不清的位置，
#   而且流水丢掉也不会被任何人发现 —— 与其记一条没人看的日志，不如把 load/save 做成
#   可验证的往返（自测直接读文件比对数量）。调用方要流水，自己 note() 即可。
from . import boost_dir, boost_path, norm, cjk_count, hits, has_any, now, note
from . import append_jsonl, read_jsonl, read_json, write_json  # noqa: F401 — 统一导入面

# ==================================================================== 常量区
# kind 的四个取值。为什么只留四个而不是更细（比如把"组织"单列）：
# 细分类别需要模型来判，而本模块的红线是"不调模型"；四个类目靠规则就能分开，
# 且足够支撑 inject() 的分组展示与 conflicts() 的"同名不同类"判据。
# 去掉 kind：add 就没法发现"苹果"既是人名又是物件这种明显冲突。
KIND_PERSON = "person"
KIND_PLACE = "place"
KIND_TIME = "time"
KIND_OBJECT = "object"
KINDS = (KIND_PERSON, KIND_PLACE, KIND_TIME, KIND_OBJECT)
KIND_CN = {KIND_PERSON: "人名", KIND_PLACE: "地名",
           KIND_TIME: "时间", KIND_OBJECT: "物件"}

# 上限。为什么必须有：本模块对外的承诺是"任何输入都不抛异常"，
# 而超长串、被污染的落盘文件都会从"慢"变成"内存爆掉"。
# 这几个数取得**远大于真实用量**（提示词 8000 字、实体名最长也就几个字），
# 所以正常场景一个都不会碰到；去掉它们，一次脏数据就能让整个进程卡死。
_MAX_NAME = 32          # 单个实体名最长字符数（超长串截断，而不是拒收）
_MAX_ALIASES = 64       # 单条目别名上限（防某一条目无限堆别名）
_MAX_SCAN = 200000      # extract 最多扫描的字符数（超长文本只取前一段）
_REL_WINDOW = 12        # 关系词左右找实体的最大字符距离
_MAX_OBJ = 6            # 关系另一侧"兜底取词"的最长汉字数

# ------------------------------------------------------------------ 姓氏表
# 为什么写死一张表而不是引入 jieba / HanLP：本包禁止新增 pip 依赖，
# 而且中文姓名识别在"粗粒度"需求上，姓氏表 + 通用字规则的准确率已经够用。
# 这里收的是《百家姓》全表 + 常见现代姓（含"沈"，本模块自测就靠它）。
# 去掉姓氏表：要么上依赖，要么完全抽不出人名 —— 而人名恰恰是长文里最容易变形的实体。
_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍"
    "虞万支柯昝管卢莫经房裘缪干解应宗丁宣贲邓郁单杭洪包诸左石崔吉钮龚"
    "程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓"
    "牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙"
    "叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双"
    "闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍卻璩桑桂濮牛寿通边扈燕冀郏浦尚农"
    "温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘"
    "匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空"
    "曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
    # 常见但不在《百家姓》里的现代姓/简化姓（缺了它们，"覃/闫/付/肖"会全部漏抽）
    "覃闫付肖莎奕"
)
_SURNAME_SET = set(_SURNAMES)

# ------------------------------------------------------------------ 姓名识别辅助
# 称谓词：`姓 + 称谓`（李医生 / 王老师）整体算一个人名。
# 为什么单独列出来：这类写法里的"名"根本不是名字，用通用规则会抽成"李医"这种残词，
# 而且称谓本身是**强人名信号**（比"姓+单字"可靠得多）。
# 去掉它：长文里最常见的"李医生/王老师"全丢，而这恰恰是配角的主要写法。
_TITLES = ("医生", "大夫", "老师", "先生", "女士", "博士", "教授", "经理", "主任",
           "同学", "老板", "师傅", "律师", "护士", "警察", "记者", "厨师", "司机",
           "会计", "作家", "演员", "明星", "部长", "局长", "校长", "院长", "班长",
           "组长", "市长", "书记", "主管", "总监", "助理", "秘书", "教练", "法官",
           "警官", "院士", "队长", "店长")

# 绝不可能出现在名字里的字（虚词 / 动词 / 代词 / 方位）。
# 判据是"这个字在一个姓后面"—— 汉字里"姓+虚词"几乎必然是普通词而不是人名。
# 例：沈清**是**医生 → 3 字候选"沈清是"的末字是"是" → 否掉，退回 2 字"沈清"。
# 去掉它：满篇抽出"沈清是""李在了"这种垃圾实体，实体表一脏，
# 后面 check() 的"新实体"提示会被噪声淹没，用户就不再信这个功能了。
_BAD_TAIL = set(
    "的了是在和与也都就还吗呢吧啊呀哦嗯很不没有我你他她它们个这那这些"
    "上下里中外来去说要会能想得过把被给对从到向为而且然后因所以如"
    "什么怎么又再已经正在将可以应该必须让使做作成为觉得知道认为希望"
    "开始继续停走出回跑坐站看听读写讲问答吃喝玩睡买用拿放送找等带帮教"
    "干搞弄管办变化跟并或若虽但却才更最太挺真假该每各只从并且不过"
)

# 形如人名、其实是常用词的排除表（姓 + 一个字构成的常用词）。
# 为什么需要它（而不是只靠 _BAD_TAIL）："白天/很多"的末字都不是虚词，
# 但它们是词不是人。这类误抽**不会报错**、只会默默污染实体表，
# 所以必须显式列出来。去掉它：一段普通叙述会抽出十几个"人"，表就废了。
_NAME_STOP = set((
    "马上", "马路", "马桶", "白马", "白天", "白云", "白菜", "白色", "白发",
    "石头", "石油", "金子", "金鱼", "金钱", "金属", "金色", "许多", "许可",
    "高兴", "高级", "高潮", "高原", "方法", "方式", "方面", "方向", "方案",
    "方针", "于是", "程度", "程序", "过程", "里程", "工程", "王国", "王者",
    "王朝", "张望", "张口", "陈述", "陈旧", "陈年", "杨树", "杨柳", "黄色",
    "黄叶", "周末", "周围", "周期", "周记", "谢谢", "何必", "何况", "任何",
    "任务", "任性", "田野", "田地", "叶子", "叶片", "苏醒", "雷雨", "雷声",
    "龙头", "龙眼", "陶瓷", "黎明", "顾客", "顾问", "毛巾", "毛病", "毛衣",
    "万一", "千万", "钱包", "严肃", "严格", "严重", "武器", "武功", "莫名",
    "莫非", "孔雀", "关键", "关系", "关心", "关注", "安排", "安全", "安静",
    "安心", "全部", "全面", "全国", "明白", "成功", "成长", "习惯", "经常",
    "解释", "经过", "绝对", "终于", "项目", "需要", "态度", "证明", "负责",
    "喜欢", "讨厌", "支持", "反对", "属于", "认识", "知道", "感觉", "应该",
    "可能", "可以", "当然", "突然", "果然", "确实", "的确", "简直", "毕竟",
))

# ------------------------------------------------------------------ 地名
# 后缀式地名：以这些词结尾的整块字串当地名。
# 为什么用"后缀 + 向左回扫"而不是"N 字窗口"：
# "我今天去了趟济南市"用固定窗口会切出"了趟济南市"，而回扫会在"趟"（量词）处停住。
# 去掉后缀表：地名只能靠动词触发（住在/来自…）→ "济南市很大"这类句子全漏。
_PLACE_SUFFIXES = ("医院", "学校", "大学", "公司", "公园", "广场", "车站", "机场",
                   "省", "市", "县", "区", "镇", "乡", "村", "街", "路", "巷", "号")
_PLACE_SUFFIX_RE = re.compile("|".join(sorted(_PLACE_SUFFIXES, key=len, reverse=True)))

# 地名触发词：这些词**后面**接的那块字多半是地名。
# 为什么触发式与后缀式必须并存：中文地名常常不带后缀（"住在济南"），
# 只靠后缀会漏；只靠触发会漏掉"济南市很大"这种没动词的句子。两条路都要走。
_PLACE_TRIGGERS = ("住在", "搬到", "来自", "回到", "到达", "位于", "去了", "去", "到", "在")

# 顺手取出"在 X 工作/上班"里的 X —— 这是本模块规格里点名要支持的关系写法。
_WORK_VERBS = ("工作", "上班")
_WORK_RE = re.compile(r"在([\u4e00-\u9fff]{1,6}?)(?:工作|上班)")

# 向左 / 向右取词时的硬停字。为什么左右两张表不一样：
#   向左：宁可少取 —— 左边界贴着的主语常常是代词（"他"），把代词算进实体名等于制造垃圾名；
#   向右：可以多取 —— 右边是宾语/补语，"支持这个方案"里"这个方案"虽然要削掉指示词，
#         但整个短语仍是有效宾语，比直接放弃这条边强。
# 去掉它们：会抽出"他住在"、"并且很"这种把动词粘在实体上的词，实体表立刻失去意义。
_LEFT_STOP_CHARS = set(
    "的了是在和与也都就还吗呢吧啊呀哦嗯很不没有我你他她它们个这那这些"
    "上下里中外来去说要会能想得过把被给对从到向为而且然后因所以如"
    "什么怎么又再已经正在将可以应该必须让使做作成为跟并或若虽但却才更最"
    "太挺住您咱谁哪"
)
_RIGHT_STOP_CHARS = set(
    "的了是在和与也都就还很不没有我你他她它们个来去说要会能想得过把被"
    "给对从向为而且然后因所以如什么怎么又再已经将可以应该必须让使做作"
    "成为觉得跟并或若虽但却才更最太挺住您咱谁哪"
)

# 向右取地名时要停住的"动作词"：地名后面紧跟这些词时，地名到此为止。
# 例："在济南上班" → 取到"济南"就停，不会变成"济南上班"。
# 去掉它：触发式取词会把动词一起吞掉，抽出的"地名"根本没法用于比对。
_PLACE_FWD_STOP = ("上班", "工作", "生活", "上学", "读书", "吃饭", "睡觉",
                   "旅游", "出差", "加班", "看病", "养老", "玩", "住", "忙", "等")

# ------------------------------------------------------------------ 时间
# 绝对时间用正则（结构明确），相对时间词用公共层的 hits()（口径与全包一致）。
# 为什么要分开：相对词是"闭集合"，用 hits 还能顺带复用全包统一的命中排序口径；
# 绝对时间必须靠正则才能把"2026年 9月 14日"（含空格）整体抓住。
_TIME_RES = (
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]",     # 2026年9月14日
    r"\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}",        # 2026-09-14
    r"\d{4}\s*年\s*\d{1,2}\s*月",                        # 2026年9月
    r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]",                  # 9月14日
    r"\d{4}\s*年",                                       # 2026年
    r"\d{1,2}\s*月",                                     # 9月
)
_REL_TIME_WORDS = (
    "今天", "昨天", "前天", "明天", "后天", "大后天", "上周", "本周", "下周",
    "上个月", "这个月", "下个月", "上个星期", "这个星期", "下个星期",
    "去年", "今年", "明年", "刚才", "刚刚", "现在", "当时", "最近", "后来",
    "早上", "上午", "中午", "下午", "晚上", "夜里", "凌晨", "半夜", "周末",
    "周一", "周二", "周三", "周四", "周五", "周六", "周日", "周天", "星期天",
)

# ------------------------------------------------------------------ 引号内的称呼
# 为什么单列一类：中文里"引号里的 2~4 字"极大概率是名字/称呼/专名，
# 而它们在正文里往往**没有姓氏**（"大家都叫他'老猫'"）。
# 去掉它：绰号、外号、代号全部漏抽 —— 而长文里最会"变名字"的恰恰是这些。
_QUOTE_RES = (
    r"[\u0022\u201c\u201d]([^\u0022\u201c\u201d]{2,4})[\u0022\u201c\u201d]",
    r"[\u300c\u300e]([^\u300c\u300d\u300e\u300f]{2,4})[\u300d\u300f]",
)

# ------------------------------------------------------------------ 关系
# 关系词表。**顺序必须按长度倒排**（构造正则时排序）：
# 因为 Python 正则的选择分支是"先写在前的先试"，在"不是"的位置上
# 若不先试"不是"而先试"是"，就会抽出一条错误的肯定边 ——
# 这是本模块最容易踩、且后果最严重的一个坑（矛盾检测会被自己造出的假边污染）。
# 去掉倒排：所有否定句都会被读成肯定句，"小明不是医生"会让系统以为小明是医生。
_REL_WORDS = ("不属于", "不住在", "不喜欢", "不认识", "不支持", "不是", "不在",
              "讨厌", "喜欢", "支持", "反对", "认识", "住在", "搬到", "来自",
              "属于", "是", "爱", "恨")
_REL_RE = re.compile("|".join(sorted((re.escape(w) for w in _REL_WORDS),
                                    key=len, reverse=True)))

# 互斥表：同一对实体上同时出现这两条边 → 矛盾。
# 规格点名要求覆盖：是/不是、喜欢/讨厌、住在/不在、爱/恨、支持/反对、属于/不属于。
# 这里额外补了"不喜欢/不支持/不住在/不认识"这四个常见的否定写法 ——
# 它们和"住"系列是同一类语义，不补进去等于让最常见的否定句逃过检查。
# 注意：两个**否定**之间不许互斥（"不在"和"不住在"不是矛盾），
# 只有"肯定 ↔ 它的否定"才算。写错这一条，正常文本会被大面积误报成矛盾。
_MUTEX_PAIRS = (
    ("是", "不是"),
    ("喜欢", "讨厌"), ("喜欢", "不喜欢"),
    ("住在", "不在"), ("住在", "不住在"),
    ("爱", "恨"),
    ("支持", "反对"), ("支持", "不支持"),
    ("属于", "不属于"),
    ("认识", "不认识"),
)
_MUTEX = {}
for _x, _y in _MUTEX_PAIRS:                 # 建对称表：谁问都查得到
    _MUTEX.setdefault(_x, set()).add(_y)
    _MUTEX.setdefault(_y, set()).add(_x)
del _x, _y


# ==================================================================== 小工具
# 为什么把"取副本 / 安全取字段 / 名字相似"这类判断放在模块级私有函数：
# 实体表、关系图、check() 三处都要用同一份判断（尤其"像不像同一个名字"），
# 各写一份必然分叉 —— 于是会出现"实体表认为是一个人、check 认为是两个人"这种自相矛盾。
# 去掉集中：同一份数据在两处得到不同结论，用户看到的就是"它一会儿记得住一会儿记不住"。
def _clip(s, limit=_MAX_NAME):
    """规整成字符串并按上限截断（None → ""）。

    为什么截断而不是拒收：超长串多半是上游把整段文本当名字传进来了，
    拒收会让这条信息彻底消失，截断至少留下可追溯的前缀。
    去掉它（不设上限）：一次脏输入就能把巨大的字符串写进实体表并落盘，
    load 时每次都要把它全读进内存。
    """
    v = norm(s)
    if limit and len(v) > limit:
        return v[:limit]
    return v


def _is_cjk(ch):
    """是不是中日韩统一表意文字（单字）。"""
    return bool(ch) and "\u4e00" <= ch <= "\u9fff"


def _is_cjk_word(s):
    """整串都是汉字（空串不算）。

    为什么要求"整串"：抽出来的实体名必须是纯汉字才有确定性；
    混进数字/字母/空格的候选（"3-2-1"、"a b"）在长文里几乎都是别的结构被误切的结果。
    去掉它：实体表里会出现一堆半截数字串，check() 的"新实体"提示变成噪声。
    """
    s = norm(s)
    if not s:
        return False
    return all(_is_cjk(c) for c in s)


def _safe_int(v, default=0):
    """把任意值安全地读成 int（失败给默认值）。为什么需要：load 读到的可能是被手改坏的字段。"""
    try:
        return int(v)
    except Exception:      # noqa: silent-ok — 坏字段按默认值处理，不连累整条记录
        return default


def _safe_float(v, default=0.0):
    """把任意值安全地读成 float（失败给默认值）。"""
    try:
        return float(v)
    except Exception:      # noqa: silent-ok — 同上
        return default


def _safe_list(v):
    """把任意值安全地读成 list（只有 list/tuple 才算，其余给空表）。

    为什么不直接 `list(v)`：对字符串调用 `list("abc")` 会得到 ['a','b','c']，
    把"别名列表"悄悄变成单字表 —— 这类错误不会报错，只会让数据慢慢变形。
    去掉它：一次脏落盘就能让别名字段退化成字符数组。
    """
    if isinstance(v, (list, tuple)):
        return list(v)
    return []


def _safe_dict(v):
    """把任意值安全地读成 dict（其余给空字典）。"""
    return dict(v) if isinstance(v, dict) else {}


def _safe_kind(v):
    """把任意 kind 值归一到四个合法取值之一（非法 → object）。

    为什么非法值归一到 object 而不是报错：调用方传错 kind 是可预期的
    （上游可能把"地名"这种中文直接传进来），让整条添加操作失败比"当作物件记下来"糟得多。
    归一后原值会被记进条目里的 kind_raw，所以"上游传错了"这件事仍然查得到。
    去掉 kind_raw：错误会永久消失，下次再出问题只能重新猜。
    """
    k = norm(v).lower()
    return k if k in KINDS else KIND_OBJECT


def _entry_copy(e):
    """条目的深一层副本（只复制会变的字段）。

    为什么对外必须给副本：all() 的调用方（inject/check/save）只该读，
    万一有人顺手改了返回值，表里的真实数据就跟着变了 —— 这种污染极难定位。
    去掉它：一次 `for x in table.all(): x["name"] = ...` 就能静默改坏整张表。
    """
    if not isinstance(e, dict):
        return {}
    out = dict(e)
    out["aliases"] = [_clip(a) for a in _safe_list(e.get("aliases")) if _clip(a)]
    out["kinds_seen"] = [k for k in _safe_list(e.get("kinds_seen")) if k in KINDS]
    out["meta"] = _safe_dict(e.get("meta"))
    return out


def _lev(a, b):
    """编辑距离（只用于很短的汉字串，滚动数组实现）。

    为什么自己写而不是引库：本包禁止新增依赖；而这里只需要算 2~8 字的短串，
    手写 20 行的滚动数组足够快，也足够读懂。
    去掉它：就没法判"沈清"和"沈青"是同一个人的两种写法，
    check() 只剩"完全相等"这一条判据，换名字的检测形同虚设。
    """
    a, b = norm(a), norm(b)
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (0 if ca == cb else 1)))
        prev = cur
    return prev[-1]


def _name_similar(a, b):
    """两个名字是否"高度相似但不同"（长文换名字的判据）。

    三条规则，都需要**首字相同**：
      ① 一个是另一个的前缀（≥2 字）：沈清 / 沈清舟；
      ② 长度差 ≤1 且编辑距离 ≤1：沈清 / 沈青；
      ③ 都不短（≥4）且编辑距离 ≤2：欧阳明月 / 欧阳明玥。
    为什么硬性要求首字相同：中文姓氏几乎决定了"是不是同一个人"，
    放宽首字会让"李明"和"王明"被判成同一个人的两种写法 —— 误报比漏报更伤信任。
    去掉这个函数：check() 只剩"字符串完全相等"，
    而规格里"名字变了"的定义**恰恰是**"不相等但明显指同一个"。
    """
    a, b = _clip(a), _clip(b)
    if not a or not b or a == b:
        return False
    if a[0] != b[0]:
        return False
    if len(a) >= 2 and len(b) >= 2 and (a.startswith(b) or b.startswith(a)):
        return True
    if abs(len(a) - len(b)) <= 1 and _lev(a, b) <= 1:
        return True
    if min(len(a), len(b)) >= 4 and _lev(a, b) <= 2:
        return True
    return False


def _mutex(rel_a, rel_b):
    """两条关系是否互斥（同一对实体上不许同时成立）。

    为什么要一张显式的表而不是"关系词带'不'就算对立"：
    中文的否定形态不统一（不在/不住在/不喜欢），规则化推不出来。
    显式表虽然窄，但**不会误报** —— 而误报是这类功能最致命的失败模式。
    """
    rel_a, rel_b = _clip(rel_a), _clip(rel_b)
    if not rel_a or not rel_b or rel_a == rel_b:
        return False
    return rel_b in _MUTEX.get(rel_a, ())


def _num_like(s):
    """整串是不是"数字/量词"组成的（用来否掉"一号"这种假地名）。"""
    s = norm(s)
    if not s:
        return True
    return all(c in "一二三四五六七八九十百千万亿两零第几0123456789" for c in s)


# ==================================================================== 实体表
class EntityTable:
    """实体表：长文/长会话里"谁出现过、规范名叫什么、出现过几次、什么类型"。

    【为什么是"表 + 别名索引"而不是一个大 dict】
        别名索引（alias → 规范名）让 `get("沈清舟")` 命中"沈清"那一条，
        同时**别名不单独占条目** —— 否则 all() 会把同一个人算成两个人，
        数量统计和注入提示词全错。
    【为什么条目里要留 kinds_seen】
        同名重复添加只 count+1、不新增条目，所以**只记当前 kind 的话，
        "苹果"先被当物件、后被当人这件事会被后一次覆盖掉，永不报冲突**。
        这是本模块最容易漏的一处：冲突检测的全部依据就是历次 kind 的集合。
        去掉 kinds_seen：conflicts() 永远返回空表。
    """

    def __init__(self, entities=None):
        """`entities` 可选：同名字符串列表、条目字典列表，或 (名字, kind) 元组列表。

        为什么构造器要这么宽容：落盘文件是给人看也给人改的，
        上游也可能直接把 extract 的结果喂回来。宽容的读入让"手改坏一个字段"
        只丢一个字段，而不是整个表加载失败。去掉它：一次手抖 = 整表丢失。
        """
        self._items = []       # 规范条目；顺序 = 首次出现顺序（merge_alias 判先后靠它）
        self._index = {}       # 规范名 -> 条目（精确命中，O(1)）
        self._alias = {}       # 别名 -> 规范名（"同一个人不同写法"靠它命中）
        self._restore(entities)

    # ---------------------------------------------------------- 内部
    def _restore(self, entities):
        """从外部数据恢复条目；**一条坏数据只丢它自己**，绝不让整表加载失败。"""
        if entities is None:
            return
        if isinstance(entities, dict):
            seq = list(entities.values())
        elif isinstance(entities, (list, tuple)):
            seq = list(entities)
        else:
            return
        for raw in seq:
            try:
                if isinstance(raw, dict):
                    self._insert_raw(raw)
                elif isinstance(raw, str):
                    self.add(raw)
                elif isinstance(raw, (list, tuple)) and len(raw) >= 1:
                    self.add(raw[0], kind=(raw[1] if len(raw) > 1 else KIND_PERSON))
            except Exception:      # noqa: silent-ok — 单条坏数据不能连累整张表
                continue

    def _insert_raw(self, raw):
        """把一个"落盘形状"的条目直接放回表里（保留 first_seen/count/别名等历史）。

        为什么不走 add()：add() 只会 count+1，会把历史计数和别名丢掉 ——
        那样 load() 之后"越用越大"这件事就断了。去掉本函数：每次重启实体表都退化成空表。
        """
        name = _clip(raw.get("name"))
        if not name:
            return
        kind = _safe_kind(raw.get("kind"))
        exist = self.get(name)
        if exist is not None:
            # 已经有过同名（或它已经是某条目的别名）→ 只累加，绝不新建第二条
            exist["count"] = _safe_int(exist.get("count"), 0) + _safe_int(raw.get("count"), 1)
            for k in _safe_list(raw.get("kinds_seen")) or [kind]:
                ks = exist.setdefault("kinds_seen", [])
                if k in KINDS and k not in ks:
                    ks.append(k)
            for a in _safe_list(raw.get("aliases")):
                a = _clip(a)
                if a and a != exist.get("name") and a not in exist["aliases"]:
                    exist["aliases"].append(a)
                    self._alias[a] = exist["name"]
            return
        entry = {
            "name": name,
            "kind": kind,
            "first_seen": norm(raw.get("first_seen")),
            "aliases": [],
            "count": max(1, _safe_int(raw.get("count"), 1)),
            "ts": _safe_float(raw.get("ts"), now()),
            "meta": _safe_dict(raw.get("meta")),
            "kinds_seen": [],
        }
        kraw = norm(raw.get("kind_raw"))
        if kraw and kraw != kind:
            entry["kind_raw"] = kraw
        for k in _safe_list(raw.get("kinds_seen")) or [kind]:
            if k in KINDS and k not in entry["kinds_seen"]:
                entry["kinds_seen"].append(k)
        if kind not in entry["kinds_seen"]:
            entry["kinds_seen"].insert(0, kind)
        for a in _safe_list(raw.get("aliases"))[:_MAX_ALIASES]:
            a = _clip(a)
            if a and a != name and a not in entry["aliases"]:
                entry["aliases"].append(a)
        self._items.append(entry)
        self._index[name] = entry
        for a in entry["aliases"]:
            self._alias[a] = name

    # ---------------------------------------------------------- 写
    def add(self, name, kind="person", first_seen=""):
        """加一个实体（或给已有实体计数 +1）。

        返回：`{"ok","added","name","kind","canonical","count"}`；
        名字为空时返回 `{"ok": False, ...}` 并且**什么都不做**。
        为什么空名字必须拒绝而不是"存个空字符串"：空名字会被后续所有匹配命中
        （`"" in x` 恒真一类），一条空条目能污染整张表的查找结果。
        去掉这条检查：一次上游笔误就让整表长期带一条幽灵条目。
        为什么重复添加只 count+1 且**不覆盖 first_seen**：
        first_seen 是"这个人第一次被登记的时间"，是 merge_alias 判规范名的依据；
        被后来者覆盖，等于每次重复出现都"重新出生"，先出现的写法反而会被并掉。
        """
        n = _clip(name)
        if not n:
            return {"ok": False, "added": False, "name": "", "kind": "",
                    "canonical": "", "count": 0,
                    "reason": "名字为空 → 忽略（空名字会命中后面所有查找）"}
        k_raw = norm(kind).lower()
        k = k_raw if k_raw in KINDS else KIND_OBJECT
        entry = self.get(n)
        if entry is not None:
            entry["count"] = _safe_int(entry.get("count"), 0) + 1
            ks = entry.setdefault("kinds_seen", [])
            if k not in ks:
                ks.append(k)
            if k_raw and k_raw != k and not entry.get("kind_raw"):
                entry["kind_raw"] = k_raw
            return {"ok": True, "added": False, "name": n,
                    "kind": entry.get("kind"), "canonical": entry.get("name"),
                    "count": entry["count"]}
        entry = {
            "name": n,
            "kind": k,
            "first_seen": norm(first_seen),
            "aliases": [],
            "count": 1,
            "ts": now(),
            "meta": {},
            "kinds_seen": [k],
        }
        if k_raw and k_raw != k:
            entry["kind_raw"] = k_raw
        self._items.append(entry)
        self._index[n] = entry
        return {"ok": True, "added": True, "name": n, "kind": k,
                "canonical": n, "count": 1}

    def merge_alias(self, a, b):
        """把两种写法归一到同一条：`a` 与 `b` 是同一个人，只留**先出现的那个**当规范名。

        返回 `{"ok","canonical","alias","merged"}`；`a == b` 或任一方为空 → `ok=False` 且不改动。
        为什么任一方不存在要**自动补建**：调用方的信息来源常常不完整
        （比如只从记忆里捞到了"沈清舟"这一种写法，但用户其实第一次说的是"沈清"）。
        因为"没登记过"就失败，等于把一次本来正确的归一机会扔掉了。
        为什么要**传递闭包**：`b` 可能已经是第三条的别名（老王 = 王先生），
        不把那条一起并进来，all() 里就会剩下两条指向同一个人的条目 ——
        这正是本模块存在的意义（别名不占条目）被破坏的唯一方式。
        """
        na, nb = _clip(a), _clip(b)
        if not na or not nb:
            return {"ok": False, "canonical": na or nb, "alias": "", "merged": [],
                    "reason": "两边都要有名字才谈得上归一（空名字不参与合并）"}
        ea, eb = self.get(na), self.get(nb)
        if ea is None and eb is None:
            # 谁都没登记过：补建。kind 用 person —— 会被拿来归一别名的，基本是人名/称呼。
            self.add(na, kind=KIND_PERSON)
            self.add(nb, kind=KIND_PERSON)
            ea, eb = self.get(na), self.get(nb)
        elif ea is None:
            self.add(na, kind=(eb.get("kind") or KIND_PERSON))
            ea = self.get(na)
        elif eb is None:
            self.add(nb, kind=(ea.get("kind") or KIND_PERSON))
            eb = self.get(nb)
        if ea is None or eb is None:      # 理论上到不了这里；留一手，保证绝不抛
            return {"ok": False, "canonical": na, "alias": nb, "merged": [],
                    "reason": "补建后仍取不到条目"}
        if ea is eb:
            # 已经指向同一条（含"其中一个是另一个的别名"）→ 无事可做，如实返回 False
            return {"ok": False, "canonical": ea.get("name") or na,
                    "alias": (nb if nb != (ea.get("name") or "") else na), "merged": [],
                    "reason": "两种写法已经指向同一条条目"}
        if self._earlier(ea, eb):
            win, lose = ea, eb
        else:
            win, lose = eb, ea
        win_name = win.get("name") or ""
        lose_name = lose.get("name") or ""
        merged = []
        for nm in [lose_name] + _safe_list(lose.get("aliases")):
            nm = _clip(nm)
            if nm and nm != win_name and nm not in merged:
                merged.append(nm)
        aliases = [_clip(x) for x in _safe_list(win.get("aliases"))]
        aliases = [x for x in aliases if x and x != win_name]
        for nm in merged:
            if nm not in aliases:
                aliases.append(nm)
        win["aliases"] = aliases[:_MAX_ALIASES]
        win["count"] = (_safe_int(win.get("count"), 0)
                        + _safe_int(lose.get("count"), 0))
        ks = win.setdefault("kinds_seen", [])
        for k in _safe_list(lose.get("kinds_seen")):
            if k in KINDS and k not in ks:
                ks.append(k)
        wmeta = win.setdefault("meta", {})
        if not isinstance(wmeta, dict):
            wmeta = {}
            win["meta"] = wmeta
        for kk, vv in _safe_dict(lose.get("meta")).items():
            wmeta.setdefault(kk, vv)
        # first_seen 一律以 win 的为准（win 按定义就是"先出现的那个"），不做覆盖。
        # 为什么连"win 为空、lose 有值"也不填：填了就等于让后来者改写"首次"，
        # 而 first_seen 是 merge_alias 判先后的依据 —— 自己改自己的判据会形成环。
        # 从表里摘掉 lose：这只是内存里少一条，**不动磁盘上的任何东西**。
        self._items = [it for it in self._items if it is not lose]
        if self._index.get(lose_name) is lose:
            self._index.pop(lose_name, None)
        self._index[win_name] = win
        for nm in list(win["aliases"]) + merged:
            self._alias[nm] = win_name
        return {"ok": True, "canonical": win_name, "alias": lose_name,
                "merged": merged}

    def _earlier(self, x, y):
        """x 是否比 y 先出现：先比 first_seen（都有值且不同才比），否则比插入顺序。

        为什么两者都有 first_seen 时才用它比：first_seen 可能是空串
        （extract 抽出来的实体就没有时间），空串按字典序排在所有日期之前，
        那会让"后来才登记、但时间写得早"的条目永远赢 —— 这不是我们想要的口径。
        去掉插入顺序这层兜底：extract() 抽出来的整张表全都 first_seen=""，
        merge_alias 就没有任何依据判断先后，规范名会变得随机。
        """
        fx, fy = norm(x.get("first_seen")), norm(y.get("first_seen"))
        if fx and fy and fx != fy:
            return fx < fy
        ox, oy = -1, -1
        for i, it in enumerate(self._items):
            if it is x:
                ox = i
            elif it is y:
                oy = i
        if ox == -1 or oy == -1:
            return True
        return ox <= oy

    # ---------------------------------------------------------- 读
    def get(self, name, default=None):
        """按名字取条目（**别名也能取到**）；取不到返回 `default`（默认 None）。

        为什么带 `default` 参数（本可以是纯单参函数）：
            调用方读这张表时几乎总是"取不到就得有个兜底"——
            写成 `t.get(n) or {}` 也行，但十处调用就会有三种写法（`or {}` / `or None` / if 判断），
            早晚有一处忘了兜底变成 `None.get(...)` 崩掉。
            直接对齐 dict 的两参签名，是让**所有调用点写法一致**的最省事办法。
            别名回退这一步是"同一个人不同写法"功能的核心 ——
            去掉它，get("沈清舟") 会返回 None，调用方会以为表里没这个人，于是重复登记。
        """
        n = _clip(name)
        if not n:
            return default
        e = self._index.get(n)
        if e is not None:
            return e
        owner = self._alias.get(n)
        if owner is None:
            return default
        got = self._index.get(owner)
        return got if got is not None else default

    def all(self):
        """全部**规范条目**（副本，按首次出现顺序）。别名不单独占条目。"""
        return [_entry_copy(e) for e in self._items]

    def names(self):
        """全部规范名（按首次出现顺序）。给"注入提示词/做对比"用的轻量视图。"""
        return [e.get("name") or "" for e in self._items if e.get("name")]

    def conflicts(self):
        """同名不同 kind → 冲突（`[{"name","kinds","detail"}]`）。

        这里就是那个最容易漏的点：条目本身"同名不新增只 count+1"，
        所以冲突的唯一依据是条目里**历次出现过的 kind 集合**（kinds_seen）。
        若只记当前 kind，add("苹果", object) 后再 add("苹果", person) 会把
        object 直接覆盖成 person，conflicts() 永远空 —— 这个 bug 不会报错，
        只是功能静默失效，所以强烈建议保留 kinds_seen 的写入与自测。
        """
        out = []
        for e in self._items:
            ks = []
            for k in _safe_list(e.get("kinds_seen")):
                if k in KINDS and k not in ks:
                    ks.append(k)
            if len(ks) > 1:
                names = "、".join(KIND_CN.get(k, k) for k in ks)
                out.append({
                    "name": e.get("name") or "",
                    "kinds": ks,
                    "detail": "「%s」被登记过 %s 两种类型：同一个名字不可能既是人名又是"
                              "地名/时间/物件 —— 要么是同名不同物，要么上游把 kind 判错了。"
                              "先用 merge_alias 归一到具体的那个实体，或人工确认后重登记。"
                              % (e.get("name") or "", names),
                })
        return out

    def stats(self):
        """`{"entities","aliases","by_kind"}`：给自检和"越用越大"的观察用。"""
        by_kind = {}
        alias_n = 0
        for e in self._items:
            k = e.get("kind") if e.get("kind") in KINDS else KIND_OBJECT
            by_kind[k] = by_kind.get(k, 0) + 1
            alias_n += len(_safe_list(e.get("aliases")))
        return {"entities": len(self._items), "aliases": alias_n,
                "by_kind": by_kind, "conflicts": len(self.conflicts())}

    def __len__(self):
        """`len(table)` = 规范条目数（别名不算）。"""
        return len(self._items)

    def __contains__(self, name):
        """`"沈清舟" in table` —— 别名同样算在内（与 get 口径一致）。"""
        return self.get(name) is not None

    def __repr__(self):
        """给人看的短描述（日志里出现 EntityTable(...) 时能直接看出规模）。"""
        return "EntityTable(entities=%d, aliases=%d)" % (
            len(self._items), self.stats()["aliases"])


# ==================================================================== 关系图
class RelationGraph:
    """关系图：`a -[rel]-> b` 的集合，重复边只累加 count。

    【为什么键用 (a, b, rel) 三元组】
        关系是"有方向的标签边"。同名同关系的重复出现必须合并成一条（count+1），
        否则长文里同一句被重复 5 次就会变成 5 条边，"这条关系有多确定"就无从谈起。
    【为什么 contradictions() 要按"无序对"分组，却保留方向信息】
        规格要求把 `a-b` 与 `b-a` 去重成同一对 —— 因为矛盾往往是两个人对着说反话
        （"小明是医生"/"医生不是小明"）；但返回里仍要把原始方向带出来，
        否则人看到矛盾却不知道是谁在说谁。
    """

    def __init__(self, relations=None):
        """`relations` 可选：关系字典列表，或 (a, rel, b) 元组列表。"""
        self._items = []       # 保插入序，all()/relations_of() 顺序稳定
        self._index = {}       # (a, b, rel) -> 条目
        self._restore(relations)

    def _restore(self, relations):
        """从外部数据恢复关系；**一条坏数据只丢它自己**。"""
        if relations is None:
            return
        if isinstance(relations, dict):
            seq = list(relations.values())
        elif isinstance(relations, (list, tuple)):
            seq = list(relations)
        else:
            return
        for raw in seq:
            try:
                if isinstance(raw, dict):
                    self._insert_raw(raw)
                elif isinstance(raw, (list, tuple)) and len(raw) >= 3:
                    self.add(raw[0], raw[1], raw[2])
            except Exception:      # noqa: silent-ok — 单条坏关系不能连累整张图
                continue

    def _insert_raw(self, raw):
        """把一个"落盘形状"的关系放回图里（保留 count / ts）。"""
        a, rel, b = _clip(raw.get("a")), _clip(raw.get("rel")), _clip(raw.get("b"))
        if not a or not rel or not b:
            return
        key = (a, b, rel)
        count = max(1, _safe_int(raw.get("count"), 1))
        ts = raw.get("ts")
        ts = norm(ts) if isinstance(ts, str) else _safe_float(ts, now())
        e = self._index.get(key)
        if e is not None:
            e["count"] = _safe_int(e.get("count"), 0) + count
            return
        e = {"a": a, "b": b, "rel": rel, "ts": (ts or now()), "count": count}
        self._items.append(e)
        self._index[key] = e

    def add(self, a, rel, b, ts=""):
        """加一条 `a -[rel]-> b`；同名同关系重复添加只 count+1。

        `ts` 为空则用 now()。任一参数为空 → 安全返回 `{"ok": False, ...}`，不抛也不改图。
        为什么用 now() 当默认值而不是空串：时间戳是"这条边什么时候第一次被确认"的
        证据，缺了它就没法做"最近的关系优先"这类排序；而空串排在最前会让新边看起来最旧。
        """
        na, nrel, nb = _clip(a), _clip(rel), _clip(b)
        if not na or not nrel or not nb:
            return {"ok": False, "added": False, "a": na, "rel": nrel, "b": nb,
                    "count": 0,
                    "reason": "a/rel/b 任一为空 → 忽略（残缺边比对不上任何东西）"}
        key = (na, nb, nrel)
        e = self._index.get(key)
        if e is not None:
            e["count"] = _safe_int(e.get("count"), 0) + 1
            return {"ok": True, "added": False, "a": na, "rel": nrel, "b": nb,
                    "count": e["count"], "ts": e.get("ts")}
        _ts = norm(ts) or now()
        e = {"a": na, "b": nb, "rel": nrel, "ts": _ts, "count": 1}
        self._items.append(e)
        self._index[key] = e
        return {"ok": True, "added": True, "a": na, "rel": nrel, "b": nb,
                "count": 1, "ts": _ts}

    def relations_of(self, a):
        """与 `a` 相关的所有关系（**两个方向都算**：a 当主语和 a 当宾语）。

        为什么两个方向都要：用户问"沈清是什么人"时，
        "沈清-是->医生"和"李医生-认识->沈清"都是关于沈清的事实，
        只取一个方向会让答案凭空少一半。
        """
        na = _clip(a)
        if not na:
            return []
        out = []
        for e in self._items:
            if e.get("a") == na or e.get("b") == na:
                out.append(dict(e))
        return out

    def contradictions(self):
        """同一对实体上出现互斥关系 → `[{"a","b","rels","detail"}]`。

        实现上分两步：先按(无序)实体对分组，再在组内两两比互斥表。
        为什么必须按无序对分组：`add("小明","是","医生")` 与
        `add("医生","不是","小明")` 说的是同一件事，不归到一组就永远查不出矛盾。
        返回里的 a/b 取"先被登记的那条边"的方向，保证人看得出是谁说的谁。
        """
        groups = {}
        for e in self._items:
            a, b = _clip(e.get("a")), _clip(e.get("b"))
            if not a or not b:
                continue
            key = tuple(sorted((a, b)))
            groups.setdefault(key, []).append(e)
        out = []
        for key, edges in groups.items():
            n = len(edges)
            for i in range(n):
                for j in range(i + 1, n):
                    r1, r2 = _clip(edges[i].get("rel")), _clip(edges[j].get("rel"))
                    if not _mutex(r1, r2):
                        continue
                    first = edges[i]
                    out.append({
                        "a": first.get("a") or key[0],
                        "b": first.get("b") or key[1],
                        "rels": [r1, r2],
                        "detail": "「%s」与「%s」之间同时存在互斥关系「%s」和「%s」"
                                  "（%s / %s）—— 同一对实体不可能既成立又反过来，"
                                  "这两句里必有一句是错的。"
                                  % (key[0], key[1], r1, r2,
                                     "%s-%s->%s" % (edges[i].get("a"), r1, edges[i].get("b")),
                                     "%s-%s->%s" % (edges[j].get("a"), r2, edges[j].get("b"))),
                    })
        return out

    def all(self):
        """全部关系（副本，按首次添加顺序）。"""
        return [dict(e) for e in self._items]

    def stats(self):
        """`{"relations","pairs","contradictions"}`。"""
        pairs = set()
        for e in self._items:
            a, b = _clip(e.get("a")), _clip(e.get("b"))
            if a and b:
                pairs.add(tuple(sorted((a, b))))
        return {"relations": len(self._items), "pairs": len(pairs),
                "contradictions": len(self.contradictions())}

    def __len__(self):
        """`len(rels)` = 关系条数（重复边合并后的条数）。"""
        return len(self._items)

    def __contains__(self, key):
        """`("小明", "是", "医生") in rels` —— 与 add 的键口径完全一致。"""
        try:
            a, rel, b = key
        except Exception:      # noqa: silent-ok — 不是三元组就当"没有"
            return False
        return (_clip(a), _clip(b), _clip(rel)) in self._index

    def __repr__(self):
        """给人看的短描述。"""
        return "RelationGraph(relations=%d, pairs=%d)" % (
            len(self._items), self.stats()["pairs"])


# ==================================================================== 抽取工具
# 下面这一批函数只做"从字串里取出候选"。为什么不塞进类里：
# 它们不持有状态、只依赖字串与已占用区间，放模块级便于单独自测与复用；
# 塞进类里会逼着 extract 造一个只为调用它们而存在的对象。
def _spans_overlap(spans, s, e):
    """候选区间是否与已占用的区间重叠。

    为什么必须有"占位"机制：同一块文字会被多条规则同时看上
    （"2026年9月14日"里的"9月"、"济南市"里的"济南"）。
    不占位就会抽出同一段文字的好几个"实体"，实体表瞬间灌水，
    而 check() 会把它们全报成"新实体"。
    """
    for cs, ce in spans:
        if not (e <= cs or s >= ce):
            return True
    return False


def _in_spans(spans, i):
    """位置 i 是否落在某个已占用区间内。"""
    for cs, ce in spans:
        if cs <= i < ce:
            return True
    return False


def _cut_back(t, pos, limit, stops, spans=None):
    """从 pos 往左取最多 limit 个汉字，遇停字/非汉字/已占用区间即停。"""
    i = pos - 1
    chars = []
    while i >= 0 and len(chars) < limit:
        ch = t[i]
        if not _is_cjk(ch) or ch in stops:
            break
        if spans is not None and _in_spans(spans, i):
            break
        chars.append(ch)
        i -= 1
    return "".join(reversed(chars))


def _cut_fwd(t, pos, limit, stops, spans=None, stop_words=None):
    """从 pos 往右取最多 limit 个汉字，遇停字/非汉字/停用词/已占用区间即停。"""
    n = len(t)
    i = pos
    chars = []
    while i < n and len(chars) < limit:
        ch = t[i]
        if not _is_cjk(ch) or ch in stops:
            break
        if spans is not None and _in_spans(spans, i):
            break
        if stop_words:
            hit = False
            for w in stop_words:
                if t.startswith(w, i):
                    hit = True
                    break
            if hit:
                break
        chars.append(ch)
        i += 1
    return "".join(chars)


def _trim_lead(w):
    """削掉宾语前的指示词/量词（"这个方案" → "方案"）。

    为什么要削：指示词会让同一个宾语在不同句子里变成不同的实体名
    （"这个问题"/"那个问题"），而它们指的东西根本是同一个。
    去掉它：实体表里会出现"这个问题""那个问题"两条互不相干的条目。
    """
    w = norm(w)
    for pre in ("这个", "那个", "这些", "那些", "一个", "一种", "一位", "一些", "一下"):
        if w.startswith(pre) and len(w) > len(pre):
            return w[len(pre):]
    return w


def _find_times(t):
    """抽时间实体：绝对时间用正则，相对时间词用全包统一的 hits()。"""
    out = []
    for pat in _TIME_RES:
        try:
            for m in re.finditer(pat, t):
                w = re.sub(r"\s+", "", m.group(0))
                if w:
                    out.append((m.start(), m.end(), w, KIND_TIME))
        except Exception:      # noqa: silent-ok — 单个正则不匹配也不能中断抽取
            continue
    for w in hits(t, _REL_TIME_WORDS):
        i = t.find(w)
        if i >= 0:
            out.append((i, i + len(w), w, KIND_TIME))
    return out


def _find_quoted(t):
    """抽引号里的称呼/专名（2~4 字，纯汉字）。kind 交给上下文判（这里给 None）。"""
    out = []
    for pat in _QUOTE_RES:
        try:
            for m in re.finditer(pat, t):
                w = norm(m.group(1))
                if len(w) < 2 or not _is_cjk_word(w):
                    continue
                out.append((m.start(1), m.end(1), w, None))
        except Exception:      # noqa: silent-ok — 同上
            continue
    return out


def _guess_kind(name, t, s, e):
    """按上下文猜 kind：判不出就 person（规格要求）。

    为什么默认 person 而不是 object：引号里/被当作称呼的 2~4 字，
    绝大多数是人的称呼；默认 object 会让 inject() 把它们归到"物件"，
    提示词里写错分组，模型反而更容易用错。
    """
    after = t[e:e + 1]
    before = t[max(0, s - 4):s]
    if after in _PLACE_SUFFIXES:
        return KIND_PLACE
    if has_any(before, _PLACE_TRIGGERS):
        return KIND_PLACE
    if has_any(before, _REL_TIME_WORDS) or after in ("年", "月", "日", "号"):
        return KIND_TIME
    return KIND_PERSON


def _find_places(t, spans):
    """抽地名：① 后缀式（回扫取词）② 触发式（动词后面取词）。"""
    out = []
    emitted = set()
    # ① 后缀式
    try:
        for m in re.finditer(_PLACE_SUFFIX_RE, t):
            sfx = m.group(0)
            e = m.end()
            chunk = _cut_back(t, m.start(), 4, _LEFT_STOP_CHARS, spans)
            if not chunk or _num_like(chunk):
                continue
            s = m.start() - len(chunk)
            name = chunk + sfx
            if name in emitted or _spans_overlap(spans, s, e):
                continue
            emitted.add(name)
            out.append((s, e, name, KIND_PLACE))
    except Exception:      # noqa: silent-ok — 后缀扫描失败也不能让整次抽取失败
        pass
    # ② 触发式（"住在济南""来自山东""在济南上班"）
    for w in hits(t, _PLACE_TRIGGERS):
        try:
            for m in re.finditer(re.escape(w), t):
                p = m.end()
                if _in_spans(spans, p) or (p > 0 and _in_spans(spans, p - 1)):
                    continue
                chunk = _cut_fwd(t, p, 4, _RIGHT_STOP_CHARS, spans, _PLACE_FWD_STOP)
                name = _trim_lead(chunk)
                if len(name) < 2 or _num_like(name) or name in emitted:
                    continue
                s = p + (len(chunk) - len(name))
                e2 = p + len(chunk)
                if _spans_overlap(spans, s, e2) or not _is_cjk_word(name):
                    continue
                emitted.add(name)
                out.append((s, e2, name, KIND_PLACE))
        except Exception:      # noqa: silent-ok — 单个触发词出错不影响其它触发词
            continue
    return out


def _find_persons(t, spans):
    """抽中文人名：姓氏表 + 1~2 字，或"姓 + 称谓"。"""
    out = []
    n = len(t)
    i = 0
    while i < n:
        ch = t[i]
        if ch not in _SURNAME_SET or _in_spans(spans, i):
            i += 1
            continue
        got = None
        # ① 姓 + 称谓（李医生 / 王老师）—— 比通用规则可靠，优先
        for title in sorted(_TITLES, key=len, reverse=True):
            if t.startswith(title, i + 1):
                cand = ch + title
                if cand not in _NAME_STOP:
                    got = (i, i + len(cand), cand)
                break
        # ② 姓 + 1~2 字；先试 3 字，被否掉再退回 2 字
        if got is None:
            for ln in (3, 2):
                if i + ln > n:
                    continue
                cand = t[i:i + ln]
                if not _is_cjk_word(cand):
                    continue
                if cand[-1] in _BAD_TAIL or cand in _NAME_STOP:
                    continue
                if ln == 3 and cand[1] in _BAD_TAIL:
                    continue
                if _spans_overlap(spans, i, i + ln):
                    continue
                if _num_like(cand):
                    continue
                got = (i, i + ln, cand)
                break
        if got is None:
            i += 1
            continue
        out.append((got[0], got[1], got[2], KIND_PERSON))
        i = got[1]          # 跳过已认出的名字，避免从"沈清"里面再切出一个"清X"
    return out


def _subject_before(t, pos, ents):
    """关系词左边的主语：先看代词，再取最近的实体，最后兜底取词。

    代词这一步是本模块少见的"懂一点汉语"的地方，但很值：
    "沈清是医生，他住在济南"里，住在的主语是"他"——
    只看最近的实体只会得到"医生"，抽出的边就变成"医生住在济南"（错的）。
    规则是：紧邻关系词前两字里有代词 → 用**此前最后一个 person 实体**。
    去掉它：一旦句子用了代词，前后两个实体的关系就接错，关系图越用越脏。
    """
    tail = t[max(0, pos - 2):pos]
    if has_any(tail, ("他", "她", "它", "其", "他们", "她们")):
        for s, e, name, kind in reversed(ents):
            if e <= pos and kind == KIND_PERSON:
                return name
    best = None
    for s, e, name, kind in ents:
        if e <= pos and (pos - e) <= _REL_WINDOW and not _in_spans([(e, pos)], s):
            if best is None or e > best[0]:
                best = (e, name)
    if best is not None:
        return best[1]
    chunk = _cut_back(t, pos, _MAX_OBJ, _LEFT_STOP_CHARS)
    chunk = _trim_lead(chunk)
    if len(chunk) >= 2 and _is_cjk_word(chunk):
        return chunk
    return ""


def _object_after(t, pos, ents):
    """关系词右边的宾语：先取最近的实体，再兜底取词。"""
    best = None
    for s, e, name, kind in ents:
        if s >= pos and (s - pos) <= _REL_WINDOW:
            if best is None or s < best[0]:
                best = (s, name)
    if best is not None:
        return best[1]
    chunk = _cut_fwd(t, pos, _MAX_OBJ, _RIGHT_STOP_CHARS)
    chunk = _trim_lead(chunk)
    if chunk and _is_cjk_word(chunk):
        return chunk
    return ""


def _trim_place(w):
    """把"济南市历下区"这类长串在第一个行政后缀处断开，取"济南市"。"""
    w = norm(w)
    if not w:
        return ""
    for i, ch in enumerate(w):
        if ch in ("省", "市", "县", "区"):
            return w[:i + 1]
    return w


# ==================================================================== 抽取主函数
def extract(text):
    """纯规则抽取：一段中文 → `(EntityTable, RelationGraph)`。

    **绝不调用模型**。理由见模块 docstring：一致性判断的可信度来自确定性，
    用一个会犯错的东西去查另一个会犯错的东西，只会把错误变成不可复现的。

    返回的表和图中：每个实体是独立条目、别名不占条目、重复出现只 count+1。
    `text=None`（或全空白）→ 返回空表 + 空图，绝不抛。
    """
    t = norm(text)[:_MAX_SCAN]
    table, graph = EntityTable(), RelationGraph()
    if not t:
        return table, graph

    spans = []      # 已占用的字符区间，防止同一段文字被两条规则重复认领
    occ = []        # (start, end, name, kind) —— 抽到的实体，最后按出现位置入表

    # ① 时间（结构最明确，先占位，免得"9月"被当成地名/人名的一部分）
    for s, e, name, kind in sorted(_find_times(t), key=lambda x: (x[0], -(x[1] - x[0]))):
        if not name or _spans_overlap(spans, s, e):
            continue
        if any(o[2] == name for o in occ):
            continue
        spans.append((s, e))
        occ.append((s, e, name, KIND_TIME))

    # ② 引号里的称呼（优先级高于通用人名，因为引号本身是强信号）
    for s, e, name, kind in sorted(_find_quoted(t), key=lambda x: (x[0], -(x[1] - x[0]))):
        if _spans_overlap(spans, s, e) or any(o[2] == name for o in occ):
            continue
        spans.append((s, e))
        occ.append((s, e, name, kind or _guess_kind(name, t, s, e)))

    # ③ 地名（后缀式优先，因为它比触发式更精确：有"市/县/医院"这类明确标记）
    for s, e, name, kind in sorted(_find_places(t, spans), key=lambda x: (x[0], -(x[1] - x[0]))):
        if _spans_overlap(spans, s, e) or any(o[2] == name for o in occ):
            continue
        spans.append((s, e))
        occ.append((s, e, name, KIND_PLACE))

    # ④ 人名
    for s, e, name, kind in sorted(_find_persons(t, spans), key=lambda x: (x[0], -(x[1] - x[0]))):
        if _spans_overlap(spans, s, e) or any(o[2] == name for o in occ):
            continue
        spans.append((s, e))
        occ.append((s, e, name, KIND_PERSON))

    # 按出现位置入表：**顺序就是"首次出现顺序"**，merge_alias 判规范名要靠它。
    # 如果按"先时间后地名后人名"的抽取顺序入表，第一段的"济南"会排在
    # 第一句开头的"沈清"前面 —— 规范名判定就跟原文顺序对不上了。
    occ.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    for s, e, name, kind in occ:
        table.add(name, kind=kind)

    ents = list(occ)      # 关系抽取用的实体表（顺序即出现顺序）

    # ⑤ "在 X 工作/上班" —— 规格点名的关系写法，单独走一遍
    if has_any(t, _WORK_VERBS):
        try:
            for m in re.finditer(_WORK_RE, t):
                raw_place = _trim_place(m.group(1))
                if len(raw_place) < 2 or _num_like(raw_place):
                    continue
                ps = m.start(1)
                subj = _subject_before(t, m.start(), ents)
                if not subj:
                    continue
                graph.add(subj, "在…工作", raw_place)
                if not _spans_overlap(spans, ps, ps + len(raw_place)):
                    spans.append((ps, ps + len(raw_place)))
                    table.add(raw_place, kind=KIND_PLACE)
                    ents.append((ps, ps + len(raw_place), raw_place, KIND_PLACE))
        except Exception:      # noqa: silent-ok — 这一条规则失败不影响主关系抽取
            pass

    # ⑥ 关系词 → 边。正则的分支已按长度倒排，"不是"不会被读成"是"。
    try:
        for m in _REL_RE.finditer(t):
            rel = m.group(0)
            subj = _subject_before(t, m.start(), ents)
            if not subj:
                continue
            obj = _object_after(t, m.end(), ents)
            if not obj or obj == subj:
                continue
            graph.add(subj, rel, obj)
            # 兜底取来的词也登记进实体表（否则 check() 里"新实体"永远查不到它，
            # 而 inject() 也就永远不知道有这个宾语存在）
            for nm, kd in ((subj, None), (obj, None)):
                if table.get(nm) is None:
                    table.add(nm, kind=(kd or KIND_OBJECT))
    except Exception:      # noqa: silent-ok — 关系抽取失败时至少保住实体表
        pass

    return table, graph


# ==================================================================== 生成前注入
def inject(table, prompt):
    """生成**前**把已知实体喂进提示词：列出规范名 + 全部别名，要求模型一律用规范名。

    - 表为空时**如实**说明"本会话还没有已登记实体"，绝不假装有；
    - `prompt=None` 当作空提示词，不抛。

    为什么把实体块放在原提示词**前面**：模型的注意力对"后出现的指令"更敏感，
    而这里最需要压住的是"别换名字"这条约束 —— 把它放在开头当上下文，
    用户真正的问题留在最后，模型读到的顺序是"先知道有哪些人，再回答具体问题"。
    去掉这一步（不注入）：等于把"记住名字"这件事全压给模型自己，
    8000 字以后换名字是必然而不是意外 —— 这正是本模块要消灭的失败模式。
    """
    p = norm(prompt)
    entries = _table_all(table)
    lines = ["【已登记实体（写长文时必须沿用，一律使用规范名）】"]
    if not entries:
        lines.append("· 本会话还没有已登记实体 —— 这是事实，不要凭空假设人名、地名和时间；")
        lines.append("  也不要用不同写法指同一个人。新出现的重要人物/地点请保持一致写法。")
    else:
        groups = {KIND_PERSON: [], KIND_PLACE: [], KIND_TIME: [], KIND_OBJECT: []}
        for e in entries:
            if not isinstance(e, dict):
                continue
            k = e.get("kind") if e.get("kind") in KINDS else KIND_OBJECT
            groups[k].append(e)
        for k in (KIND_PERSON, KIND_PLACE, KIND_TIME, KIND_OBJECT):
            if not groups[k]:
                continue
            lines.append("· %s：" % KIND_CN[k])
            for e in groups[k]:
                name = norm(e.get("name"))
                if not name:
                    continue
                seg = "  - %s" % name
                aliases = [a for a in _safe_list(e.get("aliases")) if norm(a)]
                if aliases:
                    seg += "（别名：%s → 一律写成「%s」）" % ("、".join(aliases), name)
                cnt = _safe_int(e.get("count"), 0)
                if cnt > 1:
                    seg += "（已出现 %d 次）" % cnt
                lines.append(seg)
        lines.append("【硬要求】上面括号里的写法**一律不许用**，只用规范名；"
                     "需要提新人新地点时，先想清楚它是不是上表里的某个人，"
                     "拿不准就沿用上表里已经出现过的写法，不要自己造新名字。")
    head = "\n".join(lines)
    if not p:
        return head
    return head + "\n\n" + p


# ==================================================================== 生成后校验
def _table_all(tbl):
    """安全地取表里全部条目（表可能是 None、也可能是个不认识的脏对象）。"""
    try:
        v = tbl.all() if tbl is not None else []
        return v if isinstance(v, list) else []
    except Exception:      # noqa: silent-ok — 拿不到表就当空表（会让 check 退化为"全是新实体"）
        return []


def _table_get(tbl, name):
    """安全地按名字取条目（失败返回 None，绝不抛）。"""
    try:
        v = tbl.get(name) if tbl is not None else None
        return v if isinstance(v, dict) else None
    except Exception:      # noqa: silent-ok — 同上
        return None


def _canon_of(tbl, name):
    """把文本里的写法转成表里的规范名（表里没有就原样返回）。"""
    e = _table_get(tbl, name)
    if e is not None:
        cn = norm(e.get("name"))
        if cn:
            return cn
    return norm(name)


def check(text, table, rels):
    """生成**后**校验：`{"ok", "issues", "names_varied"}`。

    三类 issue：
      · "名字变了"   —— 用了表里某实体的别名，或跟规范名高度相似但不同（沈清/沈清舟/沈青）；
      · "新实体"     —— 表里没有的实体（这是**提示**，可能是新信息，不算错）；
      · "关系矛盾"   —— 文本里的边与 rels 里已有的边互斥，或文本自己前后打脸。
    `ok` = 没有"名字变了"和"关系矛盾"（"新实体"不计入）。
    `text`/`table`/`rels` 任一为 None 都不抛。

    为什么"新实体"不算错：长文本本来就会引入新角色，
    把它当错误会让这个功能在每一段新内容上误报，用户三次之后就再也不看报告了。
    宁可少报（漏掉真错），不可多报（让用户不信）—— 这是本模块的基本取舍。
    """
    t = norm(text)
    result = {"ok": True, "issues": [], "names_varied": False}
    if not t:
        return result
    try:
        sub_table, sub_graph = extract(t)
    except Exception:      # noqa: silent-ok — 抽不出东西就没什么可校验的，返回"通过"
        return result

    issues = []
    names_varied = False
    seen = set()

    # ---------------------------------------------------------- ① 名字变了 / 新实体
    canon_names = []
    for e in _table_all(table):
        if isinstance(e, dict) and norm(e.get("name")):
            canon_names.append((norm(e.get("name")),
                                e.get("kind") if e.get("kind") in KINDS else KIND_OBJECT))
    for e in sub_table.all():
        nm = norm(e.get("name"))
        if not nm:
            continue
        kind = e.get("kind") if e.get("kind") in KINDS else KIND_OBJECT
        owner = _table_get(table, nm)
        if owner is not None:
            cn = norm(owner.get("name")) or nm
            if cn != nm and ("alias", nm) not in seen:
                # 用了表里登记过的别名：系统知道这是同一个人，但**生成本该用规范名**。
                # 之所以还算"名字变了"：用户读到的是两个不同的写法，
                # 这正是要消灭的现象；别名表是用来帮系统认人的，不是让模型随便挑一个用。
                seen.add(("alias", nm))
                names_varied = True
                issues.append({
                    "kind": "名字变了", "name": nm, "canonical": cn,
                    "detail": "文本里用了「%s」，它与已登记的「%s」是同一个人（别名）。"
                              "请统一写成规范名「%s」。" % (nm, cn, cn),
                })
            continue
        alike = ""
        for cn, ck in canon_names:
            if ck == kind and _name_similar(nm, cn):
                alike = cn
                break
        if alike and ("alike", nm) not in seen:
            seen.add(("alike", nm))
            names_varied = True
            issues.append({
                "kind": "名字变了", "name": nm, "canonical": alike,
                "detail": "文本里的「%s」跟已登记的「%s」只差一两个字 —— "
                          "长文里最常见的「换名字」就是这个样子。请统一成「%s」。"
                          % (nm, alike, alike),
            })
        elif not alike and ("new", nm) not in seen:
            seen.add(("new", nm))
            issues.append({
                "kind": "新实体", "name": nm, "kind_of": kind,
                "detail": "文本里出现了表里没有的「%s」（%s）。这**不是错误**："
                          "可能是新引入的角色/地点，也可能只是同一个人的新写法 —— "
                          "确认后 merge_alias 登记一下，下次就能认出来了。"
                          % (nm, KIND_CN.get(kind, kind)),
            })

    # ---------------------------------------------------------- ② 关系矛盾
    def _pair(a, b):
        return tuple(sorted((norm(a), norm(b))))

    for e in sub_graph.all():
        a = _canon_of(table, e.get("a"))
        b = _canon_of(table, e.get("b"))
        rel = norm(e.get("rel"))
        if not a or not b or not rel or a == b:
            continue
        cands = []
        try:
            if isinstance(rels, RelationGraph):
                cands = rels.relations_of(a) + rels.relations_of(b)
        except Exception:      # noqa: silent-ok — 已有关系图取不到就只查文本内部矛盾
            cands = []
        for c in cands:
            if not isinstance(c, dict):
                continue
            ca, cb, cr = norm(c.get("a")), norm(c.get("b")), norm(c.get("rel"))
            if _pair(a, b) != _pair(ca, cb):
                continue
            if not _mutex(rel, cr):
                continue
            key = ("rel", _pair(a, b), rel, cr)
            if key in seen:
                continue
            seen.add(key)
            issues.append({
                "kind": "关系矛盾",
                "a": a, "b": b, "rels": [rel, cr],
                "detail": "文本说「%s -%s-> %s」，而已登记的关系是「%s -%s-> %s」—— "
                          "同一对实体上两条互斥关系不可能同时成立，其中一句是错的。"
                          % (a, rel, b, ca, cr, cb),
            })

    for c in sub_graph.contradictions():
        key = ("self", c.get("a"), c.get("b"), tuple(c.get("rels") or []))
        if key in seen:
            continue
        seen.add(key)
        issues.append({
            "kind": "关系矛盾",
            "a": c.get("a"), "b": c.get("b"), "rels": list(c.get("rels") or []),
            "detail": "这段文本自己前后打脸：%s" % (c.get("detail") or ""),
        })

    bad = ("名字变了", "关系矛盾")
    result["issues"] = issues
    result["names_varied"] = names_varied
    result["ok"] = not any(i.get("kind") in bad for i in issues)
    return result


# ==================================================================== 落盘
def _default_path():
    """默认落盘位置：`logs/boost/consistency.json`。

    为什么不把路径在 import 期算成常量：boost_path 依赖 core.boost 的仓库根推断，
    把它固化在模块顶层，一旦有人以别的方式加载本模块（软链、打包），
    路径就会指向一个不存在的地方，而且**没有任何提示**。
    去掉它（不兜底）：boost_path 一旦抛异常，save/load 会整条挂掉。
    """
    try:
        return boost_path("consistency.json")
    except Exception:      # noqa: silent-ok — 拼路径失败也要给一个能用的相对路径
        return os.path.join("logs", "boost", "consistency.json")


def save(table, rels, path=None):
    """把实体表 + 关系图写进 `logs/boost/consistency.json`，返回 True/False（**绝不抛**）。

    格式：`{"version":1,"updated_at":<float>,"entities":[...],"relations":[...]}`
    为什么带 version：表的结构以后一定会加字段（比如给实体加重要性），
    有版本号才能在 load 时区分"这是老格式"还是"这是被改坏的"。
    去掉它：将来一次结构升级就会把老文件误判成损坏，整表被当成空表丢掉。
    为什么**直写**（不做 tmp+rename）：Windows 上 rename 要覆盖目标，
    语义上接近"删掉旧文件"，而本层有一条硬规矩是绝不删除任何文件。
    写坏了下一次写会覆盖回来，代价远小于违反那条规矩。
    """
    try:
        p = path or _default_path()
        ents = _table_all(table)
        rel_list = []
        try:
            v = rels.all() if rels is not None else []
            rel_list = v if isinstance(v, list) else []
        except Exception:      # noqa: silent-ok — 取不到关系就只存实体表
            rel_list = []
        obj = {"version": 1, "updated_at": now(),
               "entities": ents, "relations": rel_list}
        return bool(write_json(p, obj))
    except Exception:      # noqa: silent-ok — 落盘失败只是"这次没记住"，绝不能连累对话
        return False


def load(path=None):
    """从 `logs/boost/consistency.json` 读回 `(EntityTable, RelationGraph)`。

    读不到 / 坏了 / 结构不对 → 返回 `(EntityTable(), RelationGraph())`，**绝不抛**。
    为什么不在这里"报错提示"：调用方（生成前的注入）在热路径上，
    它需要的是"尽力给出已知实体"，文件坏掉只该退化成"这次没有已知实体"，
    绝不该让整轮回答失败。
    """
    try:
        p = path or _default_path()
        raw = read_json(p, None)
        if not isinstance(raw, dict):
            return EntityTable(), RelationGraph()
        return EntityTable(raw.get("entities")), RelationGraph(raw.get("relations"))
    except Exception:      # noqa: silent-ok — 读不动等价于"没有历史"，不是错误
        return EntityTable(), RelationGraph()


__all__ = [
    "KIND_PERSON", "KIND_PLACE", "KIND_TIME", "KIND_OBJECT", "KINDS", "KIND_CN",
    "EntityTable", "RelationGraph", "extract", "inject", "check", "save", "load",
]
