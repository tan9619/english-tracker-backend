"""口语录音（元数据）。音频文件本身由客户端直传对象存储。

file_id 是不透明的 cloud:// 字符串，后端只存不解析 —— 只有删除时才需要
把 key 抠出来交给 COS。

统计口径全部基于 date（recording_date）：保存时取服务器当天，第一版不允许
用户修改。暂停期间不计入时长 —— 有效时长由客户端计时器算好后传上来。
"""

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import func

from ..dates import now_local, today
from ..extensions import db
from ..models import Recording
from ..storage import delete_cloud_files

bp = Blueprint('recordings', __name__)

MAX_LIMIT = 200
MAX_TITLE = 128
MAX_TOPIC = 64
PRACTICE_TYPES = {'free', 'topic'}
# 旧版的分类，只为 updateCategory 兼容保留
CATEGORIES = {'journal', 'mimic', 'free', 'other'}


def _own(rec_id):
    try:
        rid = int(rec_id)
    except (TypeError, ValueError):
        return None
    return (db.session.query(Recording)
            .filter_by(id=rid, openid=g.openid).one_or_none())


def _text(value, limit):
    return str(value or '').strip()[:limit]


@bp.route('/api/recordings', methods=['POST'])
def save():
    body = request.get_json(silent=True) or {}

    # title 必填。name 是旧客户端的字段名，当作别名接受。
    title = _text(body.get('title') or body.get('name'), MAX_TITLE)
    if not title:
        return jsonify(success=False, message='Title required')

    file_id = body.get('fileId')
    if not file_id:
        return jsonify(success=False, message='Missing file')

    try:
        duration = int(body.get('duration') or 0)
    except (TypeError, ValueError):
        return jsonify(success=False, message='Invalid duration')
    if duration <= 0:
        return jsonify(success=False, message='Invalid duration')

    practice_type = body.get('practiceType') or 'free'
    if practice_type not in PRACTICE_TYPES:
        practice_type = 'free'
    topic = _text(body.get('topic'), MAX_TOPIC) if practice_type == 'topic' else ''

    rec = Recording(
        openid=g.openid,
        title=title,
        practice_type=practice_type,
        topic=topic,
        file_id=str(file_id)[:512],
        duration=duration,
        listened=False,
        date=today(),
        created_at=now_local(),
    )
    db.session.add(rec)
    db.session.commit()
    return jsonify(success=True, message='Saved', record=rec.to_dict())


@bp.route('/api/recordings', methods=['GET'])
def get_list():
    try:
        limit = min(int(request.args.get('limit', 50)), MAX_LIMIT)
        skip = max(int(request.args.get('skip', 0)), 0)
    except ValueError:
        return jsonify(success=False, message='Invalid limit/skip')

    rows = (db.session.query(Recording)
            .filter_by(openid=g.openid)
            .order_by(Recording.date.desc(), Recording.id.desc())
            .offset(skip).limit(limit).all())
    return jsonify(success=True, list=[r.to_dict() for r in rows])


@bp.route('/api/recordings/detail', methods=['GET'])
def detail():
    rec = _own(request.args.get('id'))
    if rec is None:
        return jsonify(success=False, message='Not found')
    return jsonify(success=True, record=rec.to_dict())


@bp.route('/api/recordings/rename', methods=['POST'])
def rename():
    body = request.get_json(silent=True) or {}
    rec = _own(body.get('id'))
    if rec is None:
        return jsonify(success=False, message='Not found')

    title = _text(body.get('title'), MAX_TITLE)
    if not title:
        return jsonify(success=False, message='Title required')

    rec.title = title
    rec.updated_at = now_local()
    db.session.commit()
    return jsonify(success=True, record=rec.to_dict())


def _aggregate(query):
    count, duration = query.with_entities(
        func.count(Recording.id),
        func.coalesce(func.sum(Recording.duration), 0),
    ).one()
    return int(count or 0), int(duration or 0)


@bp.route('/api/recordings/stats', methods=['GET'])
def stats():
    base = db.session.query(Recording).filter_by(openid=g.openid)
    total_count, total_duration = _aggregate(base)
    today_count, today_duration = _aggregate(
        base.filter(Recording.date == today()))
    return jsonify(
        success=True,
        todayCount=today_count,
        todayDuration=today_duration,
        totalCount=total_count,
        totalDuration=total_duration,
    )


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
    """旧版的分类修改。新界面不再使用，保留是为了已发布的老客户端不报错。"""
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
