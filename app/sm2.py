"""SM-2 间隔重复算法，1:1 移植自 cloudfunctions/review/index.js。

注意：不要在这里加 quality 映射。当前线上版本是把客户端的 0-5 评分直接
喂给 SM-2（cloudfunctions/review/index.js 里就一句 parseInt(quality)||0），
0/1/2 判为失败、3/4/5 判为通过。之前那个 {0:0,1:2,2:4,3:5} 的映射属于一次
被撤销的改写，引入它会让复习间隔跟现网不一致。
"""

from datetime import timedelta

from .dates import fmt, js_round, today


def sm2(quality, repetition, interval, easiness):
    q = quality

    if q < 3:
        repetition = 0
        interval = 1
    else:
        repetition += 1
        if repetition == 1:
            interval = 1
        elif repetition == 2:
            interval = 6
        else:
            # 用旧的 easiness，和 JS 版一致
            interval = js_round(interval * easiness)

    easiness = easiness + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if easiness < 1.3:
        easiness = 1.3

    return {
        'repetition': repetition,
        'interval': interval,
        'easiness': js_round(easiness * 100) / 100.0,
        'next_review': fmt(today() + timedelta(days=interval)),
    }
