# 文生视频（ComfyUI 与云端接口）

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-10-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `video_service/video_api.py`、`video_service/model_switch.py`、`video_service/config.py`、`video_service/workflow_wan.json`、`video_service/cloud_video.py`、`video_service/video_api_spec.py`、`video_service/video_audio.py`、`video_service/agenes.py` |
| 产物目录 | `videos/`，通过 `/videos/<文件名>` 访问 |

## 摘要

小焦内置文生视频能力，有两条并列链路：本地链路用 ComfyUI 加载 Wan2.1 权重，在显卡上真正做扩散采样；
云端链路把提示词交给**任意一家**视频 API（Agnes 只是其中一家，见第 10 节：写一块 `video_api` 就能接）。
两条链路共用同一组接口与同一个任务队列，
由 `brain.video_mode` 或 `XIAOJIAO_VIDEO_MODE` 选择。本文说明两种模式、模型与目录要求、
接口、显存让位策略与限制。

另外：本地 Wan2.1 **没有音频通道**（出不来声音）；要"有声音"由 `video_audio.py` 在成片之后
用载体自己的声音（`/api/tts` → Chatterbox）念台词混进去 —— 那是**载体替他配音**，不是模型自己在说话。

## 1. 背景与问题

视频生成需要一整套模型：主模型、文本编码器、VAE，还要一个能编排节点的工作流引擎。
这些加起来几乎占满一张消费级显卡。而小焦同时还要提供对话能力，两者不能同时驻留。
另一个问题是生成耗时以分钟计，界面必须能在等待期间给出进度，并在刷新后不丢任务。

## 2. 设计目标

- 生成期间不使用户感知到模型切换：自动卸载大脑、启动生成引擎、生成完成后按策略释放。
- 任务状态持久化到文件，刷新页面或重启前端不影响查询。
- 同一时刻只接受一个生成任务，避免多个任务争抢显存。
- 目录与路径可配置，缺配置时自动探测，找不到就明确报错而不是静默失败。

## 3. 两种模式

| 模式 | 取值 | 行为 | 是否占本地显存 |
|---|---|---|---|
| 云端 | `api` | 把提示词透传给已配置的云端视频模型 | 否 |
| 本地 | `local` | 卸载大脑、启动 ComfyUI、跑 Wan2.1 工作流 | 是 |

模式解析顺序：环境变量 `XIAOJIAO_VIDEO_MODE`，其次控制文件的 `brain.video_mode`，
都没有时返回默认值 `api`。即使解析为 `api`，若控制文件 `models` 列表里没有可用的云端视频模型
（判据见第 10.1 节：**自己声明了 `video_api`**，或地址/名称里带 video/agnes 且填了 `api_key`），
`cloud_video.available()` 返回假，任务会自动回落到本地链路。也就是说：
**没配置云端视频模型时，默认路径就是本地 ComfyUI。**

还有一种情况：配了模型但**跑不了**（协议没实测过、缺 `base_url`、缺 `api_key`）——
`cloud_video.runnable()` 会返回具体原因，日志与任务里都会如实写出这句话，然后同样回落本地。

切换模式：

```bash
curl http://127.0.0.1:5000/api/video/mode
curl -X POST http://127.0.0.1:5000/api/video/mode \
  -H "Content-Type: application/json" -d "{\"mode\":\"local\"}"
```

## 4. 本地链路的流程

```text
提交中文场景描述
  → 精炼提示词：先查小脑向量库，命中则直接用；未命中则让聊天大脑改写，并写回向量库
  → brain_manager.switch_to("video")：卸载大脑、启动 ComfyUI，等待 8188 就绪
  → 读取 workflow_wan.json，替换权重名与正向提示词，提交给 ComfyUI
  → 轮询 ComfyUI 的 /progress 取真实步数，写进任务进度
  → 下载产物到 videos/<时间戳>_wan.mp4
  → brain_manager.switch_to("chat")：恢复聊天大脑
  → 按 keep_warm 决定是否启动 15 分钟闲置释放计时
```

云端链路的流程更短：不卸载大脑、不精炼提示词、不占显存，直接把提示词交给云端适配器，
完成后再下载结果。

