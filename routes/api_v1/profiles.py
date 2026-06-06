from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import User, db, followers
from . import api_v1


@api_v1.route('/profiles/<username>', methods=['GET'])
@jwt_required()
def get_profile(username):
    uid = int(get_jwt_identity())
    u = User.query.filter_by(username=username).first_or_404()
    is_following = db.session.query(followers).filter_by(
        follower_id=uid, followed_id=u.id, status='approved').first() is not None
    return jsonify({'ok': True, 'profile': {
        'id': u.id, 'username': u.username, 'avatar': u.avatar,
        'bio': u.bio, 'is_private': u.is_private,
        'followers_count': u.followers.count(),
        'following_count': u.following.count(),
        'posts_count': u.posts.count() if hasattr(u.posts, 'count') else len(u.posts),
        'is_following': is_following,
        'posts': [{'id': p.id, 'media': [m.cloudinary_url or m.filename for m in p.media],
                   'created_at': p.created_at.isoformat()} for p in u.posts.order_by(
                       db.desc(db.text('created_at'))).limit(30)],
    }})


@api_v1.route('/profiles/<username>/follow', methods=['POST'])
@jwt_required()
def follow(username):
    uid = int(get_jwt_identity())
    target = User.query.filter_by(username=username).first_or_404()
    if target.id == uid:
        return jsonify({'ok': False, 'error': 'cannot_follow_self'}), 400
    existing = db.session.query(followers).filter_by(
        follower_id=uid, followed_id=target.id).first()
    if existing:
        return jsonify({'ok': True, 'status': 'already_following'})
    status = 'pending' if target.is_private else 'approved'
    db.session.execute(followers.insert().values(
        follower_id=uid, followed_id=target.id, status=status))
    db.session.commit()
    return jsonify({'ok': True, 'status': status})


@api_v1.route('/profiles/<username>/unfollow', methods=['POST'])
@jwt_required()
def unfollow(username):
    uid = int(get_jwt_identity())
    target = User.query.filter_by(username=username).first_or_404()
    db.session.execute(followers.delete().where(
        (followers.c.follower_id == uid) & (followers.c.followed_id == target.id)))
    db.session.commit()
    return jsonify({'ok': True})


@api_v1.route('/search', methods=['GET'])
@jwt_required()
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': True, 'users': []})
    users = User.query.filter(
        User.username.ilike(f'%{q}%'),
        User.is_bot == False
    ).limit(20).all()
    return jsonify({'ok': True, 'users': [
        {'id': u.id, 'username': u.username, 'avatar': u.avatar, 'bio': u.bio}
        for u in users
    ]})
