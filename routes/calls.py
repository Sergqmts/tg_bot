from datetime import datetime
from flask import jsonify, request, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Call, User


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

    @app.route('/api/calls/<int:call_id>/end', methods=['POST'])
    @login_required
    def end_call(call_id):
        call = Call.query.get_or_404(call_id)
        if current_user.id not in (call.caller_id, call.callee_id):
            return jsonify({'error': 'forbidden'}), 403
        if call.status in ('ringing', 'ongoing'):
            call.status = 'ended'
            call.ended_at = datetime.utcnow()
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
