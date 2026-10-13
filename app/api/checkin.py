"""每日打卡。"""

from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..dates import calc_streak, fmt, month_range, today
from ..extensions import db
from ..models import Checkin

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
