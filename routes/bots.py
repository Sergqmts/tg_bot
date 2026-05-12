def register_routes(app):
    import json, urllib, os, hmac, hashlib, tempfile
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from werkzeug.datastructures import FileStorage
    from datetime import datetime
    from extensions import db, csrf
    from models import User, Chat, ChatMember, Message, MessageMedia, Post, Media, Community, CommunityMember, Report, BotForm
    from app import moderate_post, create_notification, allowed_file, cloudinary_configured, upload_to_cloudinary, generate_bot_token, process_webhooks, enqueue_webhook_dispatch
    import cloudinary
    import cloudinary.uploader

    # ─── Helpers ────────────────────────────────────────────────────

    def staff_required(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not current_user.is_staff:
                abort(403)
            return f(*args, **kwargs)
        return decorated

    def bot_json_response(data, status=200):
        return jsonify({"ok": status == 200, "result": data} if status == 200 else {"ok": False, "error_code": status, "description": data}), status

    def resolve_chat(chat_id):
        if isinstance(chat_id, str) and chat_id.startswith('@'):
            user = User.query.filter_by(username=chat_id[1:]).first()
            if not user:
                return None, None
            return None, user
        chat = Chat.query.get(int(chat_id))
        if chat:
            return chat, None
        user = User.query.get(int(chat_id))
        if user:
            return None, user
        return None, None

    def get_or_create_dm(user_a, user_b):
        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(ChatMember.user_id == user_a.id).join(cm2).filter(
            cm2.user_id == user_b.id, Chat.type == 'direct'
        ).first()
        if not chat:
            chat = Chat(name=f"DM", type='direct', creator_id=user_a.id)
            db.session.add(chat)
            db.session.flush()
            for uid in [user_a.id, user_b.id]:
                if not ChatMember.query.filter_by(chat_id=chat.id, user_id=uid).first():
                    db.session.add(ChatMember(chat_id=chat.id, user_id=uid, role='member'))
        return chat

    def resolve_community(slug_or_id):
        if isinstance(slug_or_id, str) and not slug_or_id.isdigit():
            return Community.query.filter_by(slug=slug_or_id).first()
        return Community.query.get(int(slug_or_id))

    def process_video(file_data, start_time=0, duration=None, quality='medium'):
        if cloudinary_configured and file_data.get('cloudinary_url'):
            public_id = file_data['cloudinary_url']
            transforms = {}
            if start_time:
                transforms['start_offset'] = str(start_time)
            if duration:
                transforms['duration'] = str(duration)
            if quality == 'low':
                transforms['quality'] = 'auto:low'
            elif quality == 'medium':
                transforms['quality'] = 'auto'
            else:
                transforms['quality'] = 'auto:best'
            return cloudinary.CloudinaryImage(public_id).build_url(**transforms)

        import ffmpeg

        try:
            input_path = file_data.get('temp_path')
            output_filename = f'processed_{datetime.now().timestamp()}.mp4'
            output_path = os.path.join(current_app.config['UPLOAD_FOLDER'], output_filename)

            stream = ffmpeg.input(input_path, ss=start_time)

            if duration:
                stream = ffmpeg.output(stream, output_path, t=duration, **{'preset': quality})
            else:
                stream = ffmpeg.output(stream, output_path, **{'preset': quality})

            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)

            return output_filename
        except Exception as e:
            current_app.logger.error(f"Video processing error: {e}")
            return None

    def generate_video_thumbnail(video_path, timestamp=1):
        if cloudinary_configured and video_path.startswith('http'):
            public_id = video_path
            return cloudinary.CloudinaryImage(public_id).build_url(
                start_offset=timestamp,
                format='jpg',
                width=300,
                crop='scale'
            )

        import ffmpeg

        try:
            output_filename = f'thumb_{datetime.now().timestamp()}.jpg'
            output_path = os.path.join(current_app.config['UPLOAD_FOLDER'], output_filename)

            stream = ffmpeg.input(video_path, ss=timestamp)
            stream = ffmpeg.output(stream, output_path, vframes=1, format='image2', vcodec='mjpeg')
            ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)

            return output_filename
        except Exception as e:
            current_app.logger.error(f"Thumbnail generation error: {e}")
            return None

    # ─── Bot Routes ─────────────────────────────────────────────────

    @app.route('/bots')
    @login_required
    def my_bots():
        bots = User.query.filter_by(is_bot=True, creator_id=current_user.id).all()
        return render_template('bots.html', bots=bots)

    @app.route('/bot-docs')
    def bot_docs():
        return render_template('bot_docs.html')

    @app.route('/admin')
    @login_required
    @staff_required
    def admin_panel():
        bots = User.query.filter_by(is_bot=True, creator_id=None).all()
        reports = Report.query.order_by(Report.created_at.desc()).all()
        pending_reports = Report.query.filter_by(status='pending').count()
        users = User.query.filter_by(is_bot=False).order_by(User.created_at.desc()).all()
        communities = Community.query.order_by(Community.created_at.desc()).all()
        return render_template('admin.html', bots=bots, reports=reports,
                               pending_reports=pending_reports, users=users, communities=communities)

    @app.route('/admin/report/<int:report_id>/resolve', methods=['POST'])
    @login_required
    @staff_required
    def admin_approve_report(report_id):
        report = Report.query.get_or_404(report_id)
        action = request.form.get('action')
        if action == 'ban_user' and report.target_user_id:
            user = User.query.get(report.target_user_id)
            if user:
                user.is_banned = True
                report.status = 'approved'
                db.session.commit()
                flash(f'User @{user.username} banned')
        elif action == 'dismiss':
            report.status = 'dismissed'
            db.session.commit()
            flash('Report dismissed')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/toggle-ban/<int:user_id>', methods=['POST'])
    @login_required
    @staff_required
    def admin_toggle_ban(user_id):
        user = User.query.get_or_404(user_id)
        if user.is_staff:
            flash('Cannot ban staff members')
            return redirect(url_for('admin_panel'))
        user.is_banned = not user.is_banned
        db.session.commit()
        flash(f'User @{user.username} {"banned" if user.is_banned else "unbanned"}')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/toggle-community-ban/<int:community_id>', methods=['POST'])
    @login_required
    @staff_required
    def admin_toggle_community_ban(community_id):
        comm = Community.query.get_or_404(community_id)
        comm.is_banned = not comm.is_banned
        db.session.commit()
        flash(f'Community "{comm.name}" {"banned" if comm.is_banned else "unbanned"}')
        return redirect(url_for('admin_panel'))

    @app.route('/admin/toggle-staff/<int:user_id>', methods=['POST'])
    @login_required
    @staff_required
    def admin_toggle_staff(user_id):
        user = User.query.get_or_404(user_id)
        if user.is_bot:
            flash('Cannot make bots staff')
            return redirect(url_for('admin_panel'))
        user.is_staff = not user.is_staff
        db.session.commit()
        flash(f'User @{user.username} {"promoted to staff" if user.is_staff else "demoted"}')
        return redirect(url_for('admin_panel'))

    @app.route('/report', methods=['POST'])
    @login_required
    def submit_report():
        target_user_id = request.form.get('target_user_id', type=int)
        target_post_id = request.form.get('target_post_id', type=int)
        reason = request.form.get('reason', '').strip()
        if not reason:
            flash('Please provide a reason')
            return redirect(request.referrer or url_for('index'))
        if not target_user_id and not target_post_id:
            flash('No target specified')
            return redirect(request.referrer or url_for('index'))
        report = Report(
            reporter_id=current_user.id,
            target_user_id=target_user_id,
            target_post_id=target_post_id,
            reason=reason,
        )
        db.session.add(report)
        db.session.commit()
        flash('Report submitted. Thank you!')
        return redirect(request.referrer or url_for('index'))

    @app.route('/bots/new', methods=['GET', 'POST'])
    @login_required
    def create_bot():
        form = BotForm()
        if form.validate_on_submit():
            bot = User(
                username=form.username.data,
                email=f"bot_{form.username.data}@localhost",
                is_bot=True,
                bot_token=generate_bot_token(),
                bot_commands=form.commands.data or '[]',
                bio=form.description.data,
                creator_id=current_user.id,
            )
            bot.set_password(os.urandom(32).hex())
            db.session.add(bot)
            db.session.flush()

            if form.avatar.data:
                file = form.avatar.data
                filename = f"bot_{bot.id}_{secure_filename(file.filename)}"
                filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                if cloudinary_configured:
                    try:
                        upload = cloudinary.uploader.upload(filepath, folder='avatars')
                        bot.avatar_cloudinary_url = upload['secure_url']
                    except:
                        bot.avatar = filename
                else:
                    bot.avatar = filename

            db.session.commit()
            flash(f'Бот @{bot.username} создан! Токен: {bot.bot_token}. Сохраните его — он больше не покажется.')
            return redirect(url_for('bot_settings', bot_id=bot.id))

        return render_template('create_bot.html', form=form)

    @app.route('/bots/<int:bot_id>/settings', methods=['GET', 'POST'])
    @login_required
    def bot_settings(bot_id):
        bot = User.query.get_or_404(bot_id)
        if not bot.is_bot or bot.creator_id != current_user.id:
            abort(403)

        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'regenerate_token':
                bot.bot_token = generate_bot_token()
                db.session.commit()
                flash(f'Новый токен: {bot.bot_token}')
            elif action == 'update':
                bot.bio = request.form.get('description', bot.bio)
                commands_raw = request.form.get('commands', '[]')
                try:
                    json.loads(commands_raw)
                    bot.bot_commands = commands_raw
                except:
                    flash('Ошибка в JSON команд')
                bot.can_join_groups = bool(request.form.get('can_join_groups'))
                bot.privacy_mode = bool(request.form.get('privacy_mode'))
                bot.webhook_url = request.form.get('webhook_url', '') or None
                db.session.commit()
                flash('Настройки сохранены')
            elif action == 'delete':
                db.session.delete(bot)
                db.session.commit()
                flash('Бот удалён')
                return redirect(url_for('my_bots'))
            return redirect(url_for('bot_settings', bot_id=bot.id))

        return render_template('bot_settings.html', bot=bot)

    @app.route('/github-webhook', methods=['POST'])
    @csrf.exempt
    def github_webhook():
        secret = os.environ.get('GITHUB_WEBHOOK_SECRET', '')
        if secret:
            sig = request.headers.get('X-Hub-Signature-256', '')
            if not sig:
                return 'missing signature', 403
            expected = 'sha256=' + hmac.new(secret.encode(), request.data, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                return 'invalid signature', 403
        event = request.headers.get('X-GitHub-Event')
        if event != 'push':
            return 'ok', 200
        payload = request.json
        ref = payload.get('ref', '')
        if 'main' not in ref and 'master' not in ref:
            return 'ok', 200
        commits = payload.get('commits', [])
        if not commits:
            return 'ok', 200
        repo_name = payload.get('repository', {}).get('full_name', 'project')
        pusher = payload.get('pusher', {}).get('name', 'unknown')
        messages = []
        for c in commits:
            msg = c.get('message', '').split('\n')[0][:100]
            author = c.get('author', {}).get('username', c.get('committer', {}).get('username', ''))
            if author:
                messages.append(f'• {msg} (@{author})')
            else:
                messages.append(f'• {msg}')
        body = f'''🚀 Новое обновление VIBE!

        Загружено {len(commits)} коммит(ов) в {repo_name}:

        {chr(10).join(messages)}

        #обновление #фича'''
        bot = User.query.filter_by(username='NewsBot').first()
        comm = Community.query.filter_by(slug='news').first()
        if bot and comm:
            try:
                post = Post(body=body, author=bot, community=comm, is_community_post=True)
                db.session.add(post)
                db.session.commit()
                current_app.logger.info(f"github-webhook: posted update #{post.id}")
            except Exception as e:
                current_app.logger.error(f"github-webhook: post error: {e}")
                db.session.rollback()
        return 'ok', 200

    # ─── Bot API ────────────────────────────────────────────────────────

    def bot_send_media(bot, media_field, folder, media_type):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        if not chat_id:
            return bot_json_response('chat_id is required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, target_user = result

        file = request.files.get(media_field)
        caption = data.get('caption', '')
        media_url = None
        if file and file.filename:
            media_url = upload_to_cloudinary(file, folder=folder)
        elif data.get(media_field):
            media_url = data.get(media_field)

        if not media_url:
            return bot_json_response(f'{media_field} is required', 400)

        if target_user:
            chat = get_or_create_dm(bot, target_user)
            msg = Message(body=caption, sender_id=bot.id, recipient_id=target_user.id, chat_id=chat.id)
        else:
            msg = Message(body=caption, sender_id=bot.id, chat_id=chat.id)
        db.session.add(msg)
        db.session.flush()
        mm = MessageMedia(message_id=msg.id, media_url=media_url, media_type=media_type)
        db.session.add(mm)
        db.session.commit()
        return bot_json_response({'message_id': msg.id, 'media_url': media_url, 'chat_id': chat.id})

    def bot_get_me(bot):
        return bot_json_response({
            'id': bot.id,
            'username': bot.username,
            'description': bot.bio,
            'can_join_groups': bot.can_join_groups,
            'privacy_mode': bot.privacy_mode,
            'commands': bot.bot_commands,
        })

    def bot_get_chat(bot):
        chat_id = request.args.get('chat_id') or (request.json or {}).get('chat_id')
        if not chat_id:
            return bot_json_response('chat_id is required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, target_user = result
        if target_user:
            return bot_json_response({
                'id': target_user.id,
                'name': target_user.username,
                'type': 'private',
                'username': target_user.username,
            })
        return bot_json_response({
            'id': chat.id,
            'name': chat.name,
            'type': chat.type,
            'members_count': ChatMember.query.filter_by(chat_id=chat.id).count(),
        })

    def bot_get_chat_members(bot):
        chat_id = request.args.get('chat_id') or (request.json or {}).get('chat_id')
        if not chat_id:
            return bot_json_response('chat_id is required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, target_user = result
        if target_user:
            return bot_json_response([{
                'user_id': target_user.id,
                'username': target_user.username,
                'role': 'member',
            }])
        members = ChatMember.query.filter_by(chat_id=chat.id).all()
        return bot_json_response([{
            'user_id': m.user_id,
            'username': User.query.get(m.user_id).username if User.query.get(m.user_id) else 'deleted',
            'role': m.role,
        } for m in members])

    def bot_send_message(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        text = data.get('text', '').strip()
        if not chat_id or not text:
            return bot_json_response('chat_id and text are required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, target_user = result
        if target_user:
            chat = get_or_create_dm(bot, target_user)
            msg = Message(body=text, sender_id=bot.id, recipient_id=target_user.id, chat_id=chat.id)
        else:
            msg = Message(body=text, sender_id=bot.id, chat_id=chat.id)
        db.session.add(msg)
        db.session.commit()
        return bot_json_response({'message_id': msg.id, 'text': text, 'chat_id': chat.id})

    def bot_send_photo(bot):
        return bot_send_media(bot, 'photo', 'bot_photos', 'image')

    def bot_send_video(bot):
        return bot_send_media(bot, 'video', 'bot_videos', 'video')

    def bot_send_voice(bot):
        return bot_send_media(bot, 'voice', 'bot_voice', 'voice')

    def bot_send_document(bot):
        return bot_send_media(bot, 'document', 'bot_documents', 'document')

    def bot_forward_message(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        from_chat_id = data.get('from_chat_id')
        message_id = data.get('message_id')
        if not all([chat_id, from_chat_id, message_id]):
            return bot_json_response('chat_id, from_chat_id, message_id are required', 400)
        original = Message.query.get(int(message_id))
        if not original:
            return bot_json_response('Message not found', 404)
        target_result = resolve_chat(chat_id)
        if not target_result or (target_result[0] is None and target_result[1] is None):
            return bot_json_response('Target chat not found', 404)
        target_chat, target_user = target_result
        if target_user:
            target_chat = get_or_create_dm(bot, target_user)
            new_msg = Message(body=original.body, sender_id=bot.id, recipient_id=target_user.id, chat_id=target_chat.id)
        else:
            new_msg = Message(body=original.body, sender_id=bot.id, chat_id=target_chat.id)
        db.session.add(new_msg)
        db.session.flush()
        for m in original.medias:
            db.session.add(MessageMedia(message_id=new_msg.id, media_url=m.media_url, media_type=m.media_type))
        db.session.commit()
        return bot_json_response({'message_id': new_msg.id, 'chat_id': target_chat.id})

    def bot_delete_message(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        message_id = data.get('message_id')
        msg = Message.query.get(int(message_id))
        if not msg:
            return bot_json_response('Message not found', 404)
        if msg.sender_id != bot.id:
            return bot_json_response('Can only delete own messages', 403)
        db.session.delete(msg)
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_ban_chat_member(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        if not all([chat_id, user_id]):
            return bot_json_response('chat_id and user_id are required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, _ = result
        if not chat:
            return bot_json_response('Cannot ban in private chat', 400)
        member = ChatMember.query.filter_by(chat_id=chat.id, user_id=int(user_id)).first()
        if not member:
            return bot_json_response('User not in chat', 404)
        db.session.delete(member)
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_unban_chat_member(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        if not all([chat_id, user_id]):
            return bot_json_response('chat_id and user_id are required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, _ = result
        if not chat:
            return bot_json_response('Cannot unban in private chat', 400)
        existing = ChatMember.query.filter_by(chat_id=chat.id, user_id=int(user_id)).first()
        if not existing:
            member = ChatMember(chat_id=chat.id, user_id=int(user_id), role='member')
            db.session.add(member)
            db.session.commit()
        return bot_json_response({'ok': True})

    def bot_promote_chat_member(bot):
        data = request.json or request.form
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        if not all([chat_id, user_id]):
            return bot_json_response('chat_id and user_id are required', 400)
        result = resolve_chat(chat_id)
        if not result or (result[0] is None and result[1] is None):
            return bot_json_response('Chat not found', 404)
        chat, _ = result
        if not chat:
            return bot_json_response('Cannot promote in private chat', 400)
        member = ChatMember.query.filter_by(chat_id=chat.id, user_id=int(user_id)).first()
        if not member:
            return bot_json_response('User not in chat', 404)
        member.role = 'admin'
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_set_webhook(bot):
        data = request.json or request.form
        url = data.get('url', '').strip()
        if not url:
            return bot_json_response('url is required', 400)
        bot.webhook_url = url
        db.session.commit()
        return bot_json_response({'ok': True, 'url': url})

    def bot_delete_webhook(bot):
        bot.webhook_url = None
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_get_community(bot):
        community_id = request.args.get('community_id') or (request.json or {}).get('community_id')
        if not community_id:
            return bot_json_response('community_id is required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        return bot_json_response({
            'id': comm.id,
            'name': comm.name,
            'slug': comm.slug,
            'description': comm.description,
            'is_private': comm.is_private,
            'members_count': CommunityMember.query.filter_by(community_id=comm.id, status='approved').count(),
            'posts_count': comm.posts.count(),
        })

    def bot_get_community_members(bot):
        community_id = request.args.get('community_id') or (request.json or {}).get('community_id')
        if not community_id:
            return bot_json_response('community_id is required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        members = CommunityMember.query.filter_by(community_id=comm.id, status='approved').all()
        return bot_json_response([{
            'user_id': m.user_id,
            'username': m.user.username,
            'role': m.role,
            'joined_at': m.created_at.isoformat() if m.created_at else None,
        } for m in members])

    def bot_approve_join_request(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        user_id = data.get('user_id')
        if not all([community_id, user_id]):
            return bot_json_response('community_id and user_id are required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        if not CommunityMember.query.filter(CommunityMember.community_id == comm.id, CommunityMember.user_id == bot.id, CommunityMember.role.in_(('admin', 'creator')), CommunityMember.status == 'approved').first():
            return bot_json_response('Bot is not an admin of this community', 403)
        member = CommunityMember.query.filter_by(community_id=comm.id, user_id=int(user_id), status='pending').first()
        if not member:
            return bot_json_response('User not found or not pending', 404)
        member.status = 'approved'
        db.session.commit()
        return bot_json_response({'ok': True, 'user_id': int(user_id)})

    def bot_deny_join_request(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        user_id = data.get('user_id')
        if not all([community_id, user_id]):
            return bot_json_response('community_id and user_id are required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        if not CommunityMember.query.filter(CommunityMember.community_id == comm.id, CommunityMember.user_id == bot.id, CommunityMember.role.in_(('admin', 'creator')), CommunityMember.status == 'approved').first():
            return bot_json_response('Bot is not an admin of this community', 403)
        member = CommunityMember.query.filter_by(community_id=comm.id, user_id=int(user_id), status='pending').first()
        if not member:
            return bot_json_response('User not found or not pending', 404)
        db.session.delete(member)
        db.session.commit()
        return bot_json_response({'ok': True, 'user_id': int(user_id)})

    def bot_kick_member(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        user_id = data.get('user_id')
        if not all([community_id, user_id]):
            return bot_json_response('community_id and user_id are required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        bot_member = CommunityMember.query.filter_by(community_id=comm.id, user_id=bot.id, status='approved').first()
        if not bot_member or bot_member.role not in ('admin', 'creator'):
            return bot_json_response('Bot is not an admin of this community', 403)
        if int(user_id) == comm.creator_id:
            return bot_json_response('Cannot kick the creator', 403)
        member = CommunityMember.query.filter_by(community_id=comm.id, user_id=int(user_id), status='approved').first()
        if not member:
            return bot_json_response('User not in community', 404)
        db.session.delete(member)
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_promote_to_admin(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        user_id = data.get('user_id')
        if not all([community_id, user_id]):
            return bot_json_response('community_id and user_id are required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        bot_member = CommunityMember.query.filter_by(community_id=comm.id, user_id=bot.id, status='approved').first()
        if not bot_member or bot_member.role not in ('admin', 'creator'):
            return bot_json_response('Bot is not an admin of this community', 403)
        member = CommunityMember.query.filter_by(community_id=comm.id, user_id=int(user_id), status='approved').first()
        if not member:
            return bot_json_response('User not in community', 404)
        member.role = 'admin'
        db.session.commit()
        return bot_json_response({'ok': True})

    def bot_join_community(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        if not community_id:
            return bot_json_response('community_id is required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        existing = CommunityMember.query.filter_by(user_id=bot.id, community_id=comm.id).first()
        if existing:
            if existing.status == 'approved':
                return bot_json_response({'ok': True, 'status': 'already_member'})
            existing.status = 'approved'
            existing.role = 'admin'
            db.session.commit()
            return bot_json_response({'ok': True, 'status': 'approved'})
        member = CommunityMember(user_id=bot.id, community_id=comm.id, status='approved', role='admin')
        db.session.add(member)
        db.session.commit()
        return bot_json_response({'ok': True, 'status': 'joined'})

    def bot_send_post(bot):
        data = request.json or request.form
        community_id = data.get('community_id')
        body = data.get('body', '').strip()
        if not community_id:
            return bot_json_response('community_id is required', 400)
        comm = resolve_community(community_id)
        if not comm:
            return bot_json_response('Community not found', 404)
        if comm.is_banned:
            return bot_json_response('Community is banned for violations', 403)
        bot_member = CommunityMember.query.filter_by(community_id=comm.id, user_id=bot.id, status='approved').first()
        if not bot_member or bot_member.role not in ('admin', 'creator'):
            return bot_json_response('Bot is not an admin of this community', 403)

        result = moderate_post(body, bot, community=comm)
        if result == 'USER_BANNED':
            return bot_json_response('Bot is banned for violations', 403)
        if result == 'BLOCKED':
            return bot_json_response('Post rejected: NSFW content detected', 403)

        post = Post(body=body, author=bot, community=comm, is_community_post=True)
        db.session.add(post)
        db.session.flush()
        files = request.files.getlist('media')
        for file in files:
            if file.filename and allowed_file(file.filename):
                try:
                    if cloudinary_configured:
                        url = upload_to_cloudinary(file, folder='posts')
                        if url:
                            filename = url.split('/')[-1].split('.')[0]
                            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'} else 'document' if ext in {'pdf', 'doc', 'docx', 'txt'} else 'image'
                            media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                            db.session.add(media)
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'} else 'document' if ext in {'pdf', 'doc', 'docx', 'txt'} else 'image'
                        media = Media(filename=filename, media_type=media_type, post=post)
                        db.session.add(media)
                except Exception as e:
                    current_app.logger.error(f"Bot sendPost media upload error: {e}")
        db.session.commit()
        return bot_json_response({
            'post_id': post.id,
            'body': post.body,
            'community_id': comm.id,
            'community_name': comm.name,
            'created_at': post.created_at.isoformat() if post.created_at else None,
        })

    def bot_delete_post(bot):
        data = request.json or request.form
        post_id = data.get('post_id')
        if not post_id:
            return bot_json_response('post_id is required', 400)
        post = Post.query.get(int(post_id))
        if not post:
            return bot_json_response('Post not found', 404)
        if post.user_id == bot.id:
            db.session.delete(post)
            db.session.commit()
            return bot_json_response({'ok': True})
        if post.community_id:
            comm = Community.query.get(post.community_id)
            if comm:
                bot_member = CommunityMember.query.filter_by(community_id=comm.id, user_id=bot.id, status='approved').first()
                if bot_member and bot_member.role in ('admin', 'creator'):
                    db.session.delete(post)
                    db.session.commit()
                    return bot_json_response({'ok': True})
        return bot_json_response('Cannot delete this post', 403)

    @app.route('/bot<token>/<method>', methods=['GET', 'POST', 'DELETE'])
    @csrf.exempt
    def bot_api(token, method):
        bot = User.query.filter_by(bot_token=token, is_bot=True).first()
        if not bot:
            return bot_json_response('Unauthorized: invalid bot token', 401)
        if not bot.can_join_groups:
            return bot_json_response('Bot is disabled', 403)

        handlers = {
            'getMe': bot_get_me,
            'sendMessage': bot_send_message,
            'sendPhoto': bot_send_photo,
            'sendVideo': bot_send_video,
            'sendVoice': bot_send_voice,
            'sendDocument': bot_send_document,
            'forwardMessage': bot_forward_message,
            'deleteMessage': bot_delete_message,
            'banChatMember': bot_ban_chat_member,
            'unbanChatMember': bot_unban_chat_member,
            'promoteChatMember': bot_promote_chat_member,
            'getChat': bot_get_chat,
            'getChatMembers': bot_get_chat_members,
            'setWebhook': bot_set_webhook,
            'deleteWebhook': bot_delete_webhook,
            'getCommunity': bot_get_community,
            'getCommunityMembers': bot_get_community_members,
            'approveJoinRequest': bot_approve_join_request,
            'denyJoinRequest': bot_deny_join_request,
            'kickMember': bot_kick_member,
            'promoteToAdmin': bot_promote_to_admin,
            'deletePost': bot_delete_post,
            'sendPost': bot_send_post,
            'joinCommunity': bot_join_community,
        }

        handler = handlers.get(method)
        if not handler:
            return bot_json_response(f'Unknown method: {method}', 404)
        return handler(bot)

    # ─── Video Routes ───────────────────────────────────────────────

    @app.route('/video/process', methods=['POST'])
    @login_required
    def process_video_route():
        try:
            video = request.files.get('video')
            start_time = float(request.form.get('start_time', 0))
            duration = float(request.form.get('duration')) if request.form.get('duration') else None
            quality = request.form.get('quality', 'medium')

            if not video:
                return jsonify({'error': 'No video file'}), 400

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                video.save(tmp.name)
                temp_path = tmp.name

            result = process_video({'temp_path': temp_path}, start_time, duration, quality)

            try:
                os.unlink(temp_path)
            except:
                pass

            if result:
                return jsonify({'video_url': f'/media/{result}'})
            return jsonify({'error': 'Processing failed'}), 500
        except Exception as e:
            current_app.logger.error(f"Video process route error: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/video/thumbnail', methods=['POST'])
    @login_required
    def video_thumbnail_route():
        try:
            video = request.files.get('video')
            timestamp = float(request.form.get('timestamp', 1))

            if not video:
                return jsonify({'error': 'No video file'}), 400

            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                video.save(tmp.name)
                temp_path = tmp.name

            thumb = generate_video_thumbnail(temp_path, timestamp)

            try:
                os.unlink(temp_path)
            except:
                pass

            if thumb:
                return jsonify({'thumbnail': f'/media/{thumb}'})
            return jsonify({'error': 'Thumbnail generation failed'}), 500
        except Exception as e:
            current_app.logger.error(f"Thumbnail route error: {e}")
            return jsonify({'error': str(e)}), 500
