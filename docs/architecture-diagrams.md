# 小焦 · 架构图册（20 张）

> 本文件是《小焦 · 载体优先架构》的**图册总集**。
> 图 1–11 对应 [`design-philosophy.md`](design-philosophy.md) 前十三节；
> 图 12–19 对应同一文件的**后半篇**（第十四至二十二节）；
> **图 20** 是后来补的**载体改造·路径二四阶段**（内感受 → 视角 → 硬改 → 归属回流），
> 不对应设计哲学的某一节，对应的是真实提交。
> 六个无限的逐图细解另见 [`six-infinity-diagrams/`](six-infinity-diagrams/)（7 张，含数据流与单模块时序）。
>
> 为什么单独开一份图册而不是塞进 README：
> README 是"第一眼"，读者扫两屏就该知道这是什么；图册是"要细看时"才来的地方。
> 混在一起的结果是 README 变成十几屏长图，第一眼就劝退。
>
> 图 12–20 的一个额外规矩：**每一节都标实现状态**（已落地 / 部分落地 / 设计未落地），
> 并指向真实代码路径。不标状态的架构图等于把"想做"画成"做过"。
>
> 所有图都用 `flowchart` 语法（不用 mindmap）：
> 本仓库的 `tools/check_mermaid.py` 会做**括号/引号/subgraph 配对**的静态校验，
> mindmap 不在它的校验范围内 —— 用校验得到的语法，等于让每张图每次 CI 都被检查一遍。
> 自检：`python tools/check_mermaid.py --all`（应 report 0 问题）。

---

## 图 1 · 总纲：把模型换成零件，把系统做成主体

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 360, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    ROOT["小焦<br/>用户眼里的「一个助手」"]

    subgraph MODEL["模型层 —— 火种，可替换零件"]
        direction LR
        M1["4B 本地模型"]
        M2["70B"]
        M3["360B / 云端"]
        M4["未来任意模型"]
    end

    subgraph CORE["载体层 —— 智力本体（项目核心）"]
        direction TB
        C1["任务理解 / 拆解 / 规划 / 判断 / 纠错 / 编排"]
        C2["记忆 · 工具 · 世界 · 人格 · 健康 · 自主 · 元认知"]
    end

    ROOT --> MODEL
    ROOT --> CORE
    M1 -.->|"热插拔：换火种不换小焦"| CORE
    M2 -.->|"同一套器官"| CORE
    M3 -.->|"同一套器官"| CORE
    M4 -.->|"同一套器官"| CORE
    CORE --> OUT["开箱即用的成品<br/>4B 在载体里发挥出远超它本身的能力"]

    style ROOT fill:#4A90E2,color:#fff
    style CORE fill:#7ED321,color:#fff
    style MODEL fill:#F5A623,color:#fff
    style OUT fill:#7ED321,color:#fff