## 5. 工作流与模型

`video_service/workflow_wan.json` 使用 WanVideoWrapper 的节点，共 9 个：

| 节点 | 类型 | 关键参数 |
|---|---|---|
| 1 | `WanVideoModelLoader` | 权重名由 `__CKPT__` 占位替换；`fp8_e4m3fn` 量化 |
| 2 | `LoadWanVideoT5TextEncoder` | `umt5_fp8.safetensors` |
| 3 | `WanVideoTextEncode` | 正向提示词由 `__POS__` 占位替换 |
| 4 | `WanVideoEmptyEmbeds` | 832 × 480，33 帧 |
| 5 | `WanVideoSampler` | 14 步，cfg 5.0，shift 7.0，seed 42，unipc 调度 |
| 6 | `WanVideoVAELoader` | `vae_fp8.safetensors` |
| 7 | `WanVideoDecode` | 开启分块解码，块 256 × 256 |
| 8 | `CreateVideo` | 24 fps |
| 9 | `SaveVideo` | mp4，文件名前缀 `xiaojiao_wan` |

因此单次生成的分辨率是 832 × 480，帧数 33，采样 14 步。界面上的进度条分母即这 14 步。
历史上曾有生成失败的根因指向 BlockSwap 节点，当前工作流中已不含该节点。

三个权重文件的名称与放置位置：

| 文件 | 作用 | 代码查找位置 |
|---|---|---|
| `dit_fp8.safetensors` | 扩散主模型 | `models/checkpoints/`，以及视频模型总目录本身（`config.find_checkpoint()`） |
| `umt5_fp8.safetensors` | 文本编码器 | `models/text_encoders/` |
| `vae_fp8.safetensors` | VAE | `models/vae/` |

`config.find_checkpoint()` 按文件名关键词 `wan`、`fp8`、`dit`、`1.3b` 在
`models/checkpoints/` 与视频模型总目录中匹配，取排序后的第一个。
`/api/env` 的环境体检则在 `models/diffusion_models/`、`models/text_encoders/`、`models/vae/`
以及视频模型总目录中查找。两处查找目录不完全一致：**权重只放在 `models/diffusion_models/`
时，生成能跑，但环境体检会报"视频模型三件套缺"。**

## 6. 配置

| 变量或配置项 | 默认值 | 说明 |
|---|---|---|
| `XIAOJIAO_VIDEO_ROOT` | 自动探测 | 视频模型总目录；探测顺序为先看控制文件 `brain.comfy_dir` 附近的目录，再交给 `install_all.discover_video_root()` 全盘检索；都得不到时为空串 |
| `XIAOJIAO_COMFY_DIR` | 自动探测 | ComfyUI 启动目录；判定依据是该目录下存在 `main.py` |
| `XIAOJIAO_COMFY_PORT` | `8188` | ComfyUI 端口 |
| `XIAOJIAO_VIDEO_MODE` | `api` | 链路选择，取值 `api` 或 `local` |
| `XIAOJIAO_KEEP_COMFY` | 未设置 | 设为 `1` 时，启动时给 ComfyUI 加 `--lowvram`，权重放内存 |
| `XIAOJIAO_WAN_MODEL` | `wan2.6-t2v` | 提交工作流时替换 `__MODEL__` 占位符；当前工作流里没有该占位符，因此不生效 |
| `brain.keep_warm` | `false` | 为真时 ComfyUI 常驻不释放；为假时生成完启动 15 分钟闲置计时 |

启动顺序上，`start_comfy()` 优先使用便携版自带的 `python_embeded/python.exe`，
依次尝试 ComfyUI 目录的上两级、上一级与同级；都找不到时用当前解释器。
等待 8188 就绪的上限是 240 秒，超时抛"ComfyUI 启动超时(4分钟)"。

**目录结构示例**（便携版）：

```text
<视频模型总目录>\
├── ComfyUI_windows_portable_nvidia_cu126\
│   ├── python_embeded\python.exe
│   └── ComfyUI\
│       ├── main.py
│       └── models\
│           ├── checkpoints\      dit_fp8.safetensors
│           ├── text_encoders\    umt5_fp8.safetensors
│           └── vae\              vae_fp8.safetensors
└── dit_fp8.safetensors           放在总目录下也能被找到
```

