"""身份解析。

云托管在请求头注入 X-WX-OPENID，只有走微信私有链路的请求才有 —— 前提是
服务的「公网访问」已经关掉。开着公网访问时这就是个普通请求头，谁都能伪造，
**代码层面补不了**。所以真正的安全边界在控制台，这里只做失败关闭。
"""

from functools import wraps

from flask import current_app, g, jsonify, request

LOOPBACK = {'127.0.0.1', '::1'}


def _dev_openid():
    """本地开发用的假身份。四重条件同时满足才生效。"""
    cfg = current_app.config
    oid = cfg.get('DEV_OPENID')
    if not oid:
        return None
    if cfg.get('IS_PRODUCTION'):
        return None
    if request.remote_addr not in LOOPBACK:
        return None
    # 带 X-WX-SOURCE 说明请求真的经过了微信链路，那就不是本地调试
    if request.headers.get('X-WX-SOURCE'):
        return None
    return oid


def resolve_openid():
    oid = (request.headers.get('X-WX-OPENID') or '').strip()
    return oid or _dev_openid()


def check_openid():
    """蓝图级 before_request 钩子。

    返回非 None 就短路成响应，所以没身份时直接 401，路由函数根本不会执行。
    挂在蓝图上而不是逐个路由加装饰器 —— 这样以后新增路由默认就是受保护的。
    """
    oid = resolve_openid()
    if not oid:
        return jsonify(success=False, code='NO_OPENID',
                       message='Missing WeChat identity'), 401
    g.openid = oid
    return None


def require_openid(fn):
    """单个路由上用的装饰器（蓝图钩子覆盖不到时用）。"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        resp = check_openid()
        if resp is not None:
            return resp
        return fn(*args, **kwargs)
    return wrapper
