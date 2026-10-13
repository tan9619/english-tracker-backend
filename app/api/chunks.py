"""语块（短语本）。新增语块时同时建一张复习卡。"""

from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from ..dates import fmt, today
from ..extensions import db
from ..moderation import check_text, failure
from ..models import Chunk, ReviewCard

bp = Blueprint('chunks', __name__)

MAX_LIMIT = 200
TAGS = {'phrasal', 'collocation', 'sentence', 'slang'}


def _own_chunk(chunk_id):
    try:
        cid = int(chunk_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(Chunk)
            .filter_by(id=cid, openid=g.openid).one_or_none())


@bp.route('/api/chunks', methods=['POST'])
def add():
    body = request.get_json(silent=True) or {}
    phrase = str(body.get('phrase') or '').strip()
    meaning = str(body.get('meaning') or '').strip()
    source = str(body.get('source') or '').strip()
    tag = body.get('tag') or 'phrasal'

    if not phrase:
        return jsonify(success=False, message='Phrase required')
    if len(phrase) > 255:
        return jsonify(success=False, message='Phrase too long')
    if tag not in TAGS:
        tag = 'phrasal'

    # 检测 phrase + meaning + source 三段 —— source 原先漏检却会被展示
    state = check_text('\n'.join(x for x in (phrase, meaning, source) if x), g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    d = today()
    chunk = Chunk(openid=g.openid, phrase=phrase, meaning=meaning[:512],
                  source=source[:255], tag=tag, date=d)
    db.session.add(chunk)
    db.session.flush()          # 拿到 chunk.id 给下面的卡用

    db.session.add(ReviewCard(
        openid=g.openid, chunk_id=chunk.id, phrase=phrase, meaning=meaning[:512],
        repetition=0, interval=1, easiness=2.50,
        next_review=d,        # 当天即到期，和原实现一致
        last_review=None,
    ))
    db.session.commit()
    return jsonify(success=True, message='Added')


@bp.route('/api/chunks', methods=['GET'])
def get_list():
    tag = request.args.get('tag', 'all')
    try:
        limit = min(int(request.args.get('limit', 50)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    q = db.session.query(Chunk).filter_by(openid=g.openid)
    if tag and tag != 'all':
        q = q.filter_by(tag=tag)

    rows = q.order_by(Chunk.created_at.desc()).offset(skip).limit(limit).all()
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/chunks/stats', methods=['GET'])
def stats():
    d = today()
    week_start = d - timedelta(days=(d.weekday() + 1) % 7)   # 周日为一周开始，同 JS

    base = db.session.query(Chunk).filter_by(openid=g.openid)
    today_count = base.filter(Chunk.date == d).count()
    week_count = base.filter(Chunk.date >= week_start).count()
    total_count = base.count()

    return jsonify(success=True, todayCount=today_count,
                   weekCount=week_count, totalCount=total_count)


@bp.route('/api/chunks/update', methods=['POST'])
def update():
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    phrase = str(body.get('phrase') or '').strip()
    meaning = str(body.get('meaning') or '').strip()
    source = str(body.get('source') or '').strip()
    tag = body.get('tag') or chunk.tag

    if not phrase:
        return jsonify(success=False, message='Phrase required')
    if len(phrase) > 255:
        return jsonify(success=False, message='Phrase too long')
    if tag not in TAGS:
        tag = chunk.tag

    state = check_text('\n'.join(x for x in (phrase, meaning, source) if x), g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    chunk.phrase = phrase
    chunk.meaning = meaning[:512]
    chunk.source = source[:255]
    chunk.tag = tag

    # 卡片里冗余存了 phrase/meaning，要跟着更新
    (db.session.query(ReviewCard)
     .filter_by(chunk_id=chunk.id, openid=g.openid)
     .update({'phrase': phrase, 'meaning': meaning[:512]}))

    db.session.commit()
    return jsonify(success=True, message='Updated')


@bp.route('/api/chunks/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    db.session.query(ReviewCard).filter_by(chunk_id=chunk.id, openid=g.openid).delete()
    db.session.delete(chunk)
    db.session.commit()
    return jsonify(success=True, message='Deleted')