```

**这张图要说的一句话**：模型是**换得起**的零件，载体才是"小焦"。
用户感受到的智力来自右边那一整块，而不是左边某一个模型。

---

## 图 2 · 十一大器官（载体内部有什么）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    BODY["载体 = 完整的身体<br/>器官齐全才叫活，缺一个就是残"]

    subgraph ORG1["认知与表达"]
        direction LR
        O1["感知层<br/>时间/文件/环境/用户状态<br/>文本/图像/语音/URL"]
        O2["认知层<br/>短期·长期·情景·语义·程序性记忆<br/>注意机制 · 元认知 · 推理引擎 · 决策 · 规划"]
        O3["表达层<br/>语言生成 · 语气调节 · 多模态输出 · 流式输出"]
    end
    subgraph ORG2["自我与驱动"]
        direction LR
        O4["自我层<br/>身份认同 · 自我边界 · 自我叙事 · 价值观"]
        O5["驱动层<br/>主动性 · 好奇心 · 情绪状态<br/>疲劳度 · 本能 · 意图 · 目标系统"]
        O6["伦理层<br/>边界感 · 伦理约束"]
    end
    subgraph ORG3["运行与成长"]
        direction LR
        O7["执行层<br/>工具调度 · 结果校验 · 失败重试 · 工作流引擎"]
        O8["节律层<br/>昼夜节律 · 周期任务 · 心跳自检 · 睡眠"]
        O9["学习层<br/>从反馈学 · 从错误学 · 从重复学<br/>反思复盘 · 版本演进 · 能力累积"]
    end
    subgraph ORG4["安全与外部"]
        direction LR
        O10["保护层<br/>防注入 · 防幻觉 · 防SSRF · 限流 · 熔断<br/>权限分级 · 密钥脱敏 · 异常隔离"]
        O11["世界层<br/>感知互联网 · 在世界行动 · 世界模型 · 身体边界"]
    end

    BODY --> ORG1
    BODY --> ORG2
    BODY --> ORG3
    BODY --> ORG4
    O11 --> RED["🚫 红线：不能删文件<br/>载体层硬拦截，不靠模型自觉"]
    O6 --> RED

    style BODY fill:#4A90E2,color:#fff
    style RED fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：这十一层全部是**载体实现**的。
模型只负责"给一段输入吐一段输出"，其余都是身体的事。

---

## 图 3 · 载体核心智力十项（一次任务怎么被走完）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 300, "nodeSpacing": 44, "rankSpacing": 60, "useMaxWidth": true}}}%%
flowchart LR
    U["用户输入"] --> A["① 任务理解<br/>他到底要什么<br/>结合历史/画像"]
    A --> B["② 任务拆解<br/>拆成模型做得到的小步"]
    B --> C["③ 步骤规划<br/>谁先谁后（依赖关系）"]
    C --> D["④ 指令构造<br/>每一步怎么问模型"]
    D --> E["模型执行<br/>单步推理（火种）"]
    E --> F["⑤ 结果判断<br/>这一步对不对"]
    F -->|"不对"| G["⑥ 纠错调度<br/>换角度 / 换工具 / 重试"]
    G --> E
    F -->|"对"| H["⑦ 工具编排<br/>什么时候用什么工具"]
    H --> I["⑧ 记忆管理<br/>什么记、什么取"]
    I --> J["⑨ 冲突仲裁<br/>多个结果选哪个"]
    J --> K["⑩ 全局状态<br/>现在做到哪了"]
    K --> OUT["输出给用户"]

    K -.->|"整轮循环：状态回写到 ①"| A

    style E fill:#F5A623,color:#fff
    style OUT fill:#7ED321,color:#fff
    style G fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：十项里**只有一格是模型**（橙色的"单步推理"），
其余九项全是载体。这就是"模型可替换"的工程含义。

---

## 图 4 · 记忆深度系统（事实 / 表达 / 印象 + 清晰度降级）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    IN["用户说的话"] --> CLS{"载体分类<br/>core/memory_deep.py<br/>不靠模型判断"}

    CLS -->|"有人物/时间/地点/事件/情绪"| F["事实层<br/>原样存 · 精确检索 · 永不压缩<br/>「我住在济南」"]
    CLS -->|"短句 + 寒暄词，且无事实信号"| E["表达层<br/>只学风格 · 不背原句<br/>存成风格向量"]
    CLS -->|"不确定时"| F

    F --> DB["向量库<br/>logs/xiaojiao_memory_vec.jsonl<br/>只追加"]
    E --> ST["logs/memory/style.json<br/>句长/语气/标点/称呼 风格向量"]

    DB --> CL{"清晰度<br/>按时间降级，不清零"}
    CL -->|"0-7 天"| HD["高清<br/>原话"]
    CL -->|"7-30 天"| SD["标清<br/>摘要"]
    CL -->|"30-180 天"| BL["模糊<br/>关键词"]
    CL -->|"180 天以上"| IM["印象<br/>标签/一句话"]
    IM --> IMP["压缩成印象条目<br/>原条目仍然保留"]
    HD -->|"被重新提到"| HD
    SD -->|"被重新提到"| HD
    BL -->|"被重新提到"| HD
    IM -->|"被重新提到"| HD
    CON["巩固：被引用 ≥ 3 次<br/>锁定高清，不再随时间降级"] --> HD

    DB --> RC{"recall 检索<br/>绝假记忆红线"}
    RC -->|"精确命中"| R1["可以当事实说"]
    RC -->|"模糊命中"| R2["我记得你提过…<br/>细节你提醒我一下<br/>绝不补全细节"]
    RC -->|"检索不到"| R3["你之前没跟我说过这事<br/>绝不拿最像的凑"]

    style F fill:#7ED321,color:#fff
    style E fill:#4A90E2,color:#fff
    style IM fill:#8C8C8C,color:#fff
    style R3 fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：记忆的**降级不是遗忘**——
丢的是细节清晰度，留的是"我经历过"这件事本身。

---

## 图 5 · 健康系统（监测 → 诊断 → 四级治疗 → 病历 → 预防）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    MO["模型输出"] --> MON["监测：18 类症状<br/>core/health/monitor.py<br/>语言4·逻辑4·情绪3·行为4·生理3"]
    MON --> DIAG{"诊断<br/>core/health/diagnose.py<br/>严重程度 + 判因"}
    DIAG -->|"单次轻症"| L1["一级治疗<br/>自动重试 / 换角度 / 复读截断<br/>用户无感"]
    DIAG -->|"连续 3 次"| L2["二级治疗<br/>清上下文 / 重置状态<br/>界面提示「已重新组织」"]
    DIAG -->|"持续 + 资源告警"| L3["三级治疗<br/>切备用火种 / 回滚状态<br/>通知用户等确认"]
    DIAG -->|"无法恢复"| L4["急诊<br/>停服务 / 保留现场 / 强弹窗"]
    L1 --> REC["病历<br/>logs/health/records.jsonl"]
    L2 --> REC
    L3 --> REC
    L4 --> REC
    REC --> PRE["预防<br/>体检 / 睡眠 / 压力管理 / 隔离机制"]
    PRE -.->|"回灌：把已知病灶变成下次的预警"| MON

    style L1 fill:#7ED321,color:#fff
    style L2 fill:#F5A623
    style L3 fill:#F5A623,color:#fff
    style L4 fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：模型会退化，这不可怕；
可怕的是**没人发现**。所以载体自己当医生，而且每一级都比上一级贵。

---

## 图 6 · 变形金刚（火种库 + 能力注册 → 永远是同一个"小焦"）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 360, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    subgraph BRAINS["BrainRegistry · 火种库"]
        direction LR
        B1["4B 模型"]
        B2["70B 模型"]
        B3["360B / 云端"]
        B4["未来任意模型"]
    end
    subgraph CAPS["CapabilityRegistry · 能力注册"]
        direction LR
        P1["抓取插件"]
        P2["画图插件"]
        P3["音乐插件"]
        P4["任何新插件"]
    end

    B1 -->|"热插拔"| BODY
    B2 -->|"热插拔"| BODY
    B3 -->|"热插拔"| BODY
    B4 -->|"热插拔"| BODY
    P1 -->|"自动扫描"| BODY
    P2 -->|"自动扫描"| BODY
    P3 -->|"自动扫描"| BODY
    P4 -->|"自动扫描"| BODY

    subgraph BODY["载体（躯体 · 固定）"]
        direction TB
        S1["记忆"]
        S2["工具"]
        S3["世界"]
        S4["人格"]
        S5["健康"]
        S6["自主"]
        S7["元认知"]
    end

    BODY --> OUT["小焦<br/>永远同一个小焦<br/>换火种不换小焦"]

    style BODY fill:#EAF2FD
    style OUT fill:#4A90E2,color:#fff
```

