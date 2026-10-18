"""数据模型。

关键约定：主键 `id` 序列化成字符串 `_id`。前端的 WXML 到处用 `item._id`
作 wx:key 和 data-id，沿用这个字段名可以让所有模板一行都不用改。
"""

import random

from flask import current_app
from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, UniqueConstraint)

from .dates import fmt, now_local
from .extensions import db

# 用户头像的默认形象，必须与前端 images/animal/ 下的文件名一致。
# 建号时随机分配一次，之后固定。用户自己上传头像后，这个只作兜底。
ANIMALS = ('bird', 'cat', 'dog', 'sheep', 'turtle', 'whale')


def random_animal():
    return random.choice(ANIMALS)

# 生产是 MySQL 的 BIGINT AUTO_INCREMENT。但 SQLite 只有 INTEGER PRIMARY KEY
# 才自增（BIGINT 会直接 NULL 报错），本地开发用 sqlite，所以给它一个变体。
BigIntPK = BigInteger().with_variant(Integer, 'sqlite')

# 显式声明字符集。不写的话表会跟随库的默认值 —— 库若是 latin1，
# 中文昵称和释义会直接存成乱码，而且不会报任何错。
MYSQL_OPTS = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}


def get_or_create_user(openid):
    """返回 (user, is_new)。调用方负责处理异常和 rollback。"""
    user = db.session.query(User).filter_by(openid=openid).one_or_none()
    if user is not None:
        # 老账号（animal 字段是后加的）第一次访问时补一个
        if not user.animal:
            user.animal = random_animal()
            db.session.commit()
        _safe_seed_presets(user)
        return user, False
    user = User(openid=openid, animal=random_animal(), presets_seeded=False)
    db.session.add(user)
    db.session.commit()
    _safe_seed_presets(user)
    return user, True


def _safe_seed_presets(user):
    """预置语块写失败不能让人登不进来 —— 记日志、回滚，下次登录再补。"""
    if not current_app.config.get('SEED_PRESETS', True):
        return
    try:
        seed_presets(user)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('预置语块写入失败 openid=%s: %s', user.openid, e)


def seed_presets(user):
    """把内置语块连同复习卡复制到用户名下。

    每个用户一份自己的副本，之后编辑/删除/复习互不影响。
    users.presets_seeded 保证只做一次 —— 用户主动删掉预置语块后不会被重新塞回来。
    """
    if user.presets_seeded:
        return 0

    # 并发登录（两台设备同时冷启动）时用行锁串行化，避免写两份。
    # SQLite 会忽略 FOR UPDATE，本地开发无影响。
    locked = (db.session.query(User)
              .filter_by(id=user.id)
              .populate_existing()
              .with_for_update()
              .one_or_none())
    if locked is None or locked.presets_seeded:
        return 0
    user = locked

    from .dates import today
    from .presets import PRESET_SOURCE, load_presets

    d = today()
    chunks = []
    for item in load_presets():
        chunks.append(Chunk(
            openid=user.openid,
            phrase=item['phrase'][:255],
            meaning=item['meaning'][:512],
            scenario=(item.get('scenario') or '')[:128],
            example_sentence='',
            note='',
            source=PRESET_SOURCE[:255],
            tag=item.get('tag') or 'sentence',
            mastery_status=MASTERY_LEARNING,
            date=d,
            created_at=now_local(),
        ))

    db.session.add_all(chunks)
    db.session.flush()          # 需要 chunk.id 才能建复习卡

    for chunk in chunks:
        db.session.add(ReviewCard(
            openid=user.openid, chunk_id=chunk.id,
            phrase=chunk.phrase, meaning=chunk.meaning,
            repetition=0, interval=1, easiness=2.50,
            next_review=d, last_review=None,
        ))

    user.presets_seeded = True
    db.session.commit()
    current_app.logger.info('已为用户 %s 写入 %d 条预置语块', user.openid, len(chunks))
    return len(chunks)


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    nickname = db.Column(String(64), nullable=False, default='')
    avatar = db.Column(String(1024), nullable=False, default='')
    animal = db.Column(String(16), nullable=False, default='')
    # 内置语块是否已复制到该用户名下（只做一次，删了也不再补）
    presets_seeded = db.Column(Boolean, nullable=False, default=False)
    checkin_reminder = db.Column(Boolean, nullable=False, default=False)
    reminder_time = db.Column(String(5), nullable=False, default='21:00')
    review_reminder = db.Column(Boolean, nullable=False, default=False)
    created_at = db.Column(DateTime, nullable=False, default=now_local)
    updated_at = db.Column(DateTime, nullable=False, default=now_local, onupdate=now_local)

    __table_args__ = (UniqueConstraint('openid', name='uq_users_openid'), MYSQL_OPTS)

    def to_dict(self):
        return {
            '_id': str(self.id),
            'nickname': self.nickname or '',
            'avatar': self.avatar or '',
            'animal': self.animal or '',
            'checkin_reminder': bool(self.checkin_reminder),
            'reminder_time': self.reminder_time or '21:00',
            'review_reminder': bool(self.review_reminder),
        }


