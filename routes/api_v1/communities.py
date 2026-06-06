from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Community, CommunityMember, db
from . import api_v1


@api_v1.route('/communities', methods=['GET'])
@jwt_required()
def list_communities():
    comms = Community.query.filter_by(is_private=False).limit(50).all()
    return jsonify({'ok': True, 'communities': [_comm(c) for c in comms]})


@api_v1.route('/communities/<slug>', methods=['GET'])
@jwt_required()
def get_community(slug):
    c = Community.query.filter_by(slug=slug).first_or_404()
    return jsonify({'ok': True, 'community': _comm(c, with_posts=True)})


@api_v1.route('/communities/<slug>/join', methods=['POST'])
@jwt_required()
def join_community(slug):
    uid = int(get_jwt_identity())
    c = Community.query.filter_by(slug=slug).first_or_404()
    status = 'pending' if c.is_private else 'approved'
    if not CommunityMember.query.filter_by(community_id=c.id, user_id=uid).first():
        db.session.add(CommunityMember(community_id=c.id, user_id=uid, role='member', status=status))
        db.session.commit()
    return jsonify({'ok': True, 'status': status})


@api_v1.route('/communities/<slug>/leave', methods=['POST'])
@jwt_required()
def leave_community(slug):
    uid = int(get_jwt_identity())
    c = Community.query.filter_by(slug=slug).first_or_404()
    CommunityMember.query.filter_by(community_id=c.id, user_id=uid).delete()
    db.session.commit()
    return jsonify({'ok': True})


def _comm(c, with_posts=False):
    d = {
        'id': c.id, 'name': c.name, 'slug': c.slug,
        'description': c.description, 'image': c.image,
        'is_private': c.is_private,
        'members_count': CommunityMember.query.filter_by(
            community_id=c.id, status='approved').count(),
    }
    if with_posts:
        d['posts'] = [
            {'id': p.id, 'body': p.body[:100], 'created_at': p.created_at.isoformat()}
            for p in c.posts[-20:]
        ]
    return d