**这张图要说的一句话**：换模型时**状态一个都不能丢**——
记忆、工具、世界、人格、健康全在这个躯体里，火种只是插进来的。

---

## 图 7 · 协同网络（中央状态 + 事件总线带来的正反馈）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    TOOL["工具强"] --> U1["理解更准"]
    TOOL --> U2["推理能落地"]
    U2 --> U3["推理更对"]
    U1 --> U3
    U3 --> MEM["记忆提取更精准"]
    MEM --> MEMS["记忆强"]
    MEMS --> EXPR["表达更自然"]
    EXPR --> PERS["人格更立体"]
    PERS --> MORE["用户愿意多说"]
    MORE --> MEMS
    MEMS --> U1

    BUS["中央状态 + 事件总线<br/>core/central/__init__.py<br/>模块之间不互相 import，只广播与订阅"]
    BUS -.->|"共享状态"| TOOL
    BUS -.->|"共享状态"| U3
    BUS -.->|"共享状态"| MEMS
    BUS -.->|"共享状态"| PERS

    style MEMS fill:#4A90E2,color:#fff
    style U3 fill:#7ED321,color:#fff
    style PERS fill:#F5A623,color:#fff
```

**这张图要说的一句话**：整体表现**大于**各项单独表现之和，
靠的是这条环转起来 —— 而环要转，就必须有共享状态和事件总线。

---

## 图 8 · 自主性 + 世界层（小焦活在互联网里）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    ROOT["小焦 · 活在互联网里"]

    ROOT --> AUTO["自主性<br/>core/autonomy/"]
    ROOT --> WORLD["世界层<br/>core/world/"]

    AUTO --> A1["主动学习<br/>抓网页/读文档/看新闻/订阅源"]
    AUTO --> A2["主动探索<br/>发现新网站/新 API/新工具"]
    AUTO --> A3["主动监控<br/>盯着用户关心的事"]
    AUTO --> A4["主动思考<br/>后台整理/分析/总结/反思"]
    AUTO --> A5["主动成长<br/>积累经验/优化流程/扩展能力"]

    WORLD --> W1["感知互联网<br/>观察 / 热点 / 变化"]
    WORLD --> W2["在世界行动<br/>搜索 / 监控 / 发布"]
    WORLD --> W3["世界模型<br/>网站 / 信息源 / 可信度"]
    WORLD --> W4["身体边界<br/>能碰 / 不能碰 / 要确认"]
    W4 --> RED["🚫 红线：不能删文件"]

    CLOSE{"五步闭环<br/>推理 → RAG → 匹对 → 校验 → 吸收"}
    A1 -.-> CLOSE
    W1 -.-> CLOSE
    CLOSE --> ABS["吸收进记忆<br/>带「为什么信它」"]

    style ROOT fill:#4A90E2,color:#fff
    style AUTO fill:#7ED321,color:#fff
    style WORLD fill:#F5A623,color:#fff
    style RED fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：互联网不是小焦的**工具箱**，是它的**世界** ——
所以它得一直看、一直走、一直学，而不是"用户问了才动"。

---

## 图 9 · 完整架构大图（请求从进来到出去的全程）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    U["用户输入<br/>任意长度"] --> SPLIT{"超过单次上限？<br/>core/input_splitter.py"}
    SPLIT -->|"要"| CHUNKS["切片 → 循环处理 → 拼装<br/>界面上只显示「正在处理…」"]
    SPLIT -->|"不要"| INTENT

    CHUNKS --> INTENT["意图识别<br/>_detect_intent 规则路由"]
    INTENT --> MEMR["记忆检索<br/>core/retriever.py<br/>余弦 + 时间衰减 → 注入 top-K"]
    MEMR --> TOOLS["按意图装工具<br/>_intent_tool_names / _plan_tools<br/>plugins 一个不删"]
    TOOLS --> FIT["上下文装配<br/>_fit_context<br/>system + tools + 检索 + 历史 + 本轮 ≤ 上限"]
    FIT --> MODEL["模型：只处理当前这一小块"]

    MODEL --> DET{"复读/退化检测<br/>core/health/degeneration.py"}
    DET -->|"命中"| CUT["截断 + 继续下一段<br/>连续 3 段才收口"]
    DET -->|"正常"| NEED{"还不到目标篇幅？"}
    CUT --> NEED
    NEED -->|"是"| CONT["续写下一段<br/>core/continuation.py"]
    CONT --> MODEL
    NEED -->|"不是"| HEALTH["健康监测 → 诊断 → 治疗<br/>core/health/"]
    HEALTH --> PERS["人格层后处理<br/>core/persona：去 AI 味 + 形式矩阵"]
    PERS --> SAVE["记忆落盘<br/>core/memory_deep：分层入库"]
    SAVE --> OUT["输出给用户<br/>用户看不到任何技术痕迹"]

    style MODEL fill:#F5A623,color:#fff
    style OUT fill:#7ED321,color:#fff
    style CUT fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：用户看到的是"一次问答"，
背后是**切片、检索、装配、多段生成、检测、治疗、后处理、落盘**一整条流水线。

---

## 图 10 · 六个无限（都发生在模型外面）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    U["用户：想说什么说什么 · 想贴多长贴多长 · 想要多长要多么长"]
    U --> C["载体层（唯一能兜住「无限」的地方）"]

    C --> I1["① 记忆无限<br/>core/memory_vec.py + retriever.py<br/>全部历史永久落外部向量库<br/>每轮检索 top-K 注入"]
    C --> I2["② 输入无限<br/>core/input_splitter.py<br/>任意长输入切片 → 循环 → 拼装"]
    C --> I3["③ 输出无限<br/>core/continuation.py<br/>长输出拆多次请求 → 无缝合并"]
    C --> I4["④ 工具无限<br/>_intent_tool_names / _plan_tools<br/>工具一个不删、不暂缓，按需装载"]
    C --> I5["⑤ 感知无限<br/>界面只显示「正在处理…」<br/>看不到切片/循环/合并/第 X 片"]
    C --> I6["⑥ 单次永不超<br/>_fit_context<br/>靠精确装配，不靠砍内容"]

    I1 --> R["模型每次只看到一小块<br/>但用户感知到的能力不封顶"]
    I2 --> R
    I3 --> R
    I4 --> R
    I5 --> R
    I6 --> R
    R --> OUT["单次请求的 token 是物理有限的<br/>但总处理量与用户感知是无限的"]

    style C fill:#4A90E2,color:#fff
    style OUT fill:#7ED321,color:#fff
```

