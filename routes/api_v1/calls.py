from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import Call, User, db
from . import api_v1
import datetime


@api_v1.route('/calls/initiate', methods=['POST'])
@jwt_required()
def initiate_call():
    uid = int(get_jwt_identity())
    data = request.get_json()
    callee = User.query.filter_by(username=data['callee_username']).first_or_404()
    call = Call(
        caller_id=uid, callee_id=callee.id,
        call_type=data.get('call_type', 'video'), status='ringing',
    )
    db.session.add(call)
    db.session.commit()
    return jsonify({'ok': True, 'call_id': call.id})


@api_v1.route('/calls/<int:call_id>/answer', methods=['POST'])
@jwt_required()
def answer_call(call_id):
    call = Call.query.get_or_404(call_id)
    call.status = 'ongoing'
    call.started_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@api_v1.route('/calls/<int:call_id>/end', methods=['POST'])
@jwt_required()
def end_call(call_id):
    call = Call.query.get_or_404(call_id)
    call.status = 'ended'
    call.ended_at = datetime.datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@api_v1.route('/calls/turn-credentials', methods=['GET'])
@jwt_required()
def turn_credentials():
    from routes.calls import get_turn_credentials
    creds = get_turn_credentials()
    return jsonify({'ok': True, 'credentials': creds or []})
