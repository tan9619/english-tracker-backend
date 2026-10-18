"""英文单词统计。

前后端必须用同一套规则，否则用户在前端看到的词数和存进库里的对不上。
规则（来自需求文档）：

- 只统计英文单词
- 常见缩写算一个词：don't / I'm / it's
- 标点符号不单独计数
- 纯数字不计
- 中文、标题、中文备注都不计入

实现上就是"匹配连续的英文字母，允许中间夹一个撇号"。纯数字自然匹配不到，
标点和中文也不会被算进来。

对应前端 utils/text.js 里的实现，改动时两边要一起改。
"""

import re

WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")


def count_words(text):
    """英文单词数。"""
    return len(WORD_RE.findall(text or ''))


def char_count(text):
    """字符数，按 Unicode 码点计（与前端 Array.from(s).length 一致）。"""
    return len(text or '')
