"""登录 / 用户行建立。

后端其实不需要这个接口来确立身份 —— X-WX-OPENID 请求头已经带了。保留它
是因为客户端仍然需要：① 知道自己是谁（profile 页显示、上传路径要拼），
② 保证用户行存在。原先 app.getOpenid() 读的是 result.openid / result.errMsg，
这里保持同一契约。
"""

from flask import Blueprint, g, jsonify

from ..extensions import db
from ..models import User

bp = Blueprint('login', __name__)


@bp.route('/api/login', methods=['POST'])
def login():
    openid = g.openid

    try:
        user = db.session.query(User).filter_by(openid=openid).one_or_none()
        is_new = user is None
        if is_new:
            user = User(openid=openid)
            db.session.add(user)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify(success=False, openid=openid,
                       errMsg=str(e) or 'Database error')

    return jsonify(success=True, openid=openid, isNewUser=is_new,
                   userInfo=user.to_dict())
