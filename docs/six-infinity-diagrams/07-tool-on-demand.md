# 工具按需加载流程图

> 「工具无限」的准确含义是：**工具一个不删、不暂缓、不砍**；载体只决定"这一轮真发哪几个的 schema 出去"。
> 完整工具目录始终随 system 下发，模型点名的工具下一轮就装上。
> 对应实现：`_detect_intent` / `_intent_tool_names` / `_tool_index` / `_plan_tools` / `_build_tools`。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    Q["😀 用户这一句话"] --> DI["_detect_intent 规则识别意图（不靠模型）<br/>顺序即优先级：画图 &gt; 网址 &gt; 命令原文 &gt; 查询 &gt; 命令词 &gt; 闲聊 &gt; chat 兜底"]

    DI --> I_DIAG["diagram"]
    DI --> I_SCRAPE["scrape"]
    DI --> I_QUERY["query"]
    DI --> I_SHELL["shell"]
    DI --> I_CHAT["chat"]

    subgraph LOAD["📦 _intent_tool_names 该意图加载哪些工具（永不返回 None）"]
        direction TB
        L1["chat → 3 个<br/>web_search · read_memory · list_files"]
        L2["scrape → 10 个<br/>get · fetch · stealthy_fetch · scrape_with_selector · download …"]
        L3["query → 5 个<br/>net_ip · collect_vulnerabilities · get_weather · read_file · web_search"]
        L4["shell → 3 个<br/>run_command · read_file · write_file"]
        L5["diagram → 18 个<br/>archify 全链 + read_file · open_app · list_files"]
        L6["full → _FULL_CORE_TOOLS 核心 10 个<br/>不是全部 77 个；完整目录由 system 里的工具索引下发"]
        L7["返回前与 all_tool_names 对一遍<br/>不存在的名字直接丢掉，防止『以为给了工具其实没给』"]
    end

    I_CHAT --> L1
    I_SCRAPE --> L2
    I_QUERY --> L3
    I_SHELL --> L4
    I_DIAG --> L5

    subgraph WHY["❗ 为什么不能一轮全发（实测数字）"]
        direction TB
        Y1["全部工具 77 个的完整 schema<br/>= 13891 token<br/>= 可用上限 19224 的 72%"]
        Y2["第 1 步之前的兜底是 full → None → 全量 77 个<br/>结果：说一句『你好』都撞 ctx 墙<br/>这正是把兜底从 full 改成 chat 的原因"]
        Y1 --> Y2
    end

    L1 --> INDEX
    L2 --> INDEX
    L3 --> INDEX
    L4 --> INDEX
    L5 --> INDEX
    L6 --> INDEX["_tool_index only=本轮工具<br/>把工具名 + 一句话说明拼进 system<br/>清单里出现的就是这一轮真能调的"]

    INDEX --> SYS["system_for_intent<br/>chat 的 system 只要 248 token<br/>diagram 的 system 是 2596 token"]
    SYS --> PLAN["_plan_tools 定本轮工具并保证装得下<br/>budget = max_ctx - system - 本轮 - 消息外壳开销<br/>tok = _tools_tokens 这组工具的 schema 预估"]

    PLAN --> FIT{"schema token &gt; budget ？"}
    FIT -->|没超| KEEP["按意图装载，直接发出去"]
    FIT -->|超了| TRIM["从列表尾部收敛本轮装载量<br/>日志中性表述：本轮按意图装载 N 个工具<br/>完整工具表仍在 plugins/ 目录，按需加载"]
    TRIM --> KEEP

    KEEP --> CTX["_fit_context tools_tokens=本组工具<br/>把 tools schema 的 token 算进总量<br/>漏算它就会出现『裁完了还是超限』"]
    CTX --> CALL["llm_chat_tools tools_subset=本轮工具<br/>_build_tools 只构造这一组的 schema"]

    CALL --> M["🤖 模型（工人）<br/>只在看得见的工具里挑"]
    M --> HIT{"模型点名了清单里没有的工具？"}
    HIT -->|点名了| NEXT["下一轮按名字把它装上<br/>_named_tools / _noarg_named_tool 识别<br/>零参数工具（如 archify_doctor）直接调用"]
    HIT -->|没有| EXEC["执行工具 · 结果回灌 · 继续轮次<br/>同一工具连续失败 3 次熔断，把真实报错摆给用户"]
    NEXT --> CALL

    subgraph S5["🚧 第 5 步：工具调度 + 上下文隔离（设计中，尚未落地 —— 落地后接入上面这一步）"]
        direction TB
        D1["代码层强制路由<br/>URL → scrapling ｜ 画图 → archify 链<br/>搜索 → 禁功能字 ｜ 查询 → net_ip / collect_vulnerabilities<br/>未识别 → chat"]
        D2["约 500 字以上的工具结果只存摘要进持久历史<br/>前 200 字 + 工具名 + 状态码<br/>完整结果仍对当次回答可用<br/>大 JSON / HTML 不进历史"]
        D3["结果校验：对照目标特征（域名 / 标题）<br/>不符就标记『可能幻觉』"]
        D4["工作流强制<br/>先 archify_read_skill<br/>archify_deliver 前必须有 archify_validate，缺了代码层补调"]
    end

    EXEC -.-> S5

    classDef q fill:#fef9c3,stroke:#eab308,color:#713f12;
    classDef load fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef why fill:#fee2e2,stroke:#f87171,color:#7f1d1d;
    classDef plan fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef s5 fill:#f1f5f9,stroke:#94a3b8,color:#1e293b;
    class Q,DI,I_DIAG,I_SCRAPE,I_QUERY,I_SHELL,I_CHAT q;
    class L1,L2,L3,L4,L5,L6,L7 load;
    class Y1,Y2 why;
    class INDEX,SYS,PLAN,FIT,KEEP,TRIM,CTX,CALL,M,HIT,NEXT,EXEC plan;
    class D1,D2,D3,D4 s5;
