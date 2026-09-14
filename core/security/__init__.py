# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 安全阀（security）

这里是**载体层的闸门**，不是提示词里的"请勿"。
区别在于：提示词是"请求"模型别乱来，模型可以有别的想法；
闸门是代码里的一道判断，模型说什么都没用，也没有否决权。

目前只有一个模块，也是整个系统唯一的禁区：
  no_delete.py —— **删除禁区**：小焦可以在自己世界里做任何事，唯独不能删东西。

为什么单独开一个包、而不是塞进 core/ 里某个文件：
  ① 这是"安全边界"，要有自己的目录名，审代码的人一眼能找到（安全代码最怕藏得深）；
  ② 它必须能被**单独 import** —— 工具层、任务层、外部脚本都要用它，
     所以本包不依赖 Flask、不依赖主程序、不引入任何新依赖；
  ③ 边界要少而稳：以后再有安全约束（比如"不外发密钥""不跑未知网络请求"），
     也该落在这个包里，而不是散在各个功能模块里各写各的。

对外只暴露这些名字（顺便把 `core.security` 变成一层薄壳，
调用方不必记住模块文件名）：
    BAN_RULES / SUSPECT_RULES        可审计的规则表
    is_delete_command(cmd)           纯判断 → (是否删除, 证据)
    check_command(cmd)               命令守卫 → 空串=放行，非空=可读中文提示
    guard_command(cmd)               同上（语义化别名）
    check_file_op(op, path, ...)     文件操作守卫
    guard_write(path, content, mode) 写文件守卫
    assert_command(cmd)              被拦就抛 DeleteBlocked
    explain()                        给用户/文档看的"为什么不能删"
"""
from .no_delete import (  # 包级再导出：调用方不必关心模块文件名（__all__ 里已声明，不会被当成未使用）
    BAN_RULES,
    SUSPECT_RULES,
    DeleteBlocked,
    assert_command,
    check_command,
    check_file_op,
    explain,
    guard_command,
    guard_write,
    is_delete_command,
)

__all__ = [
    "BAN_RULES",
    "DeleteBlocked",
    "SUSPECT_RULES",
    "assert_command",
    "check_command",
    "check_file_op",
    "explain",
    "guard_command",
    "guard_write",
    "is_delete_command",
]