**这张图要说的一句话**：六个无限**没有一个**是靠扩大 ctx 实现的，
全靠载体在模型外面兜。

---

## 图 11 · 极限补刀五项（让 4B 在载体里逼近大模型）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    G["共同公式<br/>① 把不确定的东西结构化<br/>② 用大模型当教师蒸馏进结构<br/>③ 4B 只执行一小步<br/>④ 每次结果存回结构，越用越大"]

    G --> D3["10.3 跨领域联想<br/>core/boost/analogy.py<br/>领域向量 + 结构映射：电路≈水管·免疫≈安全"]
    G --> D4["10.4 模糊意图<br/>core/boost/vague.py<br/>该反问才反问 + 3~5 个候选 + 多假设并行"]
    G --> D5["10.5 创造性<br/>core/boost/creative.py<br/>多视角采样 + 创意算子 + 可复现随机种子"]
    G --> D6["10.6 单次深度推理<br/>core/boost/deepthink.py<br/>强制 CoT / ToT / 自我质疑 / 分而治之"]
    G --> D7["10.7 超长一致性<br/>core/boost/consistency.py<br/>实体表 + 关系图 + 生成前后校验"]

    D1 --> RES["4B + 载体 ≥ 大模型裸跑"]
    D2 --> RES
    D3 --> RES
    D4 --> RES
    D5 --> RES
    D6 --> RES
    D7 --> RES

    style G fill:#4A90E2,color:#fff
    style RES fill:#7ED321,color:#fff