权重来源为 Hugging Face 的 Wan 仓库。网络受限时可设置 `HF_ENDPOINT=https://hf-mirror.com`，
或从镜像站手工下载。

## 7. 接口

| 接口 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `/api/video` | POST | `prompt` | 提交生成任务，返回 `{"ok": true, "job": "<job_id>"}`；已有任务在跑时返回 `busy` |
| `/api/video/status` | GET | `job` | 查询指定任务的状态与进度 |
| `/api/video/current` | GET | 无 | 当前进行中的任务，附带 `phase` 与 `busy` |
| `/api/video/state` | GET | 无 | 生成引擎的状态（阶段、消息、是否忙） |
| `/api/video/mode` | GET、POST | `mode` | 读或切链路模式 |
| `/api/video/refine` | GET | `prompt` | 只精炼提示词，不学习、不切换，返回精炼后的提示词与中文大意 |
| `/api/video/promptkb` | GET | 无 | 向量库里已学到的提示词条数与最近几条 |
| `/videos/<文件名>` | GET | 无 | 下载或播放产物 |

提交示例：

```bash
curl -X POST http://127.0.0.1:5000/api/video \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"黄昏的湖面上有一只白鹭飞过\"}"
```

`prompt` 会被截断到 80 个字符。任务对象包含 `state`、`prompt`、`refined_prompt`、
`progress`（`{"value", "max"}`）、`url`、`error` 等字段。任务表写入
`video_service/_jobs.json`，因此重启后仍可查询历史任务。

## 8. 提示词精炼与小脑学习

`_refine_prompt()` 分三步：

1. 查小脑向量库 `self_learn/vstore`，命中相似条目时取回已学过的精炼结果。
2. 未命中则让聊天大脑把描述改写成一段英文电影提示词，成功后以标签 `video_prompt`
   写回向量库。
3. 大脑不可用或超时（6 秒）时用模板兜底：在原描述后追加电影风格修饰词。

第 2 步会带上 `chat_template_kwargs` 关闭思考。`/api/video/promptkb` 想读的是
`video_service/knowledge_vec.json` 中标签为 `video_prompt` 的条目，用于展示"学到了什么"。

#### 那处对不上的地方**已经修了**（2026-09-18）

原来这里是"如实标注一处 bug"：写入方与读取方**不是同一个文件**，于是那个接口**永远显示 0**。
现在**修好了**，两边的记录都留在这儿：

| | 修之前 | 修之后 |
|---|---|---|
| **提示词真的写进了哪** | `self_learn/knowledge_vec.json`（`_refine_prompt` 第 2 步走 `self_learn/vstore`） | 同左（没动写入侧） |
| **接口读的是哪** | `video_service/knowledge_vec.json` | **同一个库**：直接问 `vstore`（拿不到 API 才退回读它自己的 `VS` 路径） |
| **后果** | 那个文件**不存在** → 按 `__file__` 拼路径打开抛异常 → 被吞掉 → `count` 永远 **0**，而且**没有任何报错** | 写入与读取只有一个事实来源，读得到就读得到、读不到就如实返回 0 |
| **实测** | 接口返回 `count: 0` | 直接调用视图函数：**`count: 3`**，并列出三条真实精炼结果（女孩漫步 / 樱花树下漫步 / 樱花树下散步） |

**根因不是"少建了一个文件"，是"同一份数据有两个地址"** —— 那种 bug 不会报错，只会一直显示空。
所以修法是让读取方走写入方那个库，而不是再建一个空文件糊上。

详见 [`../video_service/README.md`](../video_service/README.md) 的核对记录。

## 9. 显存让位与温存策略

| 时机 | 动作 |
|---|---|
| 提交本地生成 | `switch_to("video")`：处于温存状态的其他大脑被彻底卸载，当前运行的大脑转入温存，然后启动 ComfyUI |
| 生成完成 | `switch_to("chat")`：恢复聊天大脑 |
| 生成失败 | 兜底再调一次 `switch_to("chat")`，尽力恢复 |
| 完成后 | `keep_warm` 为假时起一个后台计时线程，15 分钟后若没有新任务则停止 ComfyUI；为真时 ComfyUI 常驻 |

