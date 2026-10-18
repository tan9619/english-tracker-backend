"""繁體 -> 简体。

用 OpenCC 的 t2s 词典做整词转换（頭髮->头发、臺灣->台湾），不是逐字替换。
写入路径统一走这里，保证库里只有简体；英文原样通过。

转换失败（依赖没装、词典异常）时返回原文 —— 宁可存繁體，也不能让用户存不了语块。
"""

from functools import lru_cache


# OpenCC 的 t2s 会保留「妳 / 牠 / 著」——它们在简体里也算合法字，
# 但台湾用语里就是繁體写法。按词补一刀，避免释义里混着繁體。
# 注意只替换「著」作助词的常见词，著名 / 著作 / 显著 保持原样。
_PHRASE_FIXES = (
    ('妳', '你'),
    ('牠', '它'),
    ('沿著', '沿着'), ('接著', '接着'), ('穿著', '穿着'), ('看著', '看着'),
    ('想著', '想着'), ('拿著', '拿着'), ('跟著', '跟着'), ('帶著', '带着'),
    ('睡著', '睡着'), ('等著', '等着'), ('坐著', '坐着'), ('站著', '站着'),
    ('躺著', '躺着'), ('記著', '记着'), ('隨著', '随着'), ('意味著', '意味着'),
    ('忙著', '忙着'), ('試著', '试着'), ('笑著', '笑着'), ('說著', '说着'),
    ('聽著', '听着'), ('執著', '执着'), ('著急', '着急'),
)


@lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC
    return OpenCC('t2s')


def to_simplified(text):
    if not text:
        return text or ''
    try:
        out = _converter().convert(text)
    except Exception:
        out = text
    for trad, simp in _PHRASE_FIXES:
        if trad in out:
            out = out.replace(trad, simp)
    return out