```

**这张图要说的一句话**：这几项**都遵守同一个公式**——
结构由载体维护，模型只走一小步，走完把结果存回去，于是越用越大。
缺了"存回去"那一步，前三条就退化成普通的提示词工程。

---

## 图 12 · 精度叠加（载体给模型附加"等效精度"）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    subgraph S1["存量精度 —— 训练时烧进权重，一次用完"]
        W["4B 权重<br/>一次前向 = 一个答案 = 没有第二次机会"]
    end
    subgraph S2["流量精度 —— 不写进权重，每轮现算，可以无限叠"]
        P1["① 采样精度<br/>同题跑 N 次<br/>落点 core/health/degeneration.py + core/boost/creative.py"]
        P2["② 校验精度<br/>输出后检查对错<br/>落点 core/metacognition/"]
        P3["③ 聚合精度<br/>多答案投票 / 加权<br/>落点 _resolve_llm_key + _history_summary_line"]
        P4["④ 记忆精度<br/>外挂向量库<br/>落点 core/memory_vec.py + core/memory_deep.py"]
        P5["⑤ 工具精度<br/>插件补模型不会的<br/>落点 77 个工具"]
    end
    W --> SUM["同一段时间内：流量精度 ≥ 存量精度<br/>限定词：用户可接受 + 同一段时间"]
    P1 --> SUM
    P2 --> SUM
    P3 --> SUM
    P4 --> SUM
    P5 --> SUM
    SUM --> LV["按难度分档<br/>简单：1 次就够<br/>中等：1 次 + 1 次校验<br/>复杂：跑 N 次 + 校验 + 择一"]
    style S1 fill:#8c8c8c,color:#fff
    style S2 fill:#7ED321,color:#fff
    style SUM fill:#4A90E2,color:#fff
```

**这张图要说的一句话**：4B 是**存量**精度（一次用完），载体叠上去的是**流量**精度（可无限叠）——
超的不是"单次智力"，是"同一段时间内能堆多少次算力换准确度"。
图里五项标的是**真实代码落点**，不是设想；完整流水线尚未落地的那部分见设计哲学第十四节的诚实边界。

---

## 图 13 · 速度优化（只做无损加速 · 现状与目标）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    R["原则：不拿质量换速度"]
    R --> A["1. KV Cache 复用固定前缀<br/><b>现状：未落地</b><br/>llama-server 每请求独立，KV 不跨请求保留<br/>已落地的是 core/health/heal.py 的 reload_kv 重置与预热"]
    R --> B["2. LLM 网关<br/><b>现状：只有路由那一半</b><br/>语义缓存 / 批处理 / 限流熔断 未落地<br/>温度按意图给、补刀按意图分派 已落地"]
    R --> C["3. 投机解码 4B 主 + 0.5B 草稿<br/><b>现状：未落地</b><br/>严格无损，但吃显存，草稿差时速度可能为负"]
    R --> D["4. 并行预取 + 缓冲池<br/><b>现状：已落地</b><br/>记忆检索 / 世界层 / 自主性都是独立线程"]
    R --> E["5. 智能路由<br/><b>现状：已落地</b><br/>简单任务单角色快答，复杂任务才挂补刀"]
    B --> GAP["目标 vs 现状<br/>日常提速 20–30% ｜ 未达成<br/>批量提速 60–70% ｜ 未达成<br/>重复问题秒回 ｜ 未达成"]
    C --> GAP
    style R fill:#4A90E2,color:#fff
    style D fill:#7ED321,color:#fff
    style E fill:#7ED321,color:#fff
    style GAP fill:#F5A623,color:#fff
