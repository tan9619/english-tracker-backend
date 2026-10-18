"""内置语块数据。

两批：

1. 小綠書 472 条（chunk_presets.json）
   phrase/meaning/scenario/tag；原书是繁體，入库时统一转简体。

2. 雅思 700 条高频短语（ielts_presets.json）
   phrase/meaning/category；category 直接对应 6 个固定分类。
"""

import json
import os
from functools import lru_cache

from .chinese import to_simplified

# JSON 里保留原书繁體；入库时才转简体。
# 这些常量必须和入库值完全一致 —— checkin 用它们排除预置语块。
PRESET_SOURCE_ORIGINAL = '英文聽力高頻句小綠書'
PRESET_SOURCE = to_simplified(PRESET_SOURCE_ORIGINAL)

IELTS_SOURCE = '雅思 700 条高频短语'

# 打卡统计里要排除的预置来源
PRESET_SOURCES = (PRESET_SOURCE, IELTS_SOURCE)

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


@lru_cache(maxsize=1)
def load_presets():
    """小綠書 472 条。只读一次；列表本身不要修改。"""
    with open(os.path.join(_DATA_DIR, 'chunk_presets.json'),
              encoding='utf-8') as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_ielts_presets():
    """雅思 700 条。只读一次；列表本身不要修改。"""
    with open(os.path.join(_DATA_DIR, 'ielts_presets.json'),
              encoding='utf-8') as f:
        return json.load(f)
