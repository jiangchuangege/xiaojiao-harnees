# plugins/rea_tools_zh.py —— REA 229 个工具的中文意图词表（2026-10-17）
#
# 【这是个什么文件】纯数据：把"用户/模型说的中文意图"映射到 REA 工具名里出现的英文词。
#   载体拿它做检索（载体替模型选工具），4B 只需要说"我想干什么"，不需要记住 229 个英文工具名。
#
# 【为什么单独一个文件、而不是塞进 rea.py】
#   ① 它是**词表**，改它不需要看懂接线代码；② 它会长（REA 升级会加工具），
#   放在单独的纯数据文件里，diff 一眼能看出"这次只是补了词"。
#
# 【怎么加词】`中文/口语说法: [英文线索词, ...]`，线索词要能在工具名或说明里**原样出现**才有用
#   （大小写不敏感，见 rea.py 的 _route()）。宁可多写几个同义词，也不要写只在提示词里出现的词。
INTENT_WORDS = {
    # ---- 打开与总体 ----
    "打开": ["open_binary", "open_bundle", "open"],
    "加载": ["open_binary", "open_bundle", "open"],
    "看看": ["overview", "inspect", "inventory", "list"],
    "总览": ["overview", "inventory", "binary_overview"],
    "概况": ["overview", "inventory", "binary_overview"],
    "清单": ["inventory", "list", "catalog", "members"],
    "什么格式": ["open_binary", "format", "inspect_artifact"],
    "识别": ["inspect_artifact", "open_binary", "format"],
    "哈希值": ["sha256", "digest", "integrity", "inspect_artifact", "open_binary"],
    "哈希": ["sha256", "digest", "integrity", "inspect_artifact", "open_binary"],
    "签名": ["inspect_signature", "codesign", "signature", "signing"],
    "签名验证": ["inspect_signature", "verify", "codesign", "signature"],
    "证书": ["inspect_pe_certificates", "certificate", "codesign"],
    "codesign": ["inspect_signature", "codesign"],
    "指纹": ["sha256", "digest", "integrity", "inspect_artifact"],
    "md5": ["sha256", "digest", "integrity", "inspect_artifact"],
    "校验": ["verify", "sha256", "integrity", "signature"],
    "架构": ["architecture", "arch", "slice"],
    "位数": ["architecture", "arch"],
    "大小": ["size", "bytes", "metadata"],

    # ---- 静态分析 ----
    "反编译": ["decompile", "pseudo", "pseudocode"],
    "伪代码": ["pseudocode", "pseudo_code", "decompile"],
    "函数": ["procedure", "function", "proc"],
    "方法": ["procedure", "method", "function"],
    "汇编": ["assembly", "instruction", "disassemble", "disasm"],
    "指令": ["instruction", "assembly"],
    "字符串": ["string", "strings"],
    "交叉引用": ["xref", "reference", "xrefs"],
    "引用": ["xref", "reference"],
    "调用关系": ["call_graph", "callers", "callees", "call"],
    "谁调用": ["callers", "call_graph"],
    "调用了谁": ["callees", "call_graph"],
    "段": ["segment", "section", "block"],
    "节": ["section", "segment"],
    "导入": ["import", "dependency", "dylib"],
    "导出": ["export", "symbol", "names"],
    "符号": ["symbol", "name"],
    "名字": ["name", "symbol"],
    "类型": ["type", "struct", "class"],
    "结构体": ["struct", "type"],
    "类": ["objc", "class", "classes", "type"],
    "地址": ["address", "read_bytes", "resolve"],
    "字节": ["bytes", "read_bytes"],
    "内存": ["memory", "read_bytes", "segment"],
    "搜索": ["search", "find"],
    "找": ["search", "find", "trace"],
    "特征码": ["bytes", "signature", "search_bytes"],
    "特征": ["bytes", "signature", "search_bytes"],
    "追踪": ["trace", "call_graph", "trace_call_path"],
    "路径": ["trace_call_path", "path", "call_graph"],

    # ---- 平台 ----
    "安卓": ["android", "apk", "dex"],
    "apk": ["android", "apk"],
    "苹果": ["apple", "ios", "ipa"],
    "ios": ["ios", "ipa", "mach"],
    "mac": ["mach", "macho", "apple"],
    "swift": ["swift", "demangle"],
    "oc": ["objc", "objective"],
    "类名": ["objc_class", "classes", "objc"],
    "符号还原": ["demangle", "swift", "cxx"],
    "windows": ["pe", "dos", "windows"],
    "exe": ["pe", "dos", "executable"],
    "dll": ["pe", "export", "import"],
    "dotnet": ["managed", "cli", "il"],
    ".net": ["managed", "cli", "pe"],
    "c#": ["managed", "cli"],
    "网页": ["javascript", "web", "electron", "page"],
    "js": ["javascript", "js"],
    "electron": ["electron", "javascript", "asar"],
    "浏览器": ["browser", "electron", "devtools", "page"],
    "wasm": ["wasm", "webassembly"],
    "打包": ["bundle", "archive", "asar", "package"],
    "解包": ["extract", "archive", "bundle", "asar"],
    "压缩包": ["archive", "extract", "zip"],
    "资源": ["asset", "resource", "catalog", "plist"],
    "图片资源": ["asset", "catalog", "icon"],
    "plist": ["plist", "keyed", "archive"],
    "模型文件": ["model", "gguf", "safetensors"],
    "gguf": ["gguf", "model"],
    "权重": ["model", "safetensors", "weight"],
    "显卡代码": ["cuda", "gpu", "code_objects"],

    # ---- 动态与运行时 ----
    "动态": ["frida", "runtime", "instrument"],
    "注入": ["frida", "instrument", "script"],
    "hook": ["frida", "instrument", "hook"],
    "运行时": ["runtime", "frida", "observe"],
    "进程": ["process", "frida", "pid"],
    "附加": ["attach", "frida", "session"],
    "调试": ["debug", "gdb", "lldb", "breakpoint"],
    "断点": ["breakpoint", "debug", "gdb"],
    "观察": ["observe", "capture", "runtime"],
    "抓包": ["observe", "capture", "runtime"],
    "界面": ["ui", "interface", "click", "scenario"],

    # ---- 证据与报表 ----
    "证据": ["evidence", "report", "export"],
    "报告": ["report", "evidence", "export"],
    "导出报告": ["evidence", "export", "report"],
    "比对": ["compare_application_versions", "compare_source_to_bundle", "compare"],
    "对比": ["compare_application_versions", "compare_source_to_bundle", "compare"],
    "差异": ["compare_application_versions", "compare_source_to_bundle", "compare"],
    "验证": ["verify", "check"],
    "还原": ["reconstruct", "reconstruction", "decompile"],

    # ---- 设置（REA 自己的运行时参数） ----
    "设置": ["settings", "option", "limit"],
    "上限": ["settings", "limit", "size"],
    "超时": ["settings", "deadline", "timeout"],
    "诊断": ["doctor", "diagnostic", "settings"],
}

