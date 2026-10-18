import os

from flask import Flask, jsonify, request
from sqlalchemy import inspect, text

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
                _ensure_columns(app)
                _ensure_diary_schema(app)
                _ensure_chunk_schema(app)
                _ensure_recording_schema(app)
            except Exception as e:
                # 起不来就看不到日志了，所以这里只记不抛 —— 容器照样启动，
                # /health 会如实报告 db 不通
                app.logger.error('create_all failed: %s', e)

    return app


def _ensure_columns(app):
    """给已存在的表补新增的列。

    db.create_all() 只建缺失的表，不会改已有表的结构。项目没有引入 Alembic，
    所以这里做最小的增量迁移 —— 目前只有 users.animal 一列。
    """
    insp = inspect(db.engine)
    if 'users' not in insp.get_table_names():
        return
    cols = {c['name'] for c in insp.get_columns('users')}
    if 'animal' not in cols:
        db.session.execute(text(
            "ALTER TABLE users ADD COLUMN animal VARCHAR(16) NOT NULL DEFAULT ''"))
        db.session.commit()
        app.logger.info('schema: users.animal 列已补齐')
    if 'presets_seeded' not in cols:
        db.session.execute(text(
            'ALTER TABLE users ADD COLUMN presets_seeded BOOLEAN NOT NULL DEFAULT 0'))
        db.session.commit()
        app.logger.info('schema: users.presets_seeded 列已补齐')


def _ensure_diary_schema(app):
    """日记从「一天一篇」改成「一天多篇」所需的迁移。

    db.create_all() 只建缺失的表，不会加列、也不会删约束，所以这些都得手写。
    改动是不可逆的（唯一索引删了回不去），部署前请确认有备份。
    """
    insp = inspect(db.engine)
    if 'diaries' not in insp.get_table_names():
        return

    # 1) 补列
    cols = {c['name'] for c in insp.get_columns('diaries')}
    try:
        if 'title' not in cols:
            db.session.execute(text(
                "ALTER TABLE diaries ADD COLUMN title VARCHAR(128) NOT NULL DEFAULT ''"))
            app.logger.info('schema: diaries.title 已补齐')
        if 'note' not in cols:
            db.session.execute(text('ALTER TABLE diaries ADD COLUMN note TEXT NULL'))
            app.logger.info('schema: diaries.note 已补齐')
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 日记字段迁移失败 %s', e)

    # 2) 删掉 (openid, date) 的唯一约束，允许一天多篇
    insp = inspect(db.engine)
    idx = {i['name'] for i in insp.get_indexes('diaries')}
    if 'uq_diaries_openid_date' in idx:
        if db.engine.dialect.name == 'mysql':
            try:
                db.session.execute(text(
                    'ALTER TABLE diaries DROP INDEX uq_diaries_openid_date'))
                db.session.commit()
                app.logger.info('schema: 已删除唯一索引 uq_diaries_openid_date')
            except Exception as e:
                db.session.rollback()
                app.logger.error('schema: 删除唯一索引失败 %s', e)
        else:
            app.logger.warning(
                'schema: SQLite 无法用 ALTER 删除表级唯一约束（uq_diaries_openid_date）。'
                '本地开发请删除 dev.db 重建；生产 MySQL 会自动处理。')

    # 3) 补建非唯一索引（create_all 不会给已存在的表建索引）
    try:
        insp = inspect(db.engine)
        have = {i['name'] for i in insp.get_indexes('diaries')}
        if 'ix_diaries_openid_date' not in have:
            db.session.execute(text(
                'CREATE INDEX ix_diaries_openid_date ON diaries (openid, date)'))
        if 'ix_diaries_openid_created' not in have:
            db.session.execute(text(
                'CREATE INDEX ix_diaries_openid_created ON diaries (openid, created_at)'))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 日记索引创建失败 %s', e)


def _ensure_chunk_schema(app):
    """语块新增的字段。review_records 是新表，create_all 会自动建，无需 ALTER。"""
    insp = inspect(db.engine)
    if 'chunks' not in insp.get_table_names():
        return

    cols = {c['name'] for c in insp.get_columns('chunks')}
    additions = [
        ('scenario', "VARCHAR(128) NOT NULL DEFAULT ''"),
        ('example_sentence', 'TEXT NULL'),
        ('note', 'TEXT NULL'),
        ('mastery_status', "VARCHAR(16) NOT NULL DEFAULT 'learning'"),
        ('updated_at', 'DATETIME NULL'),
    ]
    try:
        for name, ddl in additions:
            if name not in cols:
                db.session.execute(text(
                    'ALTER TABLE chunks ADD COLUMN %s %s' % (name, ddl)))
                app.logger.info('schema: chunks.%s 已补齐', name)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 语块字段迁移失败 %s', e)

    try:
        insp = inspect(db.engine)
        have = {i['name'] for i in insp.get_indexes('chunks')}
        if 'ix_chunks_openid_mastery' not in have:
            db.session.execute(text(
                'CREATE INDEX ix_chunks_openid_mastery ON chunks (openid, mastery_status)'))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 语块索引创建失败 %s', e)


def _ensure_recording_schema(app):
    """录音模块重做新增的字段。

    旧 recordings 只有 name/category。新结构用 title/practice_type/topic，
    老数据把 name 回填成 title，避免升级后列表标题全空。
    """
    insp = inspect(db.engine)
    if 'recordings' not in insp.get_table_names():
        return

    cols = {c['name'] for c in insp.get_columns('recordings')}
    additions = [
        ('title', "VARCHAR(128) NOT NULL DEFAULT ''"),
        ('practice_type', "VARCHAR(16) NOT NULL DEFAULT 'free'"),
        ('topic', "VARCHAR(64) NOT NULL DEFAULT ''"),
        ('updated_at', 'DATETIME NULL'),
    ]
    try:
        for name, ddl in additions:
            if name not in cols:
                db.session.execute(text(
                    'ALTER TABLE recordings ADD COLUMN %s %s' % (name, ddl)))
                app.logger.info('schema: recordings.%s 已补齐', name)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 录音字段迁移失败 %s', e)

    try:
        db.session.execute(text(
            "UPDATE recordings SET title = name "
            "WHERE (title IS NULL OR title = '') AND name IS NOT NULL AND name <> ''"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 录音标题回填失败 %s', e)

    try:
        insp = inspect(db.engine)
        have = {i['name'] for i in insp.get_indexes('recordings')}
        if 'ix_rec_openid_date' not in have:
            db.session.execute(text(
                'CREATE INDEX ix_rec_openid_date ON recordings (openid, date)'))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error('schema: 录音索引创建失败 %s', e)
