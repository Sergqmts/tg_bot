from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Post, Like, Comment, SavedPost, Media, User, db, followers
from . import api_v1
from sqlalchemy import desc


@api_v1.route('/feed', methods=['GET'])
@jwt_required()
def get_feed():
    uid = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 20, type=int), 50)
    followed = db.session.query(followers.c.followed_id).filter(
        followers.c.follower_id == uid,
        followers.c.status == 'approved'
    ).subquery()
    posts = Post.query.filter(
        (Post.user_id == uid) | Post.user_id.in_(followed)
    ).order_by(desc(Post.created_at)).paginate(page=page, per_page=limit, error_out=False)
    return jsonify({'ok': True, 'posts': [_post_dict(p, uid) for p in posts.items],
                    'has_next': posts.has_next})


@api_v1.route('/posts/<int:post_id>', methods=['GET'])
@jwt_required()
def get_post(post_id):
    uid = int(get_jwt_identity())
    post = Post.query.get_or_404(post_id)
    return jsonify({'ok': True, 'post': _post_dict(post, uid, with_comments=True)})


@api_v1.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    uid = int(get_jwt_identity())
    data = request.get_json()
    post = Post(user_id=uid, body=data.get('body', ''))
    db.session.add(post)
    db.session.flush()
    for url in data.get('media_urls', []):
        m = Media(post_id=post.id, cloudinary_url=url, filename=url.split('/')[-1],
                  media_type=data.get('media_type', 'image'))
        db.session.add(m)
    db.session.commit()
    return jsonify({'ok': True, 'post': _post_dict(post, uid)}), 201


@api_v1.route('/posts/<int:post_id>/like', methods=['POST'])
@jwt_required()
def toggle_like(post_id):
    uid = int(get_jwt_identity())
    like = Like.query.filter_by(user_id=uid, post_id=post_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
        return jsonify({'ok': True, 'liked': False})
    db.session.add(Like(user_id=uid, post_id=post_id))
    db.session.commit()
    return jsonify({'ok': True, 'liked': True})


@api_v1.route('/posts/<int:post_id>/comments', methods=['POST'])
@jwt_required()
def add_comment(post_id):
    uid = int(get_jwt_identity())
    data = request.get_json()
    c = Comment(post_id=post_id, user_id=uid, body=data['body'])
    db.session.add(c)
    db.session.commit()
    return jsonify({'ok': True, 'comment': {
        'id': c.id, 'body': c.body, 'user_id': c.user_id,
        'created_at': c.created_at.isoformat()
    }}), 201


def _post_dict(p, uid, with_comments=False):
    d = {
        'id': p.id, 'body': p.body,
        'created_at': p.created_at.isoformat(),
        'user': {'id': p.user.id, 'username': p.user.username, 'avatar': p.user.avatar},
        'media': [{'url': m.cloudinary_url or m.filename, 'type': m.media_type} for m in p.media],
        'likes_count': p.likes.count(),
        'comments_count': p.comments.count(),
        'liked_by_me': p.likes.filter_by(user_id=uid).first() is not None,
        'saved_by_me': SavedPost.query.filter_by(user_id=uid, post_id=p.id).first() is not None,
    }
    if with_comments:
        d['comments'] = [{'id': c.id, 'body': c.body, 'user_id': c.user_id,
                           'username': c.user.username, 'avatar': c.user.avatar,
                           'created_at': c.created_at.isoformat()} for c in p.comments]
    return d
