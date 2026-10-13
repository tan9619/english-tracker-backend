"""用户资料与提醒设置。

替换掉前端原先直连数据库的 4 处调用（pages/settings/index.js:7,8 和
pages/profile/index.js:33,93）—— 那些绕过了云函数，迁移时最容易漏。
"""

import re

from flask import Blueprint, g, jsonify, request

from ..extensions import db
from ..models import get_or_create_user

bp = Blueprint('user', __name__)

TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _current():
    user, _ = get_or_create_user(g.openid)
    return user


@bp.route('/api/user/profile', methods=['GET'])
def get_profile():
    user = _current()
    return jsonify(success=True, openid=g.openid, userInfo=user.to_dict())


@bp.route('/api/user/profile', methods=['PATCH'])
def patch_profile():
    body = request.get_json(silent=True) or {}
    user = _current()

    if 'nickname' in body:
        user.nickname = str(body.get('nickname') or '')[:64]
    if 'avatar' in body:
        user.avatar = str(body.get('avatar') or '')[:1024]

    db.session.commit()
    return jsonify(success=True, userInfo=user.to_dict())


@bp.route('/api/user/settings', methods=['PATCH'])
def patch_settings():
    body = request.get_json(silent=True) or {}
    user = _current()

    if 'checkin_reminder' in body:
        user.checkin_reminder = bool(body['checkin_reminder'])
    if 'review_reminder' in body:
        user.review_reminder = bool(body['review_reminder'])
    if 'reminder_time' in body:
        t = str(body.get('reminder_time') or '')
        if not TIME_RE.match(t):
            return jsonify(success=False, message='Invalid reminder_time')
        user.reminder_time = t

    db.session.commit()
    return jsonify(success=True, userInfo=user.to_dict())