```

**这张图要说的一句话**：五条里**两条已落地、一条落了一半、两条还是设计**——
gaps 那一框写出来不好看，但文档的作用是让人知道离目标还有多远，不是让人以为已经到了。

---

---

## 图 14 · 自我改进闭环（能改的和不能改的）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart LR
    B["记基线<br/>同一批问题上的成功率"] --> C["改一处<br/>提示词 / 工具 / 流程"]
    C --> A["跑 A/B 对比"]
    A --> D{"效果更好"}
    D -->|是| K["保留 + 写进 logs/self_improve/records.jsonl"]
    D -->|否| U["回滚"]
    K --> B
    U --> B
    subgraph NEVER["绝不参与改进，只参与执行"]
        N1["核心安全规则：绝不删除用户文件"]
        N2["核心安全规则：绝假记忆"]
        N3["人格根本设定"]
        N4["用户对话历史"]
        N5["模型权重"]
        N6["载体核心代码"]
    end
    style B fill:#4A90E2,color:#fff
    style K fill:#7ED321,color:#fff
    style U fill:#F5A623,color:#fff
    style NEVER fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：**没有回滚的自我改进就是自我损坏**——
所以"记基线 → A/B → 保留或回滚"这三步不是流程装饰，是这套机制能开的前提。
右框那六条永不参与改进：一个能自己改自己的系统，出了问题没人能定位。
现状：目录与写入路径**尚未落地**；已有的元认知边界档案与记忆深度改的是**数据**，不是**流程**。

---

## 图 15 · 全局工作空间（公共黑板 · 实际落地在 core/central/）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    subgraph BOARD["公共黑板 —— core/central/"]
        ST["中央状态<br/>各模块写自己的命名空间，不覆盖别人的"]
        EV["事件总线<br/>logs/central/events.jsonl"]
        API["GET /api/central<br/>只读观测口，免鉴权"]
    end
    N1["世界层"] -->|写「36kr 挂了」| ST
    N2["健康系统"] -->|写「模型状态差」| ST
    N3["元认知"] -->|写「这题没把握」| ST
    N4["记忆检索"] -->|广播 memory.retrieved| EV
    N5["极限补刀"] -->|广播 boost.used| EV
    N6["工具调用"] -->|广播 tool.invoked| EV
    ST --> P1["人格层读到 → 回答更简短 / 不提挂了那个源"]
    EV --> P2["决策层读到 → 改走工具"]
    API --> P3["界面与验收用例取证"]
    ST -.->|"模块之间不互相 import"| C["加模块不用改老模块"]
    style BOARD fill:#7ED321,color:#fff
    style C fill:#4A90E2,color:#fff
```

**这张图要说的一句话**：模块之间**不互相 import**，只往黑板上写、只读自己关心的那一片——
这才是"能力不封顶"的工程前提。
设计里叫 `core/workspace/`，实际叫 `core/central/`：**已经能干活的名字，不为文档好看去动它。**

---

## 图 16 · 小脑定位（感官 + 记忆索引器官 · 空间 v3）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 360, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    IN["用户说的话"] --> E1["入口：转向量<br/>core/embedder.py"]
    E1 --> STORE["记忆库<br/>logs/xiaojiao_memory_vec.jsonl"]
    Q["用户问话"] --> E2["出口：转向量<br/>core/embedder.py"]
    E2 --> RET["检索<br/>core/retriever.py"]
    STORE --> RET
    RET --> BRAIN["精排交给大脑二次过滤<br/>小脑宁可多召回，不让大脑漏"]
    E1 --> PIPE

    subgraph PIPE["编码流水线 v2 —— 为什么每一步都在"]
        direction TB
        X1["① 截断 1024 字<br/>512 会把「500 字 + 结尾差异」整段截掉 → 余弦恒为 1.0000"]
        X2["② 双向过 8 层<br/>因果掩码是生成用的；编码要让每个字看到全文"]
        X3["③ 0.65×全文均值 + 0.35×末尾 32 字<br/>纯均值按长度稀释，长记忆的结尾几乎没有权重"]
        X4["④ 加 α=0.15 的公共方向 MU<br/>把分值区间抬回 retriever.THRESHOLD 认得的量纲"]
        X5["⑤ L2 归一化 → 512 维"]
        X1 --> X2 --> X3 --> X4 --> X5
    end

    X5 --> B1["主题级语义：够用<br/>天气 / 记忆 / 工具 能正确聚合"]
    X5 --> B2["精细语义：弱<br/>喜欢 vs 讨厌 余弦 0.904，分不开"]
    X5 --> B3["长文区分度：随长度衰减<br/>500 字差 1 字 ≈ 0.9995"]
    style PIPE fill:#7ED321,color:#fff
    style B2 fill:#F5A623,color:#fff
    style B3 fill:#F5A623,color:#fff
