"""语块（短语本）。

新增语块时同时建一张复习卡，并把掌握状态初始化成 learning。
掌握状态只存在 chunks 上，复习流程负责更新它。
"""

from datetime import timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_

from ..dates import now_local, today
from ..extensions import db
from ..moderation import check_text, failure
from ..models import MASTERY_LEARNING, MASTERY_MASTERED, Chunk, ReviewCard, ReviewRecord

bp = Blueprint('chunks', __name__)

# 内置语块有 472 条，列表一次要能拉全（约 200KB，远低于云托管 1MB 响应上限）
MAX_LIMIT = 500
TAGS = {'phrasal', 'collocation', 'sentence', 'slang'}
STATUSES = {'all', 'learning', 'mastered'}


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


def _moderation_text(fields):
    return '\n'.join(x for x in fields if x)


def _apply(body, chunk):
    """把请求体里的可编辑字段写到 chunk 上，返回错误响应或 None。"""
    phrase = str(body.get('phrase', chunk.phrase) or '').strip()
    meaning = str(body.get('meaning', chunk.meaning) or '').strip()
    scenario = str(body.get('scenario', chunk.scenario) or '').strip()
    example = str(body.get('example_sentence', chunk.example_sentence) or '')
    note = str(body.get('note', chunk.note) or '')
    source = str(body.get('source', chunk.source) or '').strip()
    tag = body.get('tag', chunk.tag) or chunk.tag

    if not phrase:
        return jsonify(success=False, message='Phrase required')
    if len(phrase) > 255:
        return jsonify(success=False, message='Phrase too long')
    if not meaning:
        return jsonify(success=False, message='Meaning required')
    if len(meaning) > 512:
        return jsonify(success=False, message='Meaning too long')
    if tag not in TAGS:
        tag = chunk.tag if chunk.tag in TAGS else 'phrasal'

    state = check_text(
        _moderation_text([phrase, meaning, scenario, example, note, source]), g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    chunk.phrase = phrase
    chunk.meaning = meaning
    chunk.scenario = scenario[:128]
    chunk.example_sentence = example
    chunk.note = note
    chunk.source = source[:255]
    chunk.tag = tag
    return None


@bp.route('/api/chunks', methods=['POST'])
def add():
    body = request.get_json(silent=True) or {}
    d = today()
    chunk = Chunk(openid=g.openid, date=d, mastery_status=MASTERY_LEARNING,
                  phrase='', meaning='', scenario='', source='', tag='phrasal')

    err = _apply(body, chunk)
    if err is not None:
        return err

    db.session.add(chunk)
    db.session.flush()          # 拿到 chunk.id 给下面的卡用

    db.session.add(ReviewCard(
        openid=g.openid, chunk_id=chunk.id, phrase=chunk.phrase, meaning=chunk.meaning,
        repetition=0, interval=1, easiness=2.50,
        next_review=d, last_review=None,
    ))
    db.session.commit()

    # 返回创建结果 —— 前端需要 _id 才能立刻进入详情/编辑
    return jsonify(success=True, message='Added', chunk=chunk.to_dict())


@bp.route('/api/chunks', methods=['GET'])
def get_list():
    status = request.args.get('status', 'all') or 'all'
    if status not in STATUSES:
        status = 'all'

    try:
        limit = min(int(request.args.get('limit', 100)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    q = db.session.query(Chunk).filter_by(openid=g.openid)

    if status != 'all':
        q = q.filter(Chunk.mastery_status == status)

    tag = request.args.get('tag')
    if tag and tag != 'all':
        q = q.filter(Chunk.tag == tag)

    keyword = (request.args.get('q') or '').strip()
    if keyword:
        like = '%' + keyword + '%'
        # 需求：搜索英文表达和中文释义
        q = q.filter(or_(Chunk.phrase.like(like), Chunk.meaning.like(like)))

    rows = q.order_by(Chunk.created_at.desc(), Chunk.id.desc()) \
        .offset(skip).limit(limit).all()
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/chunks/detail', methods=['GET'])
def detail():
    chunk = _own_chunk(request.args.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    card = _own_card(chunk.id)
    return jsonify(success=True, chunk=chunk.to_dict(),
                   card=card.to_dict() if card else None)


@bp.route('/api/chunks/update', methods=['POST'])
def update():
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    err = _apply(body, chunk)
    if err is not None:
        return err

    chunk.updated_at = now_local()

    # 卡片里冗余存了 phrase/meaning，要跟着更新
    (db.session.query(ReviewCard)
     .filter_by(chunk_id=chunk.id, openid=g.openid)
     .update({'phrase': chunk.phrase, 'meaning': chunk.meaning}))

    db.session.commit()
    return jsonify(success=True, message='Updated', chunk=chunk.to_dict())


@bp.route('/api/chunks/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    # 显式清掉关联数据（SQLite 不强制外键，不能只靠 CASCADE）
    db.session.query(ReviewRecord).filter_by(chunk_id=chunk.id, openid=g.openid).delete()
    db.session.query(ReviewCard).filter_by(chunk_id=chunk.id, openid=g.openid).delete()
    db.session.delete(chunk)
    db.session.commit()
    return jsonify(success=True, message='Deleted')


@bp.route('/api/chunks/stats', methods=['GET'])
def stats():
    base = db.session.query(Chunk).filter_by(openid=g.openid)
    total = base.count()
    mastered = base.filter(Chunk.mastery_status == MASTERY_MASTERED).count()
    return jsonify(success=True, totalCount=total, masteredCount=mastered,
                   learningCount=total - mastered)
