from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Message, Chat, ChatMember, MessageMedia, db, User
from . import api_v1
from sqlalchemy import or_, desc


@api_v1.route('/messages/conversations', methods=['GET'])
@jwt_required()
def conversations():
    uid = int(get_jwt_identity())
    dms = Message.query.filter(
        or_(Message.sender_id == uid, Message.recipient_id == uid),
        Message.chat_id == None
    ).order_by(desc(Message.created_at)).all()
    seen = set()
    result = []
    for m in dms:
        partner_id = m.recipient_id if m.sender_id == uid else m.sender_id
        if partner_id and partner_id not in seen:
            seen.add(partner_id)
            partner = User.query.get(partner_id)
            if not partner:
                continue
            unread = Message.query.filter_by(
                sender_id=partner_id, recipient_id=uid, read=False).count()
            result.append({
                'type': 'dm', 'partner': {
                    'id': partner.id, 'username': partner.username, 'avatar': partner.avatar
                },
                'last_message': {'body': m.body or '', 'created_at': m.created_at.isoformat()},
                'unread': unread,
            })
    memberships = ChatMember.query.filter_by(user_id=uid).all()
    for cm in memberships:
        chat = cm.chat
        last = chat.messages.order_by(desc(Message.created_at)).first()
        result.append({
            'type': 'group', 'chat': {
                'id': chat.id, 'name': chat.name,
            },
            'last_message': {'body': last.body or '' if last else '',
                             'created_at': last.created_at.isoformat() if last else ''},
            'unread': 0,
        })
    result.sort(key=lambda x: x['last_message']['created_at'], reverse=True)
    return jsonify({'ok': True, 'conversations': result})


@api_v1.route('/messages/dm/<int:partner_id>', methods=['GET'])
@jwt_required()
def get_dm(partner_id):
    uid = int(get_jwt_identity())
    page = request.args.get('page', 1, type=int)
    msgs = Message.query.filter(
        or_(
            (Message.sender_id == uid) & (Message.recipient_id == partner_id),
            (Message.sender_id == partner_id) & (Message.recipient_id == uid)
        ),
        Message.chat_id == None
    ).order_by(desc(Message.created_at)).paginate(page=page, per_page=40, error_out=False)
    Message.query.filter_by(sender_id=partner_id, recipient_id=uid, read=False).update({'read': True})
    db.session.commit()
    return jsonify({'ok': True, 'messages': [_msg_dict(m) for m in reversed(msgs.items)],
                    'has_more': msgs.has_next})


@api_v1.route('/messages/dm/<int:partner_id>', methods=['POST'])
@jwt_required()
def send_dm(partner_id):
    uid = int(get_jwt_identity())
    data = request.get_json()
    m = Message(sender_id=uid, recipient_id=partner_id, body=data.get('body', ''))
    db.session.add(m)
    db.session.commit()
    return jsonify({'ok': True, 'message': _msg_dict(m)}), 201


def _msg_dict(m):
    return {
        'id': m.id, 'body': m.body or '', 'sender_id': m.sender_id,
        'recipient_id': m.recipient_id, 'chat_id': m.chat_id,
        'created_at': m.created_at.isoformat(), 'read': m.read,
        'media': [{'url': mm.media_url, 'type': mm.media_type} for mm in m.medias] if m.medias else [],
    }
