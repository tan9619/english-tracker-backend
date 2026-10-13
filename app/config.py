"""配置。全部来自环境变量，本地开发用 .env 注入。"""

import os
from urllib.parse import quote_plus

APP_ENV = os.environ.get('APP_ENV', 'development')
IS_PRODUCTION = APP_ENV == 'production'


def _database_url():
    """优先 DATABASE_URL（本地开发方便），否则从云托管的 MYSQL_* 拼。"""
    url = os.environ.get('DATABASE_URL')
    if url:
        return url

    address = os.environ.get('MYSQL_ADDRESS', '')
    if ':' in address:
        host, port = address.rsplit(':', 1)
    else:
        host, port = address, '3306'

    return 'mysql+pymysql://{u}:{p}@{h}:{port}/{db}?charset=utf8mb4'.format(
        u=quote_plus(os.environ.get('MYSQL_USERNAME', '')),
        p=quote_plus(os.environ.get('MYSQL_PASSWORD', '')),
        h=host,
        port=port,
        db=os.environ.get('MYSQL_DATABASE', 'english_tracker'),
    )


DATABASE_URL = _database_url()


def _engine_options(url):
    opts = {'pool_pre_ping': True}
    if url.startswith('sqlite'):
        # SQLite 是本地开发用的，不涉及连接池超时；而且它不接受 connect_timeout
        return opts
    # pool_recycle 要小于 MySQL 的 wait_timeout，否则空闲连接会被服务端掐掉，
    # 下一个请求拿到死连接直接报错。
    opts.update({
        'pool_recycle': 280,
        'pool_size': 5,
        'max_overflow': 5,
        'pool_timeout': 10,
        'connect_args': {'connect_timeout': 5},
    })
    return opts


class Config:
    APP_ENV = APP_ENV
    IS_PRODUCTION = IS_PRODUCTION

    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(DATABASE_URL)

    AUTO_CREATE_TABLES = os.environ.get('AUTO_CREATE_TABLES', '1') == '1'

    # 本地开发用的假身份。生产环境设了它会在下面直接拒绝启动。
    DEV_OPENID = os.environ.get('DEV_OPENID', '')

    # 'off' 只允许非生产环境使用，用来在没网/没配额时跳过内容检测。
    MODERATION_MODE = os.environ.get('MODERATION_MODE', 'on')
    MODERATION_TIMEOUT = float(os.environ.get('MODERATION_TIMEOUT', '3'))

    # 云托管「开放接口服务」的入口。容器内用 http，由 sidecar 代理并注入
    # access_token —— 所以这里不需要、也不应该配 token。
    WX_API_BASE = os.environ.get('WX_API_BASE', 'http://api.weixin.qq.com')

    # 对象存储（删除文件时才用到；上传是客户端直传）
    COS_BUCKET = os.environ.get('COS_BUCKET', '')
    COS_REGION = os.environ.get('COS_REGION', 'ap-shanghai')
    COS_SECRET_ID = os.environ.get('COS_SECRET_ID', '')
    COS_SECRET_KEY = os.environ.get('COS_SECRET_KEY', '')

    EXPECTED_APPID = os.environ.get('EXPECTED_APPID', 'wx7bbc279908cb6fe3')


def validate(config):
    """启动时的硬检查 —— 宁可起不来，也不要带着危险配置对外服务。"""
    if config.get('IS_PRODUCTION'):
        if config.get('DEV_OPENID'):
            raise RuntimeError(
                'DEV_OPENID must not be set when APP_ENV=production —— '
                '它会让任何人都能冒充这个用户身份'
            )
        if config.get('MODERATION_MODE') == 'off':
            raise RuntimeError(
                'MODERATION_MODE=off must not be set when APP_ENV=production —— '
                '内容检测失败关闭是过审前提'
            )
    return config
