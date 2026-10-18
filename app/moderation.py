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

    # v1 风格的"内容违规"
    if code == 87014:
        return RISKY

    # 任何非零 errcode 都表示**调用失败**（缺 access_token、权限不足、参数错、
    # 用户久未访问等），不是"内容违规"。绝不能当成 RISKY —— 否则会把服务配置
    # 问题报成用户的内容有问题，让人完全查错方向。
    if code != 0:
        current_app.logger.error(
            'msg_sec_check 调用失败 code=%s msg=%s',
            code, d.get('errmsg') or d.get('errMsg') or d.get('errMsg'))
        return ERROR

    # v2：errcode=0 只代表调用成功，真正的判定在 result.suggest
    result = d.get('result') or {}
    suggest = result.get('suggest')

    if suggest == 'pass':
        return OK

    if suggest == 'risky':
        current_app.logger.info('msg_sec_check risky label=%s', result.get('label'))
        return RISKY

    if suggest == 'review':
        # 官方定义是"建议人工审核"。本项目没有人工审核流程，记录后放行，
        # 避免把正常内容误拦。
        current_app.logger.warning(
            'msg_sec_check suggest=review label=%s', result.get('label'))
        return OK

    # 没有 result.suggest，说明响应结构不是 v2 预期的（多半是开放接口服务
    # 没生效，请求直接打到了微信 API）
    current_app.logger.error('msg_sec_check 响应缺少 result.suggest: %s', d)
    return ERROR


def failure(code):
    """把三态结果转成客户端约定的错误响应体。"""
    if code == RISKY:
        return {'success': False, 'code': 'RISKY', 'message': 'Content flagged'}
    return {'success': False, 'code': 'ERROR',
            'message': 'Content check unavailable, please try again'}