`--lowvram` 只在 `keep_warm` 为真或设置了 `XIAOJIAO_KEEP_COMFY=1` 时附加。
两种策略的取舍是：常驻换取连续生成的秒级启动，代价是内存与显存长期被占。

## 10. 云端链路（兼容任意厂商，不是只认某一家）

`cloud_video.py` 是入口，真正干活的是 **`video_api_spec.py`：一套配置驱动的通用适配引擎**。

### 10.1 它按「你自己的声明」说话，不按域名猜

2026-10-14 之前这里是"按 `base_url` / 模型名特征猜协议"：认得出 Agnes 就走 Agnes 那一套写死的
参数，认不出就回一句"暂未支持的协议"。这等于**把某一家的规矩写进了载体** ——
换一家（可灵、海螺、万相、Veo、Replicate…）就得改代码。

现在改成：**接一家新厂商 = 在控制文件里给那个模型写一块 `video_api`，不用改任何代码**。
引擎只做三件通用的事：按模板发建任务请求 → 按 JSON 路径轮询状态 → 取回成片。

| 情形 | 引擎怎么处理 |
|---|---|
| 条目里写了 `video_api` | **以它为准**（这是接任意厂商的正路） |
| 没写，但域名/名字像 Agnes | 用内置 `agnes` 预设（**已实测**） |
| 没写，其它 | 按 OpenAI 兼容视频形状试，并**如实标出"这是猜的、未实测"** |
| 像 Gemini/Veo | **不编字段**：给骨架 + 明确提示"按它的文档填 `video_api`" |

### 10.2 `video_api` 可以写哪些字段（全部可选）

| 字段 | 作用 |
|---|---|
| `kind` | 预设名：`agnes` / `openai-video` / `custom` |
| `create_path` / `query_path` | 建任务 / 查任务路径，可带 `{id}` `{model}` 占位 |
| `create_body` | 建任务请求体里**额外**的固定字段（如 `{"resolution":"1080p"}`） |
| `auth` | `{style: bearer x-api-key query header none, header, scheme, param}` |
| `headers` | 额外的固定请求头 |
| `id_paths` / `status_paths` / `url_paths` / `progress_paths` / `error_paths` | 从响应里取值的 JSON 路径候选（支持 `data.0.task.id` 这种嵌套与数组下标） |
| `done` / `failed` / `pending` | 状态值字面量（不区分大小写，中文也认） |
| `result_kind` | `url`（默认）或 `base64`（有的厂商直接回一段 base64） |
| `poll_interval` / `queue_retry` | 轮询间隔、队列满时的重试次数 |
| `verified` | 自己声明"这套字段我实测过"。为假时**默认拒绝执行**，要显式 `allow_unverified` 才跑 |

实例（一家形状很怪的厂商，全靠配置接上）：

```json
{
  "name": "某家云视频", "base_url": "https://api.vendor.example",
  "api_key": "sk-...", "model": "vendor-video-3",
  "video_api": {
    "kind": "custom",
    "create_path": "/v1/videos",
    "query_path": "/v1/jobs/{id}",
    "auth": {"style": "x-api-key", "header": "X-Api-Key"},
    "id_paths": ["data.job.uuid"],
    "status_paths": ["data.job.state"],
    "url_paths": ["data.job.file.mp4"],
    "progress_paths": ["data.job.pct"],
    "done": ["ok"], "failed": ["dead"], "pending": ["queued", "running"]
  }
}
```

### 10.3 三条硬规矩

1. **未实测的协议默认拒绝执行**（除非显式放行）。拿没验过的协议去跑，用户花的是自己的钱和时间，
   报错时还看不出是"协议不对"还是"服务不行"。
2. **状态认不出来一律当"还没好"**，绝不把半成品当成品交出去。
3. **队列满 / 限流 / 断线 = 再试一次；参数错（400/401）当场报出来** —— 两种代价不对等。
   取不到任务 id 或成片地址时，错误信息会直接告诉用户改 `id_paths` / `url_paths` 里的哪个字段。

