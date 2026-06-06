from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Shorts, ShortsLike, db
from . import api_v1
from sqlalchemy import desc


@api_v1.route('/shorts', methods=['GET'])
@jwt_required()
def get_shorts():
    uid = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    shorts = Shorts.query.order_by(desc(Shorts.created_at)).paginate(
        page=page, per_page=10, error_out=False)
    return jsonify({'ok': True, 'shorts': [
        {
            'id': s.id, 'video_url': s.video_url, 'caption': s.caption,
            'user': {'username': s.user.username, 'avatar': s.user.avatar},
            'likes_count': ShortsLike.query.filter_by(shorts_id=s.id).count(),
            'liked_by_me': ShortsLike.query.filter_by(
                shorts_id=s.id, user_id=uid).first() is not None,
        }
        for s in shorts.items
    ], 'has_next': shorts.has_next})


@api_v1.route('/shorts/<int:short_id>/like', methods=['POST'])
@jwt_required()
def toggle_short_like(short_id):
    uid = int(get_jwt_identity())
    like = ShortsLike.query.filter_by(shorts_id=short_id, user_id=uid).first()
    if like:
        db.session.delete(like)
        db.session.commit()
        return jsonify({'ok': True, 'liked': False})
    db.session.add(ShortsLike(shorts_id=short_id, user_id=uid))
    db.session.commit()
    return jsonify({'ok': True, 'liked': True})
