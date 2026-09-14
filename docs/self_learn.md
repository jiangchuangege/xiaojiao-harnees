# 持续学习（小脑跟着大脑学）

| 项 | 值 |
| --- | --- |
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 文档定位 | 持续学习链路：记录、反馈、积累、向量检索、出厂预置 |

**摘要**：小焦把「大脑答得好」的交互沉淀成文本与向量，供小脑检索复用，从而在不增加算力的前提下持续变强；本文说明该链路的六个环节、每个环节的真实文件与代码位置。

## 目录

1. [原理与分工](#1-原理与分工)
2. [数据流](#2-数据流)
3. [记录层](#3-记录层)
4. [反馈层](#4-反馈层)
5. [积累层](#5-积累层)
6. [向量检索](#6-向量检索)
7. [工具使用学习](#7-工具使用学习)
8. [出厂预置数据](#8-出厂预置数据)
9. [N.E.K.O. 学习通道](#9-neko-学习通道)
10. [如何判断小脑变强](#10-如何判断小脑变强)
11. [优化建议](#11-优化建议)
12. [目录结构](#12-目录结构)

---

## 1. 原理与分工

小焦分两层：

| 层 | 实现 | 职责 |
| --- | --- | --- |
| 大脑 | 本地或云端的大模型 | 推理、调用工具、生成回答 |
| 小脑 | 自研 MiniGPT + 检索 | 复用学过的答案与工具用法，离线可用 |

持续学习做的事只有一件：把大脑每次「做得好」的套路记进不断增长的文本库与向量库，小脑检索命中即可复用。它不依赖算力，依赖的是积累量与检索质量。

小脑**不负责跑插件**：插件由大脑调用，约 3273 万参数的字符级模型无法承担 function calling（工具调用）。小脑的变强路径是「学会怎么答」，不是「亲手执行」。

---

## 2. 数据流

**图 1 · 持续学习的六个环节**
说明：日常使用产生记录，反馈筛选出值得学的交互，积累成知识库与向量库，可选重训后验证上线。
代码位置索引：`xiaojiao_app.py` 的 `_record_interaction()` / `api_feedback()`，`self_learn/learn.py`，`train_model.py`

```mermaid
flowchart TB
    subgraph USE["1 日常使用"]
        U["用户提问"] --> B["大脑推理"]
        B --> T["调用工具"]
        B --> A["生成回答"]
    end
    subgraph LOG["2 记录层"]
        L["logs/chat_history.jsonl<br/>时间 / log_id / 用户 / 回答 / 工具轨迹"]
    end
    subgraph FB["3 反馈层"]
        F["logs/feedback.jsonl<br/>good / bad / 4星 / 5星 / 更正"]
        X["不值得学的条目<br/>不进入积累"]
    end
    subgraph GROW["4 积累层"]
        K["小脑知识库<br/>self_learn/little_brain_knowledge.txt"]
        P["检索池<br/>training_data_pool_clean.txt"]
        V["向量库<br/>self_learn/knowledge_vec.json"]
    end
    subgraph TRAIN["5 训练层 · 可选"]
        TR["train_model.py 重训小模型"]
    end
    subgraph DEP["6 部署"]
        D["验证通过则替换权重<br/>变差则回退"]
    end
    A --> L
    T --> L
    L --> F
    F -- "值得学" --> K
    F -- "不值得学" --> X
    K --> P
    K --> V
    K --> TR
    TR --> D
    style U fill:#4A90E2,color:#fff
    style B fill:#4A90E2,color:#fff
    style T fill:#4A90E2,color:#fff
    style A fill:#4A90E2,color:#fff
    style L fill:#7ED321,color:#fff
    style F fill:#F5A623,color:#fff
    style X fill:#E74C3C,color:#fff
    style K fill:#7ED321,color:#fff
    style P fill:#7ED321,color:#fff
    style V fill:#7ED321,color:#fff
    style TR fill:#F5A623,color:#fff
    style D fill:#4A90E2,color:#fff
```

一句话概括：大脑做得好，被点赞或被更正，这条「用户要什么 + 大脑怎么解决」被写进小脑知识库与向量库，下次相似问题检索命中即可复用。

---

## 3. 记录层

`xiaojiao_app.py` 的 `_record_interaction(user, answer, tool_trace)` 在每次回答产出后追加一行到 `logs/chat_history.jsonl`，并返回 `log_id`。字段如下：

| 字段 | 含义 |
| --- | --- |
| `time` | 秒级时间戳 |
| `log_id` | 形如 `20260914_181530123456` 的标识符，反馈层靠它关联到具体某一次交互 |
| `user` | 用户本轮输入 |
| `final_reply` | 最终回答 |
| `tool_trace` | 工具轨迹（JSON 字符串），这是「功能用法」的来源 |

记录是自动的，无需手动操作。本次实测该文件为 2130 行。

---

## 4. 反馈层

网页每条回答下有两个按钮，分别提交 `good` 与 `bad` 到 `/api/feedback`；命令行可传更多取值。判定「值得学」的条件是三者之一：

1. 带更正内容（`corrected_reply` 非空）；
2. 反馈值为 `good`（网页点赞按钮提交该值，命令行同理）；
3. 反馈值去掉「星」字后为 `4` 或 `5`。

命中后，服务端按 `log_id` 从 `logs/chat_history.jsonl` 找回该条，拼成一行：

```text
用户 <问题> 小焦 <回答> 用工具:<工具轨迹>
```

追加进 `self_learn/little_brain_knowledge.txt`，并同步追加进检索池 `training_data_pool_clean.txt`。也就是说，点赞即学习，不必等批处理。本次实测 `logs/feedback.jsonl` 为 6 行，`self_learn/little_brain_knowledge.txt` 为 214 行。

---

## 5. 积累层

`self_learn/learn.py` 是独立可用的学习引擎，在 `self_learn` 目录下运行：

```powershell
cd self_learn
python learn.py log "在桌面建 tests1 写上 index.html" "已完成" '[{"tool":"run_command"},{"tool":"write_file"}]'
python learn.py feedback 20260914_181530123456 good
python learn.py feedback 20260914_181530123456 5星
python learn.py feedback 20260914_181530123456 bad "更正的答案"
python learn.py build
python learn.py reflect "问题" "原来的回答" bad "更正的答案"
python learn.py search "建文件夹写文件"
python learn.py stats
```

| 命令 | 作用 |
| --- | --- |
| `log` | 手动记录一次交互，第三个参数是工具轨迹（可选） |
| `feedback` | 记录反馈：`good` / `bad` / `4星` / `5星`，可带更正后的回答 |
| `build` | 把「值得学」的交互灌进知识库与向量库，并同步检索池 |
| `reflect` | 生成「为什么没答好、下次怎么改」的反思，写入知识库与向量库 |
| `search` | 直接测试向量检索命中（阈值 0.5） |
| `stats` | 打印成长指标：日志条数、反馈分布、知识库与检索池条数、向量库条数 |
| `train` | 只打印提示，实际重训要运行 `train_model.py` |

两点实测行为需要留意：

- `build` 有新增时会把**整个知识库**追加进检索池，重复执行会重复追加，检索池因此可能膨胀。
- `train` 不执行任何训练，只是提示去运行 `train_model.py`；训练层是手工触发的。

`learn.py` 的三个路径常量：`LOG_FILE` 指向 `logs/chat_history.jsonl`，`FEED_FILE` 指向 `logs/feedback.jsonl`，`KNOW_FILE` 指向 `self_learn/little_brain_knowledge.txt`。

---

## 6. 向量检索

`self_learn/vstore.py` 是一个零依赖的本地向量库（对标 Chroma / FAISS 的简化实现）：

| 项 | 值 |
| --- | --- |
| 向量维度 | 256 |
| 编码方式 | 字符 2-gram（权重 1.0）与 3-gram（权重 0.6）计数后 L2 归一化 |
| 哈希 | 31 进制确定性哈希，取低 16 位模维度（跨进程稳定，不用内置 `hash`） |
| 相似度 | 余弦，等价于归一化向量的点积 |
| 默认阈值 | 0.13（检索注入用 0.12） |
| 存储 | `self_learn/knowledge_vec.json`，每条含 `id` / `text` / `tag` / `v` |

标签区分来源：`learned`（`build` 写入的交互）、`reflection`（反思）、`tool_skill`（工具使用经验）。本次实测该文件为 297 条。

注意两套向量各成一库，不要混用：

| 库 | 维度 | 编码者 | 用途 |
| --- | --- | --- | --- |
| `self_learn/knowledge_vec.json` | 256 | `self_learn/vstore.py` 的哈希 n-gram | 小脑知识检索 |
| 记忆向量（`logs/xiaojiao_memory_vec.jsonl`） | 512 | `core/embedder.py`（主后端为 MiniGPT） | 长期记忆召回 |

对话时的检索顺序是：先查 `vstore`（`xiaojiao_harness.py` 的 `retrieve_reply()`，阈值 0.13），未命中再退到训练语料的字符二元组重叠检索；两者都没命中才让模型生成或联网。记忆侧的向量口径见 [xiaojiao_model.md](xiaojiao_model.md) 第 7 节。

---

## 7. 工具使用学习

除了「问答式」学习，`xiaojiao_app.py` 还会从**实际使用**中积累工具经验：

- `_learn_skill(user_input, tool, args, ok, detail)`：把「什么需求、用了哪个工具、参数是什么、成功还是失败」写成一行，追加到 `self_learn/tool_skills.txt`，同时写入向量库（标签 `tool_skill`）。失败时会调用 `_reflect()` 生成「下次怎么改」的经验。
- `_recall_skills(query, k=3)`：按当前问题检索工具用法（阈值 0.12），把命中的经验注入本轮提示词。

本次实测 `self_learn/tool_skills.txt` 为 3024 行。这条链路是「用得越多，越知道该怎么用工具」的落地方式。

---

## 8. 出厂预置数据

「开箱即用」由 `core/preinstall/__init__.py` 负责装配：它把六类数据补齐（幂等合并，已有条目不动），并用 `verify()` 如实盘点条数。

| 类别 | 产地 | 实测条数 |
| --- | --- | --- |
| 规则库（推理路径） | `logs/preinstall/rules.json` | 10 |
| 案例库（场景解法） | `logs/preinstall/cases.json` | 8 |
| 知识库 | `self_learn/knowledge_vec.json` | 297 |
| 人格模型（成型人设） | `presets/xiaojiao-default.json` | 6 |
| 元推理模板 | `logs/boost/templates.json` | 64 |
| 结构映射库 | `logs/boost/maps.json` | 11 |

实测命令与输出：

```text
>>> from core import preinstall
>>> preinstall.summary()
六类预置数据齐备（规则库 10 条、知识库 297 条、案例库 8 条、人格模型 6 条、元推理模板 64 条、结构映射库 11 条）；开箱即用不依赖用户先养。
```

补充说明：`logs/preinstall/manifest.json` 记录的是**最近一次装配新增的条数**，不是库存盘点。因此「已有内容、本次没新增」时它的 `by_category` 会全是 0，判断是否齐备要看 `verify()`。

---

## 9. N.E.K.O. 学习通道

`learn_from_neko.py` 从 N.E.K.O. 猫娘的记忆目录读取内容并写入小焦自己的记忆文件：

- 来源：`%LOCALAPPDATA%\N.E.K.O\memory\YUI\` 下的 `facts.json`（关于主人的事实）与 `persona.json`（说话风格）。
- 落点：`xiaojiao_knowledge_memory.json` 的 `学会:*` 键与 `猫娘说话风格` 键。
- 用法：`python learn_from_neko.py` 运行一次。

需要说明的实现现状：`start_xiaojiao.py` 会以 `--daemon --interval 300` 拉起该脚本，但脚本本身没有解析命令行参数，也没有循环，因此实际行为是**运行一次后退出**（设计为每 5 分钟轮询一次，未落地）。想周期刷新时，需要外部定时任务反复调用。猫娘一侧的说明见 [neko.md](neko.md)。

---

## 10. 如何判断小脑变强

可量化的四个观察点：

1. **知识库在长**：`self_learn/little_brain_knowledge.txt` 行数上升。
2. **检索命中**：问学过的问题，能直接命中并复用学过的答案。
3. **对比测试**：同一组测试题，积累更多之后命中率上升。
4. **重训之后**：损失下降，同类问题的输出更通顺。

`python learn.py stats` 会把上述指标一次性打印出来（交互记录条数、反馈分布、知识库与检索池条数、向量库条数）。

---

## 11. 优化建议

- **反馈要真实**：只给确实好的回答点赞或更正，避免错误样本进库；宁少勿滥。
- **优先学功能用法**：建文件、查 IP、写代码这类「用了哪个工具、怎么用」的经验复用价值最高，闲聊复用的收益低。
- **定期重训**：积累到一定量后运行 `train_model.py`，但**先备份权重**再训练；训练侧存在覆盖风险，详见 [xiaojiao_model.md](xiaojiao_model.md) 第 5.2 节。
- **控制知识库体积**：`build` 会把知识库整体追加进检索池，重复运行会重复追加；需要时对知识库与检索池做去重。
- **留意向量空间版本**：更换 `core/embedder.py` 的池化口径后，已入库的 512 维记忆向量需要重建。

---

## 12. 目录结构

```text
self_learn/
├── learn.py                     # 持续学习引擎：log / feedback / build / reflect / search / stats / train
├── vstore.py                    # 256 维哈希向量库（Embedding + 余弦）
├── README.md                    # 引擎说明
├── little_brain_knowledge.txt   # 小脑知识库：由 build 与点赞自动追加
├── tool_skills.txt              # 工具使用经验：由 _learn_skill 追加
└── knowledge_vec.json           # 向量库持久化文件
```

项目根相关文件：`logs/chat_history.jsonl`（记录层）、`logs/feedback.jsonl`（反馈层）、`training_data_pool_clean.txt`（检索池）。

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
