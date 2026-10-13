"""时间与日期工具。

容器默认跑 UTC，而客户端和原来的云函数都按北京时间。如果不显式指定时区，
用户在 00:30 打卡会被记成前一天 —— 这类 bug 不会报错，只会让日历莫名其妙
少一天。所以所有"今天"都必须走这里。
"""

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CN = ZoneInfo('Asia/Shanghai')


def now_local():
    """当前北京时间，返回 naive datetime 以便直接写进 MySQL DATETIME。"""
    return datetime.now(CN).replace(tzinfo=None)


def today():
    return now_local().date()


def fmt(d):
    """date/datetime -> 'YYYY-MM-DD'"""
    return d.strftime('%Y-%m-%d')


def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def js_round(x):
    """JS 的 Math.round：四舍五入（.5 向上）。

    Python 内置 round() 是银行家舍入（round(2.5) == 2），跟 JS 不一致。
    SM-2 里的 Math.round(intv*ef) 和 Math.round(ef*100)/100 必须逐位对齐，
    否则复习间隔会跟旧版本算出不同结果。
    """
    return math.floor(x + 0.5) if x >= 0 else -math.floor(-x + 0.5)


def calc_streak(dates):
    """连续打卡天数，1:1 移植自 cloudfunctions/checkin/index.js 的 calcStreak。

    规则：如果今天和昨天都没打卡，连续天数归零（断了）。否则从最近一次打卡
    往前数连续的天数。
    """
    s = sorted(set(dates))
    if not s:
        return 0
    t, y = fmt(today()), fmt(today() - timedelta(days=1))
    if t not in s and y not in s:
        return 0
    c, d = 0, parse_date(s[-1])
    while fmt(d) in s:
        c += 1
        d -= timedelta(days=1)
    return c


def month_range(year, month):
    """返回该月的第一天和最后一天（month 是 1-based）。"""
    first = datetime(year, month, 1).date()
    last = (datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)).date() - timedelta(days=1)
    return first, last
