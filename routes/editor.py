def register_routes(app):
    import os
    from datetime import datetime, timedelta
    from flask import request, jsonify, redirect, url_for, abort, current_app
    from flask_login import login_required, current_user
    from extensions import db
    from models import Post, Story, Shorts, Draft, Media, MusicTrack
    import jwt as pyjwt

    EDITOR_SERVICE_TOKEN = os.environ.get('EDITOR_SERVICE_TOKEN')
    JWT_SECRET = os.environ.get('EDITOR_JWT_SECRET') or app.config.get('SECRET_KEY', 'dev-secret')
    EDITOR_SERVICE_URL = os.environ.get('EDITOR_SERVICE_URL', 'http://localhost:8080').rstrip('/')

    def check_service_token():
        token = request.headers.get('X-Service-Token')
        if not token or token != EDITOR_SERVICE_TOKEN:
            abort(403)

    def generate_editor_token(user):
        payload = {
            'user_id': user.id,
            'username': user.username,
            'exp': datetime.utcnow() + timedelta(hours=1),
        }
        return pyjwt.encode(payload, JWT_SECRET, algorithm='HS256')

    @app.route('/api/editor/publish', methods=['POST'])
    def editor_publish():
        check_service_token()
        data = request.get_json(force=True)

        image_url = data.get('image_url')
        caption = data.get('caption', '')
        target = data.get('target', 'feed')
        user_id = data.get('user_id')
        return_url = data.get('return_url')

        if not image_url or not user_id:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        if target == 'feed':
            post = Post(body=caption, user_id=user_id)
            db.session.add(post)
            db.session.flush()
            media = Media(filename='editor', cloudinary_url=image_url, media_type='image', post_id=post.id)
            db.session.add(media)
            db.session.commit()
            response = {'post_id': post.id}

        elif target == 'story':
            story = Story(
                user_id=user_id,
                media_url=image_url,
                media_type='image',
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            db.session.add(story)
            db.session.commit()
            response = {'post_id': story.id}

        elif target == 'shorts':
            shorts = Shorts(video_url=image_url, caption=caption, user_id=user_id)
            db.session.add(shorts)
            db.session.commit()
            response = {'post_id': shorts.id}

        elif target == 'draft':
            draft = Draft(user_id=user_id, caption=caption, media_data=image_url)
            db.session.add(draft)
            db.session.commit()
            response = {'post_id': draft.id}

        else:
            return jsonify({'status': 'error', 'message': 'Invalid target'}), 400

        if return_url:
            response['redirect_url'] = return_url
        return jsonify(response)

    @app.route('/api/editor/publish-video', methods=['POST'])
    def editor_publish_video():
        check_service_token()
        data = request.get_json(force=True)

        cloudinary_url = data.get('cloudinary_url')
        caption = data.get('caption', '')
        user_id = data.get('user_id')
        audio_id = data.get('audio_id')

        if not cloudinary_url or not user_id:
            return jsonify({'status': 'error', 'message': 'Missing required fields'}), 400

        audio = MusicTrack.query.get(audio_id) if audio_id else None

        shorts = Shorts(
            video_url=cloudinary_url,
            caption=caption,
            user_id=user_id,
            audio_id=audio.id if audio else None
        )
        db.session.add(shorts)
        db.session.commit()

        return jsonify({'shorts_id': shorts.id})

    @app.route('/api/editor/draft/<int:draft_id>')
    def editor_get_draft(draft_id):
        check_service_token()
        draft = Draft.query.get(draft_id)
        if not draft:
            return jsonify({'status': 'error', 'message': 'Draft not found'})
        return jsonify({'media_data': draft.media_data, 'caption': draft.caption})

    @app.route('/proxy/edit/photo')
    @login_required
    def proxy_photo_editor():
        return redirect(url_for('photo_editor', **request.args))

    @app.route('/proxy/edit/video')
    @login_required
    def proxy_video_editor():
        return redirect(url_for('video_editor'))
