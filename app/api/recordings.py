"""口语录音（元数据）。音频文件本身由客户端直传对象存储。

file_id 是不透明的 cloud:// 字符串，后端只存不解析 —— 只有删除时才需要
把 key 抠出来交给 COS。
"""

from flask import Blueprint, current_app, g, jsonify, request

from ..dates import today
from ..extensions import db
from ..models import Recording
from ..storage import delete_cloud_files

bp = Blueprint('recordings', __name__)

MAX_LIMIT = 200
CATEGORIES = {'journal', 'mimic', 'free', 'other'}


def _own(rec_id):
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(Recording)
            .filter_by(id=rid, openid=g.openid).one_or_none())


@bp.route('/api/recordings', methods=['POST'])
def save():
    body = request.get_json(silent=True) or {}
    file_id = body.get('fileId')
    if not file_id:
        return jsonify(success=False, message='Missing file')

    category = body.get('category') or 'other'
    if category not in CATEGORIES:
        category = 'other'

    d = today()
    db.session.add(Recording(
        openid=g.openid,
        name=str(body.get('name') or '')[:128],
        file_id=str(file_id)[:512],
        duration=int(body.get('duration') or 0),
        category=category,
        listened=False,
        date=d,
    ))
    db.session.commit()
    return jsonify(success=True, message='Saved')


@bp.route('/api/recordings', methods=['GET'])
def get_list():
    category = request.args.get('category', 'all')
    try:
        limit = min(int(request.args.get('limit', 50)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    q = db.session.query(Recording).filter_by(openid=g.openid)
    if category and category != 'all':
        q = q.filter_by(category=category)

    rows = q.order_by(Recording.created_at.desc()).offset(skip).limit(limit).all()
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/recordings/listened', methods=['POST'])
def mark_listened():
    body = request.get_json(silent=True) or {}
    rec = _own(body.get('id'))
    if rec is None:
        return jsonify(success=False, message='Not found')

    rec.listened = True
    db.session.commit()
    return jsonify(success=True)


@bp.route('/api/recordings/category', methods=['POST'])
def update_category():
    body = request.get_json(silent=True) or {}
    rec = _own(body.get('id'))
    if rec is None:
        return jsonify(success=False, message='Not found')

    category = body.get('category')
    if category not in CATEGORIES:
        return jsonify(success=False, message='Invalid category')

    rec.category = category
    db.session.commit()
    return jsonify(success=True)


@bp.route('/api/recordings/delete', methods=['POST'])
def delete():
    body = request.get_json(silent=True) or {}
    rec = _own(body.get('id'))
    if rec is None:
        return jsonify(success=False, message='Not found')

    file_id = rec.file_id
    db.session.delete(rec)
    db.session.commit()

    # 先删行再删文件：文件删不掉只是留个孤儿，行删不掉会让用户觉得没删成功
    if file_id:
        deleted, failed = delete_cloud_files([file_id])
        if failed:
            current_app.logger.warning('录音文件未删除: %s', failed)

    return jsonify(success=True)
