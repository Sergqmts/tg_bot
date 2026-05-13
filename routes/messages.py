from faster_whisper import WhisperModel
import tempfile

model = None


def get_whisper_model():
    global model
    if model is None:
        model = WhisperModel("base", device="cpu", compute_type="int8")
    return model


def register_routes(app):
    import os, re, cloudinary
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from werkzeug.datastructures import FileStorage
    from datetime import datetime
    from extensions import db
    from models import Message, MessageMedia, Chat, ChatMember, User, Post
    from helpers import enqueue_webhook_dispatch, create_notification, allowed_file, cloudinary_configured, upload_to_cloudinary

    @app.route('/messages')
    @login_required
    def messages():
        blocked_ids = [u.id for u in current_user.blocked]

        conversations = {}
        recent_received = current_user.messages_received.filter(
            ~Message.sender_id.in_(blocked_ids)
        ).order_by(Message.created_at.desc()).limit(100).all()

        for msg in recent_received:
            if msg.sender_id not in conversations:
                conversations[msg.sender_id] = {'user': msg.sender, 'last': msg, 'unread': 0, 'type': 'private'}
            if not msg.read:
                conversations[msg.sender_id]['unread'] += 1

        recent_sent = current_user.messages_sent.filter(
            ~Message.recipient_id.in_(blocked_ids)
        ).order_by(Message.created_at.desc()).limit(100).all()

        for msg in recent_sent:
            if msg.recipient_id not in conversations:
                conversations[msg.recipient_id] = {'user': msg.recipient, 'last': msg, 'unread': 0, 'type': 'private'}

        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        group_chats = []
        for member in user_chats:
            chat = Chat.query.get(member.chat_id)
            if chat and chat.type == 'group':
                last_msg = chat.messages.order_by(Message.created_at.desc()).first()
                unread_count = Message.query.filter_by(chat_id=chat.id).filter(Message.sender_id != current_user.id, Message.read == False).count()
                group_chats.append({
                    'chat': chat,
                    'last': last_msg,
                    'unread': unread_count,
                    'type': 'group'
                })

        conversations = sorted(conversations.values(), key=lambda x: x['last'].created_at if x.get('last') else datetime.min, reverse=True)

        conversations = [c for c in conversations if c.get('user')]

        self_messages = Message.query.filter(
            Message.sender_id == current_user.id,
            Message.recipient_id == current_user.id
        ).order_by(Message.created_at.desc()).first()
        if self_messages:
            conversations.insert(0, {
                'user': current_user,
                'last': self_messages,
                'unread': 0,
                'type': 'self'
            })

        group_chats = sorted(group_chats, key=lambda x: x['last'].created_at if x.get('last') else datetime.min, reverse=True)

        followed = [u for u in current_user.followed
                   if u.id not in conversations and not current_user.is_blocking(u)]
        return render_template('messages.html', conversations=conversations, group_chats=group_chats, suggested_users=followed)


    @app.route('/messages/<username>', methods=['GET', 'POST'])
    @login_required
    def conversation(username):
        other_user = User.query.filter_by(username=username).first_or_404()

        if username != current_user.username:
            if current_user.is_blocking(other_user) or other_user.is_blocking(current_user):
                flash('Вы не можете отправить сообщение этому пользователю')
                return redirect(url_for('messages'))

        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(ChatMember.user_id == current_user.id).join(cm2).filter(
            cm2.user_id == other_user.id,
            Chat.type == 'direct'
        ).first()

        try:
            Message.query.filter_by(sender=other_user, recipient=current_user, read=False).update({'read': True})
            db.session.commit()
        except:
            db.session.rollback()

        if request.method == 'POST':
            body = request.form.get('body', '').strip()
            media_url = None
            media_type = None

            current_app.logger.info(f"POST conversation: form={list(request.form.keys())}, files={list(request.files.keys())}")

            if 'media' in request.files:
                file = request.files['media']
                file_len = file.seek(0, 2)
                file.seek(0)
                if file.filename and file_len > 0 and allowed_file(file.filename):
                    if cloudinary_configured:
                        media_url = upload_to_cloudinary(file, folder='messages')
                        if media_url:
                            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                            if ext in {'mp4', 'webm', 'mov'}:
                                media_type = 'video'
                            elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                                media_type = 'audio'
                            elif ext in {'pdf', 'doc', 'docx', 'txt'}:
                                media_type = 'document'
                            else:
                                media_type = 'image'
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                        media_url = '/media/' + filename
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        if ext in {'mp4', 'webm', 'mov'}:
                            media_type = 'video'
                        elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                            media_type = 'audio'
                        elif ext in {'pdf', 'doc', 'docx', 'txt'}:
                            media_type = 'document'
                        else:
                            media_type = 'image'
                    current_app.logger.info(f"Media: {media_url}, type: {media_type}")
                else:
                    current_app.logger.warning(f"File skipped: filename='{file.filename}', size={file_len}")

            if body or media_url:
                try:
                    msg = Message(body=body or '', sender=current_user, recipient=other_user)
                    db.session.add(msg)
                    db.session.flush()

                    if media_url:
                        media = MessageMedia(message_id=msg.id, media_url=media_url, media_type=media_type)
                        db.session.add(media)

                    db.session.commit()
                    enqueue_webhook_dispatch(msg.id)
                    create_notification(other_user.id, current_user.id, 'message', message_id=msg.id)
                    current_app.logger.info(f"Message saved with media: {media_url}")
                except Exception as e:
                    current_app.logger.error(f"Message error: {e}", exc_info=True)
                    db.session.rollback()

        try:
            if other_user.id == current_user.id:
                messages = Message.query.filter(
                    Message.sender_id == current_user.id,
                    Message.recipient_id == current_user.id
                ).order_by(Message.created_at.desc()).limit(100).all()
                messages = list(reversed(messages))
            else:
                messages = Message.query.filter(
                    ((Message.sender == current_user) & (Message.recipient == other_user)) |
                    ((Message.sender == other_user) & (Message.recipient == current_user))
                ).order_by(Message.created_at.desc()).limit(100).all()
                messages = list(reversed(messages))
        except Exception as e:
            current_app.logger.error(f"Load messages error: {e}")
            messages = []

        return render_template('conversation.html', other_user=other_user, messages=messages, Post=Post, chat=chat, bg_data=chat.get_background_data() if chat else {})


    @app.route('/chat/create', methods=['GET', 'POST'])
    @login_required
    def create_chat():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            member_ids = request.form.getlist('members')

            if not name:
                flash('Введите название чата')
                return redirect(url_for('create_chat'))

            chat = Chat(name=name, creator_id=current_user.id)
            db.session.add(chat)
            db.session.flush()

            member = ChatMember(chat_id=chat.id, user_id=current_user.id, role='admin')
            db.session.add(member)

            for member_id in member_ids:
                if int(member_id) != current_user.id:
                    member = ChatMember(chat_id=chat.id, user_id=int(member_id), role='member')
                    db.session.add(member)

            db.session.commit()
            flash(f'Чат "{name}" создан')
            return redirect(url_for('messages'))

        followed_ids = [u.id for u in current_user.followed]
        bot_ids = [u.id for u in User.query.filter_by(is_bot=True).all()]
        user_ids = set(followed_ids + bot_ids)
        user_ids.discard(current_user.id)
        users = User.query.filter(User.id.in_(user_ids)).all()
        return render_template('create_chat.html', users=users)


    @app.route('/messages/<username>/voice', methods=['POST'])
    @login_required
    def send_voice(username):
        other_user = User.query.filter_by(username=username).first_or_404()

        if current_user.is_blocking(other_user) or other_user.is_blocking(current_user):
            return 'Blocked', 403

        current_app.logger.info(f"Voice message from {current_user.username} to {username}")
        current_app.logger.info(f"Files: {request.files}")
        current_app.logger.info(f"Voice file: {request.files.get('voice')}")

        if 'voice' not in request.files:
            current_app.logger.error("No voice file in request")
            return {'error': 'No voice file'}, 400

        voice_file = request.files['voice']
        if not voice_file.filename:
            current_app.logger.error("Empty filename")
            return {'error': 'No file'}, 400

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                voice_file.save(tmp.name)
                temp_path = tmp.name

            whisper_model = get_whisper_model()
            segments, info = whisper_model.transcribe(temp_path, language='ru')

            transcription = ''
            for segment in segments:
                transcription += segment.text.strip() + ' '
            transcription = transcription.strip()

            os.unlink(temp_path)
            temp_path = None

            voice_file.seek(0)
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    voice_file, folder='voice', resource_type='video',
                    timeout=30
                )
                media_url = result['secure_url']
            else:
                filename = secure_filename(f"voice_{int(datetime.now().timestamp())}.webm")
                voice_file.seek(0)
                voice_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                media_url = '/media/' + filename

            msg = Message(body=transcription if transcription else '', sender=current_user, recipient=other_user, transcription=transcription)
            db.session.add(msg)
            db.session.flush()

            media = MessageMedia(message_id=msg.id, media_url=media_url, media_type='voice')
            db.session.add(media)
            db.session.commit()
            enqueue_webhook_dispatch(msg.id)

            return 'OK', 200
        except Exception as e:
            current_app.logger.error(f"Voice message error: {e}")
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            return str(e), 500


    @app.route('/messages/<username>/video-message', methods=['POST'])
    @login_required
    def send_video_message(username):
        other_user = User.query.filter_by(username=username).first_or_404()

        if current_user.is_blocking(other_user) or other_user.is_blocking(current_user):
            return 'Blocked', 403

        if 'video_message' not in request.files:
            return {'error': 'No video file'}, 400

        video_file = request.files['video_message']
        if not video_file.filename:
            return {'error': 'No file'}, 400

        ext = video_file.filename.rsplit('.', 1)[1].lower() if '.' in video_file.filename else 'webm'
        if ext not in {'webm', 'mp4', 'mov'}:
            return {'error': 'Invalid format'}, 400

        try:
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    video_file, folder='video_messages', resource_type='video',
                    timeout=30
                )
                media_url = result['secure_url']
            else:
                filename = secure_filename(f"vm_{int(datetime.now().timestamp())}_{current_user.id}.{ext}")
                video_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                media_url = '/media/' + filename

            msg = Message(sender=current_user, recipient=other_user, body='')
            db.session.add(msg)
            db.session.flush()

            media = MessageMedia(message_id=msg.id, media_url=media_url, media_type='video_message')
            db.session.add(media)
            db.session.commit()
            enqueue_webhook_dispatch(msg.id)

            return 'OK', 200
        except Exception as e:
            current_app.logger.error(f"Video message error: {e}")
            return str(e), 500


    @app.route('/chat/<int:chat_id>', methods=['GET', 'POST'])
    @login_required
    def chat_view(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            flash('Вы не состоите в этом чате')
            return redirect(url_for('messages'))

        if request.method == 'POST':
            body = request.form.get('body', '').strip()
            post_id = request.form.get('post_id')
            media_url = None
            media_type = None

            current_app.logger.info(f"POST chat: form={list(request.form.keys())}, files={list(request.files.keys())}")

            if 'media' in request.files:
                    file = request.files['media']
                    file_len = file.seek(0, 2)
                    file.seek(0)
                    if file.filename and file_len > 0 and allowed_file(file.filename):
                        try:
                            media_url = None
                            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                            if ext in {'mp4', 'webm', 'mov'}:
                                media_type = 'video'
                            elif ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
                                media_type = 'image'
                            else:
                                media_type = 'document'

                            if cloudinary_configured:
                                media_url = upload_to_cloudinary(file, folder='messages')
                                if media_url:
                                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                                    media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                                    if ext in {'pdf', 'doc', 'docx', 'txt'}:
                                        media_type = 'document'
                                    elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                                        media_type = 'audio'

                            if not media_url:
                                filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                                media_url = '/media/' + filename
                                ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                                media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                                if ext in {'pdf', 'doc', 'docx', 'txt'}:
                                    media_type = 'document'
                                elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                                    media_type = 'audio'
                            current_app.logger.info(f"Media: {media_url}, type: {media_type}")
                        except Exception as e:
                            current_app.logger.error(f"Media upload error: {e}", exc_info=True)
                    else:
                        current_app.logger.warning(f"File not allowed or empty: filename='{file.filename}', size={file_len}")

            has_content = body or media_url or post_id

            if has_content:
                try:
                    msg = Message(
                        body=body or '',
                        sender_id=current_user.id,
                        chat_id=chat_id,
                        post_id=int(post_id) if post_id else None
                    )
                    db.session.add(msg)
                    db.session.flush()
                    current_app.logger.warning(f"Message created with id={msg.id}")

                    if media_url:
                        current_app.logger.warning(f"Adding media: url={media_url}, type={media_type}")
                        media = MessageMedia(message_id=msg.id, media_url=media_url, media_type=media_type)
                        db.session.add(media)

                    db.session.commit()
                    enqueue_webhook_dispatch(msg.id)
                    current_app.logger.warning(f"Message and media saved successfully!")
                except Exception as e:
                    current_app.logger.error(f"Chat message error: {e}")
                    db.session.rollback()

        messages = chat.messages.order_by(Message.created_at.asc()).all()

        Message.query.filter_by(chat_id=chat_id).filter(Message.sender_id != current_user.id, Message.read == False).update({'read': True})
        db.session.commit()

        return render_template('chat.html', chat=chat, messages=messages, Post=Post, bg_data=chat.get_background_data() if chat else {})


    @app.route('/chat/<int:chat_id>/voice', methods=['POST'])
    @login_required
    def send_chat_voice(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            return 'Not a member', 403

        if 'voice' not in request.files:
            return 'No voice file', 400

        voice_file = request.files['voice']
        if not voice_file.filename:
            return 'No file', 400

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as tmp:
                voice_file.save(tmp.name)
                temp_path = tmp.name

            whisper_model = get_whisper_model()
            segments, info = whisper_model.transcribe(temp_path, language='ru')

            transcription = ''
            for segment in segments:
                transcription += segment.text.strip() + ' '
            transcription = transcription.strip()

            os.unlink(temp_path)
            temp_path = None

            voice_file.seek(0)
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    voice_file, folder='voice', resource_type='video',
                    timeout=30
                )
                media_url = result['secure_url']
            else:
                filename = secure_filename(f"voice_{int(datetime.now().timestamp())}.webm")
                voice_file.seek(0)
                voice_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                media_url = '/media/' + filename

            msg = Message(body=transcription if transcription else '', sender=current_user, chat_id=chat_id, transcription=transcription)
            db.session.add(msg)
            db.session.flush()

            media = MessageMedia(message_id=msg.id, media_url=media_url, media_type='voice')
            db.session.add(media)
            db.session.commit()
            enqueue_webhook_dispatch(msg.id)

            return 'OK', 200
        except Exception as e:
            current_app.logger.error(f"Chat voice message error: {e}")
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            return str(e), 500


    @app.route('/chat/<int:chat_id>/video-message', methods=['POST'])
    @login_required
    def send_chat_video_message(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            return 'Not a member', 403

        if 'video_message' not in request.files:
            return {'error': 'No video file'}, 400

        video_file = request.files['video_message']
        if not video_file.filename:
            return {'error': 'No file'}, 400

        ext = video_file.filename.rsplit('.', 1)[1].lower() if '.' in video_file.filename else 'webm'
        if ext not in {'webm', 'mp4', 'mov'}:
            return {'error': 'Invalid format'}, 400

        try:
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    video_file, folder='video_messages', resource_type='video',
                    timeout=30
                )
                media_url = result['secure_url']
            else:
                filename = secure_filename(f"vm_{int(datetime.now().timestamp())}_{current_user.id}.{ext}")
                video_file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                media_url = '/media/' + filename

            msg = Message(sender=current_user, chat_id=chat_id, body='')
            db.session.add(msg)
            db.session.flush()

            media = MessageMedia(message_id=msg.id, media_url=media_url, media_type='video_message')
            db.session.add(media)
            db.session.commit()
            enqueue_webhook_dispatch(msg.id)

            return 'OK', 200
        except Exception as e:
            current_app.logger.error(f"Chat video message error: {e}")
            return str(e), 500


    @app.route('/chat/<int:chat_id>/leave', methods=['POST'])
    @login_required
    def leave_chat(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            flash('Вы не состоите в этом чате')
            return redirect(url_for('messages'))

        if chat.creator_id == current_user.id:
            flash('Создатель не может покинуть чат')
            return redirect(url_for('chat_view', chat_id=chat_id))

        db.session.delete(member)
        db.session.commit()
        flash('Вы покинули чат')
        return redirect(url_for('messages'))


    @app.route('/message/<int:message_id>/forward', methods=['GET', 'POST'])
    @login_required
    def forward_message(message_id):
        message = Message.query.get_or_404(message_id)

        if message.sender_id != current_user.id and message.recipient_id != current_user.id:
            if not message.chat_id:
                flash('Нет доступа к этому сообщению')
                return redirect(url_for('messages'))
            member = ChatMember.query.filter_by(chat_id=message.chat_id, user_id=current_user.id).first()
            if not member:
                flash('Нет доступа к этому сообщению')
                return redirect(url_for('messages'))

        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'to_chat':
                chat_id = request.form.get('chat_id')
                if chat_id:
                    chat = Chat.query.get(int(chat_id))
                    member = ChatMember.query.filter_by(chat_id=chat.id, user_id=current_user.id).first()
                    if member:
                        if message.body:
                            forward_body = message.body
                        else:
                            forward_body = None

                        new_msg = Message(
                            body=forward_body,
                            sender_id=current_user.id,
                            chat_id=chat.id,
                            post_id=message.post_id,
                            forwarded_from_id=message.sender_id
                        )
                        db.session.add(new_msg)
                        db.session.flush()

                        for m in message.medias:
                            new_media = MessageMedia(
                                message_id=new_msg.id,
                                media_url=m.media_url,
                                media_type=m.media_type
                            )
                            db.session.add(new_media)

                        db.session.commit()
                        flash(f'Сообщение переслано в чат {chat.name}')
                        return redirect(url_for('chat_view', chat_id=chat.id))

            elif action == 'to_user':
                username = request.form.get('username', '').strip()
                user = User.query.filter_by(username=username).first()
                if user:
                    if message.body:
                        forward_body = message.body
                    else:
                        forward_body = None

                    new_msg = Message(
                        body=forward_body,
                        sender_id=current_user.id,
                        recipient_id=user.id,
                        post_id=message.post_id,
                        forwarded_from_id=message.sender_id
                    )
                    db.session.add(new_msg)
                    db.session.flush()

                    for m in message.medias:
                        new_media = MessageMedia(
                            message_id=new_msg.id,
                            media_url=m.media_url,
                            media_type=m.media_type
                        )
                        db.session.add(new_media)

                    db.session.commit()
                    flash(f'Сообщение переслано пользователю {user.username}')
                    return redirect(url_for('conversation', username=user.username))

            flash('Ошибка при пересылке')
            return redirect(url_for('messages'))

        user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
        chats = [Chat.query.get(cm.chat_id) for cm in user_chats]

        following = current_user.followed.all()

        other_user = None
        if message.recipient_id and not message.chat_id:
            other_user = User.query.get(message.recipient_id)

        return render_template('forward_message.html', message=message, chats=chats, other_user=other_user, following=following, Post=Post)


    @login_required
    def forward_message_post(message_id):
        message = Message.query.get_or_404(message_id)

        action = request.form.get('action')

        if action == 'to_chat':
            chat_id = request.form.get('chat_id')
            if chat_id:
                chat = Chat.query.get(int(chat_id))
                member = ChatMember.query.filter_by(chat_id=chat.id, user_id=current_user.id).first()
                if member:
                    if message.body:
                        forward_body = message.body
                    else:
                        forward_body = None

                    new_msg = Message(
                        body=forward_body,
                        sender_id=current_user.id,
                        chat_id=chat.id,
                        post_id=message.post_id,
                        forwarded_from_id=message.sender_id
                    )
                    db.session.add(new_msg)
                    db.session.flush()

                    for m in message.medias:
                        new_media = MessageMedia(
                            message_id=new_msg.id,
                            media_url=m.media_url,
                            media_type=m.media_type
                        )
                        db.session.add(new_media)

                    db.session.commit()
                    flash(f'Сообщение переслано в чат {chat.name}')
                    return redirect(url_for('chat_view', chat_id=chat.id))

        elif action == 'to_user':
            username = request.form.get('username', '').strip()
            user = User.query.filter_by(username=username).first()
            if user:
                if message.body:
                    forward_body = message.body
                else:
                    forward_body = None

                new_msg = Message(
                    body=forward_body,
                    sender_id=current_user.id,
                    recipient_id=user.id,
                    post_id=message.post_id,
                    forwarded_from_id=message.sender_id
                )
                db.session.add(new_msg)
                db.session.flush()

                for m in message.medias:
                    new_media = MessageMedia(
                        message_id=new_msg.id,
                        media_url=m.media_url,
                        media_type=m.media_type
                    )
                    db.session.add(new_media)

                db.session.commit()
                flash(f'Сообщение переслано пользователю {user.username}')
                return redirect(url_for('conversation', username=user.username))

        flash('Ошибка при пересылке')
        return redirect(url_for('messages'))


    @app.route('/message/<int:message_id>/delete', methods=['POST'])
    @login_required
    def delete_message(message_id):
        message = Message.query.get_or_404(message_id)

        is_sender = message.sender_id == current_user.id
        is_recipient = message.recipient_id == current_user.id if message.recipient_id else False

        member = None
        if message.chat_id:
            member = ChatMember.query.filter_by(chat_id=message.chat_id, user_id=current_user.id).first()

        is_chat_member = member is not None if message.chat_id else False

        if not (is_sender or is_recipient or is_chat_member):
            flash('Нет доступа к этому сообщению')
            return redirect(request.referrer or url_for('messages'))

        delete_type = request.form.get('delete_type', 'me')

        if delete_type == 'me':
            message.body = '[удалено]'
            for m in message.medias:
                db.session.delete(m)
            db.session.commit()
            flash('Сообщение удалено для вас')
        elif delete_type == 'all':
            if is_sender:
                for m in message.medias:
                    db.session.delete(m)
                db.session.delete(message)
                db.session.commit()
                flash('Сообщение удалено для всех')
            else:
                flash('Только автор может удалить сообщение для всех')

        return redirect(request.referrer or url_for('messages'))


    @app.route('/chat/<int:chat_id>/members')
    @login_required
    def chat_members(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            flash('Вы не состоите в этом чате')
            return redirect(url_for('messages'))

        members = ChatMember.query.filter_by(chat_id=chat_id).all()
        all_users = User.query.filter(User.id != current_user.id).all()
        current_member_ids = [m.user_id for m in members]
        available_users = [u for u in all_users if u.id not in current_member_ids]
        current_user_role = member.role

        return render_template('chat_members.html', chat=chat, members=members, available_users=available_users, current_user_role=current_user_role)


    @app.route('/chat/<int:chat_id>/shared_media')
    @login_required
    def chat_shared_media(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            flash('Вы не состоите в этом чате')
            return redirect(url_for('messages'))

        media_type = request.args.get('type', 'photos')

        photos_videos = []
        documents = []
        links = []

        messages = Message.query.filter_by(chat_id=chat_id).all()

        for msg in messages:
            if msg.medias:
                for media in msg.medias:
                    if media.media_type in ['image', 'video']:
                        photos_videos.append({'media': media, 'message': msg})
                    else:
                        documents.append({'media': media, 'message': msg})

            if msg.body:
                import re
                urls = re.findall(r'(https?://[^\s]+)', msg.body)
                for url in urls:
                    links.append({'url': url, 'message': msg})

        seen = set()
        unique_links = []
        for item in links:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique_links.append(item)

        return render_template('chat_shared_media.html',
                             chat=chat,
                             photos_videos=photos_videos if media_type == 'photos' else [],
                             documents=documents if media_type == 'docs' else [],
                             links=unique_links if media_type == 'links' else [],
                             media_type=media_type)


    @app.route('/direct/<int:user_id>/shared_media')
    @login_required
    def direct_shared_media(user_id):
        other_user = User.query.get_or_404(user_id)

        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(ChatMember.user_id == current_user.id).join(cm2).filter(
            cm2.user_id == other_user.id,
            Chat.type == 'direct'
        ).first()

        if not chat:
            flash('Чат не найден')
            return redirect(url_for('messages'))

        media_type = request.args.get('type', 'photos')

        photos_videos = []
        documents = []
        links = []

        messages = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.recipient_id == other_user.id)) |
            ((Message.sender_id == other_user.id) & (Message.recipient_id == current_user.id))
        ).all()

        for msg in messages:
            if msg.medias:
                for media in msg.medias:
                    if media.media_type in ['image', 'video']:
                        photos_videos.append({'media': media, 'message': msg})
                    else:
                        documents.append({'media': media, 'message': msg})

            if msg.body:
                import re
                urls = re.findall(r'(https?://[^\s]+)', msg.body)
                for url in urls:
                    links.append({'url': url, 'message': msg})

        seen = set()
        unique_links = []
        for item in links:
            if item['url'] not in seen:
                seen.add(item['url'])
                unique_links.append(item)

        return render_template('direct_shared_media.html',
                             other_user=other_user,
                             photos_videos=photos_videos if media_type == 'photos' else [],
                             documents=documents if media_type == 'docs' else [],
                             links=unique_links if media_type == 'links' else [],
                             media_type=media_type)


    @app.route('/direct/<int:user_id>/edit', methods=['GET', 'POST'])
    @login_required
    def direct_edit(user_id):
        other_user = User.query.get_or_404(user_id)

        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(ChatMember.user_id == current_user.id).join(cm2).filter(
            cm2.user_id == other_user.id,
            Chat.type == 'direct'
        ).first()

        if not chat:
            flash('Чат не найден')
            return redirect(url_for('conversation', user_id=user_id))

        if request.method == 'POST':
            bg_type = request.form.get('background_type', 'default')
            bg_value = request.form.get('background_value', '').strip()

            if bg_type in ['default', 'color', 'gradient', 'image']:
                chat.background_type = bg_type
                if bg_type == 'default':
                    chat.background_value = ''
                elif bg_type == 'image' and 'background_image' in request.files:
                    file = request.files['background_image']
                    if file.filename and allowed_file(file.filename):
                        if cloudinary_configured:
                            url = upload_to_cloudinary(file, folder='chat_backgrounds')
                            if url:
                                chat.background_value = url
                        else:
                            filename = secure_filename(f"bg_{datetime.now().timestamp()}_{file.filename}")
                            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                            chat.background_value = filename
                else:
                    chat.background_value = bg_value

            db.session.commit()
            flash('Фон чата обновлён')
            return redirect(url_for('conversation', username=other_user.username))

        return render_template('direct_edit.html', chat=chat, other_user=other_user)


    @app.route('/chat/<int:chat_id>/add_member', methods=['GET', 'POST'])
    @login_required
    def chat_add_member(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member:
            flash('Вы не состоите в этом чате')
            return redirect(url_for('messages'))

        if request.method == 'POST':
            user_id = request.form.get('user_id')
            if user_id:
                user = User.query.get(user_id)
                if user:
                    new_member = ChatMember(chat_id=chat_id, user_id=user.id, role='member')
                    db.session.add(new_member)
                    db.session.commit()
                    flash(f'{user.username} добавлен в чат')
            return redirect(url_for('chat_members', chat_id=chat_id))

        members = ChatMember.query.filter_by(chat_id=chat_id).all()
        current_member_ids = [m.user_id for m in members]
        all_users = User.query.filter(User.id.notin_(current_member_ids)).all()

        return render_template('chat_add_member.html', chat=chat, users=all_users)


    @app.route('/chat/<int:chat_id>/remove_member/<int:user_id>', methods=['POST'])
    @login_required
    def chat_remove_member(chat_id, user_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member or member.role != 'admin':
            flash('Только администратор может удалять участников')
            return redirect(url_for('chat_members', chat_id=chat_id))

        if user_id == chat.creator_id:
            flash('Нельзя удалить создателя чата')
            return redirect(url_for('chat_members', chat_id=chat_id))

        member_to_remove = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
        if member_to_remove:
            db.session.delete(member_to_remove)
            db.session.commit()
            flash('Участник удален')

        return redirect(url_for('chat_members', chat_id=chat_id))


    @app.route('/chat/<int:chat_id>/make_admin/<int:user_id>', methods=['POST'])
    @login_required
    def chat_make_admin(chat_id, user_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member or member.role != 'admin':
            flash('Только администратор может назначать админов')
            return redirect(url_for('chat_members', chat_id=chat_id))

        target_member = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
        if target_member:
            target_member.role = 'admin'
            db.session.commit()
            flash('Участник назначен администратором')

        return redirect(url_for('chat_members', chat_id=chat_id))


    @app.route('/chat/<int:chat_id>/edit', methods=['GET', 'POST'])
    @login_required
    def chat_edit(chat_id):
        chat = Chat.query.get_or_404(chat_id)
        member = ChatMember.query.filter_by(chat_id=chat_id, user_id=current_user.id).first()

        if not member or member.role != 'admin':
            flash('Только администратор может редактировать чат')
            return redirect(url_for('chat_view', chat_id=chat_id))

        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if name:
                chat.name = name

            bg_type = request.form.get('background_type', 'default')

            if bg_type in ['default', 'color', 'gradient', 'image']:
                chat.background_type = bg_type
                import json
                try:
                    bg_data = json.loads(chat.background_value) if chat.background_value else {}
                except json.JSONDecodeError:
                    bg_data = {}

                if bg_type == 'default':
                    bg_data = {"light": "chat-backgrounds/light.png", "dark": "chat-backgrounds/dark.png"}
                elif bg_type == 'image':
                    for theme, field in [('light', 'background_image_light'), ('dark', 'background_image_dark')]:
                        if field in request.files:
                            file = request.files[field]
                            if file.filename and allowed_file(file.filename):
                                if cloudinary_configured:
                                    url = upload_to_cloudinary(file, folder='chat_backgrounds')
                                    if url:
                                        bg_data[theme] = url
                                else:
                                    filename = secure_filename(f"bg_{datetime.now().timestamp()}_{file.filename}")
                                    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                                    bg_data[theme] = filename
                    light_val = request.form.get('background_value_light', '').strip()
                    dark_val = request.form.get('background_value_dark', '').strip()
                    if light_val:
                        bg_data['light'] = light_val
                    if dark_val:
                        bg_data['dark'] = dark_val
                else:
                    light_val = request.form.get('background_value_light', '').strip()
                    dark_val = request.form.get('background_value_dark', '').strip()
                    bg_data['light'] = light_val
                    bg_data['dark'] = dark_val

                chat.background_value = json.dumps(bg_data)

            if 'avatar' in request.files:
                file = request.files['avatar']
                if file.filename and allowed_file(file.filename):
                    if cloudinary_configured:
                        media_url = upload_to_cloudinary(file, folder='chats')
                        if media_url:
                            chat.avatar = media_url
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                        chat.avatar = filename

            db.session.commit()
            flash('Чат обновлён')
            return redirect(url_for('chat_view', chat_id=chat_id))

        return render_template('chat_edit.html', chat=chat, bg_data=chat.get_background_data() if chat else {})
