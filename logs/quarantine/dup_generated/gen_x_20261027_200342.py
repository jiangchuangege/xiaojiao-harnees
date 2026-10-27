"""数字转换插件 - 示例"""

import re

class NumPlugin:
    """数字转换插件"""
    
    def get_tool_descriptions(self):
        return [
            {
                "name": "cn_num_to_int_v2",
                "description": "中文数字转整数。什么时候用：用户问「三十四」这种纯中文数字；输入数字汉字；输出整数。",
                "parameters": {"type": "object", "properties": {"num": {"type": "string", "description": "中文数字"}}, "required": ["num"]}
            },
            {
                "name": "int_to_cn_num_v2",
                "description": "整数转中文数字。什么时候用：用户问「三十四」这种纯中文数字；输入整数；输出中文数字。",
                "parameters": {"type": "object", "properties": {"num": {"type": "integer", "description": "整数"}}, "required": ["num"]}
            }
        ]
    
    def execute(self, tool_name, params):
        try:
            if tool_name != "cn_num_to_int_v2" and tool_name != "int_to_cn_num_v2":
                return f"数字插件里没有「{tool_name}」这个工具（它只有 cn_num_to_int_v2 和 int_to_cn_num_v2）。"
            
            if tool_name == "cn_num_to_int_v2":
                num_str = params.get("num", "")
                if not num_str:
                    return "请告诉我中文数字"
                num_str = num_str.strip()
                if not num_str:
                    return "请告诉我中文数字"
                # 处理负数
                is_negative = False
                if num_str.startswith('-'):
                    is_negative = True
                    num_str = num_str[1:]
                if not num_str:
                    return "请告诉我中文数字"
                # 处理零
                if num_str == '零':
                    return "0"
                # 处理单位
                unit_map = {
                    '零': '0', '一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9',
                    '十': '10', '百': '100', '千': '1000', '万': '10000', '亿': '100000000', '兆': '1000000000000'
                }
                # 简单处理：直接替换单位
                result = 0
                for unit, value in unit_map.items():
                    if unit in num_str:
                        # 找到单位位置
                        idx = num_str.rfind(unit)
                        prefix = num_str[:idx]
                        suffix = num_str[idx+1:]
                        # 处理前缀
                        if prefix:
                            prefix_num = int(prefix)
                            result += prefix_num * int(value)
                        # 处理后缀
                        if suffix:
                            suffix_num = int(suffix)
                            result += suffix_num * int(value)
                if is_negative:
                    result = -result
                return str(result)
            else:
                num_str = params.get("num", "")
                if not num_str:
                    return "请告诉我整数"
                try:
                    num = int(num_str)
                    if num < 0:
                        return f"负{self._to_cn_num(-num)}"
                    return self._to_cn_num(num)
                except ValueError:
                    return "请输入有效的整数"
                    
        except Exception as e:
            return f"转换出错：{str(e)}"
    
    def _to_cn_num(self, num):
        if num == 0:
            return "零"
        units = ['', '十', '百', '千', '万', '亿', '兆']
        result = []
        while num > 0:
            digit = num % 10
            unit = units[len(result)]
            if digit > 0:
                digit_map = {'0': '', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五', '6': '六', '7': '七', '8': '八', '9': '九'}
                result.append(digit_map[str(digit)] + unit)
            num //= 10
        # 处理负数
        if result and result[-1] == '':
            result.pop()
        return ''.join(reversed(result))

def get_plugin():
    return NumPlugin()