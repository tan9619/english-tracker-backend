"""对象存储删除。

上传是客户端直传（wx.cloud.uploadFile 带云托管环境 ID），后端只存那个
不透明的 cloud:// 字符串，从不接触文件字节。只有删除才需要后端出手 ——
客户端删不掉孤儿文件。

凭据优先用环境变量里的 CAM 子账号密钥；没有就用云托管开放接口服务的
临时密钥（/_/cos/getauth，同样免 access_token）。临时密钥那条路需要在
控制台白名单里加上 /_/cos/getauth。
"""

import time

import requests
from flask import current_app

_TMP_AUTH = {'client': None, 'exp': 0}


def key_from_cloud_id(cloud_id):
    """cloud://<env>/<key> 或 cloud://<env>.<suffix>/<key> -> <key>"""
    if not cloud_id or not str(cloud_id).startswith('cloud://'):
        return None
    rest = str(cloud_id)[len('cloud://'):]
    i = rest.find('/')
    return rest[i + 1:] if i >= 0 else None


def _client():
    cfg = current_app.config

    from qcloud_cos import CosConfig, CosS3Client

    if cfg['COS_SECRET_ID'] and cfg['COS_SECRET_KEY']:
        return CosS3Client(CosConfig(
            Region=cfg['COS_REGION'],
            SecretId=cfg['COS_SECRET_ID'],
            SecretKey=cfg['COS_SECRET_KEY'],
        ))

    if _TMP_AUTH['client'] and _TMP_AUTH['exp'] > time.time() + 60:
        return _TMP_AUTH['client']

    r = requests.post(cfg['WX_API_BASE'] + '/_/cos/getauth', timeout=3)
    d = r.json()
    client = CosS3Client(CosConfig(
        Region=cfg['COS_REGION'],
        SecretId=d.get('TmpSecretId') or d.get('tmpSecretId'),
        SecretKey=d.get('TmpSecretKey') or d.get('tmpSecretKey'),
        Token=d.get('Token') or d.get('token'),
    ))
    _TMP_AUTH['client'] = client
    _TMP_AUTH['exp'] = float(d.get('ExpiredTime') or 0)
    return client


def delete_cloud_files(cloud_ids):
    """批量删除。返回 (成功数, 失败的 fileID 列表)。**永不抛异常。**

    删除失败不该阻断账号注销 —— 注销权优先于文件清理，失败的文件记进
    report 里让人工处理。
    """
    cfg = current_app.config
    ids = [c for c in (cloud_ids or []) if c]
    if not ids:
        return 0, []

    if not cfg['COS_BUCKET']:
        current_app.logger.warning(
            'COS_BUCKET 未配置，跳过 %d 个文件的删除', len(ids))
        return 0, ids

    keys = []
    key_to_id = {}
    for cid in ids:
        k = key_from_cloud_id(cid)
        if k:
            keys.append(k)
            key_to_id[k] = cid

    if not keys:
        return 0, []

    try:
        client = _client()
    except Exception as e:
        current_app.logger.error('COS client init failed: %s', e)
        return 0, ids

    deleted, failed = 0, []
    for i in range(0, len(keys), 1000):   # DeleteMultipleObjects 单次上限
        batch = keys[i:i + 1000]
        try:
            r = client.delete_objects(
                Bucket=cfg['COS_BUCKET'],
                Delete={'Object': [{'Key': k} for k in batch], 'Quiet': False},
            )
            errored = set()
            for e in (r.get('Error') or []):
                errored.add(e.get('Key'))
            deleted += len(batch) - len(errored)
            failed.extend(key_to_id[k] for k in errored if k in key_to_id)
        except Exception as e:
            current_app.logger.error('COS delete_objects failed: %s', e)
            failed.extend(key_to_id[k] for k in batch)

    if failed:
        current_app.logger.warning('未被删除的文件: %s', failed)
    return deleted, failed
