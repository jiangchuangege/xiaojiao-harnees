# 载体层内部结构图

> 「工厂」里到底有哪几个车间。八个职责全部落在 `xiaojiao_app.py` 与 `core/` 里，图上每个框都标了
> **真实存在的函数名或文件路径** —— 没有一个是规划中的概念。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    IN["📥 一次请求进来<br/>agent_run · /api/chat/stream"] --> D

    subgraph FACTORY["🏭 载体层（工厂）—— 能力全在这八格里，不在模型里"]
        direction TB
        D["① 任务分解<br/>_detect_intent 规则判意图 · split_task 拆指令与内容<br/>parse_target_chars 解析目标字数 · needs_continuation 判断要不要走长文"]
        A["② 上下文装配（按需）<br/>system_for_intent 按意图生成 system · _retrieve_memory 注入相关记忆<br/>_plan_tools 定本轮工具并算 token · _fit_context 装不下就从最老的砍"]
        S["③ 状态管理<br/>shadow 影子正文 · inflight 段号认领 · _CONT_STOP 叫停位<br/>_MEMORY_LAST 记忆回填 · seen_sents 已出现整句集合"]
        E["④ 外部存储<br/>logs/xiaojiao_memory_vec.jsonl 对话向量库<br/>logs/_chunks/ 每片产出 · logs/context_fit.log 每轮 token 账"]
        L["⑤ 循环调度<br/>generate_unlimited 主循环 · 单条预取线程 + 条件变量<br/>process_long_input 逐片循环 · llm_chat_tools 工具轮次循环"]
        T["⑥ 工具调度<br/>_intent_tool_names 意图到工具名 · _FULL_CORE_TOOLS 核心集<br/>_tool_index 目录随 system 下发 · 点名的下一轮装载"]
        R["⑦ 结果装配<br/>overlap_len 最长重叠裁接缝 · drop_repeated_sentences 去整句复读<br/>cut_at_sentence 半句回退 · merge_outputs 跨片拼装"]
        V["⑧ 校验纠错<br/>looks_offtopic 偏题/重新开场判别 · _gen_one 失败重试<br/>_tool_breaker 连续失败熔断 · _layer4_after_call 换候选或停"]
    end

    D --> A --> T --> L
    L --> M["🤖 模型（工人）<br/>只处理「当前这一小块」<br/>输入：一段 prompt · 输出：一段文本"]
    M --> V
    V --> R
    R --> OUT["📤 一段连续的结果<br/>用户看不出中间循环了几次"]
    S --- L
    S --- R
    E --- S
    E --- R

    classDef io fill:#fef9c3,stroke:#eab308,color:#713f12;
    classDef fac fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef st fill:#f3e8ff,stroke:#a78bfa,color:#4c1d95;
    classDef mdl fill:#fce7f3,stroke:#f472b6,color:#831843;
    class IN,OUT io;
    class D,A,T,L,V fac;
    class S,E,R st;
    class M mdl;
```

**为什么把"状态"和"存储"单独画出来**：这两个车间是六个无限真正的地基，也是最容易漏掉的部分。

- **没有 `shadow`（影子正文）就没有输出无限**：预取下一段时必须知道"已提交正文 + 池里已生成但还没被取走的部分"
  是什么，否则第 N+1 段的衔接锚点和去重基准都是残缺的，拼出来会重句。第 3 步实测撞上过——
  chunk 编号出现 `[1,2,2]`，根因就是主循环的串行兜底和预取线程同时产出了同一个段号。
- **没有外部存储就没有记忆无限**：对话全部落在 `logs/xiaojiao_memory_vec.jsonl`（一行一条、append-only），
  进程重启不丢；每片的产出落在 `logs/_chunks/`，进度可核对、可续跑。
- **`_fit_context` 是"单次永不超"的最后一道闸**：system 与本轮问题永远保留，历史从最老的一端开始丢，
  并且把 tools schema 的 token 一起算进去（漏算它就会出现"裁完了还是超限"）。

> 配套阅读：[03-data-flow.md](03-data-flow.md)（一次请求的完整数据流）、
> [six-infinity.md](../six-infinity.md)（六个无限各自的验收数据）。