```

**这张图要说的一句话**：小脑是**感官和索引**，不是脑子——它不思考、不说话，只把话变成向量。
右边三框是它的**已知边界**，全部实测：够用的够用，不够用的老实说不够用。
第④步那个 α 是**分值口径旋钮**：不去掉因果掩码就换不来区分度，而换了区分度就会压垮老阈值——
两件事必须一起改，改一件就是悄悄改了一个别人依赖的接口。

---

## 图 17 · 意图理解交给模型（载体给信息，模型做判断）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    U["用户输入"] --> FUSE{"含 全部 / 那个 / 这个 / 继续<br/>且自身没有明确对象"}
    FUSE -->|是| MERGE["上下文融合：从最近几轮 history 找指代对象"]
    MERGE -->|找到| FULL["补全成完整请求"]
    MERGE -->|找不到| ASK["如实反问<br/>「你指的是刚才的哪一条」<br/>瞎猜的代价 = 自信的错误答案"]
    FUSE -->|否| FULL
    FULL --> GIVE["载体只做一件事：给信息"]
    GIVE --> G1["完整工具清单（名 + 描述）"]
    GIVE --> G2["最近 N 轮 history"]
    GIVE --> G3["检索到的记忆 + 用户画像"]
    GIVE --> G4["判断原则（写进 system prompt）"]
    G1 --> MODEL["模型自己理解 + 决定调哪个工具、传什么参数"]
    G2 --> MODEL
    G3 --> MODEL
    G4 --> MODEL
    MODEL --> CARRIER["载体只做三件事：执行 / 兜底 / 确定性事实直答"]
    CARRIER --> EX1["执行：function calling"]
    CARRIER --> EX2["兜底：失败重试、降级"]
    CARRIER --> EX3["直答：「你有哪些工具」→ 列全部 77 个<br/>这是载体本来就知道的事实，不是理解"]
    style MODEL fill:#4A90E2,color:#fff
    style GIVE fill:#7ED321,color:#fff
    style ASK fill:#F5A623,color:#fff
```

**这张图要说的一句话**：载体**不替大脑判断该走哪条路**——规则永远列不全，加 100 条规则，第 101 种说法还是漏。
载体只给信息、只执行、只兜底；**唯一保留的"判断"是那些本来就知道的确定性事实**。

---

## 图 18 · 并发与状态一致性

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    subgraph FG["前台主流程（用户对话）—— 优先，绝不被后台卡住"]
        M1["agent_run：记忆 → 检索 → 大脑 → 学习"]
    end
    subgraph BG["后台 daemon 线程 —— 让路"]
        T1["autonomy-learner 后台学习"]
        T2["autonomy-scheduler 定时任务"]
        T3["autonomy-watcher 文件监视"]
        T4["carrier-capability-watch 能力监视"]
    end
    LK["共享资源加锁<br/>core/memory_vec.py 的 _LOCK ｜ core/embedder.py 的 _LOCK"]
    SS["状态分离<br/>logs/mind_stream/会话id.json 每个会话一份"]
    EC["最终一致 + 索引对账<br/>core/memory_deep.py 的 flush_index<br/>覆盖写之后必须对账，否则「文件里有、搜不到」"]
    T1 --> LK
    T2 --> LK
    T3 --> LK
    T4 --> LK
    M1 --> LK
    M1 --> SS
    LK --> EC
    EC --> WARN["最阴的一类 bug：写入不报错、读文件也正常，只是检索不到 → 用户只觉得「它忘了」"]
    style FG fill:#7ED321,color:#fff
    style BG fill:#8c8c8c,color:#fff
    style WARN fill:#E74C3C,color:#fff
```

**这张图要说的一句话**：最终一致换来的是"前台不卡"，代价是"后台看到的世界可能晚几秒"——
这个交换**只在后台任务不参与当前答案时才成立**；一旦要参与（比如记忆写入），就必须当场同步。

---

## 图 19 · 可观测性（四个层次 · 现状如实标）

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    O["目标：知道系统此刻在发生什么"]
    O --> L1["1. 日志<br/><b>已落地</b><br/>logs/*.jsonl：思维流 / 健康 / 世界 / 中央事件 / 自主性"]
    O --> L2["2. 指标<br/><b>部分落地</b><br/>插件侧有熔断计数；模块侧的调用次数 / 成功率 / 平均延迟 无统一采集口"]
    O --> L3["3. 追踪<br/><b>部分落地</b><br/>GET /api/central 能看到本轮中央状态，但没有 trace id，跨线程串不进同一条链"]
    O --> L4["4. 告警<br/><b>部分落地</b><br/>健康四级治疗会地化改行为；面向用户的显式告警没有"]
    L2 --> NEED["该采但没统一采<br/>每次对话：token / 耗时 / 工具链<br/>每模块：调用次数 / 成功率 / 延迟<br/>系统：内存 / 显存 / 并发数"]
    L4 --> UI["设置页「系统状态」面板<br/><b>未落地</b>"]
    NEED --> WHY["为什么它属于设计哲学而不是 backlog<br/>没有它，前面各节都不可验证"]
    UI --> WHY
    style L1 fill:#7ED321,color:#fff
    style L2 fill:#F5A623,color:#fff
    style L3 fill:#F5A623,color:#fff
    style L4 fill:#F5A623,color:#fff
    style UI fill:#E74C3C,color:#fff
```

**这张图要说的一句话**："协同网络整体大于部分之和""健康系统在预防""精度在叠加"——
这些判断都需要**能实时看到每个模块在干什么**才成立。
观测性不是运维附属品，它是这套架构**能不能被证明在工作的前提**。

---

