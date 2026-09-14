# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 跨领域联想（模块 10.3）

【这段为什么这么设计】
    小模型只会"就事论事"。用户问"水管压力不够怎么办"，它只会在水管里找答案，
    永远想不到"这跟电路里电压不够是同一个结构" —— 这不是它笨，
    是**载体没给它这张对照表**。人类专家的类比能力拆开来只有两步：
      ① 把这句话**定位到一个领域**（在聊电路？水管？还是免疫？）—— 查词表 + 打分；
      ② 拿**结构映射表**把 A 领域的说法逐对翻成 B 领域的说法（电压≈水压、电流≈流量）。
    两步都是纯查表，零模型依赖、零随机。所以本模块把它做成"表 + 打分"：
    `DOMAINS` 负责定位（领域 → 概念词），`STRUCTURE_MAP` 负责翻译（领域 → 领域 + 词对）。

【去掉它会怎样】
    系统里就只剩"跟这句最像的另一句"（向量检索）这一种联想：
      · 它能把"水管"联想到另一段提到水管的记忆，但**永远联想不出电路**；
      · 用户问 A 领域的难题时，模型拿不到 B 领域的现成解法，只能从零硬编 ——
        4B 模型从零硬编的结果，就是"正确的废话"（听上去对、但一句可执行的话都没有）。

【为什么映射库必须能追加（越用越大）】
    内置的十来条映射是"人类常识里最稳的那几张"（电路≈水管、免疫≈安全、市场≈生态）。
    真正的价值在于：用户在对话里**认可过的**类比能存回 `logs/boost/maps.json`，
    下次遇到同结构的问题直接复用。去掉落盘，本模块就退化成一张写死的常量表，
    用一年也不会比第一天多懂一个类比 —— 这正是公式④（结果存回结构）要防的事。

【数据落盘】（logs/ 已被 .gitignore 忽略，不脏仓库）
    logs/boost/maps.json     追加的结构映射（内置映射不写盘，只写"用户追加/覆盖"的部分）
    logs/boost/boost.jsonl   事件流水（走公共 note()）
【绝不删除任何文件】
    本模块只"读 + 覆盖写 + 追加写"，全程没有 os.remove / unlink / rmtree，
    也不做 tmp+rename（Windows 上 rename 覆盖语义等同删掉旧文件）。
