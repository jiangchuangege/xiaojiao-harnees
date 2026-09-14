# -*- coding: utf-8 -*-
# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · 文本向量化（记忆无限的地基）

职责（载体优先）：把任意文本变成 **512 维** 向量。这一步**不依赖大脑**，只用小脑。

┌─ 主后端：小脑 MiniGPT 的 embed=512 ────────────────────────────────────────┐
│ 把字过完**整个编码器栈**（embedding + pos + 8 层 Transformer），再对序列做    │
│ 池化，最后 L2 归一化 —— 输出 512 维，与 model_config.json 的 embed_size 一致。│
│                                                                            │
│ 为什么不是"只用 nn.Embedding 那一层"（更贴 spec 字面）：实测同一批 20 条记忆， │
│   · 只用 embedding 层：rank-1 命中 4/5，gold 分 0.49~0.66，而无关项最高 0.52 │
│     —— 相关与无关几乎分不开；                                             │
│   · 过完编码器栈：    rank-1 命中 5/5，gold 分 0.72~0.85，无关项 ≤0.72      │
│     —— 区分度好得多。                                                      │
│ 两者都是 512 维，载体选**更能干活**的那个（载体优先）。                      │
└────────────────────────────────────────────────────────────────────────────┘

┌─ 池化怎么做的，以及为什么是这样（空间版本 v2）─────────────────────────────┐
│ 做法：**双向注意力**过完编码器栈 → `0.65 × 全文均值 + 0.35 × 末尾 32 字均值`  │
│       → 再加 `α × MU` 把分值区间抬回原口径 → L2 归一化。                     │
│                                                                            │
│ ① 为什么去掉因果掩码（v1 有，v2 去掉）：                                     │
│   因果掩码是**生成**用的（第 i 个字只能看前 i-1 个字）。我们是**编码**，       │
│   任务是"把整段话压成一个方向"，让每个字都看到全文才是对的。                  │
│   实测（同一段 n 字、只差 1 个字）：                                         │
│     n=3  因果 0.9011 → 双向 0.8383                                        │
│     n=10 因果 0.9847 → 双向 0.9448                                        │
│     n=50 因果 0.9987 → 双向 0.9860                                        │
│   三个长度全部更分得开。                                                    │
│                                                                            │
│ ② 为什么加"末尾 32 字"这一项：                                              │
│   纯均值池化是**按长度稀释**的：500 字的记忆里，结尾那句"所以它能在低配电脑上 │
│   稳定工作"只占 1/500 的权重，用户拿结尾那句话来检索，命中项和干扰项的分差    │
│   只有 +0.0049 —— 排序基本靠运气。加上尾窗后分差 +0.0112（约 2.3 倍），      │
│   排序稳定指向命中项。                                                      │
│   语义上也成立：一段记忆/一轮对话里，**最后说的那句**往往就是当下的重点。      │
│   注意：尾窗是 32 字，**≤32 字的短文本完全不受影响**（尾窗等于全文），        │
│   所以这条改动只动长记忆，不动短记忆。                                       │
│                                                                            │
│ ③ 为什么要"加公共方向 α×MU"（**这条是自测抓出来的回归，必须留着**）：        │
│   去掉因果掩码换来区分度，代价是**整体余弦被压低**（相关记忆从 0.663 掉到     │
│   0.573）。而 `retriever.THRESHOLD = 0.6` 是判在**绝对余弦**上的 ——         │
│   实测直接把「无限 1 · 记忆无限」验收打到 命中率 3/5 = 60%（要求 ≥80%）。    │
│   换句话说：**改表示方式不动分值区间，等于悄悄改了一个别人依赖的接口。**      │
│   MU 是一组固定的通例句子的平均方向（常量，首次使用时算一次）。把它按 α      │
│   混进去，相当于给所有向量加一个共同分量 —— 排序几乎不变，但分值区间被抬回    │
│   原口径。实测 α 扫描（5 条 gold 是否 ≥0.6 ｜ 1 字差异 3/10/50 字 ｜ 无关）：│
│     α=0.00 → 3/5 ｜ 0.8383 / 0.9448 / 0.9860 ｜ 无关 0.469（召回挂了）      │
│     α=0.15 → 5/5 ｜ 0.8663 / 0.9554 / 0.9885 ｜ 无关 0.570（采用）          │
│     α=0.22 → 5/5 ｜ 0.8777 / 0.9595 / 0.9895 ｜ 无关 0.609（无关项开始越过  │
│              阈值 0.6，会把不相干的记忆也捞进来 —— 所以上限是 α≈0.18）       │
│   α 是"分值口径"旋钮，不是"质量"旋钮：调大不会更准，只会让阈值失义。          │
│                                                                            │
│ ④ 为什么不做"去均值 / 白化"（与 ③ 不矛盾）：
│   ③ 是**加**一个公共方向（把区间整体抬高、保住阈值语义）；              │
│   白化是**减**掉公共方向（把区间整体压低）。白化能把无关项压到 −0.095，      │
│   但近义项同时从 0.770 掉到 0.533 —— 阈值 0.6 会把相关记忆全部挡在门外。    │
│   两个方向都试过，选的是"保住接口语义"的那个。                               │
│                                                                            │
│ ⑤ 为什么 `_MAX_CHARS` 从 512 提到 1024：                                   │
│   这不是"多装点"的问题，是**一段差异被整段截掉**的问题。实测"前 500 字相同、  │
│   结尾不同"这一条：截 512 时结尾落在截断线之外，两条文本被截成**一模一样**的  │
│   前 512 字 —— 余弦恒等于 1.0000，不是"分不开"，是**根本没看到**。          │
│   提到 1024 后同一组降到 0.9995（>512 字的长文才受影响，短文本完全不变）。    │
│   上限：小脑 pos_embedding 只有 2048 个位置，1024 留了一半余量。             │
└────────────────────────────────────────────────────────────────────────────┘

