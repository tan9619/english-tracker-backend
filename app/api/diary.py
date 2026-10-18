"""英语日记。

一天可以写多篇，所以所有按条操作都以 id 为准（不再按日期取唯一一条）。
列表按 date DESC, id DESC 排，同一天多篇时用 id 兜底。
"""

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_

from ..dates import fmt, month_range, parse_date, today
from ..extensions import db
from ..moderation import check_text, failure
from ..models import Diary
from ..words import char_count, count_words

bp = Blueprint('diary', __name__)

MAX_LEN = 10000       # 正文
MAX_TITLE = 128
MAX_NOTE = 5000
MAX_LIMIT = 200


def _own(diary_id):
    """按 id 取且必须属于当前用户。取不到一律当作不存在，不区分"没有"和"别人的"。"""
    try:
        i = int(diary_id)
    except (TypeError, ValueError):
        return None
    return db.session.query(Diary).filter_by(id=i, openid=g.openid).one_or_none()


def _parse(raw):
    try:
        return parse_date(raw)
    except (TypeError, ValueError):
        return None


@bp.route('/api/diary', methods=['POST'])
def create():
    body = request.get_json(silent=True) or {}

    content = str(body.get('content') or '')
    if not content.strip():
        return jsonify(success=False, message='Content required')
    if len(content) > MAX_LEN:
        return jsonify(success=False, message='Content too long')

    title = str(body.get('title') or '').strip()[:MAX_TITLE]
    note = str(body.get('note') or '')[:MAX_NOTE]
    d = _parse(body.get('date')) or today()

    state = check_text(content, g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    row = Diary(
        openid=g.openid,
        title=title,
        date=d,
        content=content,
        note=note,
        word_count=count_words(content),
        char_count=char_count(content),
    )
    db.session.add(row)
    db.session.commit()
    return jsonify(success=True, message='Saved', diary=row.to_dict())


@bp.route('/api/diary', methods=['GET'])
def get_list():
    try:
        limit = min(int(request.args.get('limit', 50)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    q = db.session.query(Diary).filter_by(openid=g.openid)

    raw_date = request.args.get('date')
    if raw_date:
        d = _parse(raw_date)
        if d is None:
            return jsonify(success=False, message='Invalid date')
        q = q.filter(Diary.date == d)

    keyword = (request.args.get('q') or '').strip()
    if keyword:
        like = '%' + keyword + '%'
        # 标题和正文都搜；中文备注不参与搜索
        q = q.filter(or_(Diary.title.like(like), Diary.content.like(like)))

    rows = (q.order_by(Diary.date.desc(), Diary.id.desc())
            .offset(skip).limit(limit).all())
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/diary/detail', methods=['GET'])
def detail():
    row = _own(request.args.get('id'))
    if row is None:
        return jsonify(success=False, message='Not found')
    return jsonify(success=True, diary=row.to_dict())


@bp.route('/api/diary/update', methods=['POST'])
def update():
    body = request.get_json(silent=True) or {}
    row = _own(body.get('id'))
    if row is None:
        return jsonify(success=False, message='Not found')

    if 'content' in body:
        content = str(body.get('content') or '')
        if not content.strip():
            return jsonify(success=False, message='Content required')
        if len(content) > MAX_LEN:
            return jsonify(success=False, message='Content too long')

        state = check_text(content, g.openid)
        if state != 'ok':
            return jsonify(failure(state))

        row.content = content
        row.word_count = count_words(content)
        row.char_count = char_count(content)

    if 'title' in body:
        row.title = str(body.get('title') or '').strip()[:MAX_TITLE]
    if 'note' in body:
        row.note = str(body.get('note') or '')[:MAX_NOTE]
    if 'date' in body:
        d = _parse(body.get('date'))
        if d is None:
            return jsonify(success=False, message='Invalid date')
        row.date = d

    db.session.commit()
    return jsonify(success=True, message='Updated', diary=row.to_dict())


@bp.route('/api/diary/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    row = _own(body.get('id'))
    if row is None:
        return jsonify(success=False, message='Not found')

    db.session.delete(row)
    db.session.commit()
    return jsonify(success=True, message='Deleted')


@bp.route('/api/diary/stats', methods=['GET'])
def stats():
    """日记总数、累计单词数、本月篇数。

    本月按「日记日期」统计（需求指定），不是按创建时间。
    """
    d = today()
    first, last = month_range(d.year, d.month)
    base = db.session.query(Diary).filter_by(openid=g.openid)

    total_count = base.count()
    total_words = db.session.query(func.coalesce(func.sum(Diary.word_count), 0)) \
        .filter(Diary.openid == g.openid).scalar() or 0

    month_rows = (db.session.query(Diary.word_count)
                  .filter(Diary.openid == g.openid,
                          Diary.date >= first, Diary.date <= last).all())
    month_count = len(month_rows)
    monthly_words = sum(r[0] or 0 for r in month_rows)

    return jsonify(success=True, totalCount=total_count,
                   totalWords=int(total_words), monthCount=month_count,
                   monthlyWords=monthly_words)
