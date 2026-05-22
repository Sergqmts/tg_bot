def register_routes(app):
    import os, re
    from datetime import datetime, timedelta
    from flask import request, jsonify, redirect, url_for, abort, current_app
    from flask_login import login_required, current_user
    from extensions import db
    from models import Post, Story, Shorts, Draft, Media, MusicTrack
    import jwt as pyjwt
    import requests as http_requests

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

    def _proxy_editor_html(path, params, fallback_route):
        if 'token' not in params:
            params['token'] = generate_editor_token(current_user)
        try:
            resp = http_requests.get(
                f"{EDITOR_SERVICE_URL}{path}",
                params=params,
                timeout=30,
                headers={'User-Agent': 'VibeHub-Proxy/1.0'}
            )
            resp.raise_for_status()
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                html = resp.text
                html = re.sub(
                    r'<link[^>]*\brel=["\'](?:shortcut\s+)?icon["\'][^>]*>',
                    '',
                    html,
                    flags=re.IGNORECASE
                )
                scheme = 'https' if request.headers.get('X-Forwarded-Proto', request.scheme) == 'https' else request.scheme
                favicon_url = url_for('favicon', _scheme=scheme, _external=True)
                html = re.sub(
                    r'</head>',
                    f'<link rel="icon" type="image/x-icon" href="{favicon_url}"></head>',
                    html,
                    flags=re.IGNORECASE
                )
                html = re.sub(
                    r'<head[^>]*>',
                    lambda m: m.group() + f'<base href="{EDITOR_SERVICE_URL}/">',
                    html,
                    flags=re.IGNORECASE
                )
                return html, resp.status_code
            else:
                return resp.content, resp.status_code
        except Exception as e:
            app.logger.error(f"Editor proxy error: {e}")
            return redirect(url_for(fallback_route, **request.args))

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
        if not EDITOR_SERVICE_TOKEN:
            return redirect(url_for('photo_editor', **request.args))
        if 'token' not in request.args:
            token = generate_editor_token(current_user)
            args = dict(request.args)
            args['token'] = token
            return redirect(url_for('proxy_photo_editor', **args))
        params = dict(request.args)
        result = _proxy_editor_html('/photo', params, 'photo_editor')
        if isinstance(result, tuple):
            return result[0], result[1]
        return result

    @app.route('/proxy/edit/video')
    @login_required
    def proxy_video_editor():
        if not EDITOR_SERVICE_TOKEN:
            return redirect(url_for('video_editor'))
        if 'token' not in request.args:
            token = generate_editor_token(current_user)
            args = dict(request.args)
            args['token'] = token
            return redirect(url_for('proxy_video_editor', **args))
        result = _proxy_editor_html('/video', dict(request.args), 'video_editor')
        if isinstance(result, tuple):
            return result[0], result[1]
        return result
