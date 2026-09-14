# 数据流向图：请求 → 检索 → 装配 → 模型 → 拼装 → 输出

> 一次 `agent_run` 从进到出的完整路径。左侧标了阶段，每个框里是**真实函数名**；
> 带数字的框是实测得出的固定开销（数据来自 `python tools/check_prompt_size.py`）。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    U["😀 用户一句话 / 一大段"] --> G1

    subgraph G1["阶段 1 · 入口分流（载体先判，不浪费模型）"]
        direction TB
        C1{"_needs_input_split<br/>超过 5000 token ？"}
        LONG["_process_long_input<br/>切片 → 逐片调模型 → 落 logs/_chunks/ → 拼装"]
        DIRECT["规则直通（跳过模型）<br/>漏洞表 · 资产测绘 · 当前时间<br/>公网 IP · 零参工具点名 · shell 原文 · 带网址抓取"]
        INTENT["_detect_intent → 意图<br/>diagram / scrape / query / shell / chat"]
    end

    C1 -->|是，输入无限| LONG
    C1 -->|否| DIRECT
    DIRECT --> INTENT

    subgraph G2["阶段 2 · 检索"]
        direction TB
        M1["recall 知识记忆<br/>xiaojiao_knowledge_memory.json"]
        M2["_retrieve_memory 对话记忆<br/>core/retriever.retrieve<br/>cos ≥ 0.6 · top-K 5 · 注入 ≤ 2000 token"]
        W1["web_search 联网资料<br/>先过 resolve_search_query 清洗检索词"]
    end

    INTENT --> M1
    INTENT --> M2
    INTENT --> W1

    subgraph G3["阶段 3 · 装配（按需，能省就省）"]
        direction TB
        S1["system_for_intent 按意图生成 system<br/>chat = 248 token · diagram = 2596 token"]
        S2["拼「本轮」_current<br/>相关记忆 + 联网资料 + 小脑技能经验 + 用户原话"]
        S3["_plan_tools 定本轮工具<br/>chat 3 个 = 381 token · diagram 18 个 = 2850 token"]
        S4["_fit_context 滑动窗口 + 硬性截断<br/>system 与本轮永远保留，历史从最老的一端丢"]
        S5["写 logs/context_fit.log<br/>system=a + tools=b + 本轮=c = 合计 d / 上限 e"]
    end

    M1 --> S2
    M2 --> S1
    W1 --> S2
    S1 --> S2 --> S3 --> S4 --> S5

    subgraph G4["阶段 4 · 模型（工人干活）"]
        direction TB
        D1{"_needs_continuation<br/>用户明确要长文 ？"}
        D2["_generate_long → generate_unlimited<br/>多次请求 · 预取线程守着影子正文"]
        D3["llm_chat_tools<br/>带 tools_subset 的 function calling 循环"]
    end

    S5 --> D1
    D1 -->|是，输出无限| D2
    D1 -->|否| D3

    subgraph G5["阶段 5 · 拼装（每段都过一遍）"]
        direction TB
        A1["overlap_len 找最长重叠<br/>裁掉模型重抄的上段结尾"]
        A2["drop_repeated_sentences 去整句复读<br/>接缝裁剪管不到段中间的复读"]
        A3["cut_at_sentence 半句回退<br/>残句带进下一轮，不切在句中"]
        A4["on_chunk 把通过校验的这一段推给前端<br/>SSE 追加进同一个气泡"]
    end

    D2 --> A1 --> A2 --> A3 --> A4
    D3 --> OUT

    A4 --> OUT["📤 一段连续输出<br/>用户看不出是分了几次生成的"]

    OUT --> B1["_remember_turn 把这一轮永久写进向量库<br/>索引键 = 用户那句话 key_text"]
    B1 --> B2["_memory_used + retriever.record_usage<br/>回填「模型到底有没有用上检索到的记忆」"]
    OUT --> U

    classDef g1 fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef g2 fill:#f3e8ff,stroke:#a78bfa,color:#4c1d95;
    classDef g3 fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef g4 fill:#fce7f3,stroke:#f472b6,color:#831843;
    classDef g5 fill:#fff7ed,stroke:#fb923c,color:#7c2d12;
    class C1,LONG,DIRECT,INTENT g1;
    class M1,M2,W1 g2;
    class S1,S2,S3,S4,S5 g3;
    class D1,D2,D3 g4;
    class A1,A2,A3,A4 g5;
```

**几个容易看漏的点**：

- **阶段 1 的"直通"不是优化，是防错**。实测过的真实缺陷：问"我的公网 IP"交给模型答，它嘴上说"我通过 net_ip
  查了"，内容却是模板占位符；换个问法它**编了一个 IP** 出来。"查出来的东西"最不该由模型转述，所以规则能判的一律直通。
- **记忆注入点放在 system 拼好之后、`_plan_tools` 之前**。这样注入的记忆会被算进 token 预算，
  不会再出现"注入完了才发现超限"的老毛病——第 1 步实测踩过：先裁剪、后拼注入内容，裁剪报告写
  "合计 18926 / 上限 19000"，实际请求却是 19898，照样超限。
- **输出侧的两条路共用同一套 system**。`_generate_long` 拿到的就是阶段 3 装好的那份 system
  （含按意图装载的工具目录），所以长文续写和普通对话的规则、记忆、工具完全一致。
- **落库发生在最后**。只有答案出来了才知道检索到的记忆有没有被用上，所以"是否使用"的回填放在这一轮结束时
  （`logs/memory_retrieval.log`）——这是"使用率"指标唯一的依据，不能自己给自己打高分。

> 配套阅读：[04-output-continuation.md](04-output-continuation.md)（阶段 4→5 的细节）、
> [05-input-splitter.md](05-input-splitter.md)（阶段 1 的切片细节）。
