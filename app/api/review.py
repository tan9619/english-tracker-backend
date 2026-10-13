"""SM-2 间隔重复复习。

算法本身在 app/sm2.py。这里不做评分映射 —— 客户端的 0-5 原样进算法，
0/1/2 判失败、3/4/5 判通过，和现网行为一致。
"""

from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from ..dates import fmt, parse_date, today
from ..extensions import db
from ..models import Chunk, ReviewCard
from ..sm2 import sm2

bp = Blueprint('review', __name__)


def _own_card(card_id):
    try:
        cid = int(card_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(ReviewCard)
            .filter_by(id=cid, openid=g.openid).one_or_none())


@bp.route('/api/review/due', methods=['GET'])
def due():
    d = today()
    rows = (db.session.query(ReviewCard)
            .filter(ReviewCard.openid == g.openid, ReviewCard.next_review <= d)
            .order_by(ReviewCard.next_review.asc()).all())
    return jsonify(success=True, cards=[r.to_dict() for r in rows],
                   dueCount=len(rows))


@bp.route('/api/review/rate', methods=['POST'])
def rate():
    body = request.get_json(silent=True) or {}
    card = _own_card(body.get('cardId'))
    if card is None:
        return jsonify(success=False, message='Card not found')

    try:
        quality = int(body.get('quality') or 0)
    except (TypeError, ValueError):
        quality = 0

    result = sm2(quality, card.repetition, card.interval, float(card.easiness))

    card.repetition = result['repetition']
    card.interval = result['interval']
    card.easiness = result['easiness']
    # sm2() 按 JS 契约返回字符串，存库要转回 date
    card.next_review = parse_date(result['next_review'])
    card.last_review = today()
    db.session.commit()

    return jsonify(success=True, updated=result)


@bp.route('/api/review/skip', methods=['POST'])
def skip():
    body = request.get_json(silent=True) or {}
    card = _own_card(body.get('cardId'))
    if card is None:
        return jsonify(success=False, message='Card not found')

    card.next_review = today() + timedelta(days=1)
    db.session.commit()
    return jsonify(success=True)


@bp.route('/api/review/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    card = _own_card(body.get('cardId'))
    if card is None:
        return jsonify(success=False, message='Card not found')

    # 反向删除：从复习页删卡时，关联的语块也一起删（与原实现一致）
    chunk = (db.session.query(Chunk)
             .filter_by(id=card.chunk_id, openid=g.openid).one_or_none())
    if chunk is not None:
        db.session.delete(chunk)

    db.session.delete(card)
    db.session.commit()
    return jsonify(success=True)


@bp.route('/api/review/stats', methods=['GET'])
def stats():
    d = today()
    due_count = (db.session.query(ReviewCard)
                 .filter(ReviewCard.openid == g.openid, ReviewCard.next_review <= d)
                 .count())
    total = db.session.query(ReviewCard).filter_by(openid=g.openid).count()
    return jsonify(success=True, dueCount=due_count, totalCards=total)
