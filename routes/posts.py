def register_routes(app):
    import os, re, base64, io
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from werkzeug.datastructures import FileStorage
    from datetime import datetime
    from PIL import Image, ImageEnhance, ImageFilter
    from extensions import db
    from models import Post, Repost, SavedPost, Reaction, Comment, CommentReaction, CommentMedia, MessageReaction, Message, Media, Tag, PostTag, Draft, Shorts, User, Community, Chat, ChatMember, MusicTrack, Notification, ModerationLog, PostView

    @app.route('/')
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        try:
            followed_ids = [u.id for u in current_user.followed]
            blocked_ids = [u.id for u in current_user.blocked]
            member_communities = [cm.community_id for cm in current_user.community_memberships.filter_by(status='approved').all()]
            
            user_interests = set(current_user.interests.lower().split()) if current_user.interests else set()
            likers = [l.user_id for l in current_user.likes.all()]
            
            query = Post.query
            if blocked_ids:
                query = query.filter(~Post.user_id.in_(blocked_ids))
            posts = query.order_by(Post.created_at.desc()).limit(100).all()
            
            repost_counts = {p.id: Repost.query.filter_by(post_id=p.id).count() for p in posts}
            
            shorts_list = Shorts.query.order_by(Shorts.created_at.desc()).limit(5).all()
        except Exception as e:
            app.logger.error(f"Feed Error: {e}")
            posts = []
            repost_counts = {}
            shorts_list = []
        return render_template('index.html', posts=posts, repost_counts=repost_counts, shorts_list=shorts_list)

    @app.route('/create', methods=['GET', 'POST'])
    @login_required
    def create():
        if request.method == 'POST':
            try:
                body = request.form.get('body', '').strip()
                
                is_draft = request.args.get('draft') == '1'
                if is_draft:
                    media_data = request.form.get('media_data')
                    draft = Draft(user_id=current_user.id, media_data=media_data, caption=body)
                    db.session.add(draft)
                    db.session.commit()
                    flash('Черновик сохранён')
                    return redirect(url_for('drafts'))
                
                from helpers import moderate_post
                result = moderate_post(body, current_user)
                if result == 'USER_BANNED':
                    flash('Ваш аккаунт заблокирован за нарушение правил')
                    return redirect(url_for('index'))
                if result == 'BLOCKED':
                    flash('Пост отклонён: обнаружен неприемлемый контент. Проверьте личные сообщения.')
                    return redirect(url_for('index'))
                
                media_data = request.form.get('media_data')
                music_track_id = request.form.get('music_track_id', type=int)
                
                from helpers import cloudinary_configured, upload_to_cloudinary
                
                post = Post(body=body, author=current_user)
                if music_track_id:
                    track = MusicTrack.query.get(music_track_id)
                    if track:
                        post.music_track = track
                db.session.add(post)
                db.session.flush()
                
                hashtags = re.findall(r'#(\w+)', body)
                for tag_name in set(hashtags):
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if not tag:
                        tag = Tag(name=tag_name)
                        db.session.add(tag)
                        db.session.flush()
                    post_tag = PostTag(post_id=post.id, tag_id=tag.id)
                    db.session.add(post_tag)
                
                if media_data:
                    header, data = media_data.split(',', 1)
                    if 'image/jpeg' in header:
                        ext = 'jpg'
                        media_type = 'image'
                    elif 'image/png' in header:
                        ext = 'png'
                        media_type = 'image'
                    else:
                        ext = 'jpg'
                        media_type = 'image'
                    
                    binary = base64.b64decode(data)
                    file = FileStorage(io.BytesIO(binary), filename=f'photo.{ext}', content_type=f'image/{ext}')
                    
                    if cloudinary_configured:
                        url = upload_to_cloudinary(file, folder='posts')
                        if url:
                            filename = url.split('/')[-1].split('.')[0]
                            media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                            db.session.add(media)
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_photo.{ext}")
                        with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                            f.write(binary)
                        media = Media(filename=filename, media_type=media_type, post=post)
                        db.session.add(media)
                
                files = request.files.getlist('media')
                app.logger.info(f"Files count: {len(files)}")
                for file in files:
                    app.logger.info(f"Processing file: {file.filename}")
                    from helpers import allowed_file
                    if file.filename and allowed_file(file.filename):
                        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                        if ext in {'mp4', 'webm', 'mov'}:
                            media_type = 'video'
                        elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                            media_type = 'audio'
                        elif ext in {'pdf', 'doc', 'docx', 'txt'}:
                            media_type = 'document'
                        else:
                            media_type = 'image'
                        
                        if cloudinary_configured:
                            url = upload_to_cloudinary(file, folder='posts')
                            if url:
                                filename = url.split('/')[-1].split('.')[0]
                                media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                                db.session.add(media)
                        else:
                            filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                            app.logger.info(f"Saving file: {filename}")
                            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                            media = Media(filename=filename, media_type=media_type, post=post)
                            db.session.add(media)
                
                db.session.commit()
                app.logger.info(f"Post created: {post.id} by user {current_user.id}")
                flash('Пост опубликован!')
            except Exception as e:
                app.logger.error(f"Post creation error: {e}")
                db.session.rollback()
                flash(f'Ошибка: {e}')
            return redirect(url_for('index'))
        return render_template('create.html')

    @app.route('/photo_editor', methods=['GET', 'POST'])
    @login_required
    def photo_editor():
        if request.method == 'POST':
            media_data = request.form.get('media_data')
            if media_data:
                import base64, io
                header, data = media_data.split(',', 1)
                binary = base64.b64decode(data)
                from werkzeug.datastructures import FileStorage
                file = FileStorage(io.BytesIO(binary), filename=f'avatar_{current_user.id}.jpg', content_type='image/jpeg')
                from helpers import cloudinary_configured, upload_to_cloudinary
                if cloudinary_configured:
                    url = upload_to_cloudinary(file, folder='avatars')
                    if url:
                        current_user.avatar_cloudinary_url = url
                        current_user.avatar = url.split('/')[-1].split('.')[0]
                else:
                    filename = secure_filename(f"avatar_{current_user.id}_{int(datetime.utcnow().timestamp())}.jpg")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    current_user.avatar = filename
                    current_user.avatar_cloudinary_url = None
                db.session.commit()
                return jsonify({'status': 'ok'})
            return jsonify({'status': 'error', 'message': 'No image data'}), 400

        draft_id = request.args.get('draft')
        target = request.args.get('target', 'feed')
        editing = draft_id is not None
        if draft_id:
            draft = Draft.query.get_or_404(draft_id)
            if draft.user_id != current_user.id:
                abort(403)
        else:
            draft = None
        return render_template('photo_editor.html', editing=editing, draft=draft, target=target)

    @app.route('/drafts')
    @login_required
    def drafts():
        user_drafts = Draft.query.filter_by(user_id=current_user.id).order_by(Draft.created_at.desc()).all()
        return render_template('drafts.html', drafts=user_drafts)

    @app.route('/drafts/<int:draft_id>/delete', methods=['POST'])
    @login_required
    def delete_draft(draft_id):
        draft = Draft.query.get_or_404(draft_id)
        if draft.user_id != current_user.id:
            abort(403)
        db.session.delete(draft)
        db.session.commit()
        flash('Черновик удалён')
        return redirect(url_for('drafts'))

    @app.route('/photo_transform', methods=['POST'])
    @login_required
    def photo_transform():
        try:
            preview_data = request.form.get('preview_data')
            transform_type = request.form.get('transform_type')
            transform_value = request.form.get('transform_value')
            
            if not preview_data:
                return '', 400
            
            header, data = preview_data.split(',', 1)
            binary = base64.b64decode(data)
            
            img = Image.open(io.BytesIO(binary))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            if transform_type == 'rotate':
                angle = int(transform_value) if transform_value else 0
                img = img.rotate(angle, expand=True)
            elif transform_type == 'flip':
                if transform_value == 'h':
                    img = img.transpose(Image.FLIP_LEFT_RIGHT)
                elif transform_value == 'v':
                    img = img.transpose(Image.FLIP_TOP_BOTTOM)
            elif transform_type == 'crop':
                w, h = img.size
                left = int(w * 0.1)
                top = int(h * 0.1)
                right = int(w * 0.9)
                bottom = int(h * 0.9)
                img = img.crop((left, top, right, bottom))
            
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=92)
            output.seek(0)
            
            return output.getvalue(), 200, {'Content-Type': 'image/jpeg'}
        except Exception as e:
            app.logger.error(f"Photo transform error: {e}")
            return str(e), 500

    @app.route('/announce-features', methods=['POST'])
    @login_required
    def announce_features():
        if not current_user.is_staff:
            abort(403)
        from helpers import announce_pending_features
        announce_pending_features()
        flash('Pending features announced')
        return redirect(request.referrer or url_for('index'))

    @app.route('/video_editor', methods=['GET', 'POST'])
    @login_required
    def video_editor():
        if request.method == 'POST':
            from helpers import cloudinary_configured

            # Case 1: Upload raw video to Cloudinary
            if request.files.get('video'):
                video = request.files['video']
                if cloudinary_configured:
                    import cloudinary.uploader
                    result = cloudinary.uploader.upload(
                        video, folder='shorts', resource_type='video',
                        timeout=30
                    )
                    return jsonify({
                        'public_id': result['public_id'],
                        'version': result['version'],
                        'url': result['secure_url'],
                        'success': True
                    })
                else:
                    filename = secure_filename(f"shorts_{current_user.id}_{int(datetime.utcnow().timestamp())}.mp4")
                    video.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    url = url_for('uploaded_file', filename=filename, _external=True)
                    return jsonify({'url': url, 'success': True})

            # Case 2: Build Cloudinary URL with transformations
            data = request.get_json()
            if data and data.get('public_id'):
                public_id = data['public_id']
                version = data.get('version')
                start_offset = data.get('start_offset', 0)
                end_offset = data.get('end_offset', 0)
                effect = data.get('filter', '')
                speed = data.get('speed', 1)

                filter_map = {
                    'grayscale': 'e_grayscale',
                    'sepia': 'e_sepia',
                    'vintage': 'e_art:vintage',
                    'cinematic': 'e_contrast:40,e_brightness:-20',
                    'vivid': 'e_saturation:50',
                    'cool': 'e_hue:200',
                    'warm': 'e_hue:-10',
                }

                tx_parts = []
                if start_offset > 0:
                    tx_parts.append(f'so_{start_offset}')
                if end_offset > 0:
                    tx_parts.append(f'eo_{end_offset}')
                if effect and effect in filter_map and effect != 'original':
                    tx_parts.append(filter_map[effect])
                if speed and speed != 1:
                    tx_parts.append(f'e_accelerate:{speed}')

                audio_id = data.get('audio_id')
                if audio_id:
                    from helpers import cloudinary_configured, cloud_name
                    audio_track = MusicTrack.query.get(audio_id)
                    if audio_track:
                        audio_url = audio_track.preview_url or audio_track.file_url
                        if audio_url:
                            import cloudinary.uploader
                            audio_public_id = None
                            if cloudinary_configured and 'res.cloudinary.com' in audio_url:
                                parts = audio_url.split('/')
                                if 'upload' in parts:
                                    idx = parts.index('upload') + 1
                                    path_parts = parts[idx:]
                                    if path_parts and path_parts[0].startswith('v'):
                                        path_parts = path_parts[1:]
                                    path = '/'.join(path_parts)
                                    if '.' in path:
                                        path = path.rsplit('.', 1)[0]
                                    audio_public_id = path
                            else:
                                try:
                                    result = cloudinary.uploader.upload(
                                        audio_url, folder='shorts_audio', resource_type='video',
                                        timeout=30
                                    )
                                    audio_public_id = result['public_id']
                                except:
                                    pass
                            if audio_public_id:
                                tx_parts.append('l_audio:' + audio_public_id.replace('/', ':') + ',fl_layer_apply')

                if tx_parts:
                    tx_str = '/'.join(tx_parts)
                    from helpers import cloud_name
                    if version:
                        url = f'https://res.cloudinary.com/{cloud_name}/video/upload/{tx_str}/v{version}/{public_id}'
                    else:
                        url = f'https://res.cloudinary.com/{cloud_name}/video/upload/{tx_str}/{public_id}'
                else:
                    url = data.get('original_url', '')

                return jsonify({'url': url, 'success': True})

            # Fallback: no Cloudinary, pass original URL through
            if data and data.get('original_url'):
                return jsonify({'url': data['original_url'], 'success': True})

            return jsonify({'error': 'Invalid request', 'success': False}), 400

        tracks = MusicTrack.query.order_by(MusicTrack.created_at.desc()).all()
        return render_template('video_editor.html', tracks=tracks)

    @app.route('/post/<int:post_id>/repost', methods=['GET', 'POST'])
    @login_required
    def repost(post_id):
        post = Post.query.get_or_404(post_id)
        if current_user.has_reposted(post):
            current_user.unrepost(post)
        else:
            current_user.repost(post)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/post/<int:post_id>/save', methods=['POST'])
    @login_required
    def save_post(post_id):
        post = Post.query.get_or_404(post_id)
        saved = SavedPost.query.filter_by(user_id=current_user.id, post_id=post_id).first()
        if saved:
            db.session.delete(saved)
            flash('Пост удалён из сохранённых')
        else:
            saved = SavedPost(user_id=current_user.id, post_id=post_id)
            db.session.add(saved)
            flash('Пост сохранён')
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/post/<int:post_id>/react', methods=['POST'])
    @login_required
    def react_post(post_id):
        post = Post.query.get_or_404(post_id)
        emoji = request.form.get('emoji', '❤️')
        
        existing = Reaction.query.filter_by(user_id=current_user.id, post_id=post_id).first()
        if existing:
            if existing.emoji == emoji:
                db.session.delete(existing)
            else:
                existing.emoji = emoji
        else:
            reaction = Reaction(user_id=current_user.id, post_id=post_id, emoji=emoji)
            db.session.add(reaction)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/saved')
    @login_required
    def saved_posts():
        saved = SavedPost.query.filter_by(user_id=current_user.id).order_by(SavedPost.created_at.desc()).all()
        posts = [Post.query.get(s.post_id) for s in saved if s.post_id]
        return render_template('saved.html', posts=posts)

    @app.route('/explore_tags')
    def explore_tags():
        tags = Tag.query.order_by(Tag.created_at.desc()).limit(50).all()
        return render_template('explore_tags.html', tags=tags)

    @app.route('/tag/<name>')
    def tag_posts(name):
        tag = Tag.query.filter_by(name=name.lstrip('#')).first_or_404()
        post_tags = PostTag.query.filter_by(tag_id=tag.id).order_by(PostTag.id.desc()).all()
        posts = [Post.query.get(pt.post_id) for pt in post_tags if pt.post_id]
        return render_template('tag_posts.html', tag=tag, posts=posts)

    @app.route('/post/<int:post_id>/forward', methods=['GET', 'POST'])
    @login_required
    def forward_post(post_id):
        post = Post.query.get_or_404(post_id)
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'to_profile':
                new_post = Post(body=post.body, author=current_user)
                db.session.add(new_post)
                db.session.flush()
                for media in post.media:
                    new_media = Media(filename=media.filename, cloudinary_url=media.cloudinary_url, media_type=media.media_type, post=new_post)
                    db.session.add(new_media)
                db.session.commit()
                flash('Пост добавлен в ваш профиль')
                return redirect(url_for('user_profile', username=current_user.username))
            
            chat_id = request.form.get('chat_id')
            if chat_id:
                chat = Chat.query.get(int(chat_id))
                member = ChatMember.query.filter_by(chat_id=chat.id, user_id=current_user.id).first()
                if member:
                    message_body = f"Репост от @{post.author.username}"
                    if post.body:
                        message_body += f":\n\n{post.body}"
                    msg = Message(body=message_body, sender_id=current_user.id, chat_id=chat.id, post_id=post.id)
                    db.session.add(msg)
                    db.session.commit()
                    flash(f'Пост отправлен в чат {chat.name}')
                    return redirect(url_for('chat_view', chat_id=chat.id))
            
            username = request.form.get('username', '').strip()
            user = User.query.filter_by(username=username).first()
            if user:
                message_body = f"Репост от @{post.author.username}"
                if post.body:
                    message_body += f":\n\n{post.body}"
                msg = Message(body=message_body, sender_id=current_user.id, recipient_id=user.id, post_id=post.id)
                db.session.add(msg)
                db.session.commit()
                flash(f'Пост отправлен пользователю {user.username}')
                return redirect(url_for('conversation', username=user.username))
            else:
                flash('Пользователь не найден')
        
        blocked_ids = [u.id for u in current_user.blocked]
        users = User.query.filter(User.id != current_user.id, ~User.id.in_(blocked_ids)).all()
        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        chats = [Chat.query.get(cm.chat_id) for cm in user_chats]
        return render_template('forward_post.html', post=post, users=users, chats=chats)

    @app.route('/post/<int:post_id>/like', methods=['GET', 'POST'])
    @login_required
    def like(post_id):
        post = Post.query.get_or_404(post_id)
        liked = False
        if current_user.has_liked(post):
            current_user.unlike_post(post)
        else:
            current_user.like_post(post)
            from helpers import create_notification
            create_notification(post.user_id, current_user.id, 'like', post_id=post.id)
            liked = True
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'liked': liked, 'count': post.likes.count()})
        return redirect(request.referrer or url_for('index'))

    @app.route('/post/<int:post_id>/comment', methods=['POST'])
    @login_required
    def add_comment(post_id):
        app.logger.info(f"Adding comment to post {post_id} by user {current_user.id}")
        post = Post.query.get_or_404(post_id)
        body = request.form.get('body', '').strip()
        reply_to_comment_id = request.form.get('reply_to_comment_id', type=int)
        media_url = None
        media_type = None
        
        if 'media' in request.files:
            file = request.files['media']
            from helpers import allowed_file, cloudinary_configured, upload_to_cloudinary
            if file.filename and allowed_file(file.filename):
                try:
                    if cloudinary_configured:
                        media_url = upload_to_cloudinary(file, folder='comments')
                        if media_url:
                            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'} else 'document' if ext in {'pdf', 'doc', 'docx', 'txt'} else 'image'
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        media_url = '/media/' + filename
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'} else 'document' if ext in {'pdf', 'doc', 'docx', 'txt'} else 'image'
                except Exception as e:
                    app.logger.error(f"Media upload error: {e}")
        
        app.logger.info(f"Comment body: {body}")
        if body or media_url:
            try:
                comment = Comment(body=body or '', author=current_user, post=post, media_url=media_url, media_type=media_type, reply_to_id=reply_to_comment_id)
                db.session.add(comment)
                db.session.commit()
                from helpers import create_notification
                create_notification(post.user_id, current_user.id, 'comment', post_id=post.id, comment_id=comment.id)
                if reply_to_comment_id:
                    parent_comment = Comment.query.get(reply_to_comment_id)
                    if parent_comment and parent_comment.user_id != current_user.id:
                        create_notification(parent_comment.user_id, current_user.id, 'reply', post_id=post.id, comment_id=comment.id)
                app.logger.info(f"Comment added successfully")
            except Exception as e:
                app.logger.error(f"Comment error: {e}")
                db.session.rollback()
        else:
            app.logger.warning("Empty comment body")
        return redirect(request.referrer or url_for('index'))

    @app.route('/comment/<int:comment_id>/delete', methods=['POST'])
    @login_required
    def delete_comment(comment_id):
        comment = Comment.query.get_or_404(comment_id)
        if comment.author != current_user and not current_user.is_staff:
            abort(403)
        db.session.delete(comment)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/comment/<int:comment_id>/react', methods=['POST'])
    @login_required
    def react_comment(comment_id):
        emoji = request.form.get('emoji', '👍')
        comment = Comment.query.get_or_404(comment_id)
        existing = CommentReaction.query.filter_by(comment_id=comment_id, user_id=current_user.id, emoji=emoji).first()
        if existing:
            db.session.delete(existing)
        else:
            reaction = CommentReaction(comment_id=comment_id, user_id=current_user.id, emoji=emoji)
            db.session.add(reaction)
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/post/<int:post_id>')
    def view_post(post_id):
        post = Post.query.get_or_404(post_id)
        if current_user.is_authenticated and current_user.id != post.user_id:
            view = PostView(post_id=post.id, viewer_id=current_user.id)
            db.session.add(view)
            db.session.commit()
        repost_count = Repost.query.filter_by(post_id=post.id).count()
        user_reaction = None
        if current_user.is_authenticated:
            user_reaction = Reaction.query.filter_by(user_id=current_user.id, post_id=post_id).first()
        return render_template('post.html', post=post, repost_count=repost_count, user_reaction=user_reaction)

    @app.route('/delete/<int:post_id>', methods=['POST'])
    @login_required
    def delete(post_id):
        post = Post.query.get_or_404(post_id)
        community_id = post.community_id
        author_id = post.user_id
        
        if post.author != current_user:
            abort(403)
        
        try:
            from sqlalchemy import text
            db.session.execute(text("UPDATE message SET post_id = NULL WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM repost WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM post_tag WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM notification WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM saved_post WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM comment_media WHERE post_id = :post_id"), {'post_id': post_id})
            db.session.execute(text("DELETE FROM comment_reaction WHERE comment_id IN (SELECT id FROM comment WHERE post_id = :post_id)"), {'post_id': post_id})
            db.session.execute(text("UPDATE notification SET comment_id = NULL WHERE comment_id IN (SELECT id FROM comment WHERE post_id = :post_id)"), {'post_id': post_id})
            db.session.execute(text("UPDATE comment SET reply_to_id = NULL WHERE reply_to_id IN (SELECT id FROM comment WHERE post_id = :post_id)"), {'post_id': post_id})
        except: pass
        
        for media in post.media:
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], media.filename))
            except: pass
        db.session.delete(post)
        db.session.commit()
        flash('Пост удалён')
        referer = request.referrer
        if referer and f'/post/{post_id}' in referer:
            if community_id:
                community = Community.query.get(community_id)
                return redirect(url_for('community', slug=community.slug))
            author = User.query.get(author_id)
            return redirect(url_for('user_profile', username=author.username))
        return redirect(referer or url_for('index'))
