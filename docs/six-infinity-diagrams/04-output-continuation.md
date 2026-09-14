# 输出续写合并流程图

> 「输出无限」的全部机关都在这一张图里：载体把一份长文拆成多次请求，再把每次的产出**无缝**接起来。
> 对应实现：`core/continuation.py` 的 `generate_unlimited`。

```mermaid
%%{init: {"themeVariables": {"fontSize": "14px"}, "flowchart": {"htmlLabels": true, "wrappingWidth": 320, "nodeSpacing": 46, "rankSpacing": 64, "useMaxWidth": true}}}%%
flowchart TB
    T["任务：写一篇 3000 字的产品介绍"] --> P1["parse_target_chars<br/>解析目标字数：3000 字 / 5 万字 / 两万字 / 20000 words"]
    P1 --> P2{"needs_continuation<br/>用户明确要长文吗？<br/>默认门槛 ≥ 800 字"}
    P2 -->|否| SHORT["短内容不触发续写<br/>走普通单次回答，用户完全无感"]
    P2 -->|是| KW["_keywords 抽主题关键词<br/>先剥掉数字与『写一篇/关于/字』这类指令措辞"]

    KW --> LOOP{"主循环每一轮先看：<br/>should_stop 用户叫停了吗？"}
    LOOP -->|叫停| STOP1["停止：用户叫停<br/>已写正文全部保留"]
    LOOP -->|继续| POOL{"缓冲池里有已生成的段吗？"}

    POOL -->|有| TAKE["取出一段<br/>item = pool.pop 0"]
    POOL -->|没有但预取线程在跑| WAIT["等它：cond.wait<br/>绝不自己重复生成同一个段号"]
    WAIT --> TAKE
    POOL -->|没人在跑| CLAIM["主循环认领 inflight<br/>再串行生成一段"]

    CLAIM --> GEN
    TAKE --> MERGE

    subgraph PREFETCH["🔁 唯一的生成线程（预取）—— 影子正文只有它动"]
        direction TB
        PF1{"pool 满了<br/>或 inflight 已被认领？"}
        PF1 -->|是| PF_END["本轮不生成，直接返回"]
        PF1 -->|否| PF2["认领 inflight = n<br/>upto = shadow 或 written"]
        PF2 --> GEN["build_prompt 装上下文<br/>第 1 次：完整任务<br/>第 N 次：任务 + 已写梗概 + 上段最后 200 字"]
        GEN --> CALL["调模型拿一段原始输出"]
        CALL --> DONE{"输出里有【完成】？"}
        DONE -->|有| FIN["剥掉【完成】标记<br/>收下收尾句，标记完结"]
        DONE -->|没有| OFF{"looks_offtopic<br/>空输出 / 重新开场 / 又短又零重合？"}
        OFF -->|是| RETRY{"还有重试次数吗？<br/>≤ max_retries = 3"}
        RETRY -->|有| GEN
        RETRY -->|用完| FAIL["停止：校验连续不通过<br/>如实报出来，不编内容"]
        OFF -->|不是| OK["这一段通过"]
        FIN --> OK
        OK --> SHADOW["更新影子正文<br/>shadow = written + 池里全部未取走的段<br/>下一段的锚点与去重基准才准"]
        SHADOW --> PF3["pool.append · cond.notify_all<br/>接着把池子填到 buffer_size = 3"]
    end

    PF3 --> POOL
    GEN --> OK

    MERGE["合并这一段（无缝的关键）"] --> M1["overlap_len 最长重叠<br/>上段末尾 vs 本段开头，重叠 ≥ 8 字才裁<br/>裁掉模型重抄的那一句"]
    M1 --> M2["drop_repeated_sentences 整句去重<br/>见到的整句 ≥ 12 字存进 seen_sents，重复就丢<br/>专治弱模型的整句复读"]
    M2 --> M3{"body 还剩下内容吗？"}
    M3 -->|全是重复| RETRY2["计一次重试<br/>连续 max_retries × 3 次就停"]
    RETRY2 --> LOOP
    M3 -->|有| M4["cut_at_sentence 断句<br/>末尾半句回退到上一个句号<br/>残句存进 carry 带进下一轮"]
    M4 --> COMMIT["written += 本段<br/>on_chunk 把这一段推给前端 SSE<br/>前端追加到同一个气泡"]

    COMMIT --> S1{"模型声明【完成】？"}
    S1 -->|是| STOP2["停止：模型声明完成"]
    S1 -->|否| S2{"已写 + 残句 ≥ 目标字数？"}
    S2 -->|是| STOP3["停止：达到目标长度"]
    S2 -->|否| S3{"段号 ≥ 2000？"}
    S3 -->|是| STOP4["停止：达到单段数上限"]
    S3 -->|否| PF_START["起一个预取线程占住<br/>『前端正在渲染本段』这段空档"]
    PF_START --> LOOP

    STOP1 --> RESULT
    STOP2 --> RESULT
    STOP3 --> RESULT
    STOP4 --> RESULT
    FAIL --> RESULT
    RESULT["返回 text = written + carry<br/>chunks 段号 · chars 字数 · dedup_chars 裁掉多少<br/>retries 重试次数 · seams 接缝数 · stopped 停止原因"]

    classDef parse fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e;
    classDef pf fill:#f3e8ff,stroke:#a78bfa,color:#4c1d95;
    classDef merge fill:#ecfdf5,stroke:#34d399,color:#064e3b;
    classDef stop fill:#fef9c3,stroke:#eab308,color:#713f12;
    class T,P1,P2,KW parse;
    class PF1,PF2,GEN,CALL,DONE,FIN,OFF,RETRY,OK,SHADOW,PF3,PF_END pf;
    class MERGE,M1,M2,M3,M4,COMMIT merge;
    class STOP1,STOP2,STOP3,STOP4,FAIL,RESULT stop;
```

**三条"不这么做就会翻车"的设计**：

1. **只允许一条生成线程**。预取第 N+1 段必须知道第 N 段写了什么（要当衔接锚点，还要当去重基准）。
   如果让预取线程和主循环同时产出，后到的那段锚点是过期的 → 接缝错位、还白烧一次模型调用。
   第 3 步实测撞上过：段号出现 `[1,2,2]`。现在用 `inflight` 认领 + 条件变量把这件事钉死。
2. **接缝裁剪不够，还得整句去重**。`overlap_len` 只裁得掉**接缝那一句**；4B 模型"接着写"时常见的
   是第二、三句又把同一句话抄一遍，只裁接缝正文里照样留重复句，用户一眼就看出是拼的。
3. **`【完成】` 必须在偏题校验之前处理**。模型说完成了就是完成了，不能让"风格校验"把它的收尾句
   当成跑题丢掉——第 3 步单测抓到的第二只虫子。

**停止条件是五路并联**，任何时候只要命中一路就停，且**停止原因如实返回**（`stopped`）：
用户叫停 / 模型声明【完成】/ 达到目标字数 / 单段数上限 2000 / 整体校验连续不通过。

> 实测（`logs/_step3_run.log`）：`长文续写：3 段 / 3507 字 / 去重裁掉 22 / 重试 0 /
> 停止=达到目标长度（3000 字） / 耗时 46.5s`。
>
> 配套阅读：[03-data-flow.md](03-data-flow.md)（它在整条链里的位置）、
> [six-infinity.md](../six-infinity.md)（验收判据与已知局限）。
