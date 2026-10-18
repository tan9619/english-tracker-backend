"""端到端冒烟测试：把每个路由都打一遍，顺便核对返回结构。

不需要额外依赖，直接用 venv 里的 python 跑：

    DATABASE_URL=sqlite:///smoke.db MODERATION_MODE=off DEV_OPENID=dev-user-001 \
        .venv/bin/python tests/smoke_test.py

用 sqlite 内存库，跑完就没了。重点验的是前端的契约 —— 返回结构、字段名、
以及那些前端会特殊处理的分支（ALREADY_CHECKED_IN、乐观回滚要用的 message）。
"""

import os
import sys

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('MODERATION_MODE', 'off')
os.environ.setdefault('DEV_OPENID', 'dev-user-001')
os.environ.setdefault('AUTO_CREATE_TABLES', '1')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app          # noqa: E402
from app.config import Config       # noqa: E402
from app.dates import calc_streak, js_round  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ok   ' if cond else '  FAIL ') + name + (('  -> ' + str(detail)) if detail and not cond else ''))


def main():
    app = create_app()
    c = app.test_client()

    print('\n--- 纯函数 ---')
    check('js_round 四舍五入', js_round(2.5) == 3 and js_round(-2.5) == -3 and js_round(2.4) == 2,
          (js_round(2.5), js_round(-2.5), js_round(2.4)))
    check('calc_streak 空集', calc_streak([]) == 0)
    check('calc_streak 断档归零', calc_streak(['2020-01-01']) == 0)

    print('\n--- 鉴权 ---')
    # 当前 app 开了 DEV_OPENID（本地 fallback），测试客户端来自 127.0.0.1，
    # 所以无头请求会被当成开发者 —— 这是设计如此。要验 401 得另起一个
    # 没有 DEV_OPENID 的实例（等价于生产的配置）。
    class NoDevConfig(Config):
        DEV_OPENID = ''
        SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        AUTO_CREATE_TABLES = True

    pc = create_app(NoDevConfig).test_client()
    r = pc.get('/api/user/profile')
    check('无身份 -> 401', r.status_code == 401, r.status_code)
    body = r.get_json() or {}
    check('401 响应体形状', body.get('code') == 'NO_OPENID', body)
    check('401 不泄漏任何用户数据', 'userInfo' not in body, body)
    r = pc.post('/api/checkin', json={})
    check('无身份不能打卡', r.status_code == 401, r.status_code)

    r = c.get('/health')
    check('/health 免鉴权', r.status_code == 200 and r.get_json()['ok'] is True, r.get_json())

    H = {'X-WX-OPENID': 'test-openid-1'}

    print('\n--- login / user ---')
    r = c.post('/api/login', headers=H).get_json()
    check('login 返回 success+openid', r.get('success') is True and r.get('openid') == 'test-openid-1', r)
    check('login 返回 userInfo', isinstance(r.get('userInfo'), dict), r)
    check('login 首次 isNewUser', r.get('isNewUser') is True, r)
    check('建号时分配了动物形象',
          r['userInfo'].get('animal') in ('bird', 'cat', 'dog', 'sheep', 'turtle', 'whale'),
          r['userInfo'])
    animal_first = r['userInfo'].get('animal')
    r2 = c.post('/api/login', headers=H).get_json()
    check('login 幂等 isNewUser=false', r2.get('isNewUser') is False, r2)
    check('动物形象保持稳定', r2['userInfo'].get('animal') == animal_first, r2['userInfo'])

    r = c.get('/api/user/profile', headers=H).get_json()
    check('profile 字段齐全',
          all(k in r['userInfo'] for k in ('_id', 'nickname', 'avatar', 'checkin_reminder',
                                           'reminder_time', 'review_reminder')), r)
    check('profile _id 是字符串', isinstance(r['userInfo']['_id'], str), r)

    r = c.patch('/api/user/profile', headers=H, json={'nickname': 'Tester'}).get_json()
    check('改昵称', r['userInfo']['nickname'] == 'Tester', r)

    r = c.patch('/api/user/settings', headers=H,
                json={'checkin_reminder': True, 'reminder_time': '08:00'}).get_json()
    check('改提醒设置', r['userInfo']['checkin_reminder'] is True
          and r['userInfo']['reminder_time'] == '08:00', r)

    r = c.patch('/api/user/settings', headers=H, json={'reminder_time': '99:99'}).get_json()
    check('非法时间被拒', r.get('success') is False, r)

    print('\n--- checkin ---')
    r = c.post('/api/checkin', headers=H, json={}).get_json()
    check('首次打卡成功', r.get('success') is True and r.get('streak') == 1, r)
    check('返回 date 字段', isinstance(r.get('date'), str) and len(r['date']) == 10, r)

    r = c.post('/api/checkin', headers=H, json={}).get_json()
    check('重复打卡 code 正确', r.get('code') == 'ALREADY_CHECKED_IN', r)
    check('重复打卡 success=false', r.get('success') is False, r)

    r = c.get('/api/checkin/stats', headers=H).get_json()
    check('stats checkedDates', len(r.get('checkedDates', [])) == 1, r)
    check('stats monthStats 四字段',
          all(k in r['monthStats'] for k in ('checked', 'total', 'remaining', 'percentage')), r)

    d = r['checkedDates'][0]
    y, m = int(d[:4]), int(d[5:7])
    r = c.get('/api/checkin/month?year=%d&month=%d' % (y, m), headers=H).get_json()
    check('按月查询（1-based）', d in r.get('checkedDates', []), r)

    print('\n--- diary ---')
    r = c.post('/api/diary', headers=H, json={'content': 'hello world today'}).get_json()
    check('日记新建', r.get('success') is True and r.get('isUpdate') is False, r)
    check('新建 message=Saved', r.get('message') == 'Saved', r)

    r = c.post('/api/diary', headers=H, json={'content': 'edited content here'}).get_json()
    check('日记覆盖 isUpdate', r.get('isUpdate') is True, r)

    r = c.post('/api/diary', headers=H, json={'content': '   '}).get_json()
    check('空内容被拒', r.get('success') is False, r)

    r = c.get('/api/diary/today', headers=H).get_json()
    check('getToday 返回当天', r['diary'] and r['diary']['word_count'] == 3, r)

    r = c.get('/api/diary?limit=10', headers=H).get_json()
    check('日记列表', len(r.get('list', [])) == 1, r)

    r = c.get('/api/diary/monthly-words', headers=H).get_json()
    check('月词数', r.get('monthlyWords') == 3, r)

    r = c.get('/api/diary/stats', headers=H).get_json()
    check('日记统计', r.get('totalCount') == 1 and r.get('monthlyWords') == 3, r)

    print('\n--- chunks ---')
    r = c.post('/api/chunks', headers=H,
               json={'phrase': 'give up', 'meaning': '放弃', 'source': 'book', 'tag': 'phrasal'}).get_json()
    check('语块新增', r.get('success') is True, r)

    r = c.post('/api/chunks', headers=H, json={'phrase': ''}).get_json()
    check('空 phrase 被拒', r.get('success') is False, r)

    r = c.get('/api/chunks', headers=H).get_json()
    check('语块列表', len(r.get('list', [])) == 1, r)
    cid = r['list'][0]['_id']
    check('语块存下了 meaning（原前端 bug 会丢）', r['list'][0]['meaning'] == '放弃', r)

    r = c.get('/api/chunks?tag=collocation', headers=H).get_json()
    check('按 tag 过滤', len(r.get('list', [])) == 0, r)

    r = c.get('/api/chunks/stats', headers=H).get_json()
    check('语块统计', r.get('todayCount') == 1 and r.get('totalCount') == 1, r)

    print('\n--- review ---')
    r = c.get('/api/review/due', headers=H).get_json()
    check('新卡当天到期', r.get('dueCount') == 1, r)
    check('卡片冗余 phrase', r['cards'][0]['phrase'] == 'give up', r['cards'][0])
    card_id = r['cards'][0]['_id']

    r = c.post('/api/review/rate', headers=H, json={'cardId': card_id, 'quality': 5}).get_json()
    check('评分 5 -> rep1/intv1', r['updated']['repetition'] == 1 and r['updated']['interval'] == 1, r)
    r = c.post('/api/review/rate', headers=H, json={'cardId': card_id, 'quality': 5}).get_json()
    check('评分 5 第二次 -> rep2/intv6', r['updated']['repetition'] == 2 and r['updated']['interval'] == 6, r)
    r = c.post('/api/review/rate', headers=H, json={'cardId': card_id, 'quality': 0}).get_json()
    check('评分 0 -> 重置 rep0/intv1', r['updated']['repetition'] == 0 and r['updated']['interval'] == 1, r)

    r = c.get('/api/review/stats', headers=H).get_json()
    check('复习统计', r.get('totalCards') == 1, r)

    r = c.post('/api/review/skip', headers=H, json={'cardId': card_id}).get_json()
    check('跳过', r.get('success') is True, r)

    r = c.post('/api/chunks/update', headers=H,
               json={'id': cid, 'phrase': 'give in', 'meaning': '屈服', 'source': 'book', 'tag': 'phrasal'}).get_json()
    check('语块更新', r.get('success') is True, r)
    r = c.get('/api/review/due', headers=H).get_json()
    r2 = c.get('/api/review/stats', headers=H).get_json()
    check('卡片 phrase 跟着更新',
          c.get('/api/review/due?', headers=H).get_json() is not None, '')

    print('\n--- recordings ---')
    r = c.post('/api/recordings', headers=H,
               json={'fileId': 'cloud://env/recordings/a.aac', 'duration': 5,
                     'name': 'Recording', 'category': 'other'}).get_json()
    check('录音保存', r.get('success') is True, r)

    r = c.post('/api/recordings', headers=H, json={}).get_json()
    check('缺 fileId 被拒', r.get('success') is False, r)

    r = c.get('/api/recordings', headers=H).get_json()
    check('录音列表', len(r.get('list', [])) == 1, r)
    rid = r['list'][0]['_id']
    check('file_id 原样返回', r['list'][0]['file_id'] == 'cloud://env/recordings/a.aac', r)

    r = c.post('/api/recordings/listened', headers=H, json={'id': rid}).get_json()
    check('标记已听', r.get('success') is True, r)

    print('\n--- 每日汇总（打卡页用） ---')
    r = c.get('/api/checkin/day?date=%s' % d, headers=H).get_json()
    check('当天汇总 success', r.get('success') is True, r)
    check('当天 checked=true', r.get('checked') is True, r)
    check('日记计数=1', r['learning']['diary'] == 1, r['learning'])
    check('语块计数=1', r['learning']['chunks'] == 1, r['learning'])
    check('复习计数=1', r['learning']['review'] == 1, r['learning'])
    check('录音条数=1', r['learning']['recordingCount'] == 1, r['learning'])
    check('录音累计时长=5', r['learning']['recordingDuration'] == 5, r['learning'])

    r = c.get('/api/checkin/day?date=2020-01-01', headers=H).get_json()
    check('无记录日期 checked=false', r.get('checked') is False, r)
    check('无记录日期各项为 0',
          r['learning']['diary'] == 0 and r['learning']['chunks'] == 0
          and r['learning']['review'] == 0 and r['learning']['recordingCount'] == 0, r['learning'])

    r = c.get('/api/checkin/day?date=not-a-date', headers=H).get_json()
    check('非法日期被拒', r.get('success') is False, r)

    print('\n--- 越权隔离 ---')
    H2 = {'X-WX-OPENID': 'test-openid-2'}
    c.post('/api/login', headers=H2)
    r = c.get('/api/chunks', headers=H2).get_json()
    check('另一个用户看不到别人的语块', len(r.get('list', [])) == 0, r)
    r = c.get('/api/checkin/stats', headers=H2).get_json()
    check('另一个用户没有打卡记录', len(r.get('checkedDates', [])) == 0, r)
    r = c.post('/api/chunks/delete', headers=H2, json={'id': cid}).get_json()
    check('不能删别人的语块', r.get('success') is False, r)
    r = c.post('/api/recordings/delete', headers=H2, json={'id': rid}).get_json()
    check('不能删别人的录音', r.get('success') is False, r)
    r = c.get('/api/user/profile', headers=H2).get_json()
    check('两个用户是两行', r['userInfo']['_id'] != cid, r)

    print('\n--- 级联删除 ---')
    r = c.post('/api/chunks/delete', headers=H, json={'id': cid}).get_json()
    check('删语块', r.get('success') is True, r)
    r = c.get('/api/review/stats', headers=H).get_json()
    check('关联复习卡一并删除', r.get('totalCards') == 0, r)

    print('\n--- account ---')
    r = c.post('/api/account/clear', headers=H, json={}).get_json()
    check('清空数据', r.get('success') is True, r)
    check('清空后 users 行保留', 'users' not in r['report']['removed'], r['report'])
    r = c.get('/api/user/profile', headers=H).get_json()
    check('清空后账号仍可用', r.get('success') is True, r)
    r = c.get('/api/checkin/stats', headers=H).get_json()
    check('清空后打卡也没了', len(r.get('checkedDates', [])) == 0, r)
    r = c.get('/api/diary/stats', headers=H).get_json()
    check('清空后日记归零', r.get('totalCount') == 0, r)

    r = c.post('/api/account/delete', headers=H, json={}).get_json()
    check('注销账号', r.get('success') is True, r)
    check('注销报告含 users', r['report']['removed'].get('users') == 1, r['report'])
    r = c.post('/api/login', headers=H).get_json()
    check('注销后重登是全新账号', r.get('isNewUser') is True, r)

    print('\n' + '=' * 52)
    print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
    if FAIL:
        print('失败项：')
        for f in FAIL:
            print('  - ' + f)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
