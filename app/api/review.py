"""复习。

UI 按需求只给两个结果：「还不熟悉」和「已掌握」。后台仍然用 SM-2 调度，
把两个结果分别映射到评分 2 和 5 —— 保留间隔重复能力，同时让交互符合需求。

掌握状态只写在 chunks 上；每次提交额外落一条 review_records 流水。
"""

from datetime import timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from ..dates import parse_date, today
from ..extensions import db
from ..models import (MASTERY_LEARNING, MASTERY_MASTERED, Chunk, ReviewCard,
                      ReviewRecord)
from ..sm2 import sm2

bp = Blueprint('review', __name__)

RESULT_AGAIN = 'again'
RESULT_MASTERED = 'mastered'
QUALITY = {RESULT_AGAIN: 2, RESULT_MASTERED: 5}


def _own_chunk(chunk_id):
    try:
        cid = int(chunk_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(Chunk)
            .filter_by(id=cid, openid=g.openid).one_or_none())


def _own_card(chunk_id):
    return (db.session.query(ReviewCard)
            .filter_by(chunk_id=chunk_id, openid=g.openid).one_or_none())


def _due_query(d):
    """待复习 = 掌握状态为 learning 且已到期的卡。

    掌握状态在 chunks 上，所以要 join；不能只查 review_cards。
    """
    return (db.session.query(ReviewCard)
            .join(Chunk, ReviewCard.chunk_id == Chunk.id)
            .filter(ReviewCard.openid == g.openid,
                    Chunk.openid == g.openid,
                    Chunk.mastery_status == MASTERY_LEARNING,
                    ReviewCard.next_review <= d))


def _today_reviewed(d):
    """当天复习过的**不同语块**数量（同一语块多次只算一个）。"""
    return (db.session.query(func.count(func.distinct(ReviewRecord.chunk_id)))
            .filter(ReviewRecord.openid == g.openid,
                    ReviewRecord.review_date == d).scalar() or 0)


@bp.route('/api/review/overview', methods=['GET'])
def overview():
    d = today()
    return jsonify(success=True,
                   dueCount=_due_query(d).count(),
                   todayReviewed=_today_reviewed(d))


@bp.route('/api/review/due', methods=['GET'])
def due():
    d = today()
    rows = _due_query(d).order_by(ReviewCard.next_review.asc()).all()

    cards = []
    for r in rows:
        item = r.to_dict()
        item['mastery_status'] = MASTERY_LEARNING
        cards.append(item)

    return jsonify(success=True, cards=cards, dueCount=len(cards))


@bp.route('/api/review/submit', methods=['POST'])
def submit():
    body = request.get_json(silent=True) or {}
    result = body.get('result')

    if result not in QUALITY:
        return jsonify(success=False, message='Invalid result')

    chunk = _own_chunk(body.get('chunkId'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    card = _own_card(chunk.id)
    if card is None:
        return jsonify(success=False, message='Card not found')

    quality = QUALITY[result]
    updated = sm2(quality, card.repetition, card.interval, float(card.easiness))

    card.repetition = updated['repetition']
    card.interval = updated['interval']
    card.easiness = updated['easiness']
    card.next_review = parse_date(updated['next_review'])
    card.last_review = today()

    chunk.mastery_status = MASTERY_MASTERED if result == RESULT_MASTERED else MASTERY_LEARNING

    # 每次提交都留一条流水，不覆盖历史
    db.session.add(ReviewRecord(
        openid=g.openid, chunk_id=chunk.id, review_date=today(), result=result))

    db.session.commit()

    return jsonify(success=True, chunk_id=str(chunk.id),
                   mastery_status=chunk.mastery_status, updated=updated)


@bp.route('/api/review/reset', methods=['POST'])
def reset():
    """把语块重新放回待复习。用于「已掌握」语块想再复习一次。"""
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('chunkId'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    d = today()
    chunk.mastery_status = MASTERY_LEARNING

    card = _own_card(chunk.id)
    if card is None:
        # 理论上不会发生，但补一张总比报错好
        db.session.add(ReviewCard(
            openid=g.openid, chunk_id=chunk.id, phrase=chunk.phrase,
            meaning=chunk.meaning, repetition=0, interval=1, easiness=2.50,
            next_review=d, last_review=None))
    else:
        card.next_review = d

    db.session.commit()
    return jsonify(success=True, mastery_status=MASTERY_LEARNING)


@bp.route('/api/review/stats', methods=['GET'])
def stats():
    d = today()
    total = db.session.query(Chunk).filter_by(openid=g.openid).count()
    return jsonify(success=True,
                   dueCount=_due_query(d).count(),
                   todayReviewed=_today_reviewed(d),
                   totalChunks=total)
