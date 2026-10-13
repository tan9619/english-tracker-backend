"""内容安全检测。

移植自 cloudfunctions/{diary,chunk}/index.js 的 checkText，保持三态和
失败关闭语义：检测做不完就不放行。宁可让用户看到"检测暂不可用"，
也不要让违规内容落库 —— 后者是审核红线。

云托管侧需要在控制台「开放接口服务」里把 /wxa/msg_sec_check 加进白名单，
并且改完之后**重新构建版本**，否则没有 sidecar，每个调用都会失败。
容器内用 http 调用即可，sidecar 负责代理并注入 access_token。
"""

import requests
from flask import current_app

OK = 'ok'
RISKY = 'risky'
ERROR = 'error'


def check_text(text, openid):
    """返回 'ok' | 'risky' | 'error'。"""
    content = str(text or '').strip()
    if not content:
        return OK

    cfg = current_app.config
    if cfg.get('MODERATION_MODE') == 'off':
        return OK

    try:
        r = requests.post(
            cfg['WX_API_BASE'] + '/wxa/msg_sec_check',
            json={
                'version': 2,
                'scene': 2,
                'openid': openid,
                'content': content[:2500],
            },
            timeout=cfg['MODERATION_TIMEOUT'],
        )
        d = r.json()
    except Exception as e:
        current_app.logger.error('msg_sec_check request failed: %s', e)
        return ERROR

    code = d.get('errcode', d.get('errCode'))
    if code == 0:
        return OK

    # 87014 是"内容违规"。其他任何非零码也按 risky 处理以保持与原实现一致，
    # 但要大声记日志 —— 开放接口服务配错也会落到这里，不记日志会很难查。
    current_app.logger.warning(
        'msg_sec_check code=%s msg=%s', code, d.get('errmsg') or d.get('errMsg'))
    return RISKY


def failure(code):
    """把三态结果转成客户端约定的错误响应体。"""
    if code == RISKY:
        return {'success': False, 'code': 'RISKY', 'message': 'Content flagged'}
    return {'success': False, 'code': 'ERROR',
            'message': 'Content check unavailable, please try again'}
