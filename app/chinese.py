"""繁體 -> 简体。

用 OpenCC 的 t2s 词典做整词转换（頭髮->头发、臺灣->台湾），不是逐字替换。
写入路径统一走这里，保证库里只有简体；英文原样通过。

转换失败（依赖没装、词典异常）时返回原文 —— 宁可存繁體，也不能让用户存不了语块。
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def to_simplified(text):
    if not text:
        return text or ''
    try:
        return _converter().convert(text)
    except Exception:
        return text
