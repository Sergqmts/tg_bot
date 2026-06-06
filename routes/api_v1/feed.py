import os
from urllib.parse import urlparse
from flask import request, jsonify, abort
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Post, Like, Comment, SavedPost, Media, User, CommunityMember, db, followers, blocked
from . import api_v1
from sqlalchemy import desc

_ALLOWED_MEDIA_TYPES = {'image', 'video'}
_MAX_MEDIA_PER_POST = 10
_CLOUDINARY_HOSTS = {'res.cloudinary.com'}


def _cloudinary_host_ok(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme != 'https':
            return False
        host = p.hostname or ''
        # Allow res.cloudinary.com and <cloudname>.cloudinary.com
        cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
        allowed = _CLOUDINARY_HOSTS | ({f'{cloud_name}.cloudinary.com'} if cloud_name else set())
        if host not in allowed:
            return False
        # Reject control chars or non-ASCII
        if any(ord(c) < 0x20 or ord(c) > 0x7E for c in url):
            return False
        return True
    except Exception:
        return False


def _can_view_post(uid: int, post: Post) -> bool:
    """Return True if uid is allowed to see this post. Return False to 404."""
    author = post.author

    # Blocked in either direction
    is_blocked = db.session.query(blocked).filter(
        ((blocked.c.blocker_id == author.id) & (blocked.c.blocked_id == uid)) |
        ((blocked.c.blocker_id == uid) & (blocked.c.blocked_id == author.id))
    ).first()
    if is_blocked:
        return False

    # Own post always visible
    if post.user_id == uid:
        return True

    # Private community post: requester must be an approved member
    if post.is_community_post and post.community_id:
        member = CommunityMember.query.filter_by(
            community_id=post.community_id, user_id=uid, status='approved').first()
        if not member:
            return False

    # Private author: approved follower only
    if author.is_private:
        follow_row = db.session.query(followers).filter_by(
            follower_id=uid, followed_id=author.id, status='approved').first()
        return follow_row is not None

    return True


@api_v1.route('/feed', methods=['GET'])
@jwt_required()
def get_feed():
    uid = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 20, type=int), 50)
    followed_ids = db.session.query(followers.c.followed_id).filter(
        followers.c.follower_id == uid,
        followers.c.status == 'approved'
    ).subquery()
    posts = Post.query.filter(
        (Post.user_id == uid) | Post.user_id.in_(followed_ids)
    ).order_by(desc(Post.created_at)).paginate(page=page, per_page=limit, error_out=False)
    return jsonify({'ok': True, 'posts': [_post_dict(p, uid) for p in posts.items],
                    'has_next': posts.has_next})


@api_v1.route('/posts/<int:post_id>', methods=['GET'])
@jwt_required()
def get_post(post_id):
    uid = int(get_jwt_identity())
    post = Post.query.get_or_404(post_id)
    if not _can_view_post(uid, post):
        abort(404)
    return jsonify({'ok': True, 'post': _post_dict(post, uid, with_comments=True)})


@api_v1.route('/posts', methods=['POST'])
@jwt_required()
def create_post():
    uid = int(get_jwt_identity())
    data = request.get_json() or {}
    media_urls = data.get('media_urls', [])
    media_type = data.get('media_type', 'image')

    if not isinstance(media_urls, list) or len(media_urls) > _MAX_MEDIA_PER_POST:
        return jsonify({'ok': False, 'error': 'invalid_media'}), 400
    if media_type not in _ALLOWED_MEDIA_TYPES:
        return jsonify({'ok': False, 'error': 'invalid_media_type'}), 400
    for url in media_urls:
        if not isinstance(url, str) or not _cloudinary_host_ok(url):
            return jsonify({'ok': False, 'error': 'invalid_media_url'}), 400

    post = Post(user_id=uid, body=data.get('body', ''))
    db.session.add(post)
    db.session.flush()
    for url in media_urls:
        m = Media(post_id=post.id, cloudinary_url=url, filename=url.split('/')[-1],
                  media_type=media_type)
        db.session.add(m)
    db.session.commit()
    return jsonify({'ok': True, 'post': _post_dict(post, uid)}), 201


@api_v1.route('/posts/<int:post_id>/like', methods=['POST'])
@jwt_required()
def toggle_like(post_id):
    uid = int(get_jwt_identity())
    post = Post.query.get_or_404(post_id)
    if not _can_view_post(uid, post):
        abort(404)
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
    post = Post.query.get_or_404(post_id)
    if not _can_view_post(uid, post):
        abort(404)
    data = request.get_json() or {}
    body = data.get('body', '').strip()
    if not body:
        return jsonify({'ok': False, 'error': 'empty_body'}), 400
    c = Comment(post_id=post_id, user_id=uid, body=body)
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
