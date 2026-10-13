"""数据模型。

关键约定：主键 `id` 序列化成字符串 `_id`。前端的 WXML 到处用 `item._id`
作 wx:key 和 data-id，沿用这个字段名可以让所有模板一行都不用改。
"""

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Index,
                        Integer, Numeric, String, Text, UniqueConstraint)

from .dates import fmt, now_local
from .extensions import db

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
        return user, False
    user = User(openid=openid)
    db.session.add(user)
    db.session.commit()
    return user, True


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    nickname = db.Column(String(64), nullable=False, default='')
    avatar = db.Column(String(1024), nullable=False, default='')
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
    date = db.Column(Date, nullable=False)
    content = db.Column(Text, nullable=False)
    word_count = db.Column(Integer, nullable=False, default=0)
    char_count = db.Column(Integer, nullable=False, default=0)
    created_at = db.Column(DateTime, nullable=False, default=now_local)
    updated_at = db.Column(DateTime, nullable=False, default=now_local, onupdate=now_local)

    __table_args__ = (UniqueConstraint('openid', 'date', name='uq_diaries_openid_date'), MYSQL_OPTS)

    def to_dict(self):
        return {
            '_id': str(self.id),
            'date': fmt(self.date),
            'content': self.content,
            'word_count': self.word_count,
            'char_count': self.char_count,
            'updated_at': self.updated_at.strftime('%Y-%m-%dT%H:%M:%S') if self.updated_at else '',
        }


class Chunk(db.Model):
    __tablename__ = 'chunks'

    id = db.Column(BigIntPK, primary_key=True, autoincrement=True)
    openid = db.Column(String(64), nullable=False)
    phrase = db.Column(String(255), nullable=False)
    meaning = db.Column(String(512), nullable=False, default='')
    source = db.Column(String(255), nullable=False, default='')
    tag = db.Column(String(16), nullable=False, default='phrasal')
    date = db.Column(Date, nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=now_local)

    __table_args__ = (
        Index('ix_chunks_openid_created', 'openid', 'created_at'),
        Index('ix_chunks_openid_date', 'openid', 'date'),
        Index('ix_chunks_openid_tag', 'openid', 'tag'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        return {
            '_id': str(self.id),
            'phrase': self.phrase,
            'meaning': self.meaning or '',
            'source': self.source or '',
            'tag': self.tag,
            'date': fmt(self.date),
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
    name = db.Column(String(128), nullable=False, default='')
    file_id = db.Column(String(512), nullable=False)
    duration = db.Column(Integer, nullable=False, default=0)
    category = db.Column(String(16), nullable=False, default='other')
    listened = db.Column(Boolean, nullable=False, default=False)
    date = db.Column(Date, nullable=False)
    created_at = db.Column(DateTime, nullable=False, default=now_local)

    __table_args__ = (
        Index('ix_rec_openid_created', 'openid', 'created_at'),
        Index('ix_rec_openid_category', 'openid', 'category'),
        MYSQL_OPTS,
    )

    def to_dict(self):
        return {
            '_id': str(self.id),
            'name': self.name or '',
            'file_id': self.file_id,
            'duration': self.duration,
            'category': self.category,
            'listened': bool(self.listened),
            'date': fmt(self.date),
        }
