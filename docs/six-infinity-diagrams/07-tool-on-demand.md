# 图 7 · 工具无限：按意图装载 + 点名即下轮装载

| 项 | 内容 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |

**摘要**：工具无限的含义是工具一个不删、不暂缓、不砍；载体只决定"这一轮真发哪几个工具的 schema"，
完整工具目录始终随 system 下发，模型点名的工具下一轮就装上。

配色与术语约定见 [01-overview.md](01-overview.md) 的「图册约定」。

## 1. 图 7 · 从一句话到"这一轮发哪几个工具"

```mermaid
    %%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    Q["用户这一句话"]
    DI["_detect_intent 规则识别意图<br/>不调用模型"]

    subgraph ORDER["判据顺序即优先级，命中即返回"]
        direction TB
        O1["画图 _asks_diagram"]
        O2["带网址 _looks_like_url"]
        O3["命令原文 _looks_like_shell_command"]
        O4["公网 IP 与查询词 _asks_net_ip / _INTENT_HINTS"]
        O5["明确检索请求 _asks_info_collect"]
        O6["命令词与夹着命令 _mentions_shell_command"]
        O7["明确寒暄 _is_chitchat"]
        O8["兜底 chat"]
    end

    subgraph LOADG["_intent_tool_names 该意图加载哪些工具（永不返回 None）"]
        direction TB
        L1["chat → 3 个<br/>web_search · read_memory · list_files"]
        L2["scrape → 10 个<br/>get · make_request · fetch · stealthy_fetch · bulk_get<br/>bulk_fetch · scrape_with_selector · download · screenshot · web_search"]
        L3["query → 5 个<br/>net_ip · collect_vulnerabilities · read_file · web_search · get_weather"]
        L4["shell → 3 个<br/>run_command · read_file · write_file"]
        L5["diagram → 18 个<br/>archify 全链 + read_file · open_app · list_files"]
        L6["full → _FULL_CORE_TOOLS 核心 10 个<br/>不是全部 77 个"]
        L7["返回前与 all_tool_names 对一遍<br/>不存在的名字直接丢掉"]
    end

    subgraph ASSEMBLE["装配与预算"]
        direction TB
        INDEX["_tool_index only=本轮工具<br/>工具名 + 一句话说明拼进 system<br/>清单里出现的就是这一轮真能调的"]
        SYS["system_for_intent 按意图生成 system"]
        PLAN["_plan_tools 定本轮工具<br/>budget = max_ctx - system - 本轮 - 消息外壳开销"]
        FIT{"schema token > budget？"}
        KEEP["按意图装载，直接发出去"]
        TRIM["从列表尾部收敛本轮装载量<br/>至少保留 1 个"]
        CTX["_fit_context tools_tokens=本组工具<br/>把 schema 的 token 算进总量"]
        CALL["llm_chat_tools tools_subset=本轮工具<br/>_build_tools 只构造这一组的 schema"]
    end

    M["模型（火种）<br/>只在看得见的工具里挑"]
    HIT{"模型点名了清单里没有的工具？"}
    NEXT["下一轮按名字把它装上<br/>_named_tools / _noarg_named_tool 识别<br/>零参数工具直接调用"]
    EXEC["执行工具 · 结果回灌 · 继续轮次<br/>同一工具连续失败 3 次熔断"]

    S5["第 5 步：工具调度 + 上下文隔离（设计，未落地）<br/>代码层强制路由：URL → scrapling · 画图 → archify 链<br/>搜索 → 禁功能字 · 查询 → net_ip / collect_vulnerabilities<br/>约 500 字以上的工具结果只存摘要进持久历史<br/>结果校验：对照目标特征不符则标记可能幻觉<br/>工作流强制：archify_deliver 前必须有 archify_validate"]

    Q --> DI --> ORDER
    ORDER -->|对应意图| LOADG
    LOADG --> INDEX
    O1 -.-> L5
    O2 -.-> L2
    O3 -.-> L4
    O4 -.-> L3
    O6 -.-> L4
    O7 -.-> L1
    O8 -.-> L1
    L7 --> INDEX
    INDEX --> SYS --> PLAN --> FIT
    FIT -->|没超| KEEP
    FIT -->|超了| TRIM
    TRIM --> KEEP
    KEEP --> CTX --> CALL --> M --> HIT
    HIT -->|点名了| NEXT
    HIT -->|没有| EXEC
    NEXT --> CALL
    EXEC -.-> S5

    style Q fill:#4A90E2,color:#fff
    style M fill:#4A90E2,color:#fff
    style DI fill:#7ED321,color:#fff
    style L7 fill:#7ED321,color:#fff
    style INDEX fill:#7ED321,color:#fff
    style SYS fill:#7ED321,color:#fff
    style CALL fill:#7ED321,color:#fff
    style FIT fill:#F5A623,color:#fff
    style HIT fill:#F5A623,color:#fff
    style TRIM fill:#F5A623,color:#fff
    style PLAN fill:#F5A623,color:#fff
    style L6 fill:#F5A623,color:#fff
    style O8 fill:#F5A623,color:#fff
    style S5 fill:#E74C3C,color:#fff
```

