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
# 预置语块会往每个新用户里塞 472 条，先关掉，最后单独测
os.environ.setdefault('SEED_PRESETS', '0')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app          # noqa: E402
from app.config import Config       # noqa: E402
from app.dates import calc_streak, fmt, js_round, today  # noqa: E402
from app.presets import PRESET_SOURCE  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('  ok   ' if cond else '  FAIL ') + name + (('  -> ' + str(detail)) if detail and not cond else ''))


def main():
    app = create_app()
    c = app.test_client()

    print('\n--- 纯函数 ---')
    from app.chinese import to_simplified
    check('OpenCC 繁體转简体',
          to_simplified('台灣頭髮') == '台湾头发', to_simplified('台灣頭髮'))
    check('補丁处理 妳/牠/著',
          to_simplified('妳看牠沿著路走') == '你看它沿着路走',
          to_simplified('妳看牠沿著路走'))
    check('著不是助词时不误伤',
          to_simplified('著名著作顯著') == '著名著作显著',
          to_simplified('著名著作顯著'))
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
    # 词数规则：缩写算一个，纯数字和中文不计，连字符拆成两个词
    # "I'm fine, don't worry. 123 你好 hello-world" -> I'm/fine/don't/worry/hello/world = 6
    r = c.post('/api/diary', headers=H, json={
        'title': 'A day', 'date': d,
        'content': "I'm fine, don't worry. 123 你好 hello-world",
        'note': '中文备注',
    }).get_json()
    check('日记新建', r.get('success') is True, r)
    check('词数规则：缩写算1、数字和中文不计',
          r['diary']['word_count'] == 6, r['diary'])
    first_id = r['diary']['_id']

    # 同一天写第二篇 —— 旧模型会覆盖第一篇，新模型应该并存
    r = c.post('/api/diary', headers=H, json={
        'title': '', 'date': d, 'content': 'second entry today',
    }).get_json()
    check('同一天可以写第二篇', r.get('success') is True, r)
    check('标题可以为空', r['diary']['title'] == '', r['diary'])
    second_id = r['diary']['_id']

    r = c.post('/api/diary', headers=H, json={'content': '   '}).get_json()
    check('空正文被拒', r.get('success') is False, r)

    r = c.get('/api/diary?limit=10', headers=H).get_json()
    check('同一天两篇都在', len(r.get('list', [])) == 2, r)
    check('列表按 id 倒序兜底', r['list'][0]['_id'] == second_id, r['list'])

    r = c.get('/api/diary?date=%s' % d, headers=H).get_json()
    check('按日期筛选', len(r.get('list', [])) == 2, r)

    r = c.get('/api/diary?date=2020-01-01', headers=H).get_json()
    check('无记录日期返回空列表', r.get('list') == [], r)

    r = c.get('/api/diary?q=second', headers=H).get_json()
    check('关键词搜正文', len(r.get('list', [])) == 1, r)

    r = c.get('/api/diary?q=A%20day', headers=H).get_json()
    check('关键词搜标题', len(r.get('list', [])) == 1, r)

    r = c.get('/api/diary?q=zzz_no_match', headers=H).get_json()
    check('无匹配返回空列表', r.get('list') == [], r)

    r = c.get('/api/diary/detail?id=%s' % first_id, headers=H).get_json()
    check('详情按 id 取', r.get('success') is True and r['diary']['_id'] == first_id, r)
    check('详情带中文备注', r['diary']['note'] == '中文备注', r['diary'])

    r = c.get('/api/diary/detail?id=999999', headers=H).get_json()
    check('不存在的 id 返回失败', r.get('success') is False, r)

    r = c.post('/api/diary/update', headers=H, json={
        'id': first_id, 'title': 'Updated', 'note': '',
        'content': 'totally different words here',
    }).get_json()
    check('更新成功', r.get('success') is True, r)
    check('更新后词数重算', r['diary']['word_count'] == 4, r['diary'])
    check('更新后标题变化', r['diary']['title'] == 'Updated', r['diary'])

    r = c.get('/api/diary/stats', headers=H).get_json()
    check('统计：篇数=2', r.get('totalCount') == 2, r)
    check('统计：累计词数=7', r.get('totalWords') == 7, r)
    check('统计：本月篇数=2', r.get('monthCount') == 2, r)

    r = c.post('/api/diary/delete', headers=H, json={'id': second_id}).get_json()
    check('删除成功', r.get('success') is True, r)
    r = c.get('/api/diary?date=%s' % d, headers=H).get_json()
    check('删除后列表只剩一篇', len(r.get('list', [])) == 1, r)
    r = c.get('/api/diary/stats', headers=H).get_json()
    check('删除后统计同步', r.get('totalCount') == 1 and r.get('totalWords') == 4, r)

    print('\n--- chunks ---')
    r = c.post('/api/chunks', headers=H, json={
        'phrase': 'give up', 'meaning': '放弃', 'scenario': '日常交流',
        'example_sentence': 'I give up.', 'note': '口语常用',
        'source': 'book', 'tag': 'phrasal',
    }).get_json()
    check('语块新增', r.get('success') is True, r)
    check('新增返回 _id（原实现不返回，前端乐观条目无法寻址）',
          (r.get('chunk') or {}).get('_id') is not None, r)
    check('默认掌握状态 learning',
          (r.get('chunk') or {}).get('mastery_status') == 'learning', r)
    cid = r['chunk']['_id']

    r = c.post('/api/chunks', headers=H, json={'phrase': '', 'meaning': '释义'}).get_json()
    check('空表达被拒', r.get('success') is False, r)
    r = c.post('/api/chunks', headers=H, json={'phrase': 'x', 'meaning': ''}).get_json()
    check('空释义被拒', r.get('success') is False, r)

    r = c.get('/api/chunks', headers=H).get_json()
    check('语块列表', len(r.get('list', [])) == 1, r)
    it = r['list'][0]
    check('新字段已落库', it['scenario'] == '日常交流'
          and it['example_sentence'] == 'I give up.'
          and it['note'] == '口语常用', it)
    check('释义没丢', it['meaning'] == '放弃', it)

    r = c.get('/api/chunks?q=give', headers=H).get_json()
    check('搜英文表达', len(r.get('list', [])) == 1, r)
    r = c.get('/api/chunks?q=放弃', headers=H).get_json()
    check('搜中文释义', len(r.get('list', [])) == 1, r)
    r = c.get('/api/chunks?q=zzz_no_match', headers=H).get_json()
    check('搜不到返回空', r.get('list') == [], r)

    r = c.get('/api/chunks?status=mastered', headers=H).get_json()
    check('按已掌握筛选（当前 0 条）', len(r.get('list', [])) == 0, r)
    r = c.get('/api/chunks?status=learning', headers=H).get_json()
    check('按待复习筛选', len(r.get('list', [])) == 1, r)

    r = c.get('/api/chunks/stats', headers=H).get_json()
    check('语块统计：总数/待复习/已掌握',
          r.get('totalCount') == 1 and r.get('learningCount') == 1
          and r.get('masteredCount') == 0, r)

    r = c.get('/api/chunks/detail?id=%s' % cid, headers=H).get_json()
    check('语块详情', r.get('success') is True and r['chunk']['_id'] == cid, r)
    check('详情带复习卡', r.get('card') is not None, r)

    r = c.post('/api/chunks/update', headers=H, json={
        'id': cid, 'phrase': 'give in', 'meaning': '屈服',
        'mastery_status': 'mastered',   # 客户端不该能直接改
    }).get_json()
    check('语块更新', r.get('success') is True, r)
    check('客户端改不了掌握状态', r['chunk']['mastery_status'] == 'learning', r['chunk'])

    print('\n--- review ---')
    r = c.get('/api/review/overview', headers=H).get_json()
    check('待复习=1', r.get('dueCount') == 1, r)
    check('今日已复习=0', r.get('todayReviewed') == 0, r)

    r = c.get('/api/review/due', headers=H).get_json()
    check('待复习列表含该语块', len(r.get('cards', [])) == 1, r)
    check('卡片 phrase 跟着更新', r['cards'][0]['phrase'] == 'give in', r['cards'][0])

    r = c.post('/api/review/submit', headers=H,
               json={'chunkId': cid, 'result': 'again'}).get_json()
    check('提交「还不熟悉」', r.get('success') is True, r)
    check('仍为 learning', r.get('mastery_status') == 'learning', r)

    r = c.get('/api/review/overview', headers=H).get_json()
    check('今日已复习=1', r.get('todayReviewed') == 1, r)

    c.post('/api/review/submit', headers=H, json={'chunkId': cid, 'result': 'again'})
    r = c.get('/api/review/overview', headers=H).get_json()
    check('同一语块多次复习仍只算 1', r.get('todayReviewed') == 1, r)

    r = c.post('/api/review/submit', headers=H,
               json={'chunkId': cid, 'result': 'mastered'}).get_json()
    check('提交「已掌握」', r.get('success') is True, r)
    check('状态变为 mastered', r.get('mastery_status') == 'mastered', r)

    r = c.get('/api/review/overview', headers=H).get_json()
    check('已掌握后不再待复习', r.get('dueCount') == 0, r)

    r = c.get('/api/chunks/stats', headers=H).get_json()
    check('语块统计：已掌握=1',
          r.get('masteredCount') == 1 and r.get('learningCount') == 0, r)

    r = c.post('/api/review/reset', headers=H, json={'chunkId': cid}).get_json()
    check('重置为待复习', r.get('success') is True
          and r.get('mastery_status') == 'learning', r)
    r = c.get('/api/review/overview', headers=H).get_json()
    check('重置后重新待复习', r.get('dueCount') == 1, r)

    r = c.post('/api/review/submit', headers=H,
               json={'chunkId': cid, 'result': 'whatever'}).get_json()
    check('非法结果被拒', r.get('success') is False, r)

    print('\n--- recordings ---')
    r = c.post('/api/recordings', headers=H,
               json={'title': 'Morning practice',
                     'fileId': 'cloud://env/recordings/a.aac', 'duration': 5,
                     'practiceType': 'free'}).get_json()
    check('录音保存', r.get('success') is True, r)
    rid = r['record']['_id']
    check('保存返回记录 id', bool(rid), r)
    check('标题/练习方式/话题落库',
          r['record']['title'] == 'Morning practice'
          and r['record']['practice_type'] == 'free'
          and r['record']['topic'] == '', r['record'])
    check('录音日期=服务器当天', r['record']['date'] == fmt(today()), r['record'])

    r = c.post('/api/recordings', headers=H, json={}).get_json()
    check('缺标题被拒', r.get('success') is False, r)
    r = c.post('/api/recordings', headers=H,
               json={'title': 'x', 'duration': 5}).get_json()
    check('缺 fileId 被拒', r.get('success') is False, r)
    r = c.post('/api/recordings', headers=H,
               json={'title': 'x', 'fileId': 'cloud://env/x.aac', 'duration': 0}).get_json()
    check('时长为 0 被拒', r.get('success') is False, r)

    r = c.post('/api/recordings', headers=H,
               json={'title': 'My Goals', 'fileId': 'cloud://env/recordings/b.aac',
                     'duration': 7, 'practiceType': 'topic', 'topic': 'My Goals'}).get_json()
    check('话题练习保存', r.get('success') is True
          and r['record']['practice_type'] == 'topic'
          and r['record']['topic'] == 'My Goals', r)
    rid2 = r['record']['_id']

    r = c.get('/api/recordings', headers=H).get_json()
    check('录音列表', len(r.get('list', [])) == 2, r)
    check('按录音时间倒序', r['list'][0]['_id'] == rid2, r)
    check('file_id 原样返回',
          r['list'][1]['file_id'] == 'cloud://env/recordings/a.aac', r)

    r = c.get('/api/recordings/detail?id=%s' % rid, headers=H).get_json()
    check('录音详情', r.get('success') is True
          and r['record']['title'] == 'Morning practice', r)

    r = c.post('/api/recordings/rename', headers=H,
               json={'id': rid, 'title': 'Evening practice'}).get_json()
    check('改标题', r.get('success') is True
          and r['record']['title'] == 'Evening practice'
          and r['record']['updated_at'], r)
    r = c.post('/api/recordings/rename', headers=H,
               json={'id': rid, 'title': '  '}).get_json()
    check('空标题被拒', r.get('success') is False, r)

    r = c.get('/api/recordings/stats', headers=H).get_json()
    check('统计：今日 2 条 12 秒',
          r.get('todayCount') == 2 and r.get('todayDuration') == 12, r)
    check('统计：累计 2 条 12 秒',
          r.get('totalCount') == 2 and r.get('totalDuration') == 12, r)

    r = c.post('/api/recordings/listened', headers=H, json={'id': rid}).get_json()
    check('标记已听', r.get('success') is True, r)

    r = c.post('/api/recordings/delete', headers=H, json={'id': rid2}).get_json()
    check('删除录音', r.get('success') is True, r)
    r = c.get('/api/recordings/stats', headers=H).get_json()
    check('删除后统计同步减少',
          r.get('todayCount') == 1 and r.get('todayDuration') == 5, r)
    r = c.get('/api/recordings', headers=H).get_json()
    check('删除后列表同步', len(r.get('list', [])) == 1, r)

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
    r = c.get('/api/chunks/detail?id=%s' % cid, headers=H2).get_json()
    check('不能看别人的语块详情', r.get('success') is False, r)
    r = c.post('/api/review/submit', headers=H2,
               json={'chunkId': cid, 'result': 'mastered'}).get_json()
    check('不能替别人提交复习', r.get('success') is False, r)
    r = c.post('/api/review/reset', headers=H2, json={'chunkId': cid}).get_json()
    check('不能重置别人的语块', r.get('success') is False, r)
    r = c.get('/api/diary?limit=10', headers=H2).get_json()
    check('看不到别人的日记', r.get('list') == [], r)
    r = c.get('/api/diary/detail?id=%s' % first_id, headers=H2).get_json()
    check('不能看别人的日记详情', r.get('success') is False, r)
    r = c.post('/api/diary/update', headers=H2,
               json={'id': first_id, 'content': 'hacked'}).get_json()
    check('不能改别人的日记', r.get('success') is False, r)
    r = c.post('/api/diary/delete', headers=H2, json={'id': first_id}).get_json()
    check('不能删别人的日记', r.get('success') is False, r)
    r = c.post('/api/recordings/delete', headers=H2, json={'id': rid}).get_json()
    check('不能删别人的录音', r.get('success') is False, r)
    r = c.get('/api/recordings/detail?id=%s' % rid, headers=H2).get_json()
    check('不能看别人的录音详情', r.get('success') is False, r)
    r = c.post('/api/recordings/rename', headers=H2,
               json={'id': rid, 'title': 'hacked'}).get_json()
    check('不能改别人的录音标题', r.get('success') is False, r)
    r = c.get('/api/recordings/stats', headers=H2).get_json()
    check('另一个用户的录音统计为 0',
          r.get('todayCount') == 0 and r.get('totalCount') == 0, r)
    r = c.get('/api/user/profile', headers=H2).get_json()
    check('两个用户是两行', r['userInfo']['_id'] != cid, r)

    print('\n--- 级联删除 ---')
    r = c.post('/api/chunks/delete', headers=H, json={'id': cid}).get_json()
    check('删语块', r.get('success') is True, r)
    r = c.get('/api/review/overview', headers=H).get_json()
    check('关联复习卡一并删除（不再待复习）', r.get('dueCount') == 0, r)
    r = c.get('/api/chunks/stats', headers=H).get_json()
    check('删除后语块统计归零', r.get('totalCount') == 0, r)
    r = c.get('/api/checkin/day?date=%s' % d, headers=H).get_json()
    check('删除语块后当天复习记录也清掉', r['learning']['review'] == 0, r['learning'])

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

    print('\n--- 内容检测的三态判定 ---')
    import app.moderation as mod

    class FakeResp:
        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    original_post = mod.requests.post
    saved_mode = app.config['MODERATION_MODE']
    app.config['MODERATION_MODE'] = 'on'

    def fake(payload):
        mod.requests.post = lambda *a, **k: FakeResp(payload)

    try:
        with app.app_context():
            fake({'errcode': 0, 'result': {'suggest': 'pass'}})
            check('suggest=pass -> ok', mod.check_text('hello', 'o') == mod.OK)

            fake({'errcode': 0, 'result': {'suggest': 'risky'}})
            check('suggest=risky -> risky', mod.check_text('hello', 'o') == mod.RISKY)

            fake({'errcode': 0, 'result': {'suggest': 'review'}})
            check('suggest=review -> 放行', mod.check_text('hello', 'o') == mod.OK)

            # 关键回归：开放接口服务没配好时返回的错误码，不能被当成内容违规
            fake({'errcode': 41001, 'errmsg': 'access_token missing'})
            check('errcode=41001 -> error（不是 risky）',
                  mod.check_text('hello', 'o') == mod.ERROR)

            fake({'errcode': 87014})
            check('errcode=87014 -> risky（v1 兼容）',
                  mod.check_text('hello', 'o') == mod.RISKY)

            fake({})
            check('响应缺 result -> error', mod.check_text('hello', 'o') == mod.ERROR)
    finally:
        mod.requests.post = original_post
        app.config['MODERATION_MODE'] = saved_mode

    print('\n--- 预置语块（小綠書） ---')
    class PresetConfig(Config):
        SEED_PRESETS = True

    app2 = create_app(PresetConfig)
    c2 = app2.test_client()
    HP = {'X-WX-OPENID': 'preset-user-1'}

    r = c2.post('/api/login', headers=HP).get_json()
    check('新用户登录成功', r.get('success') is True and r.get('isNewUser') is True, r)

    r = c2.get('/api/chunks/stats', headers=HP).get_json()
    check('预置语块已写入（472 条）', r.get('totalCount') == 472, r)
    check('预置语块都是待复习',
          r.get('learningCount') == 472 and r.get('masteredCount') == 0, r)

    r = c2.get('/api/review/overview', headers=HP).get_json()
    check('预置复习卡全部到期', r.get('dueCount') == 472, r)

    r = c2.get('/api/checkin/day?date=%s' % fmt(today()), headers=HP).get_json()
    check('预置语块不算用户当天添加的语块',
          r.get('learning', {}).get('chunks') == 0, r.get('learning'))

    r = c2.get('/api/chunks?limit=1', headers=HP).get_json()
    first = (r.get('list') or [{}])[0]
    check('预置语块字段完整',
          bool(first.get('phrase')) and bool(first.get('meaning'))
          and bool(first.get('category_name'))
          and first.get('source') == PRESET_SOURCE
          and first.get('source_type') == 'other'
          and first.get('tag') in ('sentence', 'phrasal'), first)
    check('预置语料已转简体',
          '會' not in first.get('meaning', '')
          and '這' not in first.get('meaning', ''), first.get('meaning'))
    check('预置语料按场景建了自定义分类',
          first.get('category_name') in ('认识新朋友', '价值观传递',
                                         '家庭对话', '餐厅点餐'), first)

    # 再次登录不能重复写
    c2.post('/api/login', headers=HP)
    r = c2.get('/api/chunks/stats', headers=HP).get_json()
    check('重复登录不会重复写入', r.get('totalCount') == 472, r)

    # 用户删掉后不再补回来（直接删库，避免 472 次 HTTP 调用）
    from app.extensions import db as _db
    from app.models import Chunk as _Chunk, ReviewCard as _Card
    with app2.app_context():
        _db.session.query(_Card).filter_by(openid='preset-user-1').delete()
        _db.session.query(_Chunk).filter_by(openid='preset-user-1').delete()
        _db.session.commit()
    c2.post('/api/login', headers=HP)
    r = c2.get('/api/chunks/stats', headers=HP).get_json()
    check('删掉的预置语块不会被重新写入', r.get('totalCount') == 0, r)

    print('\n--- 语块分类 / 来源 / 筛选 ---')
    HC = {'X-WX-OPENID': 'cat-user-1'}
    c.post('/api/login', headers=HC)

    r = c.get('/api/chunk-categories', headers=HC).get_json()
    names = [x['name'] for x in r.get('list', [])]
    check('固定分类已预置',
          names == ['工作', '日常生活', '社交沟通', '学习', '旅行', '其他'], names)
    fixed_id = r['list'][0]['_id']
    check('初始未分类为 0', r.get('uncategorizedCount') == 0, r)

    r = c.post('/api/chunk-categories', headers=HC,
               json={'name': '生活场景'}).get_json()
    check('创建自定义分类', r.get('success') is True, r)
    cat_id = r['category']['_id']

    check('重名被拒',
          c.post('/api/chunk-categories', headers=HC,
                 json={'name': '生活场景'}).get_json().get('success') is False)
    check('与固定分类重名被拒',
          c.post('/api/chunk-categories', headers=HC,
                 json={'name': '工作'}).get_json().get('success') is False)
    check('保留名「未分类」被拒',
          c.post('/api/chunk-categories', headers=HC,
                 json={'name': '未分类'}).get_json().get('success') is False)
    check('超长分类名被拒',
          c.post('/api/chunk-categories', headers=HC,
                 json={'name': 'x' * 33}).get_json().get('success') is False)

    r = c.post('/api/chunks', headers=HC, json={
        'phrase': 'give up', 'meaning': '放棄', 'category_id': cat_id,
        'source': 'CNN 新聞', 'source_type': 'article',
        'source_url': 'https://example.com/a',
    }).get_json()
    chk = r.get('chunk') or {}
    cid1 = chk.get('_id')
    check('写入时中文转简体',
          chk.get('meaning') == '放弃' and chk.get('source') == 'CNN 新闻', chk)
    check('分类已挂上',
          chk.get('category_id') == cat_id and chk.get('category_name') == '生活场景', chk)
    check('来源类型与链接',
          chk.get('source_type') == 'article'
          and chk.get('source_url') == 'https://example.com/a', chk)

    r = c.post('/api/chunks', headers=HC, json={
        'phrase': 'no source', 'meaning': '沒有來源',
    }).get_json()
    chk2 = r.get('chunk') or {}
    cid2 = chk2.get('_id')
    check('新增默认来源=用户手动添加', chk2.get('source_type') == 'manual', chk2)
    check('新增默认未分类', chk2.get('category_id') == '', chk2)

    check('非法分类 ID 被拒',
          c.post('/api/chunks', headers=HC, json={
              'phrase': 'x', 'meaning': 'y', 'category_id': '999999',
          }).get_json().get('success') is False)
    r = c.post('/api/chunks', headers=HC, json={
        'phrase': 'bogus', 'meaning': '非法类型', 'source_type': 'bogus',
    }).get_json()
    check('非法来源类型被忽略', r['chunk']['source_type'] == 'manual', r)

    r = c.get('/api/chunks?category=%s' % cat_id, headers=HC).get_json()
    check('按分类筛选', len(r.get('list', [])) == 1, r)
    r = c.get('/api/chunks?category=uncategorized', headers=HC).get_json()
    check('按未分类筛选', len(r.get('list', [])) == 2, r)
    r = c.get('/api/chunks?sourceType=article', headers=HC).get_json()
    check('按来源类型筛选', len(r.get('list', [])) == 1, r)
    r = c.get('/api/chunks?q=CNN', headers=HC).get_json()
    check('搜索能命中来源', len(r.get('list', [])) == 1, r)
    r = c.get('/api/chunks?category=uncategorized&sourceType=manual&status=learning',
              headers=HC).get_json()
    check('多条件组合', len(r.get('list', [])) == 2, r)
    r = c.get('/api/chunks?category=not-a-number', headers=HC).get_json()
    check('非法分类参数被拒', r.get('success') is False, r)

    r = c.post('/api/chunk-categories/rename', headers=HC,
               json={'id': cat_id, 'name': '生活场景对话'}).get_json()
    check('重命名自定义分类', r.get('success') is True, r)
    r = c.get('/api/chunks/detail?id=%s' % cid1, headers=HC).get_json()
    check('重命名后语块显示新分类名',
          r['chunk']['category_name'] == '生活场景对话', r['chunk'])
    check('固定分类不可改名',
          c.post('/api/chunk-categories/rename', headers=HC,
                 json={'id': fixed_id, 'name': 'X'}).get_json().get('success') is False)

    # 越权：另一个用户看不到、也改不了
    HC2 = {'X-WX-OPENID': 'cat-user-2'}
    c.post('/api/login', headers=HC2)
    r = c.get('/api/chunk-categories', headers=HC2).get_json()
    check('看不到别人的自定义分类',
          [x['name'] for x in r['list']] == names, r)
    check('不能改别人的分类',
          c.post('/api/chunk-categories/rename', headers=HC2,
                 json={'id': cat_id, 'name': 'hacked'}).get_json().get('success') is False)

    r = c.post('/api/chunk-categories/delete', headers=HC,
               json={'id': cat_id}).get_json()
    check('删除分类返回解绑数量', r.get('success') is True and r.get('moved') == 1, r)
    r = c.get('/api/chunks?category=uncategorized', headers=HC).get_json()
    check('删除分类后语块回到未分类', len(r.get('list', [])) == 3, r)
    r = c.get('/api/chunks/stats', headers=HC).get_json()
    check('删除分类不会删语块', r.get('totalCount') == 3, r)
    r = c.get('/api/review/due', headers=HC).get_json()
    check('删除分类不影响复习数据', r.get('dueCount') == 3, r)

    print('\n--- 来源计数 ---')
    r = c.get('/api/chunks/stats', headers=HC).get_json()
    sc = r.get('sourceCounts') or {}
    check('统计返回来源计数',
          sc.get('article') == 1 and sc.get('manual') == 2, sc)

    print('\n--- 每日复习目标 ---')
    r = c.get('/api/review/overview', headers=HC).get_json()
    check('默认目标 10',
          r.get('dailyGoal') == 10 and r.get('todayReviewed') == 0
          and r.get('remaining') == 10 and r.get('completion') == 0
          and r.get('goalReached') is False, r)

    for bad in (0, 101, 'abc', True):
        r = c.patch('/api/user/settings', headers=HC,
                    json={'daily_review_goal': bad}).get_json()
        check('非法目标被拒: %r' % (bad,), r.get('success') is False, r)

    r = c.patch('/api/user/settings', headers=HC,
                json={'daily_review_goal': 20}).get_json()
    check('修改每日目标', r['userInfo']['daily_review_goal'] == 20, r)
    r = c.get('/api/review/overview', headers=HC).get_json()
    check('改目标后剩余/完成率重算',
          r.get('dailyGoal') == 20 and r.get('remaining') == 20
          and r.get('completion') == 0, r)

    for cid in (cid1, cid2):
        c.post('/api/review/submit', headers=HC,
               json={'chunkId': cid, 'result': 'mastered'})
    r = c.get('/api/review/overview', headers=HC).get_json()
    check('今日已复习按不同语块计',
          r.get('todayReviewed') == 2 and r.get('remaining') == 18
          and r.get('completion') == 10, r)

    c.patch('/api/user/settings', headers=HC, json={'daily_review_goal': 1})
    r = c.get('/api/review/overview', headers=HC).get_json()
    check('超过目标时完成率封顶 100',
          r.get('completion') == 100 and r.get('remaining') == 0
          and r.get('goalReached') is True, r)

    print('\n--- 清空数据会删自定义分类、保留固定分类 ---')
    c.post('/api/chunk-categories', headers=HC, json={'name': '临时分类'})
    r = c.post('/api/account/clear', headers=HC).get_json()
    check('清空数据成功', r.get('success') is True, r)
    r = c.get('/api/chunk-categories', headers=HC).get_json()
    check('清空后只剩固定分类',
          [x['name'] for x in r['list']] == names, r)

    print('\n--- 老库迁移：scenario -> 分类 / 简体化 ---')
    import sqlite3
    import tempfile
    old_path = os.path.join(tempfile.mkdtemp(), 'old.db')
    con = sqlite3.connect(old_path)
    con.executescript('''
CREATE TABLE chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  openid VARCHAR(64) NOT NULL,
  phrase VARCHAR(255) NOT NULL,
  meaning VARCHAR(512) NOT NULL DEFAULT '',
  scenario VARCHAR(128) NOT NULL DEFAULT '',
  example_sentence TEXT NULL,
  note TEXT NULL,
  source VARCHAR(255) NOT NULL DEFAULT '',
  tag VARCHAR(16) NOT NULL DEFAULT 'phrasal',
  mastery_status VARCHAR(16) NOT NULL DEFAULT 'learning',
  date DATE NOT NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NULL
);
INSERT INTO chunks (openid,phrase,meaning,scenario,date,created_at)
VALUES ('mig-user','one','放棄','生活場景','2026-01-01','2026-01-01 10:00:00');
INSERT INTO chunks (openid,phrase,meaning,scenario,source,date,created_at)
VALUES ('mig-user','two','臺灣','日常交流','CNN','2026-01-01','2026-01-01 10:00:00');
INSERT INTO chunks (openid,phrase,meaning,scenario,date,created_at)
VALUES ('mig-user','three','頭髮','','2026-01-01','2026-01-01 10:00:00');
''')
    con.commit()
    con.close()

    class MigConfig(Config):
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + old_path
        SEED_PRESETS = False

    from app.extensions import db as _db
    from app.models import (Chunk as _Chunk, ChunkCategory as _Cat,
                            SchemaMigration as _Mig)

    app3 = create_app(MigConfig)
    with app3.app_context():
        rows = {x.phrase: x for x in _db.session.query(_Chunk).all()}
        check('老数据中文转简体',
              rows['one'].meaning == '放弃' and rows['two'].meaning == '台湾'
              and rows['three'].meaning == '头发', {k: v.meaning for k, v in rows.items()})
        cats = {x.name: x for x in _db.session.query(_Cat)
                .filter(_Cat.openid == 'mig-user').all()}
        check('scenario 变成自定义分类',
              set(cats) == {'生活场景', '日常交流'}, list(cats))
        check('语块挂上分类',
              rows['one'].category_id == cats['生活场景'].id
              and rows['two'].category_id == cats['日常交流'].id)
        check('空场景为未分类', rows['three'].category_id is None)
        check('来源类型回填',
              rows['two'].source_type == 'manual'
              and rows['three'].source_type == 'unknown',
              {k: v.source_type for k, v in rows.items()})
        check('迁移标记已写入',
              _db.session.query(_Mig).filter_by(key='chunk_v2').one_or_none() is not None)

    app4 = create_app(MigConfig)
    with app4.app_context():
        n = _db.session.query(_Cat).filter(_Cat.openid == 'mig-user').count()
        check('重复启动不会重复建分类', n == 2, n)

    print('\n' + '=' * 52)
    print('通过 %d / 失败 %d' % (len(PASS), len(FAIL)))
    if FAIL:
        print('失败项：')
        for f in FAIL:
            print('  - ' + f)
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
