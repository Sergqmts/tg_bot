def register_routes(app):
    from flask import render_template, redirect, url_for, flash, request, session
    from flask_login import login_required, current_user
    from extensions import db, limiter
    from models import User
    import pyotp
    import qrcode
    import io
    import base64

    def _generate_totp_uri(user, secret):
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=user.email,
            issuer_name='VIBE'
        )

    def _secret_to_qr_base64(uri):
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    @app.route('/settings/2fa', methods=['GET'])
    @login_required
    def settings_2fa():
        secret = None
        qr_b64 = None
        if not current_user.totp_enabled:
            secret = pyotp.random_base32()
            session['totp_setup_secret'] = secret
            uri = _generate_totp_uri(current_user, secret)
            qr_b64 = _secret_to_qr_base64(uri)
        return render_template('settings_2fa.html', secret=secret, qr_b64=qr_b64)

    @app.route('/settings/2fa/enable', methods=['POST'])
    @login_required
    @limiter.limit('5 per minute')
    def settings_2fa_enable():
        secret = session.get('totp_setup_secret')
        code = request.form.get('code', '').strip()
        if not code or not code.isdigit() or len(code) != 6:
            flash('Код должен содержать 6 цифр.')
            return redirect(url_for('settings_2fa'))
        if not secret:
            flash('Сессия истекла. Начните заново.')
            return redirect(url_for('settings_2fa'))
        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            flash('Неверный код. Проверьте время на устройстве и попробуйте снова.')
            return redirect(url_for('settings_2fa'))
        current_user.totp_secret = secret
        current_user.totp_enabled = True
        db.session.commit()
        session.pop('totp_setup_secret', None)
        flash('Двухфакторная аутентификация включена.')
        return redirect(url_for('settings_2fa'))

    @app.route('/settings/2fa/disable', methods=['POST'])
    @login_required
    @limiter.limit('5 per minute')
    def settings_2fa_disable():
        code = request.form.get('code', '').strip()
        if not code or not code.isdigit() or len(code) != 6:
            flash('Код должен содержать 6 цифр.')
            return redirect(url_for('settings_2fa'))
        if not current_user.totp_enabled or not current_user.totp_secret:
            flash('2FA не включена.')
            return redirect(url_for('settings_2fa'))
        totp = pyotp.TOTP(current_user.totp_secret)
        if not totp.verify(code, valid_window=1):
            flash('Неверный код.')
            return redirect(url_for('settings_2fa'))
        current_user.totp_secret = None
        current_user.totp_enabled = False
        db.session.commit()
        flash('Двухфакторная аутентификация отключена.')
        return redirect(url_for('settings_2fa'))
