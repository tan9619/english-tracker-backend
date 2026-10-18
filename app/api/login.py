"""登录 / 用户行建立。

后端其实不需要这个接口来确立身份 —— X-WX-OPENID 请求头已经带了。保留它
是因为客户端仍然需要：① 知道自己是谁（profile 页显示、上传路径要拼），
② 保证用户行存在。原先 app.getOpenid() 读的是 result.openid / result.errMsg，
这里保持同一契约。
"""

from flask import Blueprint, g, jsonify

from ..extensions import db
from ..models import get_or_create_user

bp = Blueprint('login', __name__)


@bp.route('/api/login', methods=['POST'])
def login():
    openid = g.openid

    try:
        # 统一走 get_or_create_user：建号时随机分配动物形象，
        # 老账号（没有 animal）也会在这里补上
        user, is_new = get_or_create_user(openid)
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, openid=openid,
                       errMsg=str(e) or 'Database error')

    return jsonify(success=True, openid=openid, isNewUser=is_new,
                   userInfo=user.to_dict())