# 目标里出现这些扩展名时，用来判断"要打开的是什么"，好挑对 open_* 工具
EXT_HINTS = {
    ".exe": ["open_binary", "pe"], ".dll": ["open_binary", "pe"], ".sys": ["open_binary", "pe"],
    ".so": ["open_binary", "elf"], ".elf": ["open_binary", "elf"], ".bin": ["open_binary"],
    ".apk": ["open_binary", "android"], ".aab": ["open_binary", "android"], ".dex": ["open_binary", "dex"],
    ".ipa": ["open_binary", "apple"], ".app": ["open_bundle", "apple"],
    ".js": ["open_binary", "javascript"], ".mjs": ["open_binary", "javascript"],
    ".asar": ["open_binary", "asar"], ".zip": ["open_binary", "archive"],
    ".plist": ["open_binary", "plist"], ".gguf": ["open_binary", "model"],
    ".safetensors": ["open_binary", "model"], ".wasm": ["open_binary", "wasm"],
}


# 【平台家族】目标扩展名 → 家族；工具名里出现某个家族的线索词，说明它只对那一类目标有效。
# 路由时"家族对不上"要**明确扣分**（实测踩过：给 .exe 找签名，结果派到 inspect_apk_signature）。
EXT_FAMILY = {
    ".exe": "pe", ".dll": "pe", ".sys": "pe", ".ocx": "pe", ".cpl": "pe",
    ".so": "linux", ".elf": "linux", ".ko": "linux",
    ".dylib": "apple", ".app": "apple", ".ipa": "apple", ".macho": "apple",
    ".apk": "android", ".aab": "android", ".dex": "android",
    ".js": "web", ".mjs": "web", ".cjs": "web", ".asar": "web", ".html": "web",
    ".gguf": "model", ".safetensors": "model", ".onnx": "model",
    ".pyc": "python", ".py": "python", ".wasm": "wasm",
}

FAMILY_WORDS = {
    "pe": ("pe", "dos", "windows", "certificates", "managed", "cli_", "dotnet", "nativeaot"),
    "apple": ("macho", "mach", "objc", "swift", "apple", "ipa", "dyld", "plist", "bundle", "codesign"),
    "android": ("android", "apk", "dex", "dart"),
    "web": ("web", "javascript", "electron", "asar", "page", "dom", "screenshot", "capture"),
    "model": ("model", "gguf", "safetensors"),
    "linux": ("elf", "so_", "linux"),
    "python": ("pyc", "python"),
    "wasm": ("wasm",),
}
