"""语块（短语本）。

新增语块时同时建一张复习卡，并把掌握状态初始化成 learning。
掌握状态只存在 chunks 上，复习流程负责更新它。

分类：固定分类全局共享，自定义分类按用户隔离；category_id 为 NULL 即未分类。
所有中文文本在写入时统一转简体（英文原样通过）。
"""

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_

from ..chinese import to_simplified
from ..dates import now_local, today
from ..extensions import db
from ..moderation import check_text, failure
from ..models import (FIXED_CATEGORY_OPENID, MASTERY_LEARNING, MASTERY_MASTERED,
                      SOURCE_MANUAL, SOURCE_TYPES, Chunk, ChunkCategory,
                      ReviewCard, ReviewRecord)

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


def _category_map():
    """{category_id: name}，只含固定分类和本人的自定义分类。"""
    rows = (db.session.query(ChunkCategory)
            .filter(ChunkCategory.openid.in_([FIXED_CATEGORY_OPENID, g.openid]))
            .all())
    return {int(c.id): c.name for c in rows}


def _chunk_dict(chunk, names):
    return chunk.to_dict(
        names.get(int(chunk.category_id)) if chunk.category_id else None)


def _resolve_category(raw):
    """返回 (category_id, error_message)。空值表示未分类。"""
    if raw is None or raw == '' or raw == 'null' or raw == 0 or raw == '0':
        return None, None
    try:
        cid = int(raw)
    except (TypeError, ValueError):
        return None, 'Invalid category'
    cat = (db.session.query(ChunkCategory)
           .filter(ChunkCategory.id == cid,
                   ChunkCategory.openid.in_([FIXED_CATEGORY_OPENID, g.openid]))
           .one_or_none())
    if cat is None:
        return None, 'Invalid category'
    return int(cat.id), None


def _moderation_text(fields):
    return '\n'.join(x for x in fields if x)


def _apply(body, chunk):
    """把请求体里的可编辑字段写到 chunk 上，返回错误响应或 None。"""
    phrase = str(body.get('phrase', chunk.phrase) or '').strip()
    meaning = to_simplified(str(body.get('meaning', chunk.meaning) or '')).strip()
    scenario = to_simplified(str(body.get('scenario', chunk.scenario) or '')).strip()
    example = to_simplified(str(body.get('example_sentence', chunk.example_sentence) or ''))
    note = to_simplified(str(body.get('note', chunk.note) or ''))
    source = to_simplified(str(body.get('source', chunk.source) or '')).strip()
    source_url = str(body.get('source_url', chunk.source_url) or '').strip()
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

    if 'category_id' in body:
        cid, err = _resolve_category(body.get('category_id'))
        if err:
            return jsonify(success=False, message=err)
        chunk.category_id = cid

    if 'source_type' in body:
        st = body.get('source_type')
        # 非法值保持原值，避免旧客户端把类型清空
        if st in SOURCE_TYPES:
            chunk.source_type = st

    state = check_text(
        _moderation_text([phrase, meaning, scenario, example, note, source]), g.openid)
    if state != 'ok':
        return jsonify(failure(state))

    chunk.phrase = phrase
    chunk.meaning = meaning[:512]
    chunk.scenario = scenario[:128]
    chunk.example_sentence = example
    chunk.note = note
    chunk.source = source[:255]
    chunk.source_url = source_url[:512]
    chunk.tag = tag
    return None


@bp.route('/api/chunks', methods=['POST'])
def add():
    body = request.get_json(silent=True) or {}
    d = today()
    chunk = Chunk(openid=g.openid, date=d, mastery_status=MASTERY_LEARNING,
                  phrase='', meaning='', scenario='', source='',
                  source_type=SOURCE_MANUAL, category_id=None, tag='phrasal')

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
    return jsonify(success=True, message='Added',
                   chunk=_chunk_dict(chunk, _category_map()))


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

    category = request.args.get('category', 'all') or 'all'
    if category == 'uncategorized':
        q = q.filter(Chunk.category_id.is_(None))
    elif category != 'all':
        try:
            q = q.filter(Chunk.category_id == int(category))
        except ValueError:
            return jsonify(success=False, message='Invalid category')

    source_type = request.args.get('sourceType', 'all') or 'all'
    if source_type != 'all' and source_type in SOURCE_TYPES:
        q = q.filter(Chunk.source_type == source_type)

    keyword = (request.args.get('q') or '').strip()
    if keyword:
        like = '%' + keyword + '%'
        # 需求：英文表达、中文释义、来源信息都要能搜到
        q = q.filter(or_(Chunk.phrase.like(like), Chunk.meaning.like(like),
                         Chunk.source.like(like)))

    rows = q.order_by(Chunk.created_at.desc(), Chunk.id.desc()) \
        .offset(skip).limit(limit).all()
    names = _category_map()
    return jsonify(success=True, list=[_chunk_dict(r, names) for r in rows])


@bp.route('/api/chunks/detail', methods=['GET'])
def detail():
    chunk = _own_chunk(request.args.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    card = _own_card(chunk.id)
    return jsonify(success=True, chunk=_chunk_dict(chunk, _category_map()),
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
    return jsonify(success=True, message='Updated',
                   chunk=_chunk_dict(chunk, _category_map()))


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


@bp.route('/api/chunks/status', methods=['POST'])
def set_status():
    """手动切换待复习 / 已掌握。

    不写 review_records —— 这不是一次复习，不能算进今日完成数。
    切回待复习时把卡片的 next_review 设为今天，让它重新出现在复习队列里。
    """
    body = request.get_json(silent=True) or {}
    chunk = _own_chunk(body.get('id'))
    if chunk is None:
        return jsonify(success=False, message='Not found')

    status = body.get('status')
    if status not in (MASTERY_LEARNING, MASTERY_MASTERED):
        return jsonify(success=False, message='Invalid status')

    chunk.mastery_status = status
    if status == MASTERY_LEARNING:
        d = today()
        card = _own_card(chunk.id)
        if card is None:
            db.session.add(ReviewCard(
                openid=g.openid, chunk_id=chunk.id,
                phrase=chunk.phrase, meaning=chunk.meaning,
                repetition=0, interval=1, easiness=2.50,
                next_review=d, last_review=None,
            ))
        else:
            card.next_review = d

    db.session.commit()
    return jsonify(success=True, chunk=_chunk_dict(chunk, _category_map()))


@bp.route('/api/chunks/stats', methods=['GET'])
def stats():
    base = db.session.query(Chunk).filter_by(openid=g.openid)
    total = base.count()
    mastered = base.filter(Chunk.mastery_status == MASTERY_MASTERED).count()
    # 来源筛选项要显示「有哪些来源、各多少条」
    rows = (db.session.query(Chunk.source_type, func.count(Chunk.id))
            .filter(Chunk.openid == g.openid)
            .group_by(Chunk.source_type).all())
    source_counts = {(st or SOURCE_UNKNOWN): int(n or 0) for st, n in rows}
    return jsonify(success=True, totalCount=total, masteredCount=mastered,
                   learningCount=total - mastered,
                   sourceCounts=source_counts)
