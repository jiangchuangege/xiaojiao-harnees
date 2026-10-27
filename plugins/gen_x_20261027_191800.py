"""数字转换插件 - 示例"""
import re

class NumPlugin:
    """数字转换插件"""
    
    def get_tool_descriptions(self):
        return [
            {
                "name": "cn_num_to_int",
                "description": "把中文数字转成整数。什么时候用：用户问「三加五等于几」；输入中文数字；输出对应的整数。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cn_num": {
                            "type": "string",
                            "description": "中文数字字符串"
                        }
                    },
                    "required": ["cn_num"]
                }
            },
            {
                "name": "int_to_cn_num",
                "description": "把整数转成中文数字。什么时候用：用户问「123 读作什么」；输入整数；输出对应的中文数字。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "int_num": {
                            "type": "integer",
                            "description": "整数"
                        }
                    },
                    "required": ["int_num"]
                }
            }
        ]
    
    def execute(self, tool_name, params):
        try:
            if tool_name != "cn_num_to_int":
                return f"数字转换插件里没有「{tool_name}」这个工具（它只有 cn_num_to_int 和 int_to_cn_num）。"
            cn_num = params.get("cn_num", "")
            if not cn_num:
                return "请告诉我你想转换哪个中文数字"
            map_dict = {
                "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
                "十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000, "兆": 1000000000000
            }
            is_neg = False
            if cn_num.startswith("负"):
                is_neg = True
                cn_num = cn_num[1:]
            elif cn_num.startswith("负号"):
                is_neg = True
                cn_num = cn_num[2:]
            elif cn_num.startswith("-"):
                is_neg = True
                cn_num = cn_num[1:]
            if "." in cn_num:
                parts = cn_num.split(".")
                int_part = parts[0]
                frac_part = parts[1]
                int_val = 0
                for i, ch in enumerate(int_part):
                    if ch in map_dict:
                        int_val += map_dict[ch] * (10 ** (len(int_part) - 1 - i))
                frac_val = 0
                for i, ch in enumerate(frac_part):
                    if ch in map_dict:
                        frac_val += map_dict[ch] * (10 ** - (i + 1))
                result = int_val + frac_val
                if is_neg:
                    result = -result
                return str(int(result)) if result == int(result) else str(result)
            else:
                int_val = 0
                for i, ch in enumerate(cn_num):
                    if ch in map_dict:
                        int_val += map_dict[ch] * (10 ** (len(cn_num) - 1 - i))
                if is_neg:
                    int_val = -int_val
                return str(int_val)
        except Exception as e:
            return f"转换失败：{str(e)}"

def get_plugin():
    return NumPlugin()