from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Story, StoryView, db, followers
from . import api_v1
from datetime import datetime


@api_v1.route('/stories', methods=['GET'])
@jwt_required()
def get_stories():
    uid = int(get_jwt_identity())
    followed = db.session.query(followers.c.followed_id).filter(
        followers.c.follower_id == uid,
        followers.c.status == 'approved'
    ).subquery()
    now = datetime.utcnow()
    stories = Story.query.filter(
        (Story.user_id == uid) | Story.user_id.in_(followed),
        Story.expires_at > now,
        Story.is_archived == False
    ).order_by(Story.created_at.desc()).all()
    return jsonify({'ok': True, 'stories': [_story_dict(s, uid) for s in stories]})


@api_v1.route('/stories/<int:story_id>/view', methods=['POST'])
@jwt_required()
def view_story(story_id):
    uid = int(get_jwt_identity())
    s = Story.query.get_or_404(story_id)
    now = datetime.utcnow()
    if s.is_archived or s.expires_at <= now:
        abort(404)
    if s.user_id != uid:
        if s.user.is_private:
            approved = db.session.query(followers).filter_by(
                follower_id=uid, followed_id=s.user_id, status='approved').first()
            if not approved:
                abort(404)
    if not StoryView.query.filter_by(story_id=story_id, user_id=uid).first():
        db.session.add(StoryView(story_id=story_id, user_id=uid))
        db.session.commit()
    return jsonify({'ok': True})


def _story_dict(s, uid):
    viewed = StoryView.query.filter_by(story_id=s.id, user_id=uid).first() is not None
    return {
        'id': s.id, 'media_url': s.media_url, 'media_type': s.media_type,
        'created_at': s.created_at.isoformat(), 'expires_at': s.expires_at.isoformat(),
        'user': {'id': s.user.id, 'username': s.user.username, 'avatar': s.user.avatar},
        'views_count': s.views.count(), 'viewed_by_me': viewed,
    }
