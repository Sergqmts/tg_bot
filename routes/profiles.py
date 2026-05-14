def register_routes(app):
    import os
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from datetime import datetime, timedelta
    from extensions import db, csrf
    from models import User, Post, Repost, Shorts, ShortsComment, ShortsLike, ShortsReaction, ShortsAudio, Notification, Tag, Community, Media, SavedPost, EditProfileForm, ProfileVisit

    @app.route('/user/<username>')
    def user_profile(username):
        user = User.query.filter_by(username=username).first_or_404()

        if user.is_business and current_user.is_authenticated and current_user.id != user.id:
            visit = ProfileVisit(profile_id=user.id, visitor_id=current_user.id)
            db.session.add(visit)
            db.session.commit()

        blocked_by_user = current_user.is_authenticated and current_user.is_blocking(user)

        if blocked_by_user:
            posts = []
            user_reposts = []
            can_view = False
        elif user.is_private and user != current_user:
            can_view = current_user.is_authenticated and (current_user.is_following(user) or current_user.is_staff)
            if can_view:
                posts = user.posts.order_by(Post.created_at.desc()).all()
                user_reposts = Repost.query.filter_by(user_id=user.id).order_by(Repost.created_at.desc()).all()
            else:
                posts = []
                user_reposts = []
        else:
            can_view = True
            posts = user.posts.order_by(Post.created_at.desc()).all()
            user_reposts = Repost.query.filter_by(user_id=user.id).order_by(Repost.created_at.desc()).all()

        repost_counts = {}
        for p in posts:
            repost_counts[p.id] = Repost.query.filter_by(post_id=p.id).count() if p.id else 0
        is_following = current_user.is_authenticated and current_user.is_following(user)
        is_blocked = current_user.is_authenticated and current_user.is_blocking(user)
        is_pending = current_user.is_authenticated and current_user.is_pending(user)
        pending_count = len(current_user.get_pending_followers()) if current_user.is_authenticated and user.id == current_user.id else 0

        user_shorts = Shorts.query.filter_by(user_id=user.id).order_by(Shorts.created_at.desc()).all()
        shorts_likes = {s.id: s.likes.count() for s in user_shorts}
        shorts_comments = {s.id: s.comments.count() for s in user_shorts}

        return render_template('profile.html', user=user, posts=posts, user_reposts=user_reposts, repost_counts=repost_counts, is_following=is_following, is_blocked=is_blocked, is_pending=is_pending, can_view=can_view, pending_count=pending_count, user_shorts=user_shorts, shorts_likes=shorts_likes, shorts_comments=shorts_comments)


    @app.route('/follow/<username>', methods=['POST'])
    @login_required
    @csrf.exempt
    def follow(username):
        user = User.query.filter_by(username=username).first_or_404()
        if user != current_user:
            from helpers import create_notification
            if user.approve_followers:
                current_user.follow(user)
                db.session.commit()
                create_notification(user.id, current_user.id, 'follow_request')
                flash(f'Запрос на подписку отправлен {user.username}. Ожидайте одобрения.')
            else:
                current_user.follow(user)
                db.session.commit()
                create_notification(user.id, current_user.id, 'follow')
                flash(f'Вы подписались на {user.username}')
        return redirect(url_for('user_profile', username=user.username))


    @app.route('/unfollow/<username>', methods=['POST'])
    @login_required
    @csrf.exempt
    def unfollow(username):
        user = User.query.filter_by(username=username).first_or_404()
        current_user.unfollow(user)
        db.session.commit()
        flash(f'Вы отписались от {user.username}')
        return redirect(url_for('user_profile', username=user.username))


    @app.route('/block/<username>', methods=['POST'])
    @login_required
    @csrf.exempt
    def block_user(username):
        user = User.query.filter_by(username=username).first_or_404()
        if user != current_user:
            current_user.block(user)
            db.session.commit()
            flash(f'Вы заблокировали {user.username}')
        return redirect(url_for('user_profile', username=user.username))


    @app.route('/unblock/<username>', methods=['POST'])
    @login_required
    @csrf.exempt
    def unblock_user(username):
        user = User.query.filter_by(username=username).first_or_404()
        current_user.unblock(user)
        db.session.commit()
        flash(f'Вы разблокировали {user.username}')
        return redirect(url_for('user_profile', username=user.username))


    @app.route('/followers/requests')
    @login_required
    def follower_requests():
        pending = current_user.get_pending_followers()
        return render_template('follower_requests.html', pending=pending)


    @app.route('/followers/approve/<username>', methods=['POST'])
    @login_required
    def approve_follower(username):
        user = User.query.filter_by(username=username).first_or_404()
        current_user.approve_follower(user)
        from helpers import create_notification
        create_notification(user.id, current_user.id, 'follow_approved')
        flash(f'Вы одобрили подписку {user.username}')
        return redirect(url_for('follower_requests'))


    @app.route('/followers/reject/<username>', methods=['POST'])
    @login_required
    def reject_follower(username):
        user = User.query.filter_by(username=username).first_or_404()
        current_user.reject_follower(user)
        flash(f'Запрос на подписку от {user.username} отклонён')
        return redirect(url_for('follower_requests'))


    @app.route('/notifications')
    @login_required
    def notifications():
        page = request.args.get('page', 1, type=int)
        notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
        unread_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
        return render_template('notifications.html', notifications=notifications, unread_count=unread_count)


    @app.route('/notifications/read/<int:notification_id>', methods=['POST'])
    @login_required
    def mark_notification_read(notification_id):
        notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
        notification.read = True
        db.session.commit()
        return redirect(request.referrer or url_for('notifications'))


    @app.route('/notifications/read_all', methods=['POST'])
    @login_required
    def mark_all_read():
        Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
        db.session.commit()
        return redirect(request.referrer or url_for('notifications'))


    @app.route('/edit_profile', methods=['GET', 'POST'])
    @login_required
    def edit_profile():
        form = EditProfileForm()
        if form.validate_on_submit():
            new_username = form.username.data.strip().lstrip('@')

            existing_user = User.query.filter(User.username == new_username, User.id != current_user.id).first()
            if existing_user:
                flash('Этот username уже занят другим пользователем')
                return redirect(url_for('edit_profile'))

            current_user.username = new_username
            current_user.bio = form.bio.data
            current_user.location = form.location.data
            current_user.website = form.website.data
            current_user.occupation = form.occupation.data
            current_user.interests = form.interests.data
            current_user.is_private = form.is_private.data
            current_user.hide_followers = form.hide_followers.data
            current_user.hide_following = form.hide_following.data
            current_user.approve_followers = form.approve_followers.data

            if form.avatar.data:
                file = form.avatar.data
                from helpers import cloudinary_configured, upload_to_cloudinary
                if cloudinary_configured:
                    url = upload_to_cloudinary(file, folder='avatars')
                    if url:
                        current_user.avatar_cloudinary_url = url
                        current_user.avatar = url.split('/')[-1].split('.')[0]
                else:
                    filename = secure_filename(f"{datetime.now().timestamp}_{file.filename}")
                    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                    current_user.avatar = filename
                    current_user.avatar_cloudinary_url = None

            if form.birthday.data:
                try:
                    current_user.birthday = datetime.strptime(form.birthday.data, '%d.%m.%Y').date()
                except ValueError:
                    flash('Неверный формат даты. Используйте ДД.ММ.ГГГГГ')
                    return render_template('edit_profile.html', form=form)

            if form.phone.data:
                phone = ''.join(c for c in form.phone.data if c.isdigit())
                if phone and phone != (current_user.phone or '').replace('+', '').replace(' ', '').replace('-', ''):
                    if len(phone) >= 10:
                        import random
                        otp = str(random.randint(100000, 999999))
                        current_user.phone_otp = otp
                        current_user.phone_otp_expires = datetime.utcnow() + timedelta(minutes=5)
                        current_user.phone = phone
                        flash(f'Код подтверждения отправлен на {phone}. Введите код на странице подтверждения.')
                    else:
                        flash('Номер телефона слишком короткий')

            db.session.commit()
            flash('Профиль обновлён')
            return redirect(url_for('user_profile', username=current_user.username))
        elif request.method == 'GET':
            form.username.data = current_user.username
            form.bio.data = current_user.bio
            form.location.data = current_user.location
            form.website.data = current_user.website
            form.occupation.data = current_user.occupation
            form.interests.data = current_user.interests
            form.is_private.data = current_user.is_private
            form.hide_followers.data = current_user.hide_followers
            form.hide_following.data = current_user.hide_following
            form.approve_followers.data = current_user.approve_followers
            form.phone.data = current_user.phone
            if current_user.birthday:
                form.birthday.data = current_user.birthday.strftime('%d.%m.%Y')
        return render_template('edit_profile.html', form=form)


    @app.route('/verify_phone', methods=['GET', 'POST'])
    @login_required
    def verify_phone():
        if request.method == 'POST':
            otp = request.form.get('otp', '')
            if current_user.phone_otp and current_user.phone_otp == otp:
                if current_user.phone_otp_expires and current_user.phone_otp_expires > datetime.utcnow():
                    current_user.phone_verified = True
                    current_user.phone_otp = None
                    current_user.phone_otp_expires = None
                    db.session.commit()
                    flash('Номер телефона подтверждён!')
                else:
                    flash('Код истёк. Запросите новый код.')
            else:
                flash('Неверный код')
            return redirect(url_for('verify_phone'))

        if current_user.phone and not current_user.phone_verified:
            import random
            otp = str(random.randint(100000, 999999))
            current_user.phone_otp = otp
            current_user.phone_otp_expires = datetime.utcnow() + timedelta(minutes=5)
            db.session.commit()
            flash(f'Код {otp} отправлен (демо-режим: код показан в flash-сообщении)')

        return render_template('verify_phone.html')


    @app.route('/explore')
    @app.route('/search')
    def explore():
        search_query = request.args.get('q', '')
        search_type = request.args.get('type', 'users')
        blocked_ids = []
        if current_user.is_authenticated:
            blocked_ids = [u.id for u in current_user.blocked]

        users = []
        tags = []
        posts = []
        communities = []

        if search_query.lstrip('#'):
            if search_type == 'tags':
                tags = Tag.query.filter(
                    Tag.name.ilike(f'%{search_query.lstrip("#")}%')
                ).order_by(Tag.created_at.desc()).limit(50).all()
            elif search_type == 'communities':
                communities = Community.query.filter(
                    Community.name.ilike(f'%{search_query}%')
                ).order_by(Community.created_at.desc()).limit(50).all()
            elif search_type == 'posts':
                posts = Post.query.filter(
                    Post.user_id.notin_(blocked_ids) if blocked_ids else True,
                    Post.body.ilike(f'%#{search_query.lstrip("#")}%')
                ).order_by(Post.created_at.desc()).limit(50).all()
                if search_query.lstrip('#'):
                    tags = Tag.query.filter(
                        Tag.name.ilike(f'%{search_query.lstrip("#")}%')
                    ).order_by(Tag.created_at.desc()).limit(20).all()
            else:
                users = User.query.filter(
                    ~User.id.in_(blocked_ids) if blocked_ids else True,
                    User.id != current_user.id if current_user.is_authenticated else True,
                    User.username.ilike(f'%{search_query.lstrip("@")}%')
                ).order_by(User.created_at.desc()).limit(50).all()
                if search_query.lstrip('#'):
                    tags = Tag.query.filter(
                        Tag.name.ilike(f'%{search_query.lstrip("#")}%')
                    ).order_by(Tag.created_at.desc()).limit(20).all()
        else:
            if search_type == 'communities':
                communities = Community.query.order_by(Community.created_at.desc()).limit(20).all()
            else:
                users = User.query.filter(
                    ~User.id.in_(blocked_ids) if blocked_ids else True,
                    User.id != current_user.id if current_user.is_authenticated else True
                ).order_by(User.created_at.desc()).limit(20).all()

        return render_template('explore.html', users=users, tags=tags, posts=posts, communities=communities, search_query=search_query, search_type=search_type)


    @app.route('/shorts')
    @app.route('/sharts')
    def shorts():
        shorts_list = Shorts.query.order_by(Shorts.created_at.desc()).limit(20).all()
        audios = ShortsAudio.query.order_by(ShortsAudio.created_at.desc()).limit(20).all()
        return render_template('shorts.html', shorts_list=shorts_list, audios=audios)


    @app.route('/shorts/create', methods=['GET', 'POST'])
    @login_required
    def create_shorts():
        if request.method == 'POST':
            video = request.files.get('video')
            media_data = request.form.get('media_data')
            caption = request.form.get('body') or request.form.get('caption', '')
            audio_id = request.form.get('audio_id')

            if media_data:
                import base64, io
                from werkzeug.datastructures import FileStorage
                header, data = media_data.split(',', 1)
                binary = base64.b64decode(data)
                file = FileStorage(io.BytesIO(binary), filename=f'shorts_{datetime.now().timestamp()}.jpg', content_type='image/jpeg')
                from helpers import cloudinary_configured, upload_to_cloudinary
                if cloudinary_configured:
                    url = upload_to_cloudinary(file, folder='shorts')
                else:
                    filename = secure_filename(f"shorts_{current_user.id}_{int(datetime.utcnow().timestamp())}.jpg")
                    with open(os.path.join(current_app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                        f.write(binary)
                    url = url_for('uploaded_file', filename=filename, _external=True)
                shorts = Shorts(video_url=url, caption=caption, user_id=current_user.id, audio_id=int(audio_id) if audio_id else None)
                db.session.add(shorts)
                db.session.commit()
                flash('Shorts опубликован!')
                return redirect(url_for('shorts'))

            if not video or video.filename == '':
                flash('Выберите видео')
                return redirect(url_for('create_shorts'))

            try:
                ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
                from helpers import cloudinary_configured, upload_to_cloudinary
                if cloudinary_configured:
                    result = cloudinary.uploader.upload(
                        video, folder='shorts', resource_type='video',
                        timeout=30
                    )
                    video_url = result['secure_url']
                else:
                    filename = f'shorts_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}'
                    video.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                    video_url = url_for('uploaded_file', filename=filename)

                shorts = Shorts(
                    video_url=video_url,
                    caption=caption,
                    user_id=current_user.id,
                    audio_id=int(audio_id) if audio_id else None
                )
                db.session.add(shorts)
                db.session.commit()
                flash('Shorts опубликован!')
                return redirect(url_for('shorts'))
            except Exception as e:
                current_app.logger.error(f"Error creating shorts: {e}")
                flash('Ошибка при загрузке видео')
                return redirect(url_for('create_shorts'))

        audios = ShortsAudio.query.order_by(ShortsAudio.created_at.desc()).all()
        return render_template('create_shorts.html', audios=audios)


    @app.route('/shorts/<int:shorts_id>', methods=['GET', 'POST'])
    def view_shorts(shorts_id):
        shorts_video = Shorts.query.get_or_404(shorts_id)

        if request.method == 'POST' and current_user.is_authenticated:
            comment_body = request.form.get('body')
            if comment_body:
                comment = ShortsComment(
                    body=comment_body,
                    user_id=current_user.id,
                    shorts_id=shorts_id
                )
                db.session.add(comment)
                db.session.commit()

        comments = shorts_video.comments.order_by(ShortsComment.created_at.desc()).all()
        return render_template('view_shorts.html', shorts=shorts_video, comments=comments)


    @app.route('/shorts/like/<int:shorts_id>', methods=['POST'])
    @login_required
    def like_shorts(shorts_id):
        shorts_video = Shorts.query.get_or_404(shorts_id)
        existing_like = ShortsLike.query.filter_by(user_id=current_user.id, shorts_id=shorts_id).first()

        if existing_like:
            db.session.delete(existing_like)
        else:
            like = ShortsLike(user_id=current_user.id, shorts_id=shorts_id)
            db.session.add(like)

        db.session.commit()
        return jsonify({'likes': shorts_video.likes.count()})


    @app.route('/shorts/<int:shorts_id>/react', methods=['POST'])
    @login_required
    def react_shorts(shorts_id):
        shorts_video = Shorts.query.get_or_404(shorts_id)
        emoji = request.form.get('emoji', '❤️')

        existing = ShortsReaction.query.filter_by(user_id=current_user.id, shorts_id=shorts_id, emoji=emoji).first()
        if existing:
            db.session.delete(existing)
        else:
            reaction = ShortsReaction(user_id=current_user.id, shorts_id=shorts_id, emoji=emoji)
            db.session.add(reaction)

        db.session.commit()
        return jsonify({'status': 'ok'})


    @app.route('/shorts/<int:shorts_id>/delete', methods=['POST'])
    @login_required
    def delete_shorts(shorts_id):
        shorts_video = Shorts.query.get_or_404(shorts_id)
        if shorts_video.user_id != current_user.id:
            abort(403)
        try:
            ShortsLike.query.filter_by(shorts_id=shorts_id).delete()
            ShortsComment.query.filter_by(shorts_id=shorts_id).delete()
            ShortsReaction.query.filter_by(shorts_id=shorts_id).delete()
            db.session.delete(shorts_video)
            db.session.commit()
            flash('Shorts удалён')
        except Exception as e:
            current_app.logger.error(f"Delete shorts error: {e}")
            db.session.rollback()
            flash('Ошибка при удалении')
        return redirect(request.referrer or url_for('user_profile', username=current_user.username))


    @app.route('/shorts/audio/upload', methods=['GET', 'POST'])
    @login_required
    def upload_shorts_audio():
        if request.method == 'POST':
            audio = request.files.get('audio')
            title = request.form.get('title', 'Original audio')

            if audio:
                from helpers import cloudinary_configured, upload_to_cloudinary
                if cloudinary_configured:
                    result = cloudinary.uploader.upload(
                        audio, folder='shorts_audio', resource_type='video',
                        timeout=30
                    )
                    audio_url = result['secure_url']
                else:
                    filename = f'saudio_{current_user.id}_{int(datetime.utcnow().timestamp())}.mp3'
                    audio.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                    audio_url = url_for('uploaded_file', filename=filename)

                shorts_audio = ShortsAudio(
                    title=title,
                    audio_url=audio_url,
                    user_id=current_user.id
                )
                db.session.add(shorts_audio)
                db.session.commit()
                return redirect(url_for('create_shorts'))

        return render_template('upload_shorts_audio.html')


    @app.route('/shorts/audio/search_freesound')
    @login_required
    def search_freesound():
        query = request.args.get('q', '').strip()
        if not query or len(query) < 2:
            return jsonify({'results': []})

        import urllib.request
        import urllib.parse
        import json

        try:
            from helpers import FREESOUND_API_KEY
            url = f'https://freesound.org/apiv2/search/text/?query={urllib.parse.quote(query)}&token={FREESOUND_API_KEY}&page=1&page_size=12&fields=id,name,previews,duration,username,tags,description'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())

            results = []
            for s in data.get('results', []):
                previews = s.get('previews', {})
                preview_url = previews.get('preview-hq-mp3') or previews.get('preview-lq-mp3')
                if preview_url:
                    results.append({
                        'id': s['id'],
                        'name': s['name'],
                        'username': s.get('username', ''),
                        'duration': s.get('duration', 0),
                        'preview_url': preview_url,
                        'tags': s.get('tags', [])[:5],
                        'description': s.get('description', '')[:200]
                    })
            return jsonify({'results': results})
        except Exception as e:
            current_app.logger.error(f"FreeSound search error: {e}")
            return jsonify({'error': str(e), 'results': []}), 500


    @app.route('/shorts/audio/add_freesound', methods=['POST'])
    @login_required
    def add_freesound_audio():
        name = request.form.get('name', '').strip()
        preview_url = request.form.get('preview_url', '').strip()
        duration = request.form.get('duration', 0, type=int)

        if not name or not preview_url:
            return jsonify({'error': 'Missing fields'}), 400

        existing = ShortsAudio.query.filter_by(audio_url=preview_url).first()
        if existing:
            return jsonify({'id': existing.id, 'title': existing.title, 'message': 'Уже добавлено'})

        audio = ShortsAudio(
            title=name,
            audio_url=preview_url,
            duration=duration,
            user_id=current_user.id
        )
        db.session.add(audio)
        db.session.commit()

        return jsonify({'id': audio.id, 'title': audio.title, 'message': 'Добавлено!'})


    @app.route('/photos')
    @login_required
    def photos():
        user_media = Media.query.join(Post).filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).all()
        return render_template('photos.html', user_media=user_media)


    @app.route('/recommendations')
    @login_required
    def recommendations():
        import re
        blocked_ids = [u.id for u in current_user.blocked]
        following_ids = [u.id for u in current_user.followed]

        user_interests = set(current_user.interests.lower().split()) if current_user.interests else set()

        recommended_users = []
        for user in User.query.filter(
            ~User.id.in_(blocked_ids),
            ~User.id.in_(following_ids),
            User.id != current_user.id
        ).limit(50).all():
            score = 0
            user_interests_set = set(user.interests.lower().split()) if user.interests else set()
            common_interests = user_interests & user_interests_set
            score += len(common_interests) * 10

            for follower in user.followers.all():
                if follower.id in following_ids:
                    score += 5

            if score > 0:
                recommended_users.append((score, user))

        recommended_users.sort(key=lambda x: x[0], reverse=True)
        recommended_users = [u for _, u in recommended_users[:10]]

        member_communities = [cm.community_id for cm in current_user.community_memberships.filter_by(status='approved').all()]

        recommended_communities = []
        for comm in Community.query.filter(
            ~Community.id.in_(member_communities) if member_communities else True
        ).limit(30).all():
            score = 0
            comm_interests = set(comm.description.lower().split()) if comm.description else set()
            common = user_interests & comm_interests
            score += len(common) * 10
            score += comm.members.count()

            if score > 0:
                recommended_communities.append((score, comm))

        recommended_communities.sort(key=lambda x: x[0], reverse=True)
        recommended_communities = [c for _, c in recommended_communities[:5]]

        interest_posts = []
        if user_interests:
            for post in Post.query.filter(
                Post.user_id.notin_(blocked_ids + [current_user.id]),
                Post.community_id == None
            ).limit(100).all():
                if post.body:
                    post_words = set(post.body.lower().split())
                    common = user_interests & post_words
                    if common:
                        interest_posts.append((len(common), post))

        interest_posts.sort(key=lambda x: x[0], reverse=True)
        interest_posts = [p for _, p in interest_posts[:10]]

        saved_posts_user_ids = [s.post.user_id for s in SavedPost.query.filter(
            SavedPost.user_id != current_user.id
        ).all() if s.post]
        from collections import Counter
        user_counter = Counter(saved_posts_user_ids)
        similar_users = [User.query.get(uid) for uid, _ in user_counter.most_common(5) if uid not in blocked_ids and uid != current_user.id]

        saved_tags = [pt.tag.name for s in SavedPost.query.filter_by(user_id=current_user.id).all() if s.post]
        tag_post_scores = []
        for post in Post.query.filter(
            Post.user_id.notin_(blocked_ids + [current_user.id])
        ).limit(100).all():
            if post.body:
                post_tags = set(re.findall(r'#(\w+)', post.body.lower()))
                saved_tags_set = set(saved_tags)
                common = post_tags & saved_tags_set
                if common:
                    tag_post_scores.append((len(common), post))

        tag_post_scores.sort(key=lambda x: x[0], reverse=True)
        posts_from_saved_tags = [p for _, p in tag_post_scores[:10]]

        return render_template('recommendations.html',
                            recommended_users=recommended_users,
                            recommended_communities=recommended_communities,
                            interest_posts=interest_posts,
                            similar_users=similar_users,
                            posts_from_saved_tags=posts_from_saved_tags)