**一句话说明**：意图决定这一轮装载哪一小撮工具，预算只影响这一轮发几个 schema，
完整工具目录始终在 system 里——所以"能力不封顶"与"单次不超"能同时成立。

## 2. 代码位置索引

| 节点 | 代码位置 |
| --- | --- |
| 意图识别 | `xiaojiao_app.py` → `_detect_intent`（第 5895 行）；辅助判据 `_asks_diagram`（第 5355 行）、`_looks_like_url`（第 5350 行）、`_looks_like_shell_command`（第 5369 行）、`_asks_net_ip`（第 5388 行）、`_asks_info_collect`（第 5442 行）、`_mentions_shell_command`（第 5944 行）、`_is_chitchat`（第 5877 行） |
| 意图词表 | `_INTENT_HINTS`（第 5420 行） |
| 意图到工具 | `_intent_tool_names`（第 5847 行）、`_INTENT_TOOLS`（第 5767 行）、`_FULL_CORE_TOOLS`（第 5763 行）、`all_tool_names`（第 5831 行） |
| 工具目录 | `_tool_index`（第 5998 行） |
| system 生成 | `system_for_intent`（第 6040 行）；模式提示 `_CHAT_SYSTEM_HINT`、`_CHAT_FALLBACK_HINT`、`_DIAGRAM_SYSTEM_HINT`（第 5776–5787 行） |
| 预算与收敛 | `_plan_tools`（第 6066 行）、`_tools_tokens`（第 5822 行）、`_estimate_tokens`（第 6105 行）、`_max_context_tokens`（第 6122 行）、`_fit_context`（第 6154 行） |
| 下发与调用 | `llm_chat_tools`（第 3339 行）、`_build_tools(only=...)`（第 1159 行） |
| 点名装载 | `_named_tools`（第 4351 行）、`_noarg_named_tool`（第 4380 行） |
| 工具熔断 | `_tool_breaker`（第 3554 行） |
| 第 5 步设计 | 见 [six-infinity.md](../six-infinity.md) 的「设计目标（尚未落地）」一节 |

## 3. 为什么不能一轮全发

| 事实 | 数字 |
| --- | --- |
| 全部工具 | 77 个 |
| 全部 schema | 13891 token |
| 占可用上限 | 72%（上限 19224） |

单这一项就吃掉上限的 72%，所以"每轮全发"必然顶穿本地上下文。历史缺陷：`full` 意图的兜底
曾经等于"全部 77 个"，说一句"你好"都可能撞上下文墙。现在 `_detect_intent` 的兜底是 `chat`，
而 `_intent_tool_names` 对未知意图、空子集一律返回核心集，**永不返回 `None`**。

## 4. 各意图的实测开销