"""
from . import boost_dir, boost_path, norm, cjk_count, bigrams, hits, has_any, weighted_hits, now
# 事件流水函数**换个名字导入**（`note_event`），把 `note` 这个名字让给业务参数。
# 为什么这么做而不是把参数改名：`add_map(..., note="...")` 是对外契约的一部分
# （自测与调用方都按这个关键字传），改名会打破调用方；而内部的流水函数名
# 只有本文件在用，改它零成本。**优先改"没人依赖的那个名字"**，这是兼容性直觉。
from . import note as note_event
from . import append_jsonl, read_jsonl, read_json, write_json

__all__ = ["DOMAINS", "STRUCTURE_MAP", "domain_vector", "best_domain",
           "list_maps", "add_map", "map_structure", "analogies"]

# 上面两行 import 里的 `bigrams` / `has_any` / `boost_dir` / `append_jsonl` /
# `read_jsonl` / `cjk_count` 本模块**暂时用不上**，但依然从公共层拿而不是各写一份：
# 领域打分、模板选型、模糊判据将来都要用同一套"命中口径"，
# 一旦某个模块自己写一个 has_any，就出现了第二种口径 —— 同一句话在两个模块里
# 命中数不一样。这是最容易发生、也最难查的一类不一致。
# 去掉这几行改成本地实现：口径立刻分叉，而且没人会同时改两个文件。
# noqa: F401

# ------------------------------------------------------------------ 领域词表
# 为什么是"领域 → 概念词表"这种最朴素的结构，而不是向量、不是模型：
#   ① 它可读。出问题时能一眼看出"它为什么把这句话判成电路"；
#   ② 它可改。用户说"我们这行管这个叫 X"，往表里加一个词就行；
#   ③ 它确定性。同一句话永远同一个分数，自测不会因为模型换了就挂。
# 去掉它改用"让模型判领域"：每次都要花一次推理的时间，结论还会飘 ——
# 而定位领域这一步是**后续所有翻译的前提**，前提一飘，后面全飘。
#
# 排序即优先级：dict 保持插入顺序，`best_domain` 并列时取**先定义**的那个领域，
# 所以前 10 个是必须有的常见领域，最后两个是补充。顺序写在这里、别随手调，
# 调了会改变并列时的结论（同一句话可能从"电路"变成"网络"）。
DOMAINS = {
    "电路": ["电压", "电流", "电阻", "电容", "短路", "回路", "开关", "负载",
             "保险丝", "并联", "串联", "电感"],
    "水管": ["水压", "流量", "管道", "水泵", "阀门", "水管", "水塔", "漏水",
             "管径", "水箱", "堵塞", "疏通"],
    "免疫": ["抗体", "病毒", "疫苗", "白细胞", "免疫", "抗原", "淋巴细胞",
             "感染", "发炎", "排异", "病原体"],
    "安全": ["防火墙", "攻击者", "补丁", "漏洞", "入侵", "加密", "密码",
             "权限", "木马", "钓鱼", "隔离", "审计"],
    "市场": ["价格", "供需", "竞争", "垄断", "利润", "商家", "需求", "供给",
             "份额", "涨价", "降价", "买家", "卖家", "库存"],
    "生态": ["食物链", "顶级掠食者", "物种", "生境", "种群", "天敌", "养分",
             "演替", "灭绝", "生态位", "降水", "植被"],
    "建筑": ["地基", "承重墙", "梁柱", "外墙", "屋顶", "门窗", "楼层", "拆迁",
             "通风", "保温层", "脚手架", "施工"],
    "人体": ["血压", "血流", "心脏", "血管", "骨骼", "关节", "脊柱", "神经",
             "皮肤", "体温", "肌肉", "呼吸"],
    "交通": ["路口", "主干道", "堵车", "信号灯", "车道", "收费站", "限流",
             "车祸", "航线", "枢纽", "通行", "运输"],
    "农业": ["灌溉", "施肥", "播种", "收割", "化肥", "害虫", "轮作", "土壤",
             "歉收", "粮仓", "订单", "收成"],
    "网络": ["带宽", "延迟", "数据包", "服务器", "端口", "协议", "路由",
             "缓存", "丢包", "宽带"],
    "教育": ["课程", "老师", "学生", "考试", "作业", "教材", "课堂", "复习",
             "家长", "学分", "成绩", "培养"],
}

# 领域打分的归一化分母：命中这么多概念词就算"满分"（1.0）。
# 为什么是 3 而不是"命中数 / 该领域词表长度"：词表长度参差不齐（10~14 个），
# 用它当分母会让长词表的领域天然吃亏 —— 同一句话在"网络"上比在"教育"上分数低，
# 纯属词表写长了。固定分母让所有领域**站在同一条起跑线上**。
# 去掉它（不归一化，直接用命中数排序）在只比大小时结论一样，
# 但对外暴露的 score 会变成"命中 2 个词"这种不可解释的量，
# 而下游（以及日志）需要的是 [0,1] 的解释性分数。
_DOMAIN_DEN = 3.0

# ------------------------------------------------------------------ 结构映射库
# 每条的字段含义（下游全靠这几个字段，多一个少一个都会让 map_structure 出错）：
#   id     稳定标识。用户追加的映射靠它做"同 id 覆盖、不同 id 追加"的合并。
#   from   源领域；to 目标领域。**只是这条记录的写法**，映射函数双向都用得。
#   note   中文一句话：为什么这两个领域同构。给人和模型看的理由，不参与计算。
#   pairs  [源说法, 目标说法] 的列表，≥3 对，用"两元素 list"而不是 dict：
#          dict 的键会去重/丢顺序，而"电压→水压、电流→流量"的**顺序本身**
#          就是给人读的推导顺序，必须能原样保序、原样落盘。
STRUCTURE_MAP = [
    {
        "id": "circuit_water", "from": "电路", "to": "水管",
        "note": "电压推动电流克服电阻，水压推动流量克服管径阻力 —— 两者是同一个守恒方程",
        "pairs": [["电压", "水压"], ["电流", "流量"], ["电阻", "管径"],
                  ["电容", "水箱"], ["短路", "爆管"], ["开关", "阀门"],
                  ["负载", "用水设备"]],
    },
    {
        "id": "immune_security", "from": "免疫", "to": "安全",
        "note": "身体识别并清除入侵者，安全系统识别并拦截攻击者 —— 都是「识别-拦截-记忆」闭环",
        "pairs": [["抗体", "防火墙"], ["病毒", "攻击者"], ["疫苗", "补丁"],
                  ["感染", "入侵"], ["抗原", "攻击特征"], ["发炎", "告警"]],
    },
    {
        "id": "market_ecology", "from": "市场", "to": "生态",
        "note": "资源有限下的争夺与淘汰，供需关系就是食物链里的能量流动",
        "pairs": [["竞争", "竞争"], ["供需", "食物链"], ["垄断", "顶级掠食者"],
                  ["份额", "生态位"], ["淘汰", "灭绝"]],
    },
    {
        "id": "building_body", "from": "建筑", "to": "人体",
        "note": "都要靠骨架承重、靠外壳防护、靠管道输送 —— 结构受力与人体支撑是同一类问题",
        "pairs": [["地基", "骨架"], ["承重墙", "脊柱"], ["外墙", "皮肤"],
                  ["屋顶", "头顶"], ["管道", "血管"]],
    },
    {
        "id": "water_body", "from": "水管", "to": "人体",
        "note": "水泵=心脏、阀门=瓣膜、水压=血压 —— 循环系统本来就是一套液压系统",
        "pairs": [["管道", "血管"], ["水泵", "心脏"], ["阀门", "瓣膜"],
                  ["水压", "血压"], ["流量", "血流"]],
    },
    {
        "id": "circuit_body", "from": "电路", "to": "人体",
        "note": "靠压力差驱动流体、靠阻力限制流量、靠保险丝自我保护 —— 神经与循环都按这套走",
        "pairs": [["电压", "血压"], ["电流", "血流"], ["电阻", "血管阻力"],
                  ["保险丝", "痛觉"], ["回路", "循环系统"]],
    },
    {
        "id": "traffic_market", "from": "交通", "to": "市场",
        "note": "都是「资源在有限通道里流动」，拥堵、限流、收费对应供不应求、配额、交易成本",
        "pairs": [["堵车", "供不应求"], ["车道", "渠道"], ["收费站", "交易成本"],
                  ["限流", "配额"], ["枢纽", "交易中心"]],
    },
    {
        "id": "agriculture_market", "from": "农业", "to": "市场",
        "note": "产量对应供给、歉收对应短缺、粮仓对应库存 —— 生产端与流通端的同一个节律",
        "pairs": [["收成", "供给"], ["歉收", "短缺"], ["化肥", "投入"],
                  ["害虫", "风险"], ["粮仓", "库存"]],
    },
    {
        "id": "building_ecology", "from": "建筑", "to": "生态",
        "note": "地基=土壤、承重结构=关键物种 —— 一旦抽掉承重者，整体结构一起塌",
        "pairs": [["地基", "土壤"], ["承重墙", "关键物种"], ["通风", "气流"],
                  ["保温层", "植被"]],
    },
    {
        "id": "network_traffic", "from": "网络", "to": "交通",
        "note": "带宽=车道、数据包=车辆、路由=路口 —— 网络拥塞与道路拥堵是同一个排队论问题",
        "pairs": [["带宽", "车道"], ["延迟", "通行时间"], ["数据包", "车辆"],
                  ["丢包", "堵车"], ["路由", "路口"]],
    },
    {
        "id": "agriculture_ecology", "from": "农业", "to": "生态",
        "note": "灌溉=降水、化肥=养分、轮作=演替 —— 农田本就是被人类接管的一片生态",
        "pairs": [["灌溉", "降水"], ["化肥", "养分"], ["害虫", "被捕食者"],
                  ["轮作", "演替"], ["收成", "生物量"]],
    },
]

# ------------------------------------------------------------------ 落盘
def _maps_path():
    """追加映射的落盘位置：`logs/boost/maps.json`。

    为什么单独一个文件、不写进STRUCTURE_MAP所在的源码：源码是**只读资产**
    （升级会覆盖、也不该被运行时改写），用户数据必须和代码分开存。
    去掉这个分离（把追加项写回源码）会在下次升级时把用户攒下的映射全部冲掉。
    """
    return boost_path("maps.json")


def _norm_pairs(pairs):
    """把任意输入规整成 `[[源, 目标], ...]`（元素统一成 list，非法项丢掉，不抛）。

    为什么不做"非法就报错"：调用方常常是"用户说了一句话，我顺手抽了几对词"，
    抽歪是完全正常的。报错会让一次对话失败；丢掉这一对只是少一个类比。
    两害相权，永远选"少一个类比"。
    为什么统一成 list 而不是保留 tuple：落盘走 JSON，tuple 存进去读回来变 list，
    如果这里不统一，就会出现"内存里是 tuple、读回来是 list"的两套形态，
    下游任何 `p[0]` 之外的写法（比如再拼一次落盘）都会在两条路径上表现不同。
    """
    out = []
    if not isinstance(pairs, (list, tuple)):
        return out
    for p in pairs:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            a, b = norm(p[0]), norm(p[1])
            if a and b and [a, b] not in out:
                out.append([a, b])
    return out


def _norm_map(m):
    """把一条映射（可能来自 JSON，也可能是人手写的 dict）规整成统一形态；不可用返回 None。

    为什么字段全过一遍 `norm`：JSON 里出现 `"from": 123` 或 `null` 是常事
    （手改文件、别的版本写下的字段）。不规整的话，`m["to"] == src` 这种比较
    会拿到 int 或 None，后面 `.replace` 直接抛 —— 而这条映射本来只是"这一条用不上"。
    """
    if not isinstance(m, dict):
        return None
    f, t = norm(m.get("from")), norm(m.get("to"))
    if not f or not t:
        return None
    mid = norm(m.get("id"))
    if not mid:
        mid = "%s__%s" % (f, t)
    return {"id": mid, "from": f, "to": t,
            "note": norm(m.get("note")), "pairs": _norm_pairs(m.get("pairs"))}


def _copy_map(m):
    """映射的浅拷贝（pairs 深一层），保证调用方改返回值不会污染内置常量表。

    为什么必须拷：`STRUCTURE_MAP` 是模块级常量，一旦有人 `list_maps()[0]["pairs"].pop()`
    就直接改了**整个进程**的映射库，且没有任何报错 —— 表现为"跑着跑着类比变少了"。
    去掉这一层拷贝，这类 bug 只能靠肉眼在几百行外发现。
    """
    return {"id": m.get("id", ""), "from": m.get("from", ""), "to": m.get("to", ""),
            "note": m.get("note", ""),
            "pairs": [list(p) for p in (m.get("pairs") or [])
                      if isinstance(p, (list, tuple)) and len(p) >= 2]}


def _load_added():
    """读回 `logs/boost/maps.json` 里追加的映射（读不到/写坏了 → 空列表，绝不抛）。

    为什么坏文件当"空"而不是当"错"：这个文件是运行时产物，进程被 kill 时
    可能只写了一半。若这里抛异常，整个跨领域联想功能会连带失效 ——
    而代价本该只是"这次少几条用户映射"（内置映射还在 STRUCTURE_MAP 里）。
    """
    try:
        raw = read_json(_maps_path(), default=None)
    except Exception:      # noqa: silent-ok — 读不动就当没有追加项
        return []
    if not isinstance(raw, dict):
        return []
    rows = raw.get("maps")
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        nm = _norm_map(r)
        if nm is not None:
            out.append(nm)
    return out


def list_maps():
    """内置映射 + 追加映射，合并后的完整列表（**副本**，可随意改返回值）。

    合并口径（必须写死在这里，否则会出现"同一 id 两条记录、一条用新一条用旧"）：
      ① 内置映射先按定义顺序铺开；
      ② 追加项若与内置 **同 id** → **原地覆盖**（保持它原来的位置，排序不乱跳）；
      ③ 追加项若是新 id → 追加在末尾（新东西排在后面，便于人肉看"最近学了什么"）。
    去掉"同 id 覆盖"会怎样：用户修正了一条内置映射，结果库里同时存在新旧两条，
    `map_structure` 按列表顺序取到旧的那条 —— 用户会看到"我改了它却还是老答案"。
    """
    out = []
    for m in STRUCTURE_MAP:
        nm = _norm_map(m)
        if nm is not None:
            out.append(_copy_map(nm))
    where = {}
    for i, m in enumerate(out):
        where[m["id"]] = i
    for m in _load_added():
        if m["id"] in where:
            out[where[m["id"]]] = _copy_map(m)
        else:
            where[m["id"]] = len(out)
            out.append(_copy_map(m))
    return out


def add_map(from_domain, to_domain, pairs, m_id=None, note=""):
    """追加一条结构映射，落 `logs/boost/maps.json`，返回追加后的映射 dict。

    ⚠️ 参数名为什么叫 `note_text` 而不是 `note`：本文件从包根 import 了 `note()`
    这个**事件流水函数**，如果参数也叫 `note`，函数体里 `note_event("analogy.add_map", ...)`
    就会去调用那个字符串 —— `TypeError: 'str' object is not callable`（自测当场抓到）。
    这类"变量把函数遮住"的错不会在 import 时报，只在真正执行到那一行时才炸，
    所以命名上直接避开同名，比事后靠记性可靠。

    追加合并的语义：**同 id 覆盖、不同 id 追加**。这就是"越用越大"的实现 ——
    用户在对话里认可过的类比，下一次直接被 `map_structure` 用上。
    `m_id` 不给就自动生成 `user_001 / user_002 ...`（按已追加条数编号，
    不用内置 hash()：hash 跨进程不稳定，同一个 id 重启一次就变，
    会让"同 id 覆盖"这条语义彻底失效）。
    任何非法输入都不抛：字段该规整的规整、该丢的丢，最后总是返回一个 dict，
    让调用方拿到结构一致的返回值（拿不到返回值的分支才是真的会让人写错）。
    """
    f, t = norm(from_domain), norm(to_domain)
    pl = _norm_pairs(pairs)
    added = _load_added()
    mid = norm(m_id)
    if not mid:
        mid = "user_%03d" % (len(added) + 1)
    rec = {"id": mid, "from": f or "未命名", "to": t or "未命名",
           "note": norm(note), "pairs": pl}
    pos = None
    for i, m in enumerate(added):
        if m.get("id") == mid:
            pos = i
            break
    if pos is None:
        added.append(rec)
    else:
        added[pos] = rec
    # 直写、不 tmp+rename：本项目的硬规矩是"绝不删除任何文件"，
    # 而 Windows 上 rename 覆盖目标等价于删旧文件。内容全在内存里，
    # 写坏了下一次写会覆盖回来 —— 直写足够，且不触删除。
    try:
        write_json(_maps_path(), {"version": 1, "updated_at": now(), "maps": added})
    except Exception:      # noqa: silent-ok — 存不上只影响"下次能不能复用"，不影响本次返回
        pass
    note_event("analogy.add_map", id=mid, domain_from=rec["from"], domain_to=rec["to"],
         pairs=len(pl), persisted=bool(pl))
    return _copy_map(rec)


# ------------------------------------------------------------------ 领域定位
def domain_vector(text):
    """这句话**属于每个领域**的分数，返回 `{领域: [0,1] 的浮点}`（所有领域都在）。

    为什么返回**所有**领域而不是"最像的那个"：
      · 一句话往往同时沾两三个领域（"病毒"既在免疫也在安全），
        只给 top-1 就把"其实还能按安全看"这条信息丢了，下游无法再判；
      · 固定 key 集合让下游可以放心 `vec["电路"]`，不用先判断 key 在不在。
    分子是命中概念词数（走公共 `weighted_hits`，权重留成参数便于将来调），
    分母是固定的 `_DOMAIN_DEN`；命中很多也只封顶 1.0。
    空输入 → 全部 0.0（不是抛错：没有文本就是没有信息，0 分是正确答案）。
    确定性：词表是常量、`hits` 按出现位置排序、不做任何随机。
    """
    t = norm(text)
    out = {}
    for d in DOMAINS:           # 按 DOMAINS 定义顺序遍历 → dict 顺序也确定
        try:
            n = weighted_hits(t, DOMAINS[d])
        except Exception:      # noqa: silent-ok — 单个领域算不动就当 0 分，不连累其它领域
            n = 0.0
        out[d] = round(min(1.0, n / _DOMAIN_DEN), 4)
    return out


def best_domain(text):
    """分数最高的领域；**全部为 0 时返回 None**（不许硬塞一个）。

    并列时取 `DOMAINS` 里**先定义**的那个领域：Python 的 dict 保序 +
    这里用严格大于（`>`）比较，所以"先到者不被后来者顶掉"。
    为什么全 0 要返回 None 而不是"猜一个最像的"：本模块后续所有动作
    （翻译、类比）都以"源领域是真的"为前提，猜一个领域等于拿错词典去翻译 ——
    输入本来就是"今天天气不错"，硬翻成电路术语只会输出一段荒谬的话。
    None 让调用方能明确地什么都不做，这比"看起来有结果"重要得多。
    """
    best, best_s = None, 0.0
    for d, s in domain_vector(text).items():
        if s > best_s:
            best, best_s = d, s
    return best


# ------------------------------------------------------------------ 词对替换
def _apply_pairs(text, pairs):
    """按 `pairs` 做替换，返回替换后的句子（单遍，绝不链式误替换）。

    为什么要走"占位符"这一趟（直接 `t.replace(a, b)` 一行就够）：
    顺序替换会**链式污染** —— 先把"电压"换成"水压"，后面某一对若是
    ["水压","压力"]，刚换出来的"水压"会被再换一次，同一处词被翻译两遍。
    用户追加的映射里出现这种交叉的概率并不低（内置表已刻意避开）。
    去掉占位符这一趟，症状是"偶尔翻出来的句子莫名其妙"，且只在特定词序下复现。
    """
    tmp = text
    slots = {}
    for i, p in enumerate(pairs):
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        a, b = norm(p[0]), norm(p[1])
        if not a or not b or a not in tmp:
            continue
        token = "\x00%d\x00" % i          # 占位符：真实文本里几乎不可能出现的形态
        slots[token] = b
        tmp = tmp.replace(a, token)
    for token, b in slots.items():
        tmp = tmp.replace(token, b)
    return tmp


def _hit_pairs(text, pairs):
    """`pairs` 里**这次真的用上**的那些对（保持 pairs 原顺序）。

    保持原顺序（而不是按命中位置排序）：映射表里的词对顺序是作者写的推导顺序，
    下游要照这个顺序去提示模型"先讲电压≈水压，再讲电流≈流量"，乱序读起来是散的。
    """
    used = []
    for p in pairs:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            a, b = norm(p[0]), norm(p[1])
            if a and b and a in text:
                used.append([a, b])
    return used


def _statements(text, used):
    """生成"跨领域说法"列表：**第一条是整句翻译**，之后每条对应一个词对。

    为什么第一条必须是整句（例："电压不够，电流就小 → 水压不够，流量就小"）：
    人（和模型）读类比时先要那句"翻译过来的整句话"，它才是真正有用的东西；
    逐对拆开的那些只是备查（"到底哪几个词翻了"）。
    反过来只给逐对结果会怎样：一句话里命中 3 对时，输出三行几乎一样的长句，
    读者得自己在脑子里做并集，等于把该载体干的活推回给了人。
    自映射（如 竞争→竞争）不产生新说法，会被下面 `!= text` 判掉并跳出 —— 
    没有变化的一行"X → X"不是类比，是噪声。
    """
    out = []
    full = _apply_pairs(text, used)
    if full != text:
        out.append("%s → %s" % (text, full))
    for p in used:
        one = _apply_pairs(text, [p])
        if one != text:
            line = "%s → %s" % (text, one)
            if line not in out:
                out.append(line)
    return out


def _why(text, src):
    """中理由串：命中源领域的哪几个词。日志和自测都靠它回答"凭什么是这个领域"。"""
    got = hits(text, DOMAINS.get(src) or ())
    return "命中源领域「%s」的词 %s" % (src, "/".join(got) if got else "（无）")


def _score(text, src, used):
    """这次映射的可信度：一半看"命中了几对词"，一半看"源领域本身有多确定"。

    命中数用**固定分母** `_DOMAIN_DEN`（命中 3 对即算满）归一，而不是
    "命中数 / 这条映射自己的词对数"。为什么不能用映射长度当分母：
    映射写得越细（比如 7 对），越难被"用满"，分数就被拖得越低 ——
    于是**一条精心写全的映射永远输给一条只有 3 对的粗糙映射**，
    表现为"越用心写的表越少被选中"，这显然反了。
    固定分母让所有映射站在同一条起跑线上，与 `domain_vector` 是同一条口径。
    为什么要掺进领域分：只命中一对词也可能拿满分，但那句话可能只是**路过**
    该领域（领域分很低）。两项都要高，才值得把这条类比端给用户。
    去掉领域分这一项会怎样：一句只含"流量"的闲话也会拿到很高的类比分，
    类比的信噪比会明显下降。
    """
    cov = min(1.0, len(used) / _DOMAIN_DEN)
    dom = domain_vector(text).get(src, 0.0)
    return round(min(1.0, 0.5 * cov + 0.5 * dom), 4)


def _oriented(m, src):
    """一条映射在"源领域 = src"下的可用形态；用不上返回 None。

    返回 `(源侧领域, 目标侧领域, 已定向的pairs, 是否反向使用)`。
    结构映射是**双向**的：记录里写 from=电路/to=水管，但用它的句子可能是水管那句
    （"水压不够"。）所以当映射的 `to` 正好等于源领域时，词对整体反过来用。
    为什么必须支持双向：内置表只写一个方向能省一半体积，但用户随时可能
    从这个领域的角度发问；不做反向的话，一半的映射等于白写 —— 
    表现为"同一个类比，换个说法就问不出来了"。
    自映射（from == to）直接判掉：那不是跨领域，是换个说法说同一件事。
    """
    if not isinstance(m, dict):
        return None
    f, t = norm(m.get("from")), norm(m.get("to"))
    if not f or not t or f == t:
        return None
    pairs = _norm_pairs(m.get("pairs"))
    if f == src:
        return f, t, pairs, False
    if t == src:
        return t, f, [[b, a] for a, b in pairs], True
    return None


def _candidate(text, m, src, idx):
    """把一条映射试成"一个候选类比"；不成立返回 None（成立=至少翻出一句话）。

    候选里带三个下划线开头的内部字段（序号/是否反向/命中数），
    是给 `analogies` 排序去重用的；对外返回前会剥掉，不污染公开结构。
    """
    o = _oriented(m, src)
    if o is None:
        return None
    mfrom, mto, pairs, rev = o
    used = _hit_pairs(text, pairs)
    if not used:
        return None
    stmts = _statements(text, used)
    if not stmts:
        return None          # 命中了对但翻不出任何变化（纯自映射）→ 不算类比
    return {"map_id": norm(m.get("id")) or ("map_%d" % idx),
            "from": mfrom, "to": mto, "pairs": used, "statements": stmts,
            "score": _score(text, src, used), "why": _why(text, src),
            "_idx": idx, "_rev": rev, "_hits": len(used)}


def _public(c):
    """剥掉内部字段，只留对外承诺的 7 个 key（顺序固定，便于日志比对）。"""
    return {"map_id": c["map_id"], "from": c["from"], "to": c["to"],
            "pairs": [list(p) for p in c["pairs"]], "statements": list(c["statements"]),
            "score": c["score"], "why": c["why"]}


# ------------------------------------------------------------------ 对外主函数
def map_structure(text):
    """对 `text` 做一次结构映射，返回一个类比 dict；**没得翻时返回 None**。

    步骤（顺序不能换）：
      1. `best_domain` 定位源领域，定不出来 → None（拿错词典比不翻更糟）；
      2. 在 `list_maps()` 里找涉及该领域的映射，方向对不上就反向用（见 `_oriented`）；
      3. 逐对替换生成跨领域说法，至少翻出一句话才算成立。

    为什么"翻不出任何东西"返回 None 而不是 `{"statements": []}`：
      返回空壳会让调用方以为"成功但要自己判断空不空"，而调用方（提示词装配、
      自测）一定会漏判 —— 于是用户看到一段"类比：无"的空标题。None 是
      "没有类比"这件事在 Python 里唯一不会引起误判的表达。
    多条映射都能用时，取"命中词对更多、其次分数更高"的那条；完全并列时取
    `list_maps()` 里靠前的（= 内置优先、定义顺序优先）→ 同一输入永远同一结果。
    """
    try:
        t = norm(text)
        if not t:
            return None
        src = best_domain(t)
        if src is None:
            return None
        best = None
        for idx, m in enumerate(list_maps()):
            c = _candidate(t, m, src, idx)
            if c is None:
                continue
            if best is None or (c["_hits"], c["score"]) > (best["_hits"], best["score"]):
                best = c
        if best is None:
            return None
        out = _public(best)
        note_event("analogy.map_structure", map_id=out["map_id"], domain_from=out["from"],
             domain_to=out["to"], pairs=len(out["pairs"]), score=out["score"])
        return out
    except Exception:      # noqa: silent-ok — 联想是加分项，绝不能因为它让主对话失败
        return None


def analogies(text, limit=3):
    """给出 1~3 个跨领域类比（`to` 互不相同、按分数降序）；没得给就返回 `[]`。

    【三条硬规矩，都是为了不糊弄用户】
      ① **同一领域不算类比**：`from != to`，且 `to != best_domain(text)`。
         把"电路"映射成"电路"是自欺 —— 用户明明在问电路，你还给他电路的说法。
      ② **一个目标领域只出一条**：同一句话可能命中三张都通向"水管"的映射，
         全给出来就是同一句话说三遍，把真正不同的那条（人体）挤到看不见。
      ③ **优先不同领域、按分数降序**：先给最可信的，且并列时按 `list_maps()` 顺序，
         同一输入永远同一顺序（自测才能断言顺序，用户才不会觉得"它忽左忽右"）。
    `limit` 会被夹到 `[0, min(limit, 3)]`：本模块对外承诺的产出上限就是 3 条 ——
    给出 8 个类比等于让用户自己挑，那正是"载体该干的活"被推回给了人。
    定位不出领域 / 无可用映射 → `[]`，**绝不编造**一个类比凑数。
    """
    try:
        t = norm(text)
        try:
            lim = int(limit)
        except Exception:      # noqa: silent-ok — limit 传了怪东西就按默认 3 条
            lim = 3
        lim = max(0, min(lim, 3))
        if not t or lim == 0:
            return []
        src = best_domain(t)
        if src is None:
            return []
        cands = []
        for idx, m in enumerate(list_maps()):
            c = _candidate(t, m, src, idx)
            if c is None or c["to"] == src:
                continue
            cands.append(c)
        # 排序键用 (负分, 序号)：分数高的在前；同分时"定义顺序靠前"的在前。
        # 不能只按 score 排 —— 并列时 Python 的稳定排序会保留 list_maps 的顺序，
        # 那是对的，但显式写出来才能让"确定性"这件事不依赖解释器的默认行为。
        cands.sort(key=lambda c: (-c["score"], c["_idx"]))
        out, seen = [], set()
        for c in cands:
            if c["to"] in seen:
                continue
            seen.add(c["to"])
            out.append(_public(c))
            if len(out) >= lim:
                break
        if out:
            note_event("analogy.analogies", src=src, n=len(out),
                 targets=",".join(o["to"] for o in out))
        return out
    except Exception:      # noqa: silent-ok — 联想失败就当"没有类比"，主对话照常走
        return []
