"""语块分类。

固定分类的 openid 是空串，全局一份、所有人可见、不可改删；
自定义分类按用户隔离。「未分类」不建行，chunks.category_id 为 NULL 即是。
"""

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from ..chinese import to_simplified
from ..dates import now_local
from ..extensions import db
from ..models import (FIXED_CATEGORY_OPENID, KIND_CUSTOM, UNCATEGORIZED_NAME,
                      Chunk, ChunkCategory)

bp = Blueprint('chunk_categories', __name__)

MAX_NAME = 32
MAX_CUSTOM = 100
RESERVED_NAMES = {UNCATEGORIZED_NAME, '全部'}


def _clean_name(raw):
    """返回清洗后的名字；非法返回 None。"""
    name = to_simplified(str(raw or '')).strip()
    if not name or len(name) > MAX_NAME or name in RESERVED_NAMES:
        return None
    return name


def _visible():
    return (db.session.query(ChunkCategory)
            .filter(ChunkCategory.openid.in_([FIXED_CATEGORY_OPENID, g.openid]))
            .order_by(ChunkCategory.kind.desc(),      # fixed 排在 custom 前
                      ChunkCategory.sort_order.asc(),
                      ChunkCategory.id.asc())
            .all())


def _counts():
    """返回 ({category_id: n}, 未分类条数)。"""
    rows = (db.session.query(Chunk.category_id, func.count(Chunk.id))
            .filter(Chunk.openid == g.openid)
            .group_by(Chunk.category_id).all())
    by_cat, uncategorized = {}, 0
    for cid, n in rows:
        if cid is None:
            uncategorized = int(n or 0)
        else:
            by_cat[int(cid)] = int(n or 0)
    return by_cat, uncategorized


def _name_taken(name, exclude_id=None):
    q = (db.session.query(ChunkCategory)
         .filter(ChunkCategory.name == name,
                 ChunkCategory.openid.in_([FIXED_CATEGORY_OPENID, g.openid])))
    if exclude_id is not None:
        q = q.filter(ChunkCategory.id != exclude_id)
    return q.first() is not None


def _own_custom(cat_id):
    """只能操作自己的自定义分类。固定分类和别人的分类一律 None。"""
    try:
        cid = int(cat_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(ChunkCategory)
            .filter_by(id=cid, openid=g.openid, kind=KIND_CUSTOM)
            .one_or_none())


@bp.route('/api/chunk-categories', methods=['GET'])
def get_list():
    counts, uncategorized = _counts()
    return jsonify(
        success=True,
        list=[c.to_dict(counts.get(int(c.id), 0)) for c in _visible()],
        uncategorizedCount=uncategorized,
    )


@bp.route('/api/chunk-categories', methods=['POST'])
def add():
    body = request.get_json(silent=True) or {}
    name = _clean_name(body.get('name'))
    if name is None:
        return jsonify(success=False, message='Invalid name')
    if _name_taken(name):
        return jsonify(success=False, message='分类名称已存在')

    used = (db.session.query(ChunkCategory)
            .filter_by(openid=g.openid, kind=KIND_CUSTOM).count())
    if used >= MAX_CUSTOM:
        return jsonify(success=False, message='自定义分类数量已达上限')

    cat = ChunkCategory(openid=g.openid, name=name, kind=KIND_CUSTOM,
                        created_at=now_local())
    db.session.add(cat)
    db.session.commit()
    return jsonify(success=True, category=cat.to_dict(0))


@bp.route('/api/chunk-categories/rename', methods=['POST'])
def rename():
    body = request.get_json(silent=True) or {}
    cat = _own_custom(body.get('id'))
    if cat is None:
        return jsonify(success=False, message='Not found')

    name = _clean_name(body.get('name'))
    if name is None:
        return jsonify(success=False, message='Invalid name')
    if _name_taken(name, exclude_id=cat.id):
        return jsonify(success=False, message='分类名称已存在')

    cat.name = name
    cat.updated_at = now_local()
    db.session.commit()
    return jsonify(success=True, category=cat.to_dict())


@bp.route('/api/chunk-categories/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    cat = _own_custom(body.get('id'))
    if cat is None:
        return jsonify(success=False, message='Not found')

    # 先解绑再删分类：语块和复习记录都保留，只是回到「未分类」
    moved = (db.session.query(Chunk)
             .filter_by(openid=g.openid, category_id=cat.id)
             .update({'category_id': None}, synchronize_session=False))
    db.session.delete(cat)
    db.session.commit()
    return jsonify(success=True, moved=int(moved or 0))
