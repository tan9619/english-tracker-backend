"""英语日记。"""

from flask import Blueprint, g, jsonify, request

from ..dates import fmt, month_range, today
from ..extensions import db
from ..moderation import check_text, failure
from ..models import Diary

bp = Blueprint('diary', __name__)

MAX_LEN = 10000
MAX_LIMIT = 200


def _get_by_date(openid, d):
    return db.session.query(Diary).filter_by(openid=openid, date=d).one_or_none()


@bp.route('/api/diary', methods=['POST'])
def save():
    body = request.get_json(silent=True) or {}
    content = body.get('content')
    if not content or not str(content).strip():
        return jsonify(success=False, message='Content required')

    content = str(content)
    if len(content) > MAX_LEN:
        return jsonify(success=False, message='Content too long')

    state = check_text(content, g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    d = today()
    words = len(content.strip().split())
    chars = len(content)

    row = _get_by_date(g.openid, d)
    if row is not None:
        row.content = content
        row.word_count = words
        row.char_count = chars
        db.session.commit()
        return jsonify(success=True, message='Updated', isUpdate=True)

    db.session.add(Diary(openid=g.openid, date=d, content=content,
                         word_count=words, char_count=chars))
    db.session.commit()
    return jsonify(success=True, message='Saved', isUpdate=False)


@bp.route('/api/diary/today', methods=['GET'])
def get_today():
    row = _get_by_date(g.openid, today())
    return jsonify(success=True, diary=row.to_dict() if row else None)


@bp.route('/api/diary', methods=['GET'])
def get_list():
    try:
        limit = min(int(request.args.get('limit', 50)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    rows = (db.session.query(Diary).filter_by(openid=g.openid)
            .order_by(Diary.date.desc()).offset(skip).limit(limit).all())
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/diary/by-date', methods=['GET'])
def get_by_date():
    raw = request.args.get('date')
    try:
        from ..dates import parse_date
        d = parse_date(raw)
    except (TypeError, ValueError):
        return jsonify(success=False, message='Invalid date')

    row = _get_by_date(g.openid, d)
    return jsonify(success=True, diary=row.to_dict() if row else None)


@bp.route('/api/diary/monthly-words', methods=['GET'])
def monthly_words():
    d = today()
    first, last = month_range(d.year, d.month)
    rows = (db.session.query(Diary.word_count)
            .filter(Diary.openid == g.openid, Diary.date >= first, Diary.date <= last)
            .all())
    return jsonify(success=True, monthlyWords=sum(r[0] or 0 for r in rows))


@bp.route('/api/diary/stats', methods=['GET'])
def diary_stats():
    """给 profile 页用的计数接口。

    原先它拉 getList limit:1000 只为了数个数 —— 既浪费流量，又可能撞上
    callContainer 的 1MB 响应上限。
    """
    d = today()
    first, last = month_range(d.year, d.month)

    total = db.session.query(Diary).filter_by(openid=g.openid).count()
    month_rows = (db.session.query(Diary.word_count)
                  .filter(Diary.openid == g.openid, Diary.date >= first, Diary.date <= last)
                  .all())
    return jsonify(success=True, totalCount=total,
                   monthlyWords=sum(r[0] or 0 for r in month_rows))