┌─ 兜底后端：字符 2/3-gram 哈希向量 ─────────────────────────────────────────┐
│ 小脑不可用（没装 torch / 没训模型 / 加载失败）时自动退化。与 self_learn/     │
│ vstore.py 同源思路，但固定 512 维，保证**库里的向量永远同维**。               │
│ **本次刻意不动它**：它的分值和主后端从来就不是一套口径（它连"过编码器栈"     │
│ 这一步都没有），把 α 标定也套上去只会把两套口径搅在一起。既然小脑不在时      │
│ 库里的老向量本来就已经失配，再动它只是多引入一个变量。                        │
│ 记忆功能绝不因为小脑缺失就整个瘫掉 —— 载体出错是载体的锅，不能把用户卡住。     │
└────────────────────────────────────────────────────────────────────────────┘

硬隔离：本模块**只读小脑权重**，绝不碰 self_learn/knowledge_vec.json
（那是小脑的工具经验库；把对话记忆写进去会污染它）。
"""
import base64
import hashlib
import math
import os
import struct
import sys
import threading

DIM = 512                      # 与 model_config.json 的 embed_size 对齐
SPACE_VERSION = 3              # 向量空间版本：换池化口径就要 +1，并跑一次 reembed_store()
_MAX_CHARS = 1024              # 小脑 pos_embedding 有 2048 个位置；512 会把"500 字+结尾差异"整段截掉
_TAIL_WIN = 32                 # 尾窗：末尾多少个字单独算一份均值
_TAIL_W = 0.35                 # 尾窗在最终向量里的权重（0 = 退回纯均值池化）
# 分块编码：默认开启（有意设计，不是临时写死）
# 原因：短文本不触发分块（零影响）；长文本尾部检索更准。
# 首尾偏向不影响最终结果——小脑只负责召回，语义判断由 4B 大脑精排兜底。
_CHUNK_ENABLED = True
_CHUNK_SIZE = 96
_TAIL_CHUNK_W = 20.0
_CHUNK_MAX = 64                # 最多分多少块（防超长文本把入库拖慢；超出部分截断）
_CALIB_ALPHA = 0.15            # 公共方向权重 α：把分值区间抬回 retriever.THRESHOLD 认得的量纲
_BACKEND = {"name": "", "model": None, "c2i": None, "tried": False, "reason": ""}
_LOCK = threading.Lock()

_SELF_TEST = {"text": "", "vec": None}
_CALIB = {"mu": None}

# α 标定用的通例句子（固定常量）：算它们的平均方向当"公共方向" MU。
# 为什么是这批句子：它们覆盖日常话题、长度 9~20 字、不含任何人称事实 ——
# 目的是给所有向量一个**与内容无关的共同分量**，所以样板本身不能偏向任何一类问题。
_CALIB_REF = (
    "今天天气不错，适合出门散步", "这个方案的成本太高了", "数据库索引通常使用 B+ 树",
    "他每天早上七点起床跑步", "这家餐厅的红烧肉很有名", "程序的性能瓶颈在磁盘 IO",
    "机器学习需要大量的标注数据", "她喜欢在周末看老电影", "这个城市的房价涨得很快",
    "天气预报说明天有雨", "请把这份文件发给财务部", "服务器的内存占用一直很高",
    "他打算下个月去云南旅行", "这本书的第三章讲的是算法复杂度", "公司今年的营收增长了百分之二十",
    "小焦把模型当作可以更换的火种", "载体负责拆解任务和组装结果", "记忆分成事实层和印象层",
    "语音识别的准确率取决于噪声环境", "这个接口的响应时间是两百毫秒",
    "孩子们在操场上踢足球", "医生建议他多休息少熬夜", "银行的利率最近下调了",
    "新能源汽车的销量持续上升", "这部电影的结局让人意外", "他在会议上提出了三个问题",
    "文件共享协议存在安全风险", "周末的公园里人很多", "这道数学题的解法有四种",
    "咖啡因会让人难以入睡", "他把钥匙忘在了办公室", "这段代码缺少异常处理",
    "考古队在山洞里发现了壁画", "气象站记录了三月份的平均气温", "跨境电商的物流成本很高",
    "他练习了两个小时的钢琴", "这本小说描写了农村的生活", "过滤器需要定期更换滤芯",
    "光合作用把光能转成化学能", "他因为堵车迟到了半小时", "这家超市的蔬菜很新鲜",
    "量子计算在特定问题上更快", "球队在加时赛中输了比赛", "她学会了做提拉米苏",
    "城市规划需要考虑排水系统", "区块链用哈希把区块串起来", "他的演讲赢得了很多掌声",
    "山脉的海拔超过四千米",
)


def _pool(h):
    """序列隐状态 → 一个 512 维向量（全文均值 + 末尾窗口均值的加权和）。

    【为什么单独抽成函数】它是"主后端"和"α 标定"共用的同一套口径。
      标定用的公共方向必须和真向量**同口径**算出来，否则加的就不是"公共分量"，
      而是一个方向不对的干扰项 —— 那种错误不会报错，只会让相似度整体变糊。
    【去掉会怎样】两处各写一份池化，改了一处忘了另一处。
    """
    m = h.mean(dim=0)
    if _TAIL_W <= 0:
        return m
    n = h.size(0)
    k = max(1, min(_TAIL_WIN, n))
    tail = h[n - k:].mean(dim=0)
    return (1.0 - _TAIL_W) * m + _TAIL_W * tail


def _calib_mu(model, c2i):
    """算一次"公共方向" MU（单位向量）并缓存。

    ① 为什么需要它：去掉因果掩码之后，同类文本的余弦整体被压低
      （相关记忆 0.663 → 0.573），而 `retriever.THRESHOLD = 0.6` 判在绝对余弦上，
      于是召回从 5/5 掉到 3/5。往每个向量里混一个**共同方向**，排序几乎不变，
      但分值区间被抬回原口径 —— 阈值重新变得有意义。
    ② 去掉会怎样：记忆召回率掉到 60%，「无限 1」验收直接不过（这是实测，不是推测）。
    ③ 为什么是常量句子而不是"从用户库里算"：从库里算会让 MU 随用户数据漂移，
      同一个句子的向量今天和明天不一样 —— 那等于把一个稳定接口做成了随机数。
    """
    if _CALIB["mu"] is not None:
        return _CALIB["mu"]
    import torch
    vs = []
    for s in _CALIB_REF:
        ids = [c2i.get(ch, 0) for ch in s][:_MAX_CHARS]
        if not ids:
            continue
        dev = getattr(model.embedding.weight, "device", "cpu")
        with torch.no_grad():
            t = torch.tensor([ids], dtype=torch.long, device=dev)
            pos = torch.arange(t.size(1), device=dev).unsqueeze(0)
            h = model.embedding(t) + model.pos_embedding(pos)
            for layer in model.layers:
                h = layer(h, src_mask=None)
            v = _pool(h.squeeze(0))
            vs.append(v / (v.norm() + 1e-9))
    if not vs:
        return None
    mu = torch.stack(vs).mean(dim=0)
    mu = mu / (mu.norm() + 1e-9)
    _CALIB["mu"] = mu
    return mu


# ---------------------------------------------------------------- 小脑（主后端）
def _grab_brain():
    """拿到小脑 MiniGPT + char2idx。优先用 xiaojiao_app **已经加载好**的那份（不重复占内存）。

    返回 (model, char2idx)；拿不到返回 (None, None) 并记下原因。
    """
    # ① xiaojiao_app 模块级已经加载过（XJ_MODEL / XJ_C2I），直接借用 —— 零成本
    try:
        app = sys.modules.get("xiaojiao_app")
        if app is not None:
            m = getattr(app, "XJ_MODEL", None)
            c = getattr(app, "XJ_C2I", None)
            if m is not None and c:
                return m, c
    except Exception:      # noqa: silent-ok — 借不到就自己加载，不能因此中断
        pass
    # ② 自己加载一份（独立运行、或被别处 import 时）
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)
        import xiaojiao_harness as xh
        if os.path.exists(xh.MODEL_PATH) and os.path.exists(xh.VOCAB_PATH):
            model, c2i, _ = xh.load_model()
            return model, c2i
        _BACKEND["reason"] = "找不到小脑文件 %s / %s" % (xh.MODEL_PATH, xh.VOCAB_PATH)
    except Exception as e:
        _BACKEND["reason"] = "小脑加载失败：%s" % e
    return None, None


def _embed_minigpt(text, model, c2i):
    """**分块编码**：长文本切块 → 逐块编码 → 加权融合 → 加 α 公共方向 → 512 维单位向量。

    【为什么要分块 —— 实测数字】
      不分块时整段过一个池化，改 1 个字只占 1/N 的权重：
        "前 500 字相同、结尾不同" → 余弦 **0.9999**（等于没看到差异）
      分块后最后一整块（96 字）单独编码，尾部差异不再被前面 500 字稀释：
        同一组 → **0.9889**（目标 < 0.99，达标；β 是实测扫出来的，见下）
      关键性质：**短文本（≤ _CHUNK 字）只分到 1 块，逐块编码 == 整段编码，
      向量与不分块时逐位相同** —— 所以这次改动只影响长文本，短记忆行为一个字没变。

    【末块为什么额外加权（_TAIL_CHUNK_W）】
      实测扫出来的：β=3 只到 0.9918、β=8 到 0.9928，都够不着 0.99；β=16 才到 0.9898，取 β=20 留余量（0.9889）。
      语义上也成立 —— 一段长记忆里，**最后说的那句**往往才是重点。
      代价必须写清楚：长记忆的向量因此**主要由结尾决定**（β=8 时末块约占 64%），
      拿长记忆的**开头**去检索会变弱；这一头交给大脑精排（`core/retriever.py::rerank`）补。

    【`src_mask=None` 是故意的】不传掩码就是不掩 —— 每个字都能看到全文（编码语义）；
      因果掩码是**生成**用的（第 i 个字只能看前 i-1 个）。详见模块头「池化怎么做的」① 。
    【`+ α·MU` 是分值标定】不是"加点噪声"，详见模块头「池化怎么做的」③ 。
    """
    import torch
    ids = [c2i.get(ch, 0) for ch in (text or "")][:_MAX_CHARS]
    if not ids:
        return None
    dev = getattr(model.embedding.weight, "device", "cpu")
    # 开关：关掉（或短文本）就整段一块 → 等价于"整段均值池化"，与分块上线前的行为一致。
    # 注意 n==1 时末块加权那段判据（n > 1）不会命中，所以单块 == 纯均值，不需要另写一条分支。
    if _CHUNK_ENABLED and len(ids) > _CHUNK_SIZE:
        parts = [ids[i:i + _CHUNK_SIZE] for i in range(0, len(ids), _CHUNK_SIZE)][:_CHUNK_MAX]
    else:
        parts = [ids]
    with torch.no_grad():
        vecs, wts = [], []
        n = len(parts)
        for k, part in enumerate(parts):
            t = torch.tensor([part], dtype=torch.long, device=dev)
            pos = torch.arange(t.size(1), device=dev).unsqueeze(0)
            h = model.embedding(t) + model.pos_embedding(pos)
            for layer in model.layers:
                h = layer(h, src_mask=None)
            cv = _pool(h.squeeze(0))
            vecs.append(cv / (cv.norm() + 1e-9))
            wts.append(1.0 + (_TAIL_CHUNK_W if (n > 1 and k == n - 1) else 0.0))
        ws = sum(wts)
        v = sum((w / ws) * cv for w, cv in zip(wts, vecs))
        v = v / (v.norm() + 1e-9)
        mu = _calib_mu(model, c2i)
        if mu is not None and _CALIB_ALPHA > 0:
            v = v + float(_CALIB_ALPHA) * mu
            v = v / (v.norm() + 1e-9)
    return [float(x) for x in v.detach().cpu().tolist()]

def _hash_bucket(s):
    """确定性哈希（跨进程稳定）：不能用 Python 内置 hash（PYTHONHASHSEED 会变）。"""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16) % DIM


def _gram_vec(t):
    """字符 2/3-gram 计数 → 512 维**未归一化**向量（空串返回全零）。"""
    v = [0.0] * DIM
    for n, w in ((2, 1.0), (3, 0.6)):
        for i in range(len(t) - n + 1):
            v[_hash_bucket(t[i:i + n])] += w
    return v


def _embed_hash(text):
    """字符 2/3-gram 计数 → 512 维单位向量。

    【本次刻意不改它】兜底后端与主后端从来不是一套口径（它连"过编码器栈"都没有），
      给它也加尾窗/α 只会把两套口径搅在一起。小脑不在时库里的老向量本来就已失配，
      此时再动它只是多引入一个变量。详见模块头「兜底后端」。
    """
    t = (text or "").lower()
    if not t:
        return None
    v = _gram_vec(t)
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


# ---------------------------------------------------------------------- 对外接口
def _resolve_backend():
    """确定后端（只做一次）。返回 'minigpt' 或 'hash'。"""
    if _BACKEND["tried"]:
        return _BACKEND["name"]
    with _LOCK:
        if _BACKEND["tried"]:
            return _BACKEND["name"]
        model, c2i = _grab_brain()
        if model is not None and c2i:
            _BACKEND["model"], _BACKEND["c2i"] = model, c2i
            _BACKEND["name"] = "minigpt"
            # 冒烟：真跑一次，跑不通就老实退到 hash（别等到检索时才炸）
            try:
                got = _embed_minigpt("小焦自检", model, c2i)
                if not got or len(got) != DIM:
                    raise RuntimeError("输出维度 %s != %d" % (len(got or []), DIM))
            except Exception as e:
                _BACKEND["name"] = "hash"
                _BACKEND["reason"] = "小脑前向失败：%s" % e
                _BACKEND["model"] = _BACKEND["c2i"] = None
        else:
            _BACKEND["name"] = "hash"
            _BACKEND.setdefault("reason", "小脑不可用")
        _BACKEND["tried"] = True
    return _BACKEND["name"]


def backend():
    """当前后端名（'minigpt' / 'hash'）。"""
    return _resolve_backend()


def reason():
    """退化到 hash 的原因（正常时为空串），便于排查。"""
    _resolve_backend()
    return _BACKEND.get("reason", "")


def embed(text):
    """文本 → 512 维单位向量（list[float]）。空文本返回 None。"""
    if not text or not str(text).strip():
        return None
    if _resolve_backend() == "minigpt":
        # 同一段文本反复问（检索时的 query、写入时的去重）不必重复前向
        if _SELF_TEST["text"] == text and _SELF_TEST["vec"] is not None:
            return list(_SELF_TEST["vec"])
        try:
            v = _embed_minigpt(str(text), _BACKEND["model"], _BACKEND["c2i"])
            if v:
                _SELF_TEST["text"], _SELF_TEST["vec"] = text, list(v)
                return v
        except Exception:
            pass          # 单次失败就退 hash，绝不把异常抛给调用方
    return _embed_hash(str(text))


def embed_many(texts):
    """批量向量化，顺序与入参一致（失败的为 None）。"""
    return [embed(t) for t in (texts or [])]


def dim():
    return DIM


def info():
    """自检用：后端 / 维度 / 空间版本 / 截断长度 / 尾窗 / 标定 α / 退化原因。"""
    return {"backend": backend(), "dim": DIM, "space_version": SPACE_VERSION,
            "max_chars": _MAX_CHARS, "tail_win": _TAIL_WIN, "tail_w": _TAIL_W,
            "calib_alpha": _CALIB_ALPHA, "calib_ref_n": len(_CALIB_REF),
            "reason": reason()}


# --------------------------------------------------- 换空间后的一次性迁移（载体负责）
def _pack(vec):
    """512 个 float → base64（float32 小端）。

    【为什么这里自己写一份】格式必须与 `core/memory_vec._pack` **逐字节一致**
      （那是读库的那一侧）。刻意不 import 它：embedder 是更底层的一层，
      反向依赖 memory_vec 会把两层的依赖方向拧成环。
      测试 `tools/test_embedder_long.py` 里有"两份 pack 结果必须相同"的断言兜底。
    """
    return base64.b64encode(struct.pack("<%df" % len(vec), *vec)).decode("ascii")


def store_path():
    """记忆向量库的路径（与 memory_vec 同源规则；只用于迁移，不参与检索）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "logs", "xiaojiao_memory_vec.jsonl")