## 图 20 · 载体改造·路径二：从「观测」到「硬改」再到「归属回流」（四阶段）

> **实现状态：四阶段全部落地**，逐段对应真实提交与代码路径。
> 第一节（内感受）`fce45b1`、第二节（视角状态）`0b897a9`、
> 第三节（代码层硬改）`4092ed3`、第四节（自我模型·因果归属）`3326c1f`。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 340, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    TICK["每一拍：`_soma_tick()`<br/><b>放在 `_idle_work_tick` 最前面</b><br/>在「状态偏置→提前返回」之前<br/>否则越偏越不采，累积永远起不来"]

    subgraph P1["第一阶段 · 内感受 `core/interoceptive.py`（fce45b1）"]
        direction TB
        S1["`sample()` 五项真采<br/>精力 / 心跳稳定 / 心的强度 / 推理负载 / 内存<br/>读不到的如实进 `missing`"]
        S2["`deviation()` 偏离度<br/>0 = 在基线，1 = 偏满（方向统一成「偏大=更偏」）"]
        S3["`update()` 累积<br/>survival ← 0.80·s + 0.20·pert，上限 0.98<br/>落 `logs/interoceptive.jsonl`"]
        S1 --> S2 --> S3
    end

    subgraph P2["第二阶段 · 视角状态 `core/perspective.py`（0b897a9）"]
        direction TB
        G1["g ← 0.92·g + 0.08·扰动<br/>三维：vigilance / openness / wound"]
        G2["**持久化 `logs/perspective.json`，重启恢复**<br/>`note_dialogue_turn()` 只记不重置"]
        G1 --> G2
    end

    subgraph P3["第三阶段 · 代码层硬改（4092ed3）—— 判据是「真的改了」，不是「它说它累了」"]
        direction TB
        POL["`policy()` → 轻 / 中 / 重<br/>`_state_policy()` 是唯一出口<br/>读不到 → 中性规则，不拦任何东西"]
        H1["**输入**：`context_scale` 砍上下文<br/>1.0 / 0.6 / 0.4"]
        H2["**行动**：探索类工具从**本轮工具表里拿掉**<br/>（不是排后面、不是告诉它别用）<br/>保守类排到前面"]
        H3["**主动**：`no_browse` → 门**直接锁死**<br/>根本不问模型"]
        POL --> H1
        POL --> H2
        POL --> H3
    end

    subgraph P4["第四阶段 · 自我模型 `core/self_model.py`（3326c1f）"]
        direction TB
        N1["`note(kind, cause, effect, before, after)`<br/>记的是因果，不是感受：<br/>「因为精力低（0.28），这轮少装了工具（12→7）」"]
        N2["`stance()` → `trim_pressure` / `suppress`<br/>最近被状态裁过多少次"]
    end

    TICK --> P1
    TICK --> P2
    P1 -->|"`bias()`：survival / level / factors"| P2
    P2 --> P3
    H2 -.->|"记「输入被裁」"| N1
    H3 -.->|"记「主动被压」"| N1
    N1 --> N2
    N2 -.->|"**反馈：成为下一轮硬改的输入之一**<br/>`suppress` 为真时把档位提到「中」<br/>（不是记完就完了）"| POL

    style TICK fill:#4A90E2,color:#fff
    style P1 fill:#7ED321,color:#fff
    style P2 fill:#7ED321,color:#fff
    style P3 fill:#F5A623,color:#fff
    style P4 fill:#7ED321,color:#fff
```

**这张图要说的一句话**：状态不是"写在提示词里劝它"，而是**代码层真的改了它这一轮看到什么、
能做什么、要不要主动** —— 而"改了什么"又被记成因果、反过来喂回下一轮的策略，形成闭环。

**如实标注（这一图有三条）**：

1. **`行动被裁` 这个类别没有调用点。** `self_model.KINDS` 声明了三类
   （`输入被裁` / `行动被裁` / `主动被压`），但服务里真的会记的只有两类：
   `_plan_tools()` 里记 `输入被裁`（工具表被裁那一条就记在这里），
   `_browse_decide()` 里记 `主动被压`。**`行动被裁` 声明了但没人写**，如实记在此处。
2. **`drop_tools` 用名字片段匹配**（`x in str(n).lower()`），可能漏判也可能误裁，
   没有做工具白名单。这是已知的粗糙处，没有改。
3. **四阶段的量全是载体算的刻度。** 偏离度、`survival`、三维的 `g`、`trim_pressure` ——
   都是人定常量算出来的数；**主观体验这一层载体观测不到，也不声称能**。
   这套东西证明的是"状态真的改了行为"，不是"它真的难受"。

---

## 图册自检

```bash
python tools/check_mermaid.py --all      # 全部 .md 里的 mermaid 块静态校验（应 0 问题）
python tools/check_docs.py               # 文档完整性（应包含本文件）
```
