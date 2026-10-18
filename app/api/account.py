"""账号注销 / 清空数据。

顺序很重要，照搬原 cloudfunctions/account/index.js：
  1. 先收集 fileID —— 行删了就再也找不到文件了
  2. 删文件（失败不阻断：注销权优先）
  3. 删业务行
  4. users 行**最后**删，且只有前面都成功了才删

第 4 步是为了避免"账号没了但数据还在"的中间态：出任何错就保留账号，
客户端可以重试。
"""

from flask import Blueprint, current_app, g, jsonify

from ..extensions import db
from ..models import (Checkin, Chunk, Diary, Recording, ReviewCard,
                      ReviewRecord, User)
from ..storage import delete_cloud_files

bp = Blueprint('account', __name__)

BUSINESS_MODELS = [Checkin, Diary, Chunk, ReviewCard, ReviewRecord, Recording]


def _collect_file_ids(openid, action):
    ids = [
        r[0] for r in db.session.query(Recording.file_id)
        .filter_by(openid=openid).all() if r[0]
    ]
    # 只清数据时保留头像 —— 用户的头像不属于"学习数据"
    if action == 'deleteAccount':
        user = db.session.query(User).filter_by(openid=openid).one_or_none()
        if user and user.avatar and user.avatar.startswith('cloud://'):
            ids.append(user.avatar)
    return ids


def _run(action):
    openid = g.openid
    report = {'action': action, 'removed': {}, 'filesDeleted': 0,
              'filesFailed': [], 'errors': []}

    # 1) 收文件 ID
    try:
        file_ids = _collect_file_ids(openid, action)
    except Exception as e:
        current_app.logger.error('collect file ids failed: %s', e)
        file_ids = []
        report['errors'].append('collectFiles: %s' % e)

    # 2) 删文件
    if file_ids:
        deleted, failed = delete_cloud_files(file_ids)
        report['filesDeleted'] = deleted
        report['filesFailed'] = failed

    # 3) 删业务行
    for model in BUSINESS_MODELS:
        try:
            n = (db.session.query(model).filter_by(openid=openid).delete())
            report['removed'][model.__tablename__] = n
        except Exception as e:
            db.session.rollback()
            report['errors'].append('%s: %s' % (model.__tablename__, e))

    if report['errors']:
        db.session.rollback()
        return jsonify(success=False, message='部分数据删除失败，请重试', report=report)

    db.session.commit()

    # 4) users 行最后删
    if action == 'deleteAccount':
        try:
            report['removed']['users'] = (
                db.session.query(User).filter_by(openid=openid).delete())
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error('delete user failed: %s', e)
            return jsonify(success=False, message='账号删除失败，请重试', report=report)

    return jsonify(
        success=True,
        message='账号已注销' if action == 'deleteAccount' else '数据已清空',
        report=report,
    )


@bp.route('/api/account/clear', methods=['POST'])
def clear():
    return _run('clearData')


@bp.route('/api/account/delete', methods=['POST'])
def delete():
    return _run('deleteAccount')