```

**四条硬性规则（第 1 步就钉死的）**：

1. **`_intent_tool_names` 永不返回 `None`**。`None` 的旧含义是"全部 77 个"，那是把 ctx 挤爆的根因。
   现在拿不准就给核心集，绝不回落全量。
2. **`_FULL_CORE_TOOLS` 是核心 10 个，不是全部**。`full` 分支保留下来只供"工具目录查询"，
   不再由意图识别触发（兜底已改为 `chat`）。
3. **`full` 意图下 `_tool_index(only=None)` 是故意的**：本轮 schema 只发核心集，但目录要列全 77 个，
   模型才知道"还有哪些工具可以点名"。
4. **日志措辞必须中性**。这里以前会写"本轮因为额度不够，所以少发了 N 个工具"——那是**错的**：
   工具一个都没删、没停用、没缩减，`plugins/` 目录 77 个一个不少。已 grep 确认
   `暂缓|预算不足|砍掉|工具预算` 在代码里 0 命中。

**一个真实事故值得记住**：`plugins/search.py` 曾被移到 `_disabled/`，实测导致 `web_search` 工具**消失**（只剩 76 个）
—— 它不是重复插件，而是 `web_search` 工具 schema 的**唯一**提供者（`load_plugins` 里 `web-search` 那条是
`builtin:True` 占位，`_build_tools` 会跳过 builtin）。已还原。**这就是"工具一个不删"这条铁律的由来。**

> 实测（`python tools/check_prompt_size.py`）：`全部工具：77 个 → 13891 token（占上限的 72%）`；
> 各意图固定开销：chat 657 / scrape 4614 / diagram 5478 / query 2666 / shell 2299 / full 7742。
>
> 配套阅读：[03-data-flow.md](03-data-flow.md)（工具装载在数据流里的位置）、
> [six-infinity.md](../six-infinity.md)（第 5 步的完整设计与验收计划）。
