def register_routes(app):
    from flask import render_template, redirect, url_for, request, jsonify
    from flask_login import login_required, current_user
    from extensions import db

    @app.route('/onboarding')
    @login_required
    def onboarding():
        if current_user.onboarding_done:
            return redirect(url_for('index'))
        return render_template('onboarding.html')

    @app.route('/onboarding/step/<int:step>', methods=['POST'])
    @login_required
    def onboarding_step(step):
        if current_user.onboarding_done:
            return jsonify({'ok': True})

        if step == 1:
            # Аватар — загрузка файла
            file = request.files.get('avatar')
            if file and file.filename:
                try:
                    from helpers import upload_to_cloudinary
                    url = upload_to_cloudinary(file, folder='avatars')
                    if url:
                        current_user.avatar_cloudinary_url = url
                        db.session.commit()
                except Exception as e:
                    app.logger.warning(f"Onboarding avatar upload failed: {e}")

        elif step == 2:
            # О себе
            bio = request.form.get('bio', '').strip()
            occupation = request.form.get('occupation', '').strip()
            location = request.form.get('location', '').strip()
            if bio:
                current_user.bio = bio
            if occupation:
                current_user.occupation = occupation
            if location:
                current_user.location = location
            db.session.commit()

        elif step == 3:
            # Интересы
            interests = request.form.get('interests', '').strip()
            if interests:
                current_user.interests = interests
                db.session.commit()

        elif step == 4:
            # Приватность
            is_private = request.form.get('is_private') == 'on'
            approve_followers = request.form.get('approve_followers') == 'on'
            current_user.is_private = is_private
            current_user.approve_followers = approve_followers
            db.session.commit()

        return jsonify({'ok': True})

    @app.route('/onboarding/finish', methods=['POST'])
    @login_required
    def onboarding_finish():
        current_user.onboarding_done = True
        db.session.commit()
        return jsonify({'redirect': url_for('index')})
