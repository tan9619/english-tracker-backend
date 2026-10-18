import os

from flask import Flask, jsonify, request
from sqlalchemy import text

from .auth import check_openid
from .config import Config, validate
from .extensions import db

# 唯一不需要身份的路由。其余一律默认受保护 —— 这样以后新增路由不会忘记加鉴权。
PUBLIC_ENDPOINTS = {'health', 'static'}


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    validate(app.config)          # 危险配置直接拒绝启动

    db.init_app(app)

    from .api import BLUEPRINTS
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    # 鉴权挂在 app 级别而不是蓝图上：蓝图是模块级单例，只能注册一次，
    # 挂 before_request 会导致第二个 app 实例（比如测试里）注册失败。
    @app.before_request
    def _require_identity():
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        return check_openid()

    # 启动时把配置问题喊出来，不要等到第一个请求才莫名其妙地失败
    if not (os.environ.get('DATABASE_URL') or os.environ.get('MYSQL_ADDRESS')):
        app.logger.error(
            'MYSQL_ADDRESS / DATABASE_URL 都没有设置 —— 数据库会退化成 localhost 并连接失败。'
            '云托管的环境变量要在「服务设置」里配置，改完必须重新部署才生效。')

    @app.route('/health')
    def health():
        ok = True
        err = ''
        try:
            db.session.execute(text('SELECT 1'))
        except Exception as e:
            app.logger.error('health: db check failed: %s', e)
            ok = False
            err = str(e).splitlines()[0][:160]

        # 诊断信息：只暴露变量「名字」和解析出的主机，不含任何密码。
        # 排查「改了环境变量但没生效」这类问题时，这几个字段能直接定论。
        url = db.engine.url
        return jsonify(
            ok=ok,
            db=ok,
            db_error=err,
            db_host=url.host or '',
            db_name=url.database or '',
            env_keys=sorted(k for k in os.environ
                            if 'MYSQL' in k.upper() or 'DATABASE' in k.upper()),
        )

    if app.config.get('AUTO_CREATE_TABLES'):
        with app.app_context():
            try:
                db.create_all()
            except Exception as e:
                # 起不来就看不到日志了，所以这里只记不抛 —— 容器照样启动，
                # /health 会如实报告 db 不通
                app.logger.error('create_all failed: %s', e)

    return app
