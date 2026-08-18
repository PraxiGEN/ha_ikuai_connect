"""iKuai Connect."""
from __future__ import annotations

import re
from urllib.parse import unquote

def extract_name_from_label(label: str) -> str:
    """从 iKuai 的备注或标签中提取名称. 
    """
    if not label:
        return ""
    
    # URL 解码 (爱快有些接口返回的是编码后的字符串)
    label = unquote(label)
    
    # 使用正则表达式提取括号内的内容
    match = re.search(r'\((.+?)\)', label)
    if match:
        return match.group(1).strip()
    
    return label.strip()


def normalize_mac(mac: str) -> str:
    """统一 MAC 地址格式：小写，横杠/点分隔符统一转为冒号。

    爱快不同型号/版本返回的 mac 可能是 08:9b:4b:01:7e:7c（冒号）
    或 08-9b-4b-01-7e-7c（横杠），统一成冒号小写为后续匹配去歧义。
    """
    if not mac:
        return ""
    return mac.strip().lower().replace("-", ":").replace(".", ":")