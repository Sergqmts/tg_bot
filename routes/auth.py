def register_routes(app):
    from flask import render_template, redirect, url_for, flash, request, current_app
    from flask_login import login_user, logout_user, login_required, current_user
    from extensions import db
    from models import User, RegistrationForm, LoginForm
    from authlib.integrations.flask_client import OAuth
    import secrets

    oauth = OAuth(app)
    google_client_id = app.config.get('GOOGLE_CLIENT_ID', '')
    google_client_secret = app.config.get('GOOGLE_CLIENT_SECRET', '')

    if google_client_id and google_client_secret:
        oauth.register(
            name='google',
            client_id=google_client_id,
            client_secret=google_client_secret,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = RegistrationForm()
        if form.validate_on_submit():
            user = User(username=form.username.data, email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            try:
                from helpers import send_welcome_dm
                send_welcome_dm(user)
            except Exception as e:
                current_app.logger.warning(f"Welcome DM failed: {e}")
            flash('Регистрация прошла успешно! Войдите в аккаунт.')
            return redirect(url_for('login'))
        return render_template('register.html', form=form)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and user.check_password(form.password.data):
                if user.is_banned:
                    flash('Ваш аккаунт заблокирован за нарушение правил')
                    return render_template('login.html', form=form)
                login_user(user, remember=form.remember.data)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('index'))
            flash('Неверное имя пользователя или пароль')
        return render_template('login.html', form=form)

    @app.route('/login/google')
    def google_login():
        if not google_client_id or not google_client_secret:
            flash('Google вход не настроен')
            return redirect(url_for('login'))
        redirect_uri = url_for('google_callback', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    @app.route('/login/google/callback')
    def google_callback():
        if not google_client_id or not google_client_secret:
            flash('Google вход не настроен')
            return redirect(url_for('login'))
        try:
            token = oauth.google.authorize_access_token()
            userinfo = token.get('userinfo')
            if not userinfo:
                userinfo = oauth.google.parse_id_token(token)
        except Exception as e:
            current_app.logger.error(f'Google auth error: {e}')
            flash('Ошибка входа через Google')
            return redirect(url_for('login'))

        google_id = userinfo.get('sub')
        email = userinfo.get('email', '')
        name = userinfo.get('name', '')
        picture = userinfo.get('picture', '')

        if not google_id:
            flash('Не удалось получить данные от Google')
            return redirect(url_for('login'))

        user = User.query.filter_by(google_id=google_id).first()

        if user:
            login_user(user)
            return redirect(url_for('index'))

        user_by_email = User.query.filter_by(email=email).first()
        if user_by_email:
            user_by_email.google_id = google_id
            if picture and not user_by_email.avatar_cloudinary_url:
                user_by_email.avatar_cloudinary_url = picture
            db.session.commit()
            login_user(user_by_email)
            return redirect(url_for('index'))

        base_username = (email.split('@')[0] if email else name.replace(' ', '_').lower() or f'user_{secrets.token_hex(4)}')
        username = base_username[:50]
        attempt = 1
        while User.query.filter_by(username=username).first():
            suffix = secrets.token_hex(2)
            username = f'{base_username[:42]}_{suffix}'
            attempt += 1
            if attempt > 10:
                username = f'user_{secrets.token_hex(4)}'
                break

        password = secrets.token_urlsafe(32)
        user = User(
            username=username,
            email=email or f'{google_id}@google.local',
            google_id=google_id,
        )
        user.set_password(password)
        if picture:
            user.avatar_cloudinary_url = picture
        db.session.add(user)
        db.session.commit()
        try:
            from helpers import send_welcome_dm
            send_welcome_dm(user)
        except Exception as e:
            current_app.logger.warning(f"Welcome DM (Google) failed: {e}")
        login_user(user)
        flash(f'Добро пожаловать! Ваш username: {username}')
        return redirect(url_for('index'))

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('index'))