### 10.4 自测怎么跑

```bash
python tools/test_cloud_video_spec.py
```

这套自测（57 项）里有一段会**真起一个本机 HTTP 服务**，用它扮演一家"从没听说过、形状很怪"的厂商
（任务字段叫 `uuid`、状态叫 `queued/running/ok`、进度叫 `pct`、成片地址埋在 `file.mp4` 里），
然后只写配置把它接上并跑完整条链路 —— 证明"接任意厂商只需写配置"不是一句口号。

免费档位有每分钟 1 次的请求限制时，适配器用一个进程内锁加时间戳做节流，两次请求之间至少间隔 60 秒。

## 11. 效果演示

以下两段视频由本地链路生成，文件位于 `media/`：

<video src="/media/wan_video_demo_1.mp4" controls width="100%"></video>
<video src="/media/wan_video_demo_2.mp4" controls width="100%"></video>

## 12. 边界与限制

1. 本文档不给出显存要求的绝对值。实际能否运行取决于权重精度、分辨率、帧数与是否使用
   `--lowvram`，请以本机实测为准。
2. 同一时刻只处理一个任务。提交时若已有任务处于切换或生成状态，返回 `busy` 而不是排队。
3. 超时判定与提示文案不一致：`_sweep()` 用的阈值是 600 秒（10 分钟），
   但写入的提示是"生成超时(30分钟)"。长时间等待时以 10 分钟为准。
4. 进度来自轮询 ComfyUI 的 `/progress`。该接口返回空时进度条不动，界面不会报错；
   换成 WebSocket 监听可以拿到更细的真实步数，尚未实现。
5. `XIAOJIAO_WAN_MODEL` 在当前工作流中不生效，因为没有 `__MODEL__` 占位符。
   更换主模型的实际做法是替换 `models/checkpoints/` 下的权重文件。
6. 首次生成需要等 ComfyUI 加载权重，耗时明显长于后续生成；这段时间计入 240 秒启动上限。
7. 精炼提示词的向量库命中阈值固定为 0.35，不由配置暴露。
8. 云端免费档位有每分钟 1 次的硬限制，节流是阻塞式的（`time.sleep`），
   期间该请求线程会一直等待。

## 13. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 报"找不到 ComfyUI" | `XIAOJIAO_COMFY_DIR` 未设且自动探测未命中 | 确认目标目录下存在 `main.py` |
| ComfyUI 启动超时 | 便携版缺少 `python_embeded`，或首次加载过慢 | 手工启动一次 ComfyUI 观察启动日志 |
| 环境体检说模型三件套缺失 | 权重放在 `models/diffusion_models/` 而体检只查该目录，或文件名不含关键词 | 对照第 5 节的查找规则摆放文件 |
| 任务 `state` 为 `error` | 读任务对象的 `error` 字段 | 云端失败会自动回落本地，两者都失败时错误取本地链路的 |
| 进度条不动 | ComfyUI `/progress` 返回空 | 查看 `/api/video/state` 的 `phase` 是否仍在 generating |
| 生成后聊天无响应 | 聊天大脑未恢复 | 调 `/api/monitor/op` 的 `switch` 指定 `chat` |
| 显存长期被占 | `keep_warm` 为真，或 15 分钟计时尚未到点 | 查看控制文件的 `brain.keep_warm` |

## 14. 参考

- 显存调度与大脑状态：[brain-switch.md](brain-switch.md)、[coding-brain.md](coding-brain.md)
- 播客与音乐同样涉及显存让位：[podcast.md](podcast.md)、[music.md](music.md)
- 依赖体检项：[dependency-check.md](dependency-check.md)
- 代码：`video_service/video_api.py`、`video_service/model_switch.py`、`video_service/config.py`、
  `video_service/workflow_wan.json`、`video_service/cloud_video.py`、`video_service/agenes.py`

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 补充云端 `api` 模式与模式解析顺序；更正 `XIAOJIAO_VIDEO_ROOT` 默认值（非写死路径，而是自动探测）；标注 `XIAOJIAO_WAN_MODEL` 不生效与超时阈值 600 秒的文案不一致 |
