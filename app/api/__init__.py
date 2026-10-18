from . import (account, categories, checkin, chunks, diary, login,
               recordings, review, user)

# create_app 会遍历这个列表给每个蓝图挂 require_openid
BLUEPRINTS = [
    login.bp,
    user.bp,
    checkin.bp,
    diary.bp,
    chunks.bp,
    categories.bp,
    review.bp,
    recordings.bp,
    account.bp,
]
