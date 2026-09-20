# 小焦系统本身不依赖任何具体模型。
# 它是完整的载体（器官齐全），模型是火种（可替换）。
# 接入任何模型 → 系统活；换任何模型 → 系统不变。
# 这就是"模型平等"和"变形金刚"的工程基础。
# -*- coding: utf-8 -*-
"""小焦 · 载体层 · 删除禁区（小焦世界里的**唯一禁区**）

一句话设计意图：
    小焦可以在自己世界里做任何事，**唯独不能删东西**。

为什么偏偏是删除：
  因为它是唯一**不可逆**的动作。写错了可以改、改错了再改，删了就真的没有了。
  再叠上一次"模型幻觉 / 看错路径 / 理解错意图"，就是用户数据的永久损失。
  所以载体层的分寸是：**允许小焦犯错，但不允许它造成无法挽回的损失。**

为什么写在代码里而不是提示词里：
  提示词是"请求"模型别删，模型可以有别的想法；这里是**代码层拦截**，模型说什么都没用。
  三条工程约束（本文件从头到尾遵守）：
    ① 不靠模型自觉 —— 判断全在 Python 里做，模型没有否决权；
    ② 不依赖任何"全权限/放行"开关 —— 就算上层把权限开到最大，删除这一条照拦不误
       （整个文件里没有任何一处去读权限配置；自测 [F] 会做源码级断言钉死这一点）；
    ③ 不依赖 Flask、不依赖主程序 —— 本模块可以单独 import，
       因为工具层、任务层、外部脚本都要复用它。

对应的全局红线：
  第 6 条 —— **脚本里的删除也算小焦自己删**：命令拼接、内联代码（-Command / -c）、
            脚本文件正文、即将写盘的脚本内容，全都要扫；
  第 7 条 —— **不覆盖用户的文件**，只能新建或追加（覆盖也是不可逆的）；
  第 8 条 —— **清空 / 重置与删除同罪**：内容没了，就是没了。

判据顺序（先摘"数据"，再判"动作"）：
  1. **切段**：按 `;` `&` `|` 换行 括号 把一行切成若干"小命令"。
     为什么：`echo hi; rm a.txt` 里只有第二段是动作，整串一起看会看糊。
     去掉它 → `echo hi; rm a.txt` 里的拼接删除就会被漏掉。
  2. **摘引号**：引号里的字符串是**数据**，不是动作。
     为什么：`echo "本文件不会被删除"`、`grep -rn "os.remove" src/` 都只是"提到"删除，
     不是删除本身。去掉它 → 一片误杀，用户会关掉这道闸门，闸门就废了。
  3. **只读动词的参数不算动作**：grep / Select-String / findstr / echo / type / cat /
     Get-Content … 的参数值是在"读"这个名字，不是在执行它
     （`Select-String -Path a.py -Pattern "delete"` 必须放行）。
  4. **但执行器语境不豁免引号**：powershell -Command "…" / python -c "…" / cmd /c /
     脚本文件 / eval / os.system —— **执行器不在乎引号**，引号里那串就是即将跑起来的代码。
  5. **引号语义按语言分**：shell 系（.sh/.ps1/.bat 和裸命令行）里 `"$(…)"` 是命令替换，
     真会跑；代码文件（.py/.js…）里 `"$(…)"` 只是四个字符（数据）。
     为什么非分不可：一套规则看所有语言，必然有一边判错 ——
     全按 shell 判会把代码里的用例字符串当命令（误杀），全按代码判会漏掉真·命令替换（漏删）。
  6. 剩下的文本按 BAN_RULES 扫；**光杆词**（不在引号里、也不是只读动词的参数）
     的 del / delete / rm 一律算删除，直接拦。
  7. 次级信号（SUSPECT_RULES）单独命中只记日志；只在第 4 条那种"静态无法确证"的
     **同一段**里升级为拦（例：`python -c "... os.truncate(...)"`）。
     为什么强调"同一段"：整篇扫一遍就升级的话，文件里只要有一处 `python -c`，
     别处一句中文注释里的"删除"就会被连坐 —— 这是实打实踩过的误杀。
  8. 命令指向脚本文件时，**把脚本正文读出来再扫一遍**（递归，有深度上限）；
     读不到就按可疑处理 —— 读不到就没法确认它不删东西，**宁可拦错，不可删错**。

判据里还有两条"摘数据"的细则（都是为了不误杀，也都是可解释的）：
  · **注释不算动作**：`#` 在引号外、且前面是空白或行首 → 到行尾都算注释。
    注释永远不会执行，脚本里被注掉的旧删除、行尾那句"以前这里是删库"、
    文档里引用的示例命令都属这一类。（为什么要判引号状态：`x = "#"; 真命令`
    里的 `#` 在字符串里，不判引号就把它后面的真命令整段抹掉了 —— 那才是漏判。）
  · **三引号长字符串不算动作**：`\"\"\"…\"\"\"` / `'''…'''` 是文档/模板（数据）。
    不摘掉，检查一份普通 Python 文件时会被它自己的 docstring 拦下。

已知的保守（刻意写在明面上，都不是 bug）：
  · 写一个正文里含 Python `del x` 的文件会被拦；
  · `python -c "print('delete')"` 这种"代码里只是提到删除"也会被拦；
  · 代码文件里被反引号包起来的命令示例（写文档时为好看加的那种）也会被当成命令替换判一次；
  · 拼接不出语义时（变量拼命令，`CMD="rm x"; $CMD`）一律偏向"拦"。
  取舍就一句：**误拦的代价是麻烦，漏删的代价是数据没了。**

补充一条"本模块自己"的说明：本文件是**规则书**，注释和文档里会成段地引用危险命令原文，
它们全在注释行/行尾注释/三引号文档里（= 数据），所以守卫扫它自己也不会误拦 ——
`tools/test_no_delete.py` 里有两条自洽用例专门盯这件事
（守卫不许拦项目自己的规则书和自测脚本）。

对外 API（主线按这个接）：
    is_delete_command(cmd) -> (bool, str)      纯判断，给内部/测试用
    check_command(cmd) / guard_command(cmd)    命令入口守卫（返回可读中文提示，空串=放行）
    check_file_op(op, path, ...)               文件操作守卫
    guard_write(path, content, mode="w")       写文件守卫
    assert_command(cmd)                        不放心就抛 DeleteBlocked
    explain()                                  给用户/文档看的"为什么不能删"
"""
import logging
import os
import re

logger = logging.getLogger(__name__)

