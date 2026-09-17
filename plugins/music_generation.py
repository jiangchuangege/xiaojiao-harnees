# plugins/music_generation.py —— 音乐生成插件(工具)：小焦说"生成音乐/曲子/旋律"时调用
# 本地 MusicGen(facebook/musicgen-small, 首次自动下载~1.5G) → 生成 wav → 前端播放
import os, sys, datetime, subprocess
import logging  # noqa: F401  （由 tools/fix_silent_except.py 注入）
try:
    from xiaojiao_log import get_logger
except Exception:  # 独立运行时退化为标准 logging
    def get_logger(name=None):
        return logging.getLogger(name or 'xiaojiao')
LOG = get_logger(__name__)

_BASE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_BASE)
_MUSIC_DIR = os.path.join(_ROOT, "media", "music")


def _free_vram():
    """让出显存给音乐模型：走**显存归属策略**（聊天模型让位，跑完必须还回去）。

    【原来是错的，两个问题】
      ① `for k in BRAINS: bm._full_stop(k)` —— **把每个大脑都按"视频"处理一遍**，
         连 ComfyUI 一起停（`_full_stop` 当时不分类型）；
      ② 而且**没有任何恢复**：生成完音乐，聊天模型永远躺在卸载状态，
         用户下一句话要重新读盘（本机盘 5 秒，USB 盒上 120 秒）。
    现在只做一件事：`use_gen("music")`（它内部会记下"该还给谁"），
    跑完由 finally 里的 `done_gen("music")` 把聊天模型顶回显存。
    """
    try:
        import brain_manager as bm
        return bm.use_gen("music")
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 16, e)
        return None


def _give_vram_back():
    """音乐生成结束（**成功失败都要**）：功能模型退到内存待命，聊天模型回显存。"""
    try:
        import brain_manager as bm
        return bm.done_gen("music")
    except Exception as e:
        LOG.debug("忽略异常(%s:%d): %s", __file__, 16, e)
        return None


class MusicGeneration:
    def get_tool_descriptions(self):
        return [{
            "name": "generate_music",
            "description": "本地生成一段音乐(MusicGen)。什么时候用：用户要「来段音乐/BGM」；输入 prompt(风格描述)、duration(秒,默认5)；输出 音频链接。首次会自动下模型(~1.5G)，较慢。"
                           "第一次使用会自动下载模型(~1.5G)并安装依赖。返回音频链接。",
            "parameters": {"type": "object", "properties": {
                "prompt": {"type": "string", "description": "音乐描述(中文/英文)"},
                "duration": {"type": "number", "description": "时长秒数(默认5, 最大20)"}},
                "required": ["prompt"]},
        }]

    def execute(self, tool_name, params):
        if tool_name != "generate_music":
            return "未知工具"
        prompt = (params.get("prompt") or "").strip()[:120]
        dur = max(1, min(int(params.get("duration", 5)), 20))
        if not prompt:
            return "请输入音乐描述"
        try:
            _free_vram()
            # 首次: 装 audiocraft
            try:
                import audiocraft  # noqa
            except Exception:
                subprocess.run([sys.executable, "-m", "pip", "install", "audiocraft", "-q"], timeout=600)
            import torch
            from audiocraft.models import MusicGen
            from audiocraft.data.audio import audio_write
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            model = MusicGen.get_pretrained("facebook/musicgen-small", device=dev)
            model.set_generation_params(duration=dur)
            wav = model.generate([prompt])
            os.makedirs(_MUSIC_DIR, exist_ok=True)
            out = os.path.join(_MUSIC_DIR, datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
            audio_write(out, wav[0].cpu(), model.sample_rate, strategy="loudness")
            rel = os.path.join("media", "music", os.path.basename(out) + ".wav").replace("\\", "/")
            return "✅ 音乐生成完成：\n[music]" + rel + "[/music]\n🎵 " + prompt + "（" + str(dur) + "秒）"
        except Exception as e:
            return "⚠️ 音乐生成失败：" + str(e)[:200]
        finally:
            # **成功、失败都必须把聊天模型还回显存**（原来这里什么都没有）
            _give_vram_back()


def get_plugin():
    return MusicGeneration()
