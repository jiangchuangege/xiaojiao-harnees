# 六个无限 · 总览图

> 一张图看清「载体优先」这一版重构的六个目标。核心一句话：**模型是工人，载体是工厂** ——
> 模型永远只处理「当前这一小块」，六个"无限"全部由载体在模型**外面**兜出来。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart LR
    U["😀 用户<br/>想说什么就说什么 · 想贴多长就贴多长 · 想要多长就要多长"]
    F["🏭 载体层（工厂）<br/>分解 · 装配 · 存储 · 调度 · 拼装 · 校验<br/>能力全在这一层实现"]

    subgraph SIX["六个无限 —— 都是载体在模型外面兜出来的结果"]
        direction TB
        I1["① 记忆无限<br/>core/memory_vec.py · core/retriever.py<br/>全部历史永久存外部向量库，每轮检索 top-K 注入 system<br/>不占模型 ctx"]
        I2["② 输入无限<br/>core/input_splitter.py<br/>任意长输入在入口被切片 → 循环处理 → 拼装<br/>用户只看到「正在处理」"]
        I3["③ 输出无限<br/>core/continuation.py<br/>任意长输出拆成多次请求生成 → 无缝合并成一段连续输出"]
        I4["④ 工具无限<br/>_intent_tool_names · _plan_tools<br/>plugins/ 里的工具一个不删、不暂缓<br/>按意图装载；模型点名的下一轮就装上"]
        I5["⑤ 感知无限<br/>SSE 只推正文，界面只显示「正在处理」<br/>用户看不到切片/循环/合并/检索/第 X 片 这类痕迹"]
        I6["⑥ 单次永不超<br/>_max_context_tokens · _plan_tools · _fit_context<br/>单次请求不超上下文窗口（物理红线，不假装无限）"]
    end

    M["🤖 模型（工人）<br/>只处理「当前这一小块」<br/>不知道自己正在被循环调度"]

    U --> F
    F --> I1
    F --> I2
    F --> I3
    F --> I4
    F --> I5
    F --> I6
    I1 --> M
    I2 --> M
    I3 --> M
    I4 --> M
    I5 --> M
    I6 --> M

    classDef user fill:#fef9c3,stroke:#eab308,color:#713f12;
    classDef fac fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef six fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef mdl fill:#fce7f3,stroke:#f472b6,color:#831843;
    class U user;
    class F fac;
    class I1,I2,I3,I4,I5,I6 six;
    class M mdl;
```

**怎么读这张图**：左边是用户，右边是模型，中间那一整块是载体层。图里没有任何一条边是"用户直接连模型"——
用户能感知到的"无限"，全部是载体在模型外面用循环、外部存储和多次请求兜出来的。

- ①③ 是**同一类手法**：单次装不下 / 单次给不完，就拆成多次，只是分别发生在输入侧和输出侧。
- ④⑥ 是**一对约束**：工具能力要"一个不少"（④），但一轮里塞不下全部工具 schema（77 个 = 13891 token，占
  19224 上限的 72%），所以只能在"哪些工具这一轮真发出去"上做取舍（⑥）。
- ⑤ 不是独立机制，而是①~④ 的**对外表现要求**：循环可以有，痕迹不能有。

> 配套阅读：[six-infinity.md](../six-infinity.md)（定义 / 痛点 / 实现 / 验收数据 / 已知局限）、
> [02-carrier-layer.md](02-carrier-layer.md)（载体层内部结构）。
