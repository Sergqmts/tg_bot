from flask import request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity
)
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy.exc import IntegrityError
from models import User, db
from extensions import limiter
from . import api_v1
import pyotp
import itsdangerous
from flask import current_app


@limiter.limit("5 per minute")
@api_v1.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    user = User.query.filter_by(email=email).first()
    pwd_valid = check_password_hash(user.password_hash if user else 'x', password)
    if not user or not pwd_valid:
        return jsonify({'ok': False, 'error': 'invalid_credentials'}), 401
    if user.totp_enabled:
        s = itsdangerous.URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        partial = s.dumps({'user_id': user.id, 'pending_2fa': True})
        return jsonify({'ok': True, 'requires_2fa': True, 'partial_token': partial})
    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))
    return jsonify({'ok': True, 'access_token': access, 'refresh_token': refresh,
                    'user': _user_dict(user)})


@limiter.limit("10 per minute")
@api_v1.route('/auth/2fa', methods=['POST'])
def verify_2fa():
    data = request.get_json(silent=True) or {}
    partial_token = data.get('partial_token') or ''
    code = data.get('code') or ''
    s = itsdangerous.URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        payload = s.loads(partial_token, max_age=300)
    except (itsdangerous.SignatureExpired, itsdangerous.BadTimeSignature):
        return jsonify({'ok': False, 'error': 'expired_token'}), 401
    except itsdangerous.BadSignature:
        return jsonify({'ok': False, 'error': 'invalid_token'}), 401
    user = User.query.get(payload['user_id'])
    if not user or not user.totp_enabled:
        return jsonify({'ok': False, 'error': 'invalid_request'}), 400
    if not code or len(code) != 6 or not code.isdigit():
        return jsonify({'ok': False, 'error': 'invalid_code_format'}), 400
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(code, valid_window=1):
        return jsonify({'ok': False, 'error': 'invalid_code'}), 401
    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))
    return jsonify({'ok': True, 'access_token': access, 'refresh_token': refresh,
                    'user': _user_dict(user)})


@api_v1.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip().lower()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    if not username or not email or not password:
        return jsonify({'ok': False, 'error': 'missing_fields'}), 400
    if len(password) < 10:
        return jsonify({'ok': False, 'error': 'password_too_short'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'ok': False, 'error': 'email_taken'}), 409
    if User.query.filter_by(username=username).first():
        return jsonify({'ok': False, 'error': 'username_taken'}), 409
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password, method='scrypt'),
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'ok': False, 'error': 'user_creation_failed'}), 500
    access = create_access_token(identity=str(user.id))
    refresh = create_refresh_token(identity=str(user.id))
    return jsonify({'ok': True, 'access_token': access, 'refresh_token': refresh,
                    'user': _user_dict(user)}), 201


@api_v1.route('/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    uid = get_jwt_identity()
    return jsonify({'ok': True, 'access_token': create_access_token(identity=uid)})


@api_v1.route('/auth/me', methods=['GET'])
@jwt_required()
def me():
    try:
        uid = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'invalid_token'}), 401
    user = User.query.get(uid)
    if not user:
        return jsonify({'ok': False, 'error': 'not_found'}), 404
    return jsonify({'ok': True, 'user': _user_dict(user)})


def _user_dict(u):
    return {
        'id': u.id,
        'public_id': u.public_id,
        'username': u.username,
        'email': u.email,
        'avatar': u.avatar,
        'bio': u.bio,
        'is_private': u.is_private,
        'is_staff': u.is_staff,
        'totp_enabled': u.totp_enabled,
        'is_business': getattr(u, 'is_business', False),
    }
