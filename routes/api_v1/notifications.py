from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Notification, User, db
from . import api_v1
from sqlalchemy import desc


@api_v1.route('/notifications/register-device', methods=['POST'])
@jwt_required()
def register_device():
    uid = int(get_jwt_identity())
    data = request.get_json()
    user = User.query.get(uid)
    user.fcm_token = data.get('fcm_token')
    db.session.commit()
    return jsonify({'ok': True})


@api_v1.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    uid = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    notifs = Notification.query.filter_by(user_id=uid).order_by(
        desc(Notification.created_at)).paginate(page=page, per_page=30, error_out=False)
    return jsonify({'ok': True, 'notifications': [
        {'id': n.id, 'type': n.type, 'read': n.read,
         'sender_id': n.sender_id, 'post_id': n.post_id,
         'created_at': n.created_at.isoformat()} for n in notifs.items
    ], 'has_next': notifs.has_next})


@api_v1.route('/notifications/read-all', methods=['POST'])
@jwt_required()
def read_all():
    uid = int(get_jwt_identity())
    Notification.query.filter_by(user_id=uid, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'ok': True})
