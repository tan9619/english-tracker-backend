"""内置语块：来自《英文聽力高頻句小綠書》。

472 条，按 16 个单元整理，每句一条：
  phrase   英文原句
  meaning  繁體中文释义（保留原书用字，未转简体）
  scenario 单元名（补充小节会带上小节名）
  tag      sentence / phrasal（补充單字表）

数据由 PDF 按列坐标解析而来，改内容直接改 chunk_presets.json。
"""

import json
import os
from functools import lru_cache

PRESET_SOURCE = '英文聽力高頻句小綠書'

_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'data', 'chunk_presets.json')


@lru_cache(maxsize=1)
def load_presets():
    """只读一次；列表本身不要修改。"""
    with open(_DATA, encoding='utf-8') as f:
        return json.load(f)
