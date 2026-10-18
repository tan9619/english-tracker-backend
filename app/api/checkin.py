"""每日打卡。"""

from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..dates import calc_streak, fmt, month_range, parse_date, today
from ..extensions import db
from ..models import Checkin, Chunk, Diary, Recording, ReviewRecord
from ..presets import PRESET_SOURCE

bp = Blueprint('checkin', __name__)


def _all_dates(openid):
    rows = db.session.query(Checkin.date).filter_by(openid=openid).all()
    return [fmt(r[0]) for r in rows]


@bp.route('/api/checkin', methods=['POST'])
def checkin():
    body = request.get_json(silent=True) or {}
    d = today()

    existing = db.session.query(Checkin).filter_by(openid=g.openid, date=d).one_or_none()
    if existing is not None:
        return jsonify(success=False, code='ALREADY_CHECKED_IN',
                       message='Already checked in', date=fmt(d))

    db.session.add(Checkin(openid=g.openid, date=d,
                           is_offline=bool(body.get('isOffline'))))
    try:
        db.session.commit()
    except IntegrityError:
        # 唯一键挡住并发重复提交 —— 这是正常情况，不是错误
        db.session.rollback()
        return jsonify(success=False, code='ALREADY_CHECKED_IN',
                       message='Already checked in', date=fmt(d))

    return jsonify(success=True, streak=calc_streak(_all_dates(g.openid)), date=fmt(d))


@bp.route('/api/checkin/stats', methods=['GET'])
def stats():
    d = today()
    first, last = month_range(d.year, d.month)

    month_dates = [
        fmt(r[0]) for r in db.session.query(Checkin.date)
        .filter(Checkin.openid == g.openid, Checkin.date >= first, Checkin.date <= last)
        .all()
    ]
    streak = calc_streak(_all_dates(g.openid))

    total = last.day
    checked = len(month_dates)
    return jsonify(
        success=True,
        checkedDates=month_dates,
        streak=streak,
        monthStats={
            'checked': checked,
            'total': total,
            'remaining': total - checked,
            'percentage': round(checked / total * 100),
        },
    )


@bp.route('/api/checkin/day', methods=['GET'])
def day_detail():
    """某一天的打卡状态 + 当天学习行为汇总。

    统计口径（四类都只算「当天」）：
      diary     当天「创建」的日记篇数（按 created_at，不是日记日期）
      chunks    当天创建的语块条数
      review    当天复习过的不同语块数（按 review_records 去重）
      recording 当天录音条数 + 累计时长（秒）

    日记按创建时间而不是日记日期统计：用户今天补录一篇 9 月的日记，
    应该算作「今天写了日记」，否则打卡页今天会显示 0。
    """
    raw = request.args.get('date')
    try:
        d = parse_date(raw)
    except (TypeError, ValueError):
        return jsonify(success=False, message='Invalid date')

    checked = (db.session.query(Checkin)
               .filter_by(openid=g.openid, date=d).one_or_none()) is not None

    day_start = datetime.combine(d, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    diary_count = (db.session.query(Diary)
                   .filter(Diary.openid == g.openid,
                           Diary.created_at >= day_start,
                           Diary.created_at < day_end).count())
    # 内置语块是建号时批量写入的，不能算成用户当天添加的学习内容
    chunk_count = (db.session.query(Chunk)
                   .filter(Chunk.openid == g.openid, Chunk.date == d,
                           Chunk.source != PRESET_SOURCE).count())
    # 按「不同语块」去重：同一语块当天复习多次只算一个
    review_count = (db.session.query(func.count(func.distinct(ReviewRecord.chunk_id)))
                    .filter(ReviewRecord.openid == g.openid,
                            ReviewRecord.review_date == d).scalar() or 0)

    rec_count, rec_duration = (db.session.query(
        func.count(Recording.id), func.coalesce(func.sum(Recording.duration), 0))
        .filter(Recording.openid == g.openid, Recording.date == d).one())

    return jsonify(
        success=True,
        date=fmt(d),
        checked=checked,
        learning={
            'diary': diary_count,
            'chunks': chunk_count,
            'review': review_count,
            'recordingCount': rec_count,
            'recordingDuration': int(rec_duration or 0),
        },
    )


@bp.route('/api/checkin/month', methods=['GET'])
def month():
    """month 是 1-based —— 客户端传的是 m+1。"""
    try:
        year = int(request.args.get('year'))
        mon = int(request.args.get('month'))
        first, last = month_range(year, mon)
    except (TypeError, ValueError):
        return jsonify(success=False, message='Invalid year/month')

    rows = (db.session.query(Checkin.date)
            .filter(Checkin.openid == g.openid, Checkin.date >= first, Checkin.date <= last)
            .all())
    return jsonify(success=True, checkedDates=[fmt(r[0]) for r in rows])
