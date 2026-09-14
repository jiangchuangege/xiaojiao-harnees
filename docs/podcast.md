# 播客大脑

| 项目 | 内容 |
|---|---|
| 适用版本 | v1.0 |
| 最后更新 | 2026-09-14 |
| 维护者 | 小焦项目 |
| 文档状态 | 稳定 |
| 代码位置 | `podcast_service/podcast_gen.py`（生成逻辑）、`podcast_service/podcast_api.py`（Blueprint 与页面） |
| 产物目录 | `media/podcast/`，通过 `/media/podcast/<文件名>` 访问 |

## 摘要

给定一个主题，小焦生成一段中文双人播客：聊天大脑写稿，本地语音模型逐句配音，
`pydub` 按对话顺序拼接成单个 mp3，可选再用文生图模型生成封面。本文给出接口、
生成阶段、参数含义与已知限制。

## 1. 背景与问题

播客是"长文本加语音加图片"的组合，一次生成要串起三类模型。若把三类模型同时放进显存，
在单张消费级显卡上会溢出。因此生成必须分阶段进行，且中间产物要能清理、
最终结果要能直接播放。另一个问题是语音合成的耗时会随稿子长度线性增长，
必须允许用户按目标时长控制篇幅。

## 2. 设计目标

- 一个接口提交主题，后台异步生成，前端可轮询进度。
- 复用小焦已有的语音模型，不重复加载一套 TTS。
- 中间产物生成后自动清理，只保留成品。
- 封面可关闭，以便在显存紧张或需要更快出结果时使用。

## 3. 生成流程

```text
提交主题
  → 写稿：调用聊天大脑（默认 http://127.0.0.1:9292/v1），分段生成双人对话
  → 配音：Chatterbox TTS 逐句合成 wav 到 media/podcast/<jid>_NN.wav
  → 拼接：pydub 按顺序拼接，段间插静音，导出 128k mp3
  → 封面（可选）：SD1.5 文生图，512×512
  → 清理中间 wav，保留 <jid>_podcast.mp3 与 <jid>_cover.png
```

四个阶段的进度写入任务对象：写稿 8%，稿成 25%，配音 25% 到 80%，拼接 85%，封面 92%，完成 100%。

## 4. 接口

### 4.1 页面

| 路径 | 说明 |
|---|---|
| `GET /podcast` | 播客生成页，含主题、主持人、轮数、风格、目标时长与封面开关 |

### 4.2 生成与查询

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/podcast` | POST | 提交生成任务，返回 `{"ok": true, "jid": "..."}` |
| `/api/podcast` | GET | 返回使用提示，说明应使用 POST |
| `/api/podcast/status/<jid>` | GET | 返回任务状态、进度与结果路径 |

POST 请求体：

```json
{
  "topic": "AI 会取代人类工作吗",
  "host_a": "小李",
  "host_b": "小焦",
  "rounds": 4,
  "style": "轻松有趣",
  "minutes": 15,
  "build_cover": true
}
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `topic` | 无，必填 | 播客主题；为空时返回 400 |
| `host_a` | `小李` | 主持人甲 |
| `host_b` | `小焦` | 主持人乙 |
| `rounds` | `4` | 对话轮数，页面提供 2、4、6、8 四个选项 |
| `style` | `轻松有趣` | 页面提供轻松有趣、专业严谨、幽默吐槽、深度访谈 |
| `minutes` | 空 | 目标时长（分钟），页面提供短播客与 5、10、15、20、30 分钟，默认选中 15 分钟 |
| `use_cover` | `true` | 保留参数，当前不影响拼接行为（见 8.6 节） |
| `build_cover` | `true` | 是否生成封面图 |

`minutes` 留空时按 `rounds` 折算篇幅：`minutes = max(1, rounds)`。
给定 `minutes` 时目标句数为 `clamp(minutes × 6, 6, 110)`，每段生成 6 句，逐段推进。

### 4.3 状态字段

| 字段 | 说明 |
|---|---|
| `state` | `queued`、`script`、`tts`、`compose`、`cover`、`done`、`error`，未找到任务时为 `notfound` |
| `progress` | 0 到 100 的整数 |
| `message` | 面向用户的中文进度描述 |
| `script` | 稿子，形如 `[["小李", "..."], ["小焦", "..."]]` |
| `audio` | 成品音频的站点路径，形如 `/media/podcast/<jid>_podcast.mp3` |
| `cover` | 封面图的站点路径，未生成则为空 |
| `error` | 失败原因，仅 `error` 状态下出现 |

## 5. 代码位置与函数

| 位置 | 名称 | 作用 |
|---|---|---|
| `podcast_service/podcast_gen.py` | `generate_script()` | 分段生成双人对话稿，支持进度回调 |
| `podcast_service/podcast_gen.py` | `_llm_chat()` | 调聊天大脑；失败时保留 system 与最近 3 条后重试，共重试 2 次 |
| `podcast_service/podcast_gen.py` | `_get_tts()` | 懒加载 TTS；优先复用 `xiaojiao_app._tts_model` |
| `podcast_service/podcast_gen.py` | `_merge_wavs()` | pydub 拼接，开头 300 毫秒静音、段间 400 毫秒静音、导出 128k mp3 |
| `podcast_service/podcast_gen.py` | `gen_cover()` | SD1.5 文生图出封面，512×512、25 步、guidance 7.5 |
| `podcast_service/podcast_gen.py` | `generate_podcast()` | 主入口，建任务并起后台线程 |
| `podcast_service/podcast_gen.py` | `job_status()` | 查询任务 |
| `podcast_service/podcast_api.py` | `bp` | Flask Blueprint，注册页面与两个接口 |