class Checkin(db.Model):
    __tablename__ = 'checkins'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    date = db.Column(Date, nullable=False)
    is_offline = db.Column(Boolean, nullable=False, default=False)
    synced = db.Column(Boolean, nullable=False, default=True)
    created_at = db.Column(DateTime, nullable=False, default=now_local)

    # 去重靠这个唯一键，而不是靠"先查再写" —— 并发下先查再写会写进两条
    __table_args__ = (UniqueConstraint('openid', 'date', name='uq_checkins_openid_date'), MYSQL_OPTS)

    def to_dict(self):
        return {
            '_id': str(self.id),
            'date': fmt(self.date),
            'is_offline': bool(self.is_offline),
            'synced': bool(self.synced),
        }


class Diary(db.Model):
    __tablename__ = 'diaries'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    title = db.Column(String(128), nullable=False, default='')
    date = db.Column(Date, nullable=False)          # 日记归属日期，用户可以改
    content = db.Column(Text, nullable=False)       # 英文正文
    note = db.Column(Text, nullable=True)           # 中文备注
    word_count = db.Column(Integer, nullable=False, default=0)
    char_count = db.Column(Integer, nullable=False, default=0)
    created_at = db.Column(DateTime, nullable=False, default=now_local)
    updated_at = db.Column(DateTime, nullable=False, default=now_local, onupdate=now_local)

    # 一天可以写多篇，所以 (openid, date) 不再唯一。列表按 date DESC, id DESC 排，
    # 同一天多篇时用 id 兜底，否则顺序不确定。
    __table_args__ = (
        Index('ix_diaries_openid_date', 'openid', 'date'),
        Index('ix_diaries_openid_created', 'openid', 'created_at'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        return {
            '_id': str(self.id),
            'title': self.title or '',
            'date': fmt(self.date),
            'content': self.content,
            'note': self.note or '',
            'word_count': self.word_count,
            'char_count': self.char_count,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%dT%H:%M:%S') if self.updated_at else '',
        }


# 掌握状态只存在 chunks 上，是唯一事实来源。复习流程负责更新它，
# 复习卡不再单独存一份，避免两边不一致。
MASTERY_LEARNING = 'learning'
MASTERY_MASTERED = 'mastered'


class Chunk(db.Model):
    __tablename__ = 'chunks'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    phrase = db.Column(String(255), nullable=False)
    meaning = db.Column(String(512), nullable=False, default='')
    scenario = db.Column(String(128), nullable=False, default='')   # 使用场景
    example_sentence = db.Column(Text, nullable=True)               # 示例句
    note = db.Column(Text, nullable=True)                           # 个人备注
    source = db.Column(String(255), nullable=False, default='')
    tag = db.Column(String(16), nullable=False, default='phrasal')
    mastery_status = db.Column(String(16), nullable=False, default=MASTERY_LEARNING)
    date = db.Column(Date, nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=now_local)
    updated_at = db.Column(DateTime, nullable=True)

    __table_args__ = (
        Index('ix_chunks_openid_created', 'openid', 'created_at'),
        Index('ix_chunks_openid_date', 'openid', 'date'),
        Index('ix_chunks_openid_tag', 'openid', 'tag'),
        Index('ix_chunks_openid_mastery', 'openid', 'mastery_status'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        return {
            '_id': str(self.id),
            'phrase': self.phrase,
            'meaning': self.meaning or '',
            'scenario': self.scenario or '',
            'example_sentence': self.example_sentence or '',
            'note': self.note or '',
            'source': self.source or '',
            'tag': self.tag,
            'mastery_status': self.mastery_status or MASTERY_LEARNING,
            'date': fmt(self.date),
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%dT%H:%M:%S') if self.updated_at else '',
        }


class ReviewRecord(db.Model):
    """复习行为流水。每次提交结果写一条，不覆盖历史。

    统计「今日已复习」时按不同 chunk_id 去重，但历史记录保留每一次。
    """
    __tablename__ = 'review_records'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    chunk_id = db.Column(BigIntPK, ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False)
    review_date = db.Column(Date, nullable=False)
    result = db.Column(String(16), nullable=False)   # again | mastered
    created_at = db.Column(DateTime, nullable=False, default=now_local)

    __table_args__ = (
        Index('ix_records_openid_date', 'openid', 'review_date'),
        Index('ix_records_openid_chunk', 'openid', 'chunk_id'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        return {
            '_id': str(self.id),
            'chunk_id': str(self.chunk_id),
            'review_date': fmt(self.review_date),
            'result': self.result,
            'created_at': self.created_at.strftime('%Y-%m-%dT%H:%M:%S') if self.created_at else '',
        }


class ReviewCard(db.Model):
    __tablename__ = 'review_cards'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    chunk_id = db.Column(BigIntPK, ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False)
    phrase = db.Column(String(255), nullable=False, default='')
    meaning = db.Column(String(512), nullable=False, default='')
    repetition = db.Column(Integer, nullable=False, default=0)
    interval = db.Column(Integer, nullable=False, default=1)
    easiness = db.Column(Numeric(4, 2), nullable=False, default=2.50)
    next_review = db.Column(Date, nullable=False)
    last_review = db.Column(Date, nullable=True)
    created_at = db.Column(DateTime, nullable=False, default=now_local)

    __table_args__ = (Index('ix_cards_openid_next', 'openid', 'next_review'), MYSQL_OPTS)

    def to_dict(self):
        return {
            '_id': str(self.id),
            'chunk_id': str(self.chunk_id),
            'phrase': self.phrase or '',
            'meaning': self.meaning or '',
            'repetition': self.repetition,
            'interval': self.interval,
            'easiness': float(self.easiness),   # Decimal -> float，跟 JS 的 2.5 一致
            'next_review': fmt(self.next_review),
            'last_review': fmt(self.last_review) if self.last_review else None,
        }


class Recording(db.Model):
    __tablename__ = 'recordings'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    title = db.Column(String(128), nullable=False, default='')
    practice_type = db.Column(String(16), nullable=False, default='free')
    topic = db.Column(String(64), nullable=False, default='')
    file_id = db.Column(String(512), nullable=False)
    duration = db.Column(Integer, nullable=False, default=0)
    listened = db.Column(Boolean, nullable=False, default=False)
    # recording_date —— 统计口径。第一版不允许用户改，保存时取服务器当天。
    date = db.Column(Date, nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=now_local)
    updated_at = db.Column(DateTime, nullable=True)
    # 旧字段，只读：老数据的标题和分类。新代码一律写 title/practice_type。
    name = db.Column(String(128), nullable=False, default='')
    category = db.Column(String(16), nullable=False, default='other')

    __table_args__ = (
        Index('ix_rec_openid_created', 'openid', 'created_at'),
        Index('ix_rec_openid_date', 'openid', 'date'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        title = self.title or self.name or ''
        return {
            '_id': str(self.id),
            'title': title,
            'practice_type': self.practice_type or 'free',
            'topic': self.topic or '',
            'file_id': self.file_id,
            'duration': self.duration,
            'listened': bool(self.listened),
            'date': fmt(self.date),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M') if self.created_at else '',
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M') if self.updated_at else '',
            # 旧字段别名，让还没升级的客户端不至于把标题显示成空
            'name': title,
            'category': self.category or 'other',
        }
