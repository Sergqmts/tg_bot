from datetime import datetime, timedelta
from flask import jsonify, request, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Call, User, Message, Chat, ChatMember


def format_duration(seconds):
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f'{m}:{s:02d}'


def create_call_dm_message(caller, callee, call_type, duration_sec=None,
                           missed=False):
    from helpers import get_or_create_dm
    chat = get_or_create_dm(caller, callee)
    icon = '📹' if call_type == 'video' else '📞'
    type_label = 'Видеозвонок' if call_type == 'video' else 'Аудиозвонок'
    if missed:
        body = f'{icon} Пропущенный {type_label.lower()}'
    elif duration_sec is not None:
        body = f'{icon} {type_label} · {format_duration(duration_sec)}'
    else:
        body = f'{icon} {type_label}'
    msg = Message(body=body, sender_id=caller.id, chat_id=chat.id)
    db.session.add(msg)
    db.session.flush()
    return msg


def create_notification(user_id, sender_id, notif_type, message_id=None):
    try:
        if user_id == sender_id:
            return
        from models import Notification
        notification = Notification(
            user_id=user_id, sender_id=sender_id,
            type=notif_type, message_id=message_id
        )
        db.session.add(notification)
        db.session.commit()
    except Exception as e:
        current_app.logger.error(f"Notification error: {e}")


def register_routes(app):

    @app.route('/api/calls/initiate', methods=['POST'])
    @login_required
    def initiate_call():
        data = request.get_json()
        callee_id = data.get('callee_id')
        call_type = data.get('call_type', 'audio')

        if not callee_id:
            return jsonify({'error': 'callee_id required'}), 400

        callee = User.query.get(callee_id)
        if not callee:
            return jsonify({'error': 'user not found'}), 404

        if callee_id == current_user.id:
            return jsonify({'error': 'cannot call yourself'}), 400

        cutoff = datetime.utcnow() - timedelta(seconds=30)
        stale = Call.query.filter(
            db.or_(
                db.and_(Call.caller_id == current_user.id, Call.callee_id == callee_id),
                db.and_(Call.caller_id == callee_id, Call.callee_id == current_user.id),
            ),
            Call.status == 'ringing',
            Call.created_at < cutoff,
        ).all()
        for s in stale:
            s.status = 'missed'
            s.ended_at = datetime.utcnow()
            caller = User.query.get(s.caller_id)
            callee_user = User.query.get(s.callee_id)
            if caller and callee_user:
                msg = create_call_dm_message(
                    caller, callee_user, s.call_type, missed=True
                )
                create_notification(
                    callee_user.id, caller.id, 'call_missed',
                    message_id=msg.id
                )

        active = Call.query.filter(
            db.or_(
                db.and_(Call.caller_id == current_user.id, Call.callee_id == callee_id),
                db.and_(Call.caller_id == callee_id, Call.callee_id == current_user.id),
            ),
            Call.status.in_(['ringing', 'ongoing'])
        ).first()
        if active:
            return jsonify({'error': 'active call already exists', 'call_id': active.id}), 409

        call = Call(
            caller_id=current_user.id,
            callee_id=callee_id,
            call_type=call_type,
            status='ringing'
        )
        db.session.add(call)
        db.session.commit()

        return jsonify({
            'call_id': call.id,
            'caller_id': current_user.id,
            'caller_username': current_user.username,
            'callee_id': callee_id,
            'call_type': call_type,
            'status': call.status,
        }), 201

    @app.route('/api/calls/<int:call_id>/status', methods=['GET'])
    @login_required
    def call_status(call_id):
        call = Call.query.get_or_404(call_id)
        if current_user.id not in (call.caller_id, call.callee_id):
            return jsonify({'error': 'forbidden'}), 403
        return jsonify({
            'call_id': call.id,
            'status': call.status,
            'call_type': call.call_type,
        })

    @app.route('/api/calls/<int:call_id>/answer', methods=['POST'])
    @login_required
    def answer_call(call_id):
        call = Call.query.get_or_404(call_id)
        if current_user.id not in (call.caller_id, call.callee_id):
            return jsonify({'error': 'forbidden'}), 403
        if call.status == 'ringing' and not call.started_at:
            call.status = 'ongoing'
            call.started_at = datetime.utcnow()
            db.session.commit()
        return jsonify({'status': call.status})

    @app.route('/api/calls/<int:call_id>/end', methods=['POST'])
    @login_required
    def end_call(call_id):
        call = Call.query.get_or_404(call_id)
        if current_user.id not in (call.caller_id, call.callee_id):
            return jsonify({'error': 'forbidden'}), 403
        if call.status in ('ringing', 'ongoing'):
            was_ongoing = call.status == 'ongoing'
            call.status = 'ended'
            call.ended_at = datetime.utcnow()
            db.session.flush()

            caller = User.query.get(call.caller_id)
            callee = User.query.get(call.callee_id)
            if caller and callee:
                if call.started_at and was_ongoing:
                    duration = (call.ended_at - call.started_at).total_seconds()
                    msg = create_call_dm_message(
                        caller, callee, call.call_type, duration_sec=duration
                    )
                else:
                    msg = create_call_dm_message(
                        caller, callee, call.call_type, missed=True
                    )
                    other_id = call.callee_id if current_user.id == call.caller_id else call.caller_id
                    create_notification(
                        other_id, call.caller_id, 'call_missed',
                        message_id=msg.id
                    )

            db.session.commit()
        return jsonify({'status': 'ended'})

    @app.route('/api/calls/history', methods=['GET'])
    @login_required
    def call_history():
        calls = Call.query.filter(
            db.or_(Call.caller_id == current_user.id, Call.callee_id == current_user.id)
        ).order_by(Call.created_at.desc()).limit(50).all()

        result = []
        for call in calls:
            other = call.callee if call.caller_id == current_user.id else call.caller
            result.append({
                'call_id': call.id,
                'with_user_id': other.id,
                'with_username': other.username,
                'call_type': call.call_type,
                'status': call.status,
                'direction': 'outgoing' if call.caller_id == current_user.id else 'incoming',
                'started_at': call.started_at.isoformat() if call.started_at else None,
                'ended_at': call.ended_at.isoformat() if call.ended_at else None,
                'created_at': call.created_at.isoformat(),
            })
        return jsonify(result)
