# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
"""小焦 · 载体层 · carrier（变形金刚的"躯干"）

这个包里放的是**载体自己认识自己**的两件事 —— 它们与"用哪个模型"完全无关：

  brain_registry.py  火种登记处：有哪些模型可用 / 现在烧哪颗 / 挂了谁顶上（可热插拔）
  capability.py      能力登记处：我现在有哪些工具（不封顶，用户丢插件就变多）

为什么这两个放在一起：
  一个是"我能换成谁"，一个是"我会干什么"。载体把这两件事都记在自己身上，
  于是「换火种不换小焦」有了落点 —— 换模型只动 brain_registry 的指针，
  capability（工具）与记忆/世界/会话全都原样保留。

① 为什么要有这一层（而不是把这些散在 xiaojiao_app.py 里）：
   app 是"用起来"的地方（HTTP 服务、对话循环），载体层是"为了可替换而存在"的地方。
   混在一起的结果是：想换一颗火种 / 想清点一次能力，都得先把整个 web 应用拉起来。
   放在这里之后，任何脚本（自测、CLI、别的入口）都能只 import 载体层就把事情办了。
② 去掉会怎样：
   换模型、加插件都退回"改 app 源码 + 重启"，"模型平等 / 能力不封顶"就只是文档里的口号。

用法（两个类都是即插即用，默认落在 logs/carrier/）：
    from core.carrier import BrainRegistry, CapabilityRegistry
    reg = BrainRegistry()               # 默认惰性读 xiaojiao_control.json 的 brains
    reg.switch("agnes")                 # 换火种：只挪指针，不碰记忆/工具/世界/会话
    cap = CapabilityRegistry()          # 默认盯 <repo>/plugins
    print(cap.scan()["count"])          # 现在有多少个工具（真实值，不是写死的 77）
"""
from .brain_registry import Brain, BrainRegistry
from .capability import CapabilityRegistry

__all__ = ["Brain", "BrainRegistry", "CapabilityRegistry"]
