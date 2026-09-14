# 输入切片流程图

> 「输入无限」——用户能贴任意长度（10 万字文章、50 万字报告），模型单次只装得下 2 万 token。
> 载体的解法是：**在入口就切片、循环、落盘、拼装**；模型每次只处理"当前这一片"。
> 对应实现：`core/input_splitter.py` 的 `split_task` / `split_input` / `process_long_input`。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    U["😀 用户贴进来一大段<br/>可能还带着一句要求：帮我总结一下这篇文章的要点"] --> ENTRY{"agent_run 入口<br/>_needs_input_split<br/>_estimate_tokens 超过 5000 吗？"}
    ENTRY -->|没超| NORMAL["普通输入<br/>照常走单次回答"]
    ENTRY -->|超了| TASK["split_task 把「要求」和「内容」分开<br/>第一段很短且总段数 ≥ 3 或 ≥ 2 → 第一段是要求<br/>找不到明显要求就用一句通用要求兜底"]

    TASK --> SPLIT{"split_input<br/>整篇 token ≤ max_chunk 吗？<br/>默认 5000"}
    SPLIT -->|是| ONE["单片直接返回<br/>短输入不切片，用户无感"]
    SPLIT -->|否| PARA["split_paragraphs 先按空行/换行切段<br/>一段完整的话，比『刚好凑满 5000』重要得多"]

    PARA --> EACH{"逐段检查：这一段自己就超限吗？"}
    EACH -->|没超| UNIT["作为一个切分单元"]
    EACH -->|超了| OVERSIZE["_split_oversize<br/>先退到句边界，_SENT_SPLIT 按 。！？!?；;… 切<br/>单句还超长 → _hard_split 硬切"]
    OVERSIZE --> HARD["_hard_split 按字符比例硬切<br/>留 0.85 安全余量<br/>不留余量实测会切出 5010 > 5000"]
    HARD --> UNIT

    UNIT --> ACC["按顺序累加装片<br/>粘合开销也要算：每多粘一段就多一个换行分隔<br/>只累加各段自己的 token，实测 sum=4988 拼出来是 5003"]
    ACC --> FULL{"cur + 分隔 + 本段 > max_chunk ？"}
    FULL -->|是| SEAL["封片，开新片"]
    FULL -->|否| KEEP["并进当前片"]
    SEAL --> ACC
    KEEP --> ACC
    ACC --> SAFETY["最后一道保险：逐片复验<br/>任何一片仍超限就硬切<br/>保证「每片都装得下」这个不变量"]

    SAFETY --> LOOP["逐片循环处理<br/>系统提示词用完整版（长文处理本来就不是闲聊，规则给足更稳）"]

    LOOP --> PROMPT["每片的 prompt<br/>用户的要求 + 这是全文的一段（共 N 段）<br/>只处理这一段，不要重复上一段结论，不要写『以下是第几段』"]
    PROMPT --> LLM["调模型处理这一片"]
    LLM --> SAVE["save_chunk 把这一片的产出落 logs/_chunks/<br/>进度不丢、可核对、可续跑"]
    SAVE --> PROG["on_progress 回调<br/>SSE 只发 progress，不带片号<br/>界面只显示『正在处理…』"]
    PROG --> MORE{"还有下一片吗？"}
    MORE -->|有| PROMPT
    MORE -->|没有| MERGE["merge_outputs 拼装<br/>跨片累加整句去重（相邻两片模型会把上片结论又复述一遍）<br/>再用换行分隔接起来"]

    MERGE --> OUT["📤 一份完整结果<br/>用户看到的是『完整总结』，不是『第 3/5 片』"]
    PROG --> FE["🖥️ 前端<br/>只显示『正在处理…』，不显示第 X/Y 片<br/>（无限 5 · 感知无限）"]

    classDef in fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef slice fill:#f3e8ff,stroke:#a78bfa,color:#4c1d95;
    classDef loop fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef ui fill:#fef9c3,stroke:#eab308,color:#713f12;
    class U,ENTRY,NORMAL,TASK,SPLIT,ONE,PARA in;
    class EACH,UNIT,OVERSIZE,HARD,ACC,FULL,SEAL,KEEP,SAFETY slice;
    class LOOP,PROMPT,LLM,SAVE,MORE,MERGE,OUT loop;
    class PROG,FE ui;
```

**切片的硬要求（以及为什么）**：

- **按段落边界切，绝不切在句中**。半句单独喂给模型，它会当成"残缺输入"去猜，输出就跟着残。
- **段落本身超长 → 退到句边界；单句还超长 → 才硬切**，而且要留 `0.85` 的字符余量：
  字符数到 token 是线性估计，边界上会差几个 token。第 4 步单测实测——不留余量时切出来 `5010 > 5000`，
  差一点点也是超。
- **粘合开销必须算进累加**。每多粘一段就多一个 `\n\n`。第 4 步单测实测：只累加各段自己的 token，
  `sum=4988` 拼出来实际是 `5003` —— 照样超。
- **最后一道保险不能省**。累加逻辑再对，也可能有边界情况；收尾逐片复验一次，
  "每片 ≤ max_chunk" 才是**不变量**而不是"通常成立"。
- **`on_progress(done, total)` 故意不暴露片数**。这是无限 5 的要求：界面只显示"正在处理"，
  用户看不到"第 X/Y 片"这种技术痕迹。

> 实测（`logs/xiaojiao.log`）：`长输入切片：22778 token → 拆成 5 片处理 / 输出 923 字 / 耗时 16.4s`
> —— 那份输入是 17326 字，切出的 5 片 token 分别是 `[4888, 4895, 4909, 4909, 3156]`，最大 4909 ≤ 5000。
>
> 切片正确性单测（`python logs/_step4_unit.py`，本文编写时复跑：通过 15 / 失败 0）：
> 20006 字 / 25934 token → 6 片；66907 字 / 86485 token → 18 片；
> 两种规模**每片 ≤ 5000 token（观测最大都是 4930）**、半句收尾 0 片；
> 极长单段也能切（9 片，最大 4843）；拼回去长度一致（64907 vs 64907）。
>
> 配套阅读：[03-data-flow.md](03-data-flow.md)、[six-infinity.md](../six-infinity.md)。