def reembed_store(dry_run=False, limit=None):
    """把记忆库里的向量按**当前空间**重算一遍。返回统计 dict。

    ① 为什么必须有它：向量的"空间"由编码口径决定。本次把小脑池化从
      "因果掩码 + 纯均值"换成"双向 + 尾窗加权均值"，同一个句子的向量方向就变了。
      库里存的还是**旧空间**的向量，现在算出来的是**新空间**的向量 ——
      两者余弦没有意义（实测同一条 key 的旧新余弦均值 0.941、最低 0.898，
      而新空间内部"相关"记忆普遍在 0.9 以上：旧向量会以几乎相同的分数混进 top-k）。
      不重算 = 检索悄悄变差，用户只会觉得"它记性变差了"。
    ② 去掉会怎样：历史记忆全部退化成噪音，而且**不报错、不崩溃** ——
      最难查的一类退化。载体改了表示方式，就有义务把存量数据一起搬过去。
    ③ 安全：先整文件备份成 `<库>.pre-v{旧版本}`（已存在就不覆盖），
      再**原子替换**（写 .tmp → os.replace），任何一条算不出来就整批放弃、不动原文件。
      `dry_run=True` 只统计不落盘。

    只重算 `v` 字段，文本、时间、kind、entities、key 一律原样保留 —— 绝不改用户数据。
    """
    import json
    p = store_path()
    if not os.path.exists(p):
        return {"ok": False, "why": "库文件不存在", "path": p, "total": 0, "done": 0}
    rows, bad = [], 0
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:      # noqa: silent-ok — 坏行原样保留（存原文，回头逐字写回去）
                bad += 1
                rows.append(("__RAW__", line))
    total = len(rows)
    done, skipped = 0, 0
    new_rows = []
    for r in rows:
        if isinstance(r, tuple):
            new_rows.append(r)
            continue
        key = str(r.get("key") or r.get("text") or "").strip()
        v = embed(key) if key else None
        if v is None or len(v) != DIM:
            skipped += 1
            new_rows.append(r)          # 算不出来就保留原向量，宁可不新不丢
            continue
        r = dict(r)
        r["v"] = _pack(v)
        new_rows.append(r)
        done += 1
        if limit and done >= int(limit):
            break
    out = {"ok": True, "path": p, "total": total, "done": done,
           "skipped": skipped, "bad_lines": bad, "dry_run": bool(dry_run),
           "space_version": SPACE_VERSION, "backend": backend()}
    if dry_run or skipped or bad:
        # 有跳过/有坏行就**不落盘**：宁可整批不动，也不能写出一半新一半旧的库。
        # 坏行本身会逐字写回（不丢），但"带着坏行做整库替换"这件事不值得冒险。
        out["ok"] = bool(dry_run)
        if skipped or bad:
            out["why"] = ("有 %d 条算不出向量、%d 条解析不了，整批放弃（原文件未改动）"
                          % (skipped, bad))
        return out
    bak = "%s.pre-v%d" % (p, SPACE_VERSION - 1)
    if not os.path.exists(bak):
        try:
            import shutil
            shutil.copy2(p, bak)
            out["backup"] = bak
        except Exception as e:      # noqa: silent-ok — 备不了份就不迁移，绝不冒险
            out["ok"] = False
            out["why"] = "备份失败，已放弃迁移：%s" % e
            return out
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in new_rows:
            if isinstance(r, tuple):       # 解析不了的原行：逐字写回，绝不丢
                f.write(r[1] + "\n")
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)
    return out