`python tools/check_prompt_size.py`（可用上限 19224）：

| 意图 | system | tools | 本轮 | 合计 | 占上限 | 本轮装载工具 |
| --- | --- | --- | --- | --- | --- | --- |
| chat | 284 | 381 | 4 | 693 | 4% | 3 个 |
| scrape | 2041 | 2576 | 9 | 4650 | 24% | 10 个 |
| diagram | 2632 | 2850 | 8 | 5514 | 29% | 18 个 |
| query | 1789 | 884 | 5 | 2702 | 14% | 5 个 |
| shell | 1727 | 581 | 4 | 2336 | 12% | 3 个 |
| full | 5678 | 2069 | 7 | 7778 | 40% | 10 个 |

| 意图 | `_intent_tool_names` 返回个数 | 该组 schema token |
| --- | --- | --- |
| chat | 3 | 381 |
| scrape | 10 | 2576 |
| query | 5 | 884 |
| shell | 3 | 581 |
| diagram | 18 | 2850 |
| full | 10 | 2069 |

## 5. 四条硬性规则

1. **`_intent_tool_names` 永不返回 `None`**。`None` 的旧含义是"全部 77 个"，那是把上下文挤爆的根因；
   现在拿不准就给核心集，绝不回落全量。
2. **`_FULL_CORE_TOOLS` 是核心 10 个，不是全部**。`full` 分支保留下来只供"工具目录查询"，
   不再由意图识别触发（兜底已改为 `chat`）。
3. **`full` 意图下 `_tool_index(only=None)` 是故意的**：本轮 schema 只发核心集，但目录要列全 77 个，
   模型才知道还有哪些工具可以点名。
4. **日志措辞必须中性**。这里以前会写"本轮因为额度不够，所以少发了 N 个工具"，那是错的：
   工具一个都没删、没停用、没缩减，`plugins/` 目录 77 个一个不少。现在的措辞是
   "本轮按意图装载 N 个工具（完整工具表仍在 plugins/ 目录，按需加载）"。

## 6. 一次真实事故：`plugins/search.py` 被移走

`plugins/search.py` 曾被移到 `_disabled/`，实测导致 `web_search` 工具消失（工具数从 77 变成 76）。
它不是重复插件，而是 `web_search` 工具 schema 的**单独提供者**：`load_plugins` 里 `web-search` 那条是
`builtin: True` 的占位，而 `_build_tools` 会跳过 builtin 条目。已还原。
这就是"工具一个不删"这条铁律的由来。

## 7. 边界与限制

| 边界 | 说明 |
| --- | --- |
| 意图判据是启发式 | 纯规则字符串判据，认不出来一律兜底 `chat`；判错时这一轮不装某些工具，模型可以点名，下一轮补装 |
| 收敛只影响一轮 | `_plan_tools` 超预算时从列表尾部收敛，**至少保留 1 个**；它不动"系统有多少工具" |
| 工具目录依赖 system | 模型能点名的前提是目录在 system 里；system 被截断或意图为 `chat` 时目录仍然存在（`_tool_index` 只收窄清单，不删除目录文本） |
| 连续失败熔断 | 同一工具连续失败 3 次后熔断并把真实报错摆给用户；熔断期间不再重复调用该工具 |
| 第 5 步未落地 | 图里红色那一格（代码层强制路由、工具结果上下文隔离、结果校验、工作流强制）是设计，尚未落地；落地前这些行为仍由模型与提示词约束 |
| 工具数量会变 | 本文的 77 个 / 13891 token 来自最近一次 `tools/check_prompt_size.py`；新增插件后需复测 |

## 8. 相关阅读

- [03-data-flow.md](03-data-flow.md)：工具装载在数据流里的位置（阶段 3）
- [06-memory-retrieval.md](06-memory-retrieval.md)：同样属于"按需装配"的记忆注入
- [six-infinity.md](../six-infinity.md)：工具无限的定义与第 5 步的完整设计

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