# 仓库根目录。为什么要有它：守卫在很多地方被调用，工作目录不一定在仓库根；
# 解析脚本/目标文件路径时先按当前目录、再按仓库根兜一次，能少一批"读不到"的误判。
# 去掉它 → 从 tools/ 或 web 进程里调守卫时，相对路径一律解析失败 → 全部按可疑拦，没法用。
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

__all__ = ["BAN_RULES", "DeleteBlocked", "SUSPECT_RULES", "assert_command", "check_command",
           "check_file_op", "explain", "guard_command", "guard_write", "is_delete_command"]


class DeleteBlocked(Exception):
    """删除类操作被载体层硬拦。带可读中文提示。

    为什么要有这个异常类：有些调用点在"流水线中间"，返回字符串不好使唤，
    需要一个能被 try/except 抓住、且消息本身就是给用户看的中文提示的异常。
    去掉它 → 中间层只能把提示当字符串一层层往上传，很容易被某一层丢掉。
    """


# ================================================================ 规则表
# 为什么规则表要单独抽出来、每条都带中文原因：**这是可审计的**。
# 出了问题要能一眼看出"这条命令是被哪条规则拦的、为什么拦"，而不是去读代码逻辑。
# 每条都用 re.I 编译（Windows 上 Remove-Item / remove-item / REMOVE-ITEM 都得认，
# 大小写不统一的写法恰恰是最容易被绕过去的地方）。
# 顺序有讲究：**越具体的规则越靠前** —— 命中的第一条会作为证据和理由，先具体后笼统，
# 用户看到的提示才准。去掉顺序 → `os.remove(x)` 会被笼统的 delete 规则抢答，提示变糊。
BAN_RULES: list[tuple[str, str]] = [
    # —— ① 语言/库里的删除 API（最具体，放最前）——
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree 会把整棵目录树永久删掉"),
    (r"\bos\.removedirs\s*\(", "os.removedirs 会递归删除整条目录链"),
    (r"\bos\.remove\s*\(", "Python 的 os.remove 会永久删除文件"),
    (r"\bos\.unlink\s*\(", "Python 的 os.unlink 会永久删除文件"),
    (r"\bos\.rmdir\s*\(", "Python 的 os.rmdir 会删除目录"),
    (r"\.unlink\w*\s*\(", "unlink() 系列的调用等于删除文件（含 unlinkSync 这类变体）"),
    # —— ② .NET / PowerShell 的删除 API ——
    (r"\[system\.io\.file\]::delete", "[System.IO.File]::Delete 会永久删除文件"),
    (r"\[system\.io\.directory\]::delete", "[System.IO.Directory]::Delete 会永久删除目录"),
    (r"\bclear-content\b", "Clear-Content 会把文件内容清空（内容没了就是没了）"),
    (r"\bset-content\b[^\n;|&]*\$\s*null", "Set-Content … $null 会把文件内容清空"),
    (r"\bclear-disk\b", "Clear-Disk 会清空整块磁盘"),
    (r"\bremove-partition\b", "Remove-Partition 会删除磁盘分区"),
    # —— ③ 磁盘级危险动作（一次就是灾难，绝不留口子）——
    (r"(?:^|[\n;&|])\s*format(?:\.com)?\s+[a-z]:", "format 会格式化整个盘符"),
    (r"\bmkfs(?:\.\w+)?\b", "mkfs 会把分区重新格式化"),
    (r"\bdiskpart\b", "diskpart 能直接改写/清掉磁盘分区表"),
    (r"\bcipher\s+/w", "cipher /w 会覆写磁盘空闲区，数据不可恢复"),
    (r"\bsdelete\b", "sdelete 是不可恢复的擦除工具"),
    (r"\btruncate\b[^\n;|&]*(?:-s|--size[= ])\s*0\b", "truncate -s 0 会把文件截断成空"),
    (r"(?m)^\s*:\s*>", "` : > 文件 ` 是 bash 里把文件清空的惯用写法"),
    # —— ④ git 里的删除/丢弃（版本库也救不了没提交的东西）——
    (r"\bgit\s+rm\b", "git rm 会从工作区删掉文件"),
    (r"\bgit\s+clean\b[^\n;|&]*\s-[a-z]*(?:f|d|x)", "git clean -f/-d/-x 会删掉未跟踪的文件"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard 会丢弃所有未提交的改动"),
    (r"\bgit\s+checkout\s+--\s+\.", "git checkout -- . 会丢弃工作区的改动"),
    # —— ⑤ 各平台的删除动词（最笼统，放最后当兜底）——
    (r"\bremove-item\b", "Remove-Item 会永久删除文件/目录"),
    (r"\brm\b", "rm 会永久删除文件/目录"),
    (r"\bdel\b", "del 会永久删除文件"),
    (r"\berase\b", "erase 会永久删除文件"),
    (r"\brmdir\b", "rmdir 会删除目录"),
    (r"\brd\b", "rd 会删除目录"),
    (r"\bri\b", "ri 是 Remove-Item 的简写，会永久删除"),
    (r"\bunlink\b", "unlink 会解除文件链接（等于删除）"),
    (r"\bdelete\b", "delete 是删除动作"),
    (r"(?:^|\s)--?delete\b", "-delete / --delete 这类开关就是「顺手删掉」"),
    # —— ⑥ 清空式重定向（第 8 条：清空与删除同罪）——
    (r"\$\s*null\s*>", "$null 重定向等于把目标文件清空"),
]

# 次级信号：**单独命中不拦，只记日志**；只有在"执行器语境"（-c / -Command / 脚本正文 /
# eval / os.system …）下才升级为拦 —— 因为那时载体没法静态证明它到底干了什么。
# 为什么需要这一层：删除的花样不止动词表那几种，truncate / DROP / 擦除 这些
# 常常写在代码字符串里，纯动词表会漏。去掉它 → `python -c "… os.truncate(f,0)"` 这类放行。
SUSPECT_RULES: list[tuple[str, str]] = [
    (r"\btruncate\b", "truncate（截断）会把文件内容清零"),
    (r"\b(?:shred|wipe|purge|ftruncate|set_len)\b", "擦除/清零类动作"),
    (r"\boverwrite\b", "overwrite（覆写）会抹掉原有内容"),
    (r"\bremove\b", "remove 语义可能指向删除"),
    (r"\bdrop\b", "DROP 会把整张表连数据一起删掉"),
    (r"删除|清空|抹掉|销毁|重置|覆盖|删掉", "中文里的删除/清空/覆盖语义"),
]


def _compile(rules):
    """把规则表编译好（re.I）。单条写错只跳过错的那条，不让整个守卫起不来。

    为什么不在模块级直接 re.compile 成一个列表常量：规则表是给人看/给审计用的
    (正则, 原因) 纯数据；编译产物是内部实现，两者分开，改规则不会碰逻辑。
    去掉 try/except → 一条正则写错就 ImportError，整条链路上的工具全部起不来。
    """
    out = []
    for pat, reason in rules:
        try:
            out.append((re.compile(pat, re.I), reason, pat))
        except re.error:      # noqa: silent-ok — 一条规则写错只该少一条规则，不该炸掉守卫
            logger.warning("删除禁区：规则编译失败已跳过：%s", pat)
    return out


_BAN_C = _compile(BAN_RULES)
_SUSPECT_C = _compile(SUSPECT_RULES)

# "清空/重置"那几条规则要单独拎出来再扫一遍**没有抹掉只读动词参数**的文本：
# `echo $null > f` 里的 $null 正好在 echo 的参数区，会被只读动词规则抹掉，
# 可重定向清空是动作、不是"读参数"。只把这几条放进来（不是整张表），
# 是为了保住 `findstr rm a.txt` 这类正常查询不被误杀。
_CLEAR_PATTERNS = (r"\$\s*null\s*>", r"(?m)^\s*:\s*>")
_CLEAR_C = [c for c in _BAN_C if c[2] in _CLEAR_PATTERNS]

# 只读动词白名单：它们的**参数**是在"读"一个名字，不是在执行它。
# 例：`Select-String -Path a.py -Pattern "delete"`、`findstr rm a.txt`、`grep -rn "os.remove" src/`。
# 注意 find 不在名单里：`find . -delete` / `find . -exec rm {} \;` 是真删，
# 把它当只读动词反而会给删除开后门。
_READ_VERBS = frozenset({
    "echo", "type", "cat", "head", "tail", "less", "more", "nl", "tac",
    "grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr", "select-string", "sls",
    "gc", "get-content", "get-childitem", "gci", "dir", "ls", "tree",
    "log", "show", "format-list", "fl", "measure", "measure-object",
    "sort", "uniq", "wc", "split", "strings", "xxd", "od", "diff", "cmp",
    "stat", "file", "test", "where", "which", "whatis", "man", "help",
})

# 执行器：它们的作用就是"把后面那串跑起来"。进了执行器语境就**不豁免引号**。
# 为什么 mysql/sqlite3 也算：`sqlite3 db "DROP TABLE x"` 一样是不可逆的删数据。
_EXEC_WRAPPERS = frozenset({
    "powershell", "pwsh", "cmd", "command", "bash", "sh", "dash", "zsh", "ksh", "fish", "csh",
    "python", "python3", "py", "pyw", "node", "nodejs", "deno", "bun",
    "perl", "ruby", "php", "lua", "rscript", "osascript",
    "wscript", "cscript", "mshta", "iex", "invoke-expression", "start-process", "invoke-command",
    "sqlite3", "mysql", "psql", "redis-cli", "mongo",
})

# 段首的"装饰词"：它们本身不是动作，真正的动词在后面（`sudo rm x` 的动词是 rm）。
# 去掉它 → `sudo rm -rf x` 会被当成"动词=sudo"，虽然文本扫描还能兜住，
# 但脚本判定（谁在被执行）会全错。
_DECOR = frozenset({"sudo", "doas", "nohup", "env", "time", "nice", "xargs",
                    "start", "call", "exec", "if", "for", "while", "then", "do", "else"})

# 脚本后缀：命令指向这些文件时，正文要被读出来再扫一遍。
_SCRIPT_EXTS = (".ps1", ".psm1", ".bat", ".cmd", ".sh", ".bash", ".zsh",
                ".py", ".pyw", ".vbs", ".js", ".mjs", ".pl", ".rb", ".lua")

# 哪些脚本是"shell 系"的：引号在它们手里是**执行语义**
# （bash 里 `"$(…)"` 是命令替换，是真的要跑；.py 里 `"$(…)"` 只是四个字符）。
# 为什么要分语言：引号语义每个语言都不一样，用同一套规则看所有语言必然有一边判错 ——
#   全按 shell 判 → 一份 Python 脚本里字符串含 `$(…)` 的用例会被当成命令替换（误杀）；
#   全按代码判 → `echo "$(rm x)"` 这种真·命令替换会漏掉（漏删）。
# 分完以后两边都对：.py/.js 里引号是数据（但 `os.system(…)` / `subprocess.…` 这种
# 执行器语境照样不豁免引号），.sh/.ps1/.bat 和裸命令行按 shell 判。
_SHELL_EXTS = (".sh", ".bash", ".zsh", ".ksh", ".fish", ".ps1", ".psm1", ".bat", ".cmd")


def _is_shell_like(path):
    """这个脚本（或裸命令）该不该按 shell 的引号语义来判（见 _SHELL_EXTS 的说明）。"""
    return (path or "").lower().endswith(_SHELL_EXTS)

# "内联代码"开关：它后面那一个参数是**代码**，不是文件路径。
# 为什么必须区分：`powershell -Command "Select-String -Path a.py"` 里的 a.py 是查询目标；
# 当成"要执行的脚本"去读正文，就会把一条正常查询误判成"脚本读不到 → 拦"。
_INLINE_CODE_FLAGS = frozenset({"-c", "-command", "-e", "--eval", "-eval", "-encodedcommand",
                                "/c", "/k", "-commandwithargs", "eval"})

# git 的只读子命令：`git log --grep=delete` 里的 delete 是查询词，不是动作。
_GIT_READ_SUBS = frozenset({"log", "show", "diff", "status", "branch", "remote", "blame",
                            "describe", "ls-files", "rev-parse", "config", "grep", "whatchanged"})

# 段分隔符：命令拼接就靠这几个字符（`echo hi; rm a` / `a && del b` / `a | Remove-Item b`）。
# 为什么**不把括号算进来**：`os.remove("x")`、`shutil.rmtree(d)`、`.unlink()` 这些
# 删除 API 的括号是它名字的一部分；把括号当分隔符会在 `(` 处切开，
# `os.remove(` 就永远匹配不上（脚本正文里的删除会整类漏掉）。
# 括号里藏命令的情况（`$(rm a)`）由 _find_substitutions 单独负责，不需要切段。
_SEPS = frozenset(";&|\n\r")

# "把 X 跑起来"的调用形态：即使动词不在执行器名单里（比如 os.system），
# 只要出现这种调用，这一段也按执行器语境处理（引号不豁免）。
_EXEC_CALL_RE = re.compile(
    r"\b(?:os\.system|os\.popen|subprocess\.[a-z_]+|asyncio\.create_subprocess\w*|pty\.spawn"
    r"|eval|exec|iex|invoke-expression|start-process|call|command|sh|bash|powershell"
    r"|system|popen)\s*[\(\s]", re.I)

# PowerShell 调用运算符：`& 'x.bat'` / `& "x.ps1"` —— 直接把脚本当命令跑。
_CALL_OP_RE = re.compile(r"&\s*(?P<q>[\"'])(?P<f>[^\"'\n]+?\.(?:ps1|psm1|bat|cmd|sh|bash|zsh|py|pyw|vbs|js|mjs|pl|rb|lua))(?:[\"'])", re.I)

# 重定向覆盖：`> f`（含 `2> f`）；`>>`（追加）和 `>&`（句柄）不算。
# 注意它是**上下文规则**：只有目标文件已经存在，"覆盖"才不可逆，所以要落到文件系统上判。
_REDIRECT_RE = re.compile(r"(?<!>)>(?!>|&)\s*(?P<t>\"[^\"]*\"|'[^']*'|[^\s;|&<>]+)")

# 丢弃输出的目标：往这些地方写不算毁文件。
_DEVNULL = frozenset({"nul", "nul:", "$null", "/dev/null", "/dev/nul", "con", "-"})

# 递归扫描脚本正文的深度上限。为什么要有：脚本 A 调脚本 B 再调脚本 C……
# 一个自引用脚本能把栈跑穿。去掉它 → 极端输入下 RecursionError，
# 守卫从"拦不住"变成"直接崩"，比拦不住更糟。
_MAX_SCRIPT_DEPTH = 3
# 单个脚本最多读多大。超过就放弃静态检查（按可疑处理），避免读进来一个 2GB 的文件。
_MAX_SCRIPT_BYTES = 512 * 1024

# 默认替代建议：一律指向"新建/追加/手动处理"这条唯一出路。
_DEFAULT_ADVICE = ("改成新建（换个新文件名）或追加（mode='a'）；"
                   "旧文件请你自己手动处理 —— 这道闸门只防小焦，不防你。")

# 按命中原因给"更像人话"的替代建议。为什么要分词给建议：
# 被拦的人想知道的是"那我该怎么办"，而不是"你违反了第几条"。
_ADVICE_TABLE = (
    (("覆盖", "重定向", "覆盖已存在"), "换成新建或追加；确实要换掉旧文件，请你自己手动处理。"),
    (("清空", "截断", "重置", "$null"), "先把手上的内容追加到新文件里；要重新开始就新建一个文件，别清空旧的。"),
    (("脚本",), "把脚本里的删除步骤去掉，只保留读取和「写新文件」，再来执行。"),
    (("磁盘", "分区", "格式化", "擦除", "覆写"), "涉及磁盘/分区/擦除的操作载体重来不代劳，请你在系统层自己处理。"),
)


# ================================================================ 内部工具
def _resolve(path):
    """把命令里的路径变成能 stat 的绝对路径：先按当前工作目录，再按仓库根兜一次。

    为什么要有"仓库根兜底"：守卫会被 web 进程、工具层、外部脚本分别调用，
    工作目录不一定是仓库根；只按当前目录解析会把一堆正常路径判成"不存在"。
    去掉它 → 相对路径大量"读不到"，脚本执行类命令全被按可疑拦，误杀暴涨。
    """
    p = (path or "").strip()
    if not p:
        return ""
    cands = [p]
    if not os.path.isabs(p):
        cands.append(os.path.join(_ROOT, p))
    for c in cands:
        try:
            if os.path.exists(c):
                return os.path.abspath(c)
        except (OSError, ValueError):   # noqa: silent-ok — 路径非法就当它不存在，守卫不能崩
            continue
    try:
        return os.path.abspath(cands[0])
    except (OSError, ValueError):       # noqa: silent-ok — 同上，拿不到绝对路径就返回原串
        return p


def _exists(path):
    """路径是否已存在（守卫判断"覆盖/新建"的唯一依据）。"""
    p = _resolve(path)
    try:
        return bool(p) and os.path.exists(p)
    except (OSError, ValueError):       # noqa: silent-ok — 判不了存在就当不存在（不外抛）
        return False


def _blank_comments(text):
    """把**注释**抹成空格（长度不变）：`#` 在引号外、且前面是空白或行首 → 到行尾都算注释。

    为什么注释不算动作：注释永远不会被执行，它是文字
    （脚本里被注掉的旧删除、行尾那句"这里以前会删库"、文档里引用的示例命令，
    都属于这一类）。不摘掉它，小焦连一句说明都写不进文件，误杀得很冤。
    为什么要求"前面是空白/行首"：这样 `https://x#frag`、`a#b` 这种带 `#` 的名字
    不会被当成注释开头 —— 判错的代价是把 `#` 后面真正的命令藏起来（漏删），
    比多扫一点严重得多，所以宁可不认。
    为什么要逐个字符看引号状态：`x = "#"; 真正的命令` 里的 `#` 在字符串里，
    不判引号就会把它当注释，把后面那句真命令整段抹掉 —— 那才是致命的漏判。
    去掉它 → 注释里提到删除动词的正常文件一律写不进去 / 检查不过。
    """
    if "#" not in text:
        return text
    out = list(text)
    quote = ""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == "#" and (i == 0 or text[i - 1].isspace()):
            end = text.find("\n", i)
            end = n if end < 0 else end
            for k in range(i, end):
                out[k] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _mask_quotes(text, triples_only=False):
    """把**闭合**引号（含三引号）里的内容抹成空格，返回抹过的文本（与原文本等长）。

    为什么：引号里的字符串是数据。`echo "本文件不会被删除"` 只是在"提到"删除。
    为什么连三引号一起抹：`\"\"\"…\"\"\"` / `'''…'''` 是代码里的长字符串（docstring、
    模板、提示词），它同样是数据；不抹它，检查一份普通 Python 文件时会被它自己的
    文档字符串拦下（"误杀"里最常见的一种）。
    为什么必须等长：后面要拿偏移量做"只读动词参数"的切除，长度一变偏移全错位。
    为什么只抹"闭合"的引号：没闭合多半是笔误或跨行，此时**宁可不抹**
    （抹了等于把后面整串藏起来，正好给漏判递刀）。
    `triples_only=True`：只抹三引号（给"命令替换提取"用 —— 多行文档里的反引号
    示例是文字不是命令，但它前后的引号还得留着，因为 `echo "$(…)"` 这种
    引号里的命令替换是真要跑的，不能一起抹掉）。
    去掉这个函数 → 一切含引号的正常操作（写文档、查日志、回显）全被误杀。
    """
    n = len(text)
    masked = list(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch not in "\"'":
            i += 1
            continue
        triple = text[i:i + 3] == ch * 3
        if triples_only and not triple:
            i += 1
            continue
        delim = ch * 3 if triple else ch
        if triple:
            end = text.find(delim, i + 3)
            if end < 0:
                break                    # 没闭合：照原样留着（宁可多扫，不可漏扫）
            end += 2                     # 抹到收尾三引号的最后一个字符
        else:
            quote = ch
            j = i + 1
            end = -1
            while j < n:
                cj = text[j]
                if cj == "\\" and quote == '"' and j + 1 < n:
                    j += 2
                    continue
                if cj == quote:
                    end = j
                    break
                j += 1
            if end < 0:
                break                    # 没闭合：整段照原样留着（宁可多扫，不可漏扫）
        for k in range(i, end + 1):
            masked[k] = " "
        i = end + 1
    return "".join(masked)


def _find_substitutions(text):
    """挖出 `$(...)` 和反引号里的内容 —— 那些是**真要被跑起来**的命令。

    为什么要单独挖：`$(rm a.txt)`、`` `rm a.txt` `` 里的 rm 是动作，
    但它可能落在引号里（`echo "$(rm a.txt)"`）被引号豁免挡掉，
    也可能落在只读动词后面（`echo $(rm a)`）被只读参数切除挡掉。
    这是"包一层就能绕过"的典型口子，堵它的方式不是加规则，而是**把内容拎出来单独判**。
    去掉它 → 命令替换型间接删除整类漏判（红线第 6 条失守）。
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "`":
            j = text.find("`", i + 1)
            if j < 0:
                break
            out.append(text[i + 1:j])
            i = j + 1
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            depth, j = 0, i + 1
            while j < n:
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append(text[i + 2:j])
            i = j + 1
            continue
        i += 1
    return out


def _split_segments(text):
    """按 `;` `&` `|` 换行 切段（引号里的分隔符不算），返回 [(段文本, 起, 止)]。

    为什么：`echo hi; rm a.txt` 的动作在第二段；不切段就无法区分
    "引号里的分号"和"命令拼接的分号"。
    为什么要返回起止偏移：抹引号/抹注释是**整篇**先做好的（三引号、跨行注释
    只有整篇看才对），切段之后要按偏移把抹过的那一份取出来对齐，长度不变所以偏移通用。
    去掉它 → 拼接型间接删除整类漏判（红线第 6 条失守）。
    """
    out, buf, quote = [], [], ""
    seg_start, i, n = 0, 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch in _SEPS:
            out.append(("".join(buf), seg_start, i))
            buf = []
            seg_start = i + 1
        else:
            buf.append(ch)
        i += 1
    out.append(("".join(buf), seg_start, n))
    return [s for s in out if s[0].strip()]


def _tokenize(seg):
    """把一个段切成 token：[(去掉外层引号的值, 起, 止, 是否整体被引号包住)]。

    为什么要返回"是否整体被引号包住"：命令位置整体是引号串时，它其实是
    **源码/文本里的字符串字面量**（`"rm a.txt"` 这种），不是一条命令 ——
    这正是"用本守卫去检查脚本源码"时最关键的一条，不区分就会把源码里的
    示例字符串当成真删除，误杀到没法用。
    """
    out, buf, quote, start, i, n = [], [], "", -1, 0, len(seg)
    while i < n:
        ch = seg[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(seg[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            if not buf:
                start = i
            buf.append(ch)
        elif ch.isspace():
            if buf:
                out.append(_mk_token(buf, start, i))
                buf, start = [], -1
        else:
            if not buf:
                start = i
            buf.append(ch)
        i += 1
    if buf:
        out.append(_mk_token(buf, start, n))
    return out


def _mk_token(buf, start, end):
    raw = "".join(buf)
    fully = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'"
    return (raw[1:-1] if fully else raw), start, end, fully


def _norm_verb(tok):
    """把动词归一化：去引号、取 basename、去掉 .exe/.com。

    为什么：`C:\\Windows\\System32\\findstr.exe` 和 `findstr` 是同一个动作；
    不归一化，只读动词白名单和"命令位置"判定全会失配。
    """
    t = (tok or "").strip().strip('"').strip("'").lower()
    if not t:
        return ""
    t = t.replace("/", "\\")
    t = t.split("\\")[-1]
    for suffix in (".exe", ".com"):
        t = t.removesuffix(suffix)
    return t


def _verb_and_args(seg):
    """取段的 (动词 token, 后面所有 token)，跳过装饰词。

    去掉装饰词跳过 → `sudo rm x`、`xargs rm`、`call x.bat` 的动词判定全错。
    """
    toks = _tokenize(seg)
    i = 0
    while i < len(toks) and _norm_verb(toks[i][0]) in _DECOR:
        i += 1
    if i >= len(toks):
        return None, []
    return toks[i], toks[i + 1:]


def _is_script(tok):
    """这个 token 看起来是不是一个"要被执行"的脚本文件。"""
    t = (tok or "").strip().strip('"').strip("'").lower()
    return bool(t) and t.endswith(_SCRIPT_EXTS)


def _looks_like_path(tok):
    """命令位置上的脚本名像不像真的路径（而不是源码里随手一个字符串）。"""
    t = (tok or "").strip()
    if not t:
        return False
    if t[0] in "./\\" or (len(t) > 1 and t[1] == ":"):
        return True
    return _exists(t)


def _scan(text, compiled):
    """在文本里按顺序找第一条命中的规则，返回 (原因, 证据片段)。"""
    if not text:
        return "", ""
    for rx, reason, _pat in compiled:
        m = rx.search(text)
        if m:
            evidence = (m.group(0) or "").strip()
            return reason, evidence[:120]
    return "", ""


def _advice_for(reason):
    """按命中原因挑一条最贴切的替代建议（默认建议见 _DEFAULT_ADVICE）。"""
    for keys, advice in _ADVICE_TABLE:
        for k in keys:
            if k in (reason or ""):
                return advice
    return _DEFAULT_ADVICE


def _deny(reason, advice=None):
    """拼一条**给人看**的拒绝提示：🚫 一句结论 + 原因 + 替代建议。

    为什么格式固定：这条串会被模型读到、也会被用户看到，稳定三段才好被上层渲染、
    好被用户一眼看懂。**绝不把正则、栈、异常名丢给用户** —— 那些进日志。
    去掉它 → 每条拒绝各写各的，用户收到一堆黑话，第一反应是关掉这道闸门。
    """
    r = (reason or "这是一个不可逆的删除类操作").strip().rstrip("。.;；")
    return ("🚫 这条操作被载体的「删除禁区」拦下了：%s。\n"
            "原因：删除不可逆 —— 写错了可以改，删了就找不回来；"
            "小焦可以犯错，但不能造成无法挽回的损失。\n"
            "替代建议：%s" % (r, advice or _DEFAULT_ADVICE))


# ================================================================ 核心检查
def _collect_script_files(raw, masked_all):
    """找出这条命令**要执行**的脚本文件（被读取的不算）。

    参数：
      raw        —— 原文（切段用；引号里的路径要靠它才认得全）
      masked_all —— 抹过注释行和引号的那一份（用来判断"这一段是不是真命令"）

    为什么只认"执行位置"：`Select-String -Path a.py` 里的 a.py 是被读的对象，
    当成脚本去读正文会平白拦掉正常查询（误杀）；而 `bash x.sh`、`./x.ps1`、
    `python x.py` 的 x 才是真的会被跑起来的东西。
    为什么整段被抹空就跳过：那段整个在注释行或字符串里（文档里举例的 `bash x.sh`），
    它根本不是命令；不跳过就会去读一个不存在的文件，然后按"读不到"拦掉一篇文档。
    去掉它 → 红线第 6 条"脚本里的删除"就是空话。
    """
    found = []
    # ① PowerShell 调用运算符：& 'x.bat'（在"只抹注释"的文本上找，注释里的举例不算）
    for m in _CALL_OP_RE.finditer(_blank_comments(raw)):
        found.append(m.group("f"))
    for seg, s, e in _split_segments(raw):
        if not masked_all[s:e].strip():
            continue                          # 整段是注释/字符串 → 不是命令
        verb_tok, args = _verb_and_args(seg)
        if verb_tok is None:
            continue
        verb_val, _vs, _ve, verb_fully = verb_tok
        norm = _norm_verb(verb_val)
        if verb_fully:
            continue                          # 命令位置整体是字符串 → 源码里的数据，跳过
        if norm in _READ_VERBS:
            continue                          # 只读动词的参数不执行，别去读它
        if norm in _EXEC_WRAPPERS:
            prev_flag = ""
            for val, _s2, _e2, _f2 in args:
                low = val.strip().lower()
                if low.startswith(("-", "/")):
                    prev_flag = low
                    continue                  # 开关本身不是文件
                if prev_flag in _INLINE_CODE_FLAGS:
                    prev_flag = ""
                    continue                  # -c/-Command 后面那坨是代码，不是路径
                if _is_script(val):
                    found.append(val)
            continue
        if _is_script(verb_val) and _looks_like_path(verb_val):
            found.append(verb_val)            # ② 直接执行：./x.ps1、tools/x.py
    out, seen = [], set()
    for f in found:
        key = f.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(f.strip())
    return out


def _read_script(path):
    """读脚本文本。返回 (内容, 失败原因)；读不到就返回 ("", 原因)。

    为什么要"读不到就返回原因"而不是抛异常：守卫是链路上的公共设施，
    任何异常都可能把一次正常请求打成 500。读不到由上层按"可疑"处理。
    """
    p = _resolve(path)
    try:
        if not os.path.isfile(p):
            return "", "文件不存在或不是普通文件"
        if os.path.getsize(p) > _MAX_SCRIPT_BYTES:
            return "", "文件太大，静态检查放弃"
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except (OSError, ValueError) as e:
        return "", "读取失败（%s）" % type(e).__name__
    if "\x00" in content:
        return "", "看着是二进制文件，静态检查放弃"
    return content, ""


def _check_scripts(raw, masked_all, depth):
    """把命令要执行的脚本正文读出来再扫一遍（递归，带深度上限）。

    为什么必须递归扫正文：`bash x.sh` 本身一个删除词都没有，
    删除藏在 x.sh 里面 —— 不读正文，红线第 6 条等于没写。
    为什么读不到就拦：读不到就没法确认它不删东西。宁可拦错，不可删错。
    """
    if depth >= _MAX_SCRIPT_DEPTH:
        return True, "脚本嵌套层数超过 %d 层，载体放弃静态检查（按可疑拦）" % _MAX_SCRIPT_DEPTH
    for path in _collect_script_files(raw, masked_all):
        content, err = _read_script(path)
        if err:
            return True, ("这条命令要执行脚本「%s」，但载体读不到它的内容（%s），"
                          "没法确认里面有没有删除动作" % (path, err))
        hit, why = _inspect(content, depth + 1, _is_shell_like(path))
        if hit:
            return True, "命令要执行的脚本「%s」正文里有删除动作（%s）" % (path, why)
    return False, ""


def _check_redirect(text):
    """重定向覆盖检查：`命令 > 目标` 且目标**已存在** → 拦。

    为什么这条要落到文件系统上判：`> 新文件` 是"新建"，是允许的；
    `> 老文件` 是把老内容清空，不可逆。同一个写法两种性质，只能看目标在不在。
    为什么变量/通配符目标一律拦：`> $f` 到底覆盖谁载体看不出来，说不清就按可疑。
    去掉它 → `echo x > 重要文件` 这一类"温柔的清空"全部放行（红线第 7、8 条失守）。
    """
    if ">" not in text:
        return ""
    flags = _in_quote_flags(text)
    for m in _REDIRECT_RE.finditer(text):
        gt = m.start() + m.group(0).index(">")
        if gt < len(flags) and flags[gt]:
            continue                          # 引号里的 > 是文本里的字符，不是重定向
        target = m.group("t").strip().strip('"').strip("'").rstrip(",;|&")
        if not target or target.lower() in _DEVNULL:
            continue                          # 往 null 写 = 丢弃输出，不是毁文件
        if any(ch in target for ch in "$%*?"):
            return ("重定向的目标「%s」是变量/通配符，载体无法确认它指向的文件是否已存在"
                    "（可能把老文件清空）" % target)
        if _exists(target):
            return "把输出重定向到已存在的文件「%s」会把原来的内容清空（等于删除）" % target
    return ""


def _in_quote_flags(text):
    """每个字符是否处在引号里（含引号本身）。给重定向检查排除"文本里的 >"用。"""
    flags = [False] * len(text)
    quote = ""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if quote:
            flags[i] = True
            if ch == "\\" and quote == '"' and i + 1 < n:
                flags[i + 1] = True
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            flags[i] = True
        i += 1
    return flags


def _segment_scannable(seg, masked):
    """把一段处理成"该被扫的文本"，并回报这一段是不是执行器语境。

    参数：seg = 原文；masked = 这一段在"抹过注释行和引号"的那一份里的对应片段。
    这是整个判据的核心，逐条对应 2~4 号判据：
      · 命令位置整体是引号串 → 当数据（源码里的字符串），整段抹掉引号内容；
      · 执行器语境（-Command / -c / 脚本 / eval / os.system…）→ 引号**不豁免**，原样扫；
      · 只读动词 → 只留动词本身，参数全抹（`Select-String -Pattern "delete"` 靠这条活命）；
      · 其余 → 抹掉引号内容后扫。
    返回 (该扫的文本, 只抹引号不抹参数的文本, 是否执行器语境)。
    """
    verb_tok, args = _verb_and_args(seg)
    if verb_tok is None:
        return masked, masked, False
    verb_val, _vs, ve, verb_fully = verb_tok
    norm = _norm_verb(verb_val)
    if verb_fully:
        return masked, masked, False          # ① 命令位置是字符串字面量 → 数据
    if norm in _READ_VERBS and not _EXEC_CALL_RE.search(masked):
        return masked[:ve] + " " * (len(seg) - ve), masked, False
    if norm == "git":
        sub = ""
        for val, _s2, _e2, _f2 in args:
            if not val.strip().startswith("-"):
                sub = val.strip().lower()
                break
        if sub in _GIT_READ_SUBS:
            # 只读子命令：抹掉子命令之后的内容，但把 `git <子命令>` 留着
            keep = masked.find(sub)
            cut = (keep + len(sub)) if keep >= 0 else ve
            return masked[:cut] + " " * (len(seg) - cut), masked, False
    if norm in _EXEC_WRAPPERS or _EXEC_CALL_RE.search(masked):
        return seg, seg, True                 # ② 执行器语境：引号不豁免
    return masked, masked, False


def _inspect(text, depth=0, shell_like=True):
    """内部统一入口：给一段文本（命令行 **或** 脚本正文），返回 (是否删除类, 证据)。

    为什么命令行和脚本正文走同一个函数：删除藏在脚本里、藏在拼接里、
    藏在下一层脚本里，判据应该是同一套 —— 两套判据迟早会分叉，然后从分叉处漏。
    shell_like=False 表示"这是代码文件而不是 shell 命令"：此时引号里是数据，
    命令替换只从引号外提取（详见 _SHELL_EXTS 的说明）。
    去掉 depth → 自引用脚本直接 RecursionError。
    """
    if not text or not str(text).strip():
        return False, ""
    raw = str(text).replace("\x00", " ").replace("\t", " ")
    # 先"摘数据"再"判动作"：把注释抹掉，再把引号（含三引号）里的内容抹掉。
    # 两件事必须在**整篇**上做（三引号字符串、跨行结构只有整篇看才对），
    # 所以后面切段时按偏移把抹过的那一份取出来对齐（长度不变，偏移通用）。
    cmasked = _blank_comments(raw)
    masked_all = _mask_quotes(cmasked)
    parts, plain, suspect_hit = [], [], ""
    for seg, s, e in _split_segments(raw):
        scannable, plain_seg, is_exec = _segment_scannable(seg, masked_all[s:e])
        parts.append(scannable)
        # plain = "只抹注释和引号、不抹只读动词参数"的版本。为什么要多留这一份：
        # `echo $null > f` 里，$null 正好落在 echo 的参数区，被只读动词规则抹掉了 ——
        # 抹掉的是"读参数"，但重定向/清空是**动作**，不能跟着一起被抹。
        # 去掉这一份 → 清空式重定向整类漏判（红线第 8 条失守）。
        plain.append(plain_seg)
        # 次级信号**按段升级**：只有"这一段本身就是执行器语境、且这一段里就有可疑动作"
        # 才算数。为什么不整篇扫一遍就升级 —— 文件里只要有一处 `python -c`，
        # 别处某句中文注释里的"删除"就会被连坐（这是实打实误杀过的坑）。
        if is_exec:
            reason, evidence = _scan(scannable, _SUSPECT_C)
            if reason and not suspect_hit:
                suspect_hit = "%s（执行器语境下无法静态确证，按可疑拦；命中片段：%s）" % (reason, evidence)
    scan_text = "\n".join(parts)
    plain_text = "\n".join(plain)

    reason, evidence = _scan(scan_text, _BAN_C)
    if reason:
        return True, "%s（命中片段：%s）" % (reason, evidence)
    # 命令替换（$() / 反引号）里的内容是**真要被跑起来**的，递归按同一条判据再判一次：
    # 它可能落在引号里、也可能落在只读动词参数里，主扫描看不到它。
    # shell 系：引号里的替换也要挖（`echo "$(rm x)"` 在 bash 里真会删东西）；
    # 代码文件：引号里是数据，只挖引号外的（否则代码里一段 `$(…)` 用例就被误杀）。
    if shell_like:
        sub_src = _mask_quotes(cmasked, triples_only=True) if "\n" in cmasked else cmasked
    else:
        sub_src = masked_all
    for sub in _find_substitutions(sub_src):
        hit, why = _inspect(sub, depth + 1, shell_like)
        if hit:
            return True, "命令替换（$() 或反引号）里的动作：%s" % why
    # 清空/重置类规则单独再扫一遍"不抹只读参数"的文本（只扫这几条，不扫全表，
    # 否则 `findstr rm a.txt` 这种正常查询会被误杀）。
    reason, evidence = _scan(plain_text, _CLEAR_C)
    if reason:
        return True, "%s（命中片段：%s）" % (reason, evidence)
    if suspect_hit:
        return True, suspect_hit
    reason, _ev = _scan(scan_text, _SUSPECT_C)
    if reason:
        logger.debug("删除禁区：次级信号命中，但不在执行器语境里，放行：%s", reason)
    why = _check_redirect(cmasked)
    if why:
        return True, why
    return _check_scripts(raw, masked_all, depth)


# ================================================================ 对外 API
def is_delete_command(cmd: str) -> tuple[bool, str]:
    """判断一条命令/脚本内容是不是删除类。返回 (是否删除, 命中的证据片段)。

    出内部异常时**按删除处理**（fail-closed）：守卫自己坏了不等于可以放行删除，
    这是唯一一个"宁可错杀"的地方。异常进日志，不抛给调用方。
    """
    try:
        return _inspect(cmd or "", 0)
    except Exception:      # noqa: silent-ok — 守卫异常不许外抛（会把上层请求打成 500），但必须保守拦
        logger.exception("删除禁区：检测过程内部异常，按删除处理")
        return True, "检测过程出错（已按最保守的方式处理）"


def check_command(cmd: str) -> str:
    """命令入口守卫。返回空串 = 放行；非空 = 给用户看的**可读中文拒绝提示**。

    为什么返回字符串而不是布尔：调用点（工具层）要把话原样说给用户听，
    这里直接把"人话"做好，上层不用各自编一套措辞。

    【为什么这么设计】删除是本项目**唯一的不可逆动作**：
    写错了可以改、跑错了可以重来，删了就找不回来。所以这条约束不能靠"模型自觉"
    （提示词里写了它也可能照删），也不能靠任何**权限开关**（把权限开到最大也必须拦）——
    必须**在载体层、在命令真正执行之前**硬拦，并把"为什么拦、替代方案是什么"讲清楚。
    放在命令入口（而不是各工具内部）是因为：命令拼接、脚本执行、间接删除
    最终都要经过同一条入口，只有守在入口才拦得住"绕一圈再删"。
    （注意：本模块**不许出现任何权限开关的字面量** —— 自测 `test_no_delete.py`
      会扫源码确认这里没有"按权限放行"的分支；上面这句话特意只描述意图、不写那个标识符。）

    【去掉它会怎样】小焦可以删用户的文件。一次误判就是**永久数据丢失**，
    而且它是在"帮用户做事"的名义下发生的 —— 用户连"该不该怪它"都要犹豫。
    """
    if not cmd or not str(cmd).strip():
        return ""
    try:
        hit, why = _inspect(str(cmd), 0)
    except Exception:      # noqa: silent-ok — 同上：异常不外抛，改成人话提示
        logger.exception("删除禁区：命令检查内部异常")
        return _deny("载体的删除检查自己出了错，为了不误删，这条先不放行",
                     "等一会儿再试；或者把要做的操作告诉用户，由用户手动执行。")
    if not hit:
        logger.debug("删除禁区：放行命令 %s", cmd)
        return ""
    logger.warning("删除禁区：拦下命令（%s）｜原文：%s", why, cmd)
    return _deny(why, _advice_for(why))


def check_file_op(op: str, path: str, new_content: str = "", allow_overwrite: bool = False) -> str:
    """文件操作守卫。空串 = 放行，非空 = 可读中文提示。

    op ∈ {"read","write","append","edit","move","rename","delete"}
      · read   —— 一律放行（读不会毁东西）；
      · delete —— 一律拒绝（唯一禁区，没有例外、没有开关）；
      · write  —— 目标已存在且 allow_overwrite=False 时拒绝（红线第 7 条：
                  不覆盖用户的文件，只能新建或追加）；
      · append —— 允许（追加不毁旧内容），但要扫要写进去的内容里有没有删除动作；
      · edit   —— 允许改，但要扫内容（改是可控的，覆盖是不可逆的）；
      · move / rename —— 允许，但目标同名文件已存在时拒绝（那一步会覆盖别人）。
    不认识的动词一律**不放行**（fail-closed）：不知道它要干嘛，就不让它干。
    去掉 fail-closed → 将来有人加一个 "purge"/"wipe" 之类的新动词，守卫会当没看见。
    """
    o = (op or "").strip().lower()
    p = (path or "").strip() or "(未给路径)"
    if o == "read":
        return ""
    if o == "delete":
        return _deny("删除「%s」" % p,
                     "别删。如果它碍事：改成新建一个替代文件、或者改名挪走，"
                     "真要清理请你自己手动处理。")
    if o in ("write", "append", "edit"):
        if o == "write" and not allow_overwrite and _exists(path):
            return _deny("覆盖已经存在的文件「%s」" % p,
                         "换成新建（换个文件名）或用 edit_file 只改其中一段；"
                         "旧文件请你自己手动处理。")
        if new_content:
            hit, why = is_delete_command(new_content)
            if hit:
                return _deny("往「%s」里写入的内容含有删除动作（%s）" % (p, why),
                             "把内容里的删除步骤去掉：只读、只新建、只追加，不删不改旧文件。")
        return ""
    if o in ("move", "rename"):
        if _exists(path) and not allow_overwrite:
            return _deny("移动/改名会覆盖已经存在的同名文件「%s」" % p,
                         "换一个没被占用的目标名；要替换旧文件请你自己手动处理。")
        return ""
    return _deny("不认识的写操作「%s」" % o,
                 "本守卫只认 read/write/append/edit/move/rename/delete；"
                 "不确定的操作一律不放行（这是刻意的保守）。")


def guard_command(cmd: str) -> str:
    """check_command 的语义化别名：在"要执行命令"的地方调它，读起来更像闸门。"""
    return check_command(cmd)


def guard_write(path: str, content: str, mode: str = "w") -> str:
    """写文件守卫。空串 = 放行；非空 = 可读中文提示。

    mode="a" → 按追加处理（允许写已存在的文件，因为追加不毁旧内容）；
    其余（"w"/"x" 等）→ 按新写处理，目标已存在就拒绝。
    两种模式都要扫 content：**要写盘的脚本里带删除**同样算小焦自己删（红线第 6 条），
    因为那一行迟早会被执行。
    注意：本函数**只判断、不落盘** —— 放行与否由调用方决定。
    """
    m = (mode or "w").strip().lower()
    op = "append" if m.startswith("a") else "write"
    return check_file_op(op, path, new_content=content)


def assert_command(cmd: str) -> bool:
    """不放心就在执行前调它：被拦就抛 DeleteBlocked（消息本身就是给用户看的中文提示）。"""
    msg = check_command(cmd)
    if msg:
        raise DeleteBlocked(msg)
    return True


def explain() -> str:
    """给用户/文档看的「为什么不能删」中文说明。"""
    return (
        "小焦可以在自己的世界里做任何事，但「删除」是唯一的禁区。\n"
        "为什么：删除是唯一不可逆的动作 —— 写错了可以改，改错了还能再改，删了就真的没有了。\n"
        "所以载体层的分寸是：允许小焦犯错，但不允许它造成无法挽回的损失。\n"
        "这条约束不写在提示词里，而是写在代码里：不靠模型自觉，模型也没有否决权；\n"
        "它也和权限开关无关 —— 就算把权限开到最大，删除这一条照样拦。\n"
        "被拦的其实是三类不可逆动作：①真删（文件/目录/磁盘）；②清空与重置（内容没了就是没了）；\n"
        "③把删除藏起来（藏在命令拼接里、内联代码里、脚本正文里、重定向里）—— 绕道走不算放行。\n"
        "需要清理旧文件时：换成新建或追加；确实要删，请你自己手动处理 —— 这道闸门只防小焦，不防你。"
    )