TTS 的加载顺序是：先尝试 `xiaojiao_app._tts_model`，取到就直接复用；取不到才自行加载
Chatterbox，模型目录由 `XIAOJIAO_TTS_MODEL`、控制文件的 `brain.tts_model_dir` 或常见位置探测决定。

## 6. 与其他大脑的关系

播客大脑已在 `brain_manager.BRAINS` 中登记，键为 `podcast`，登记端口 5000，类型 `podcast`。
登记的意义是它能出现在 `/monitor` 的大脑清单里，并与其余大脑共享同一套状态字段。

实际生成时的资源占用与登记信息并不完全一致，有三点需要说明：

1. 写稿阶段用的是聊天大脑（llama-swap，端口 9292），播客服务本身不卸载它。
2. 配音阶段复用小焦进程内的 TTS 模型；封面阶段在进程内加载 SD1.5。
3. `llama-swap.yaml` 中聊天模型配置为 `ttl: 0`（不按空闲时间自动卸载），
   因此写稿结束后聊天大脑仍占显存，直到视频、音乐或其余切换动作把它顶掉。

## 7. 依赖

| 依赖 | 用途 | 缺省后果 |
|---|---|---|
| `diffusers`、`transformers`、`accelerate`、`PIL`、`safetensors` | 加载 SD1.5 并出图 | 封面生成返回空，音频照常产出 |
| `pydub`、`soundfile` | 拼接音频 | 拼接失败，任务转为 `error` |
| `torchaudio` | 单句 wav 落盘 | 配音全部失败，最终无音频 |
| Chatterbox TTS | 语音合成 | 配音失败 |
| SD1.5 权重 | 封面 | 由 `XIAOJIAO_SD_MODEL` 指定，默认取 `G:\moxing\v1-5-pruned-emaonly.safetensors` |

封面权重路径注意两点：默认值是写死的 Windows 路径；该文件不存在时 `_get_sd()` 只打印一行提示
并返回 `None`，封面随即跳过，不影响音频。

## 8. 边界与限制

1. 任务表 `_JOBS` 只存在于内存中。小焦重启后，此前提交的任务查询会返回 `notfound`，
   而 `media/podcast/` 下的成品文件仍在。
2. 长时长的生成耗时主要落在配音阶段，因为每句都要过一次 TTS。目标句数上限为 110 句
   （约 18 分钟档），超出部分不会生成。
3. 稿子解析按 `[主持人名]: 内容` 逐行匹配。模型未按该格式输出时，该行被静默丢弃；
   极端情况下可能只剩开场白。
4. 生成失败时中间 wav 不会清理，会留在 `media/podcast/` 下，需要手工删除。
5. 封面出图在进程内加载 SD1.5，与 TTS 同处一个进程；两者叠加时的显存占用未实测。
6. `use_cover` 参数在 `_run_job()` 中的两个分支写法完全相同
   （`_merge_wavs(wavs, audio_out) if use_cover else _merge_wavs(wavs, audio_out)`），
   它对结果没有影响，实际控制拼接之外行为的是 `build_cover`。
7. 录制风格里的"目标时长"是估算：代码按每分钟左右 6 句折算，与 TTS 实际语速的偏差未实测。

## 9. 故障排查

| 现象 | 可能原因 | 排查方式 |
|---|---|---|
| 任务一直停在"排队中" | 后台线程未启动或进程被中断 | 重新提交；查询 `state` 是否为 `queued` |
| `state` 为 `error` | 拼接或封面阶段抛异常 | 读返回的 `error` 字段，同时看服务端日志中以 `[podcast]` 开头的行 |
| 有音频但没有封面 | SD 权重路径不存在，或 `diffusers` 未装 | 确认 `XIAOJIAO_SD_MODEL` 指向的文件存在 |
| 音频只有一两个人在说话 | 稿子格式不符合 `[名字]: 内容` | 查看 `script` 字段，确认模型输出格式 |
| 生成期间显存不足 | 聊天大脑未让出显存 | 生成前切换一次大脑，或临时调低目标时长并关闭封面 |
| 查询返回 `notfound` | 小焦已重启，任务表被清空 | 直接在 `media/podcast/` 里找已完成文件 |

## 10. 参考

- 语音合成接口：[api.md](api.md)
- 大脑登记与显存调度：[brain-switch.md](brain-switch.md)、[coding-brain.md](coding-brain.md)
- 同为本地生成能力：[video.md](video.md)、[music.md](music.md)
- 代码：`podcast_service/podcast_gen.py`、`podcast_service/podcast_api.py`

## 变更记录

| 日期 | 版本 | 变更 |
| --- | --- | --- |
| 2026-09-14 | v1.0 | 重写：对齐代码 + 统一文风 |
| 2026-09-14 | v1.0 | 补全 `minutes`、`use_cover` 参数与任务状态机；更正"写稿后释放聊天大脑"的说法；标注 `use_cover` 分支无效 |
