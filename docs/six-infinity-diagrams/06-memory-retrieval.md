# 记忆检索流程图

> 「记忆无限」有两条路：**写入**（把每一轮对话永久存进外部向量库）和**读取**（每轮按需检索 top-K 注入）。
> 两条路都完全在载体层完成，模型只负责"看到就用"。对应实现：
> `core/embedder.py` + `core/memory_vec.py` + `core/retriever.py` + `xiaojiao_app.py` 的
> `_remember_turn` / `_retrieve_memory`。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    subgraph WRITE["✍️ 写入路径（一轮对话结束时）"]
        direction TB
        W1["_remember_turn<br/>正文存「用户：那句话 + 小焦：回答摘要」<br/>回答只留 ≤ 200 字摘要，代码块不往记忆里塞"]
        W2["关键取舍：key_text = 用户那句话<br/>向量按『用户说了什么』算，注入用完整原文<br/>拿整段原文算向量 → 用户那句被几百字寒暄淹掉 → cos 掉到阈值以下，一条都检索不到"]
        W3["embedder.embed 把 key_text 变成 512 维单位向量"]
        W4["memory_vec.add_memory<br/>base64 编码 float32 小端，一行一条 append-only<br/>写进 logs/xiaojiao_memory_vec.jsonl"]
        W5["硬隔离 _assert_not_forbidden<br/>绝不写 self_learn/knowledge_vec.json<br/>那是小脑的工具经验库，写进去会污染它"]
        W1 --> W2 --> W3 --> W4 --> W5
    end

    subgraph EMB["🧠 向量化后端 core/embedder.py"]
        direction TB
        E1{"小脑 MiniGPT 可用吗？"}
        E1 -->|可用| E2["主后端：过完整个编码器栈<br/>embedding + pos → 8 层 Transformer → 均值池化 → L2 归一化<br/>实测 rank-1 命中 5/5，gold 分 0.72~0.85"]
        E1 -->|不可用| E3["兜底：字符 2/3-gram 哈希向量<br/>固定 512 维，与主后端同维<br/>记忆功能绝不因为小脑缺失就整个瘫掉"]
        E4["为什么不是『只用 nn.Embedding 那一层』<br/>实测同样 20 条：只用 embedding 层 rank-1 命中 4/5<br/>gold 分 0.49~0.66，与无关项的 0.52 几乎分不开<br/>两者都是 512 维，载体选更能干活的那个"]
        E2 --> E4
    end

    W3 --> E1

    subgraph READ["🔍 读取路径（每一轮提问时）"]
        direction TB
        R1["_retrieve_memory 拿用户本轮原话当 query"]
        R2["embedder.embed query → 512 维"]
        R3["memory_vec.search_memory<br/>numpy 快路径一次矩阵乘扫全库<br/>20 条约 2~5ms，没有 numpy 退化纯 Python 循环"]
        R4{"原始余弦 ≥ threshold 0.6 ？"}
        R5["时间衰减只参与排序<br/>7 天内 ×1.0 · 30 天内 ×0.7 · 更早 ×0.4<br/>按 score × decay 排序 → 取 top_k = 5"]
        R6["按 token 预算装进注入文本<br/>上限 2000 token；命中了就一定给模型看到至少 1 条<br/>每条正文压到 240 字以内"]
        R7["说话人框定<br/>每行加前缀『用户曾说过：』<br/>不加这层框定，模型会把记忆里的『我叫张三』当成在说它自己"]
        R8["注入 system<br/>_MEMORY_INSTRUCTION + 【相关记忆】<br/>注入点在 system 拼好之后、_plan_tools 之前，token 会被算进预算"]
        R9["写 logs/memory_retrieval.log<br/>后端 · 检索条数 · 每条相似度 · 注入 token · 耗时 · 模型是否使用"]
        R1 --> R2 --> R3 --> R4
        R4 -->|低于阈值| R_DROP["丢弃这一条"]
        R4 -->|达到阈值| R5
        R5 --> R6 --> R7 --> R8 --> R9
    end

    R8 --> MODEL["🤖 模型（工人）<br/>看到就用，不负责检索、不负责判断相关性"]
    MODEL --> BACK{"_memory_used 判定：<br/>答案里出现了记忆独有的实义词吗？"}
    BACK -->|出现| B1["回填 模型使用=是"]
    BACK -->|没出现| B2["回填 模型使用=否"]
    B1 --> STAT["retriever.usage_rate 统计使用率<br/>『检索到了模型不用』和『根本没检索到』要能分开看"]
    B2 --> STAT

    classDef w fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef e fill:#f3e8ff,stroke:#a78bfa,color:#4c1d95;
    classDef r fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef m fill:#fce7f3,stroke:#f472b6,color:#831843;
    class W1,W2,W3,W4,W5 w;
    class E1,E2,E3,E4 e;
    class R1,R2,R3,R4,R5,R6,R7,R8,R9,R_DROP r;
    class MODEL,BACK,B1,B2,STAT m;
```

**一条最关键的设计取舍：阈值判在"原始余弦"上，时间衰减只参与排序。**

Spec 的原话是"余弦相似度 + 时间衰减，阈值 0.6"。如果**把衰减乘进阈值判定**，会出事：
一条 0.85 分的老记忆，衰减 0.4 之后只剩 0.34 < 0.6 → 被丢掉。
那"三年前说的那个事"就**永远检索不到**了 —— 正好打死无限 1 的招牌场景。

所以这里拆开用：

- **阈值只判原始余弦**（判"这条到底相不相关"）——相关就是相关，跟多久以前无关；
- **时间衰减只参与排序**（同样相关时，优先想起最近的）——这才是我们真正想要的人类式记忆：
  老的能想起来，但新的更靠前。

**另外三个真实踩坑（都在这一步撞出来的）**：

1. **注入的记忆没有"说话人框定"** → 模型把「我叫张三」当成在说它自己，回答"你叫小焦"。
   修法：`_MEMORY_INSTRUCTION` 写明"记忆里的「我」= 用户，不是指你小焦"，注入行加前缀「用户曾说过：」。
2. **`detect_tool_intent` 用光杆动词"写"判"要新建"** → 问句「我平时最喜欢用什么语言**写**代码」
   被判成 `write_file`，让模型转成 `run_command whoami`，把用户名 "jiao" 总结成"已创建 jiao 文件夹"。
   **答非所问还谎报执行**。修法：新建类判据只认带宾语的动作短语，不认光杆"写"。
3. **写入路径存了整段回答** → 均值池化按长度加权，用户那句短话被几百字寒暄淹掉，cos 掉到阈值以下、注入 0 条。
   修法：`add_memory(..., key_text=用户那句话)`。

> 实测（`python tools/test_memory_recall.py`）：命中率 5/5 = 100%、使用率 5/5 = 100%、平均检索延迟 4.5ms
> （要求 < 100ms）。本文编写时复跑检索侧（`--no-model`，临时库、不调模型，退出码 0）：
> 后端 `minigpt` / 512 维，命中率 **5/5 = 100%**，gold 原始余弦 0.663~0.852，
> 延迟**平均 2.8~3.3ms / 最大 5.0ms**。
>
> 实测（`logs/_step2_live.py`）：20 轮无关对话冲淡后，问「我叫什么」仍检索命中「张三」
> 3 条 / 739 token，回答"你叫 **张三**"，延迟 5.1ms。
>
> 配套阅读：[six-infinity.md](../six-infinity.md) 的"已知局限"一节 —— 检索日志里也出现过
> 416.7ms / 538.0ms 的冷启动单次，以及无关问题拿到 0.6 以上相似度的情况，都如实记录了。
