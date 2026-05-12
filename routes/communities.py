def register_routes(app):
    import os, re, base64, io
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify, send_from_directory, current_app
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from werkzeug.datastructures import FileStorage
    from datetime import datetime
    from PIL import Image, ImageEnhance, ImageFilter
    from extensions import db
    from models import Post, Repost, SavedPost, Reaction, Comment, CommentReaction, CommentMedia, MessageReaction, Message, Media, Tag, PostTag, Draft, Shorts, User, Community, Chat, ChatMember, MusicTrack, Notification, ModerationLog, CommunityMember, CommunityEvent, EventAttendee, CommunityForm, CommunityPostForm

    from app import moderate_post, create_notification, allowed_file, cloudinary_configured, upload_to_cloudinary

    @app.route('/communities')
    def communities():
        all_communities = Community.query.order_by(Community.created_at.desc()).all()
        return render_template('communities.html', communities=all_communities)

    @app.route('/communities/create', methods=['GET', 'POST'])
    @login_required
    def create_community():
        form = CommunityForm()
        if form.validate_on_submit():
            slug = form.name.data.lower().replace(' ', '-').replace('_', '-')
            slug = ''.join(c for c in slug if c.isalnum() or c == '-')

            community = Community(
                name=form.name.data,
                slug=slug,
                description=form.description.data,
                is_private=form.is_private.data,
                creator=current_user
            )

            if form.image.data:
                file = form.image.data
                url = upload_to_cloudinary(file, folder='communities')
                if url:
                    community.image = url

            db.session.add(community)
            db.session.flush()

            member = CommunityMember(user_id=current_user.id, community_id=community.id, role='creator', status='approved')
            db.session.add(member)

            db.session.commit()
            flash('Сообщество создано!')
            return redirect(url_for('community', slug=slug))
        return render_template('create_community.html', form=form)

    @app.route('/community/<slug>', methods=['GET', 'POST'])
    def community(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        is_member = current_user.is_authenticated and current_user.is_member(comm)
        is_admin = current_user.is_authenticated and current_user.is_admin(comm)
        is_pending = current_user.is_authenticated and current_user.is_pending(comm)
        is_staff_view = current_user.is_authenticated and current_user.is_staff

        if comm.is_private and not is_member and not is_staff_view:
            if current_user.is_authenticated:
                flash('Это приватное сообщество')
                return redirect(url_for('communities'))
            return redirect(url_for('login'))

        posts = comm.posts.order_by(Post.created_at.desc()).all()

        show_edit = request.args.get('edit') == '1' and is_admin

        if show_edit and request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()

            if name:
                comm.name = name
                comm.description = description

                if 'image' in request.files:
                    file = request.files['image']
                    if file.filename and allowed_file(file.filename):
                        if cloudinary_configured:
                            url = upload_to_cloudinary(file, folder='communities')
                            if url:
                                comm.image = url

                db.session.commit()
                flash('Сообщество обновлено')
                return redirect(url_for('community', slug=comm.slug))

        return render_template('community.html', community=comm, posts=posts, is_member=is_member, is_admin=is_admin, is_pending=is_pending, show_edit=show_edit, is_staff_view=is_staff_view)

    @app.route('/community/<slug>/join', methods=['POST'])
    @login_required
    def join_community(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if current_user.is_member(comm):
            flash('Вы уже участник сообщества')
        elif current_user.is_pending(comm):
            flash('Ваша заявка на рассмотрении')
        else:
            current_user.join_community(comm)
            db.session.commit()
            if comm.is_private:
                flash('Заявка отправлена на рассмотрение')
            else:
                flash(f'Вы вступили в сообщество "{comm.name}"')
        return redirect(url_for('community', slug=slug))

    @app.route('/community/<slug>/events', methods=['GET', 'POST'])
    @login_required
    def community_events(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        is_member = current_user.is_member(comm)
        is_admin = current_user.is_admin(comm)

        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            event_date = request.form.get('event_date')
            location = request.form.get('location', '').strip()

            if title and event_date:
                try:
                    event_datetime = datetime.strptime(event_date, '%Y-%m-%dT%H:%M')
                    event = CommunityEvent(
                        community_id=comm.id,
                        creator_id=current_user.id,
                        title=title,
                        description=description,
                        event_date=event_datetime,
                        location=location
                    )
                    db.session.add(event)
                    db.session.commit()
                    flash('Мероприятие создано!')
                    return redirect(url_for('community_events', slug=slug))
                except ValueError:
                    flash('Неверный формат даты')
            else:
                flash('Заполните название и дату')

        for event in CommunityEvent.query.filter_by(community_id=comm.id).all():
            event.archive_if_expired()

        show_archived = request.args.get('archived') == '1' and is_admin
        if show_archived:
            events = CommunityEvent.query.filter_by(community_id=comm.id, is_archived=True).order_by(CommunityEvent.event_date.desc()).all()
        else:
            events = CommunityEvent.query.filter_by(community_id=comm.id, is_archived=False).order_by(CommunityEvent.event_date.asc()).all()

        return render_template('community_events.html', community=comm, events=events, is_member=is_member, is_admin=is_admin, show_archived=show_archived)

    @app.route('/community/<slug>/event/<int:event_id>/rsvp', methods=['POST'])
    @login_required
    def event_rsvp(slug, event_id):
        event = CommunityEvent.query.get_or_404(event_id)
        existing = EventAttendee.query.filter_by(event_id=event.id, user_id=current_user.id).first()

        is_new_attendance = False

        if existing:
            if existing.status == 'going':
                existing.status = 'maybe'
            elif existing.status == 'maybe':
                db.session.delete(existing)
            else:
                existing.status = 'going'
        else:
            attendee = EventAttendee(event_id=event.id, user_id=current_user.id, status='going')
            db.session.add(attendee)
            is_new_attendance = True

        db.session.commit()

        if is_new_attendance:
            community = event.community
            event_date = event.event_date.strftime('%d.%m.%Y в %H:%M')

            message_body = f"📢 От сообщества \"{community.name}\"\n\n🎉 Спасибо за регистрацию на мероприятие \"{event.title}\"!\n\n📅 Дата: {event_date}"
            if event.location:
                message_body += f"\n📍 Место: {event.location}"

            msg = Message(
                sender_id=community.creator_id,
                recipient_id=current_user.id,
                body=message_body
            )
            db.session.add(msg)
            db.session.commit()
            flash('Вы зарегистрированы! Информация отправлена вам в сообщения.')

        return redirect(url_for('community_events', slug=slug))

    @app.route('/community/<slug>/events/archived')
    @login_required
    def community_events_archive(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()

        if not current_user.is_admin(comm):
            abort(403)

        events = CommunityEvent.query.filter_by(community_id=comm.id, is_archived=True).order_by(CommunityEvent.event_date.desc()).all()
        return render_template('community_events_archive.html', community=comm, events=events)

    @app.route('/community/<slug>/event/<int:event_id>/unarchive', methods=['POST'])
    @login_required
    def unarchive_event(slug, event_id):
        comm = Community.query.filter_by(slug=slug).first_or_404()

        if not current_user.is_admin(comm):
            abort(403)

        event = CommunityEvent.query.get_or_404(event_id)
        event.is_archived = False
        db.session.commit()
        flash('Мероприятие восстановлено')
        return redirect(url_for('community_events_archive', slug=slug))

    @app.route('/community/<slug>/leave', methods=['POST'])
    @login_required
    def leave_community(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if current_user.is_admin(comm) and comm.creator == current_user:
            flash('Создатель не может покинуть сообщество')
        else:
            current_user.leave_community(comm)
            db.session.commit()
            flash(f'Вы покинули сообщество "{comm.name}"')
        return redirect(url_for('community', slug=slug))

    @app.route('/community/<slug>/post', methods=['GET', 'POST'])
    @login_required
    def community_post(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if not current_user.is_admin(comm):
            flash('Только создатель может публиковать записи')
            return redirect(url_for('community', slug=slug))
        if comm.is_banned:
            flash('Сообщество заблокировано за нарушение правил')
            return redirect(url_for('community', slug=slug))

        form = CommunityPostForm()
        if form.validate_on_submit():
            body = form.body.data or ''
            result = moderate_post(body, current_user, community=comm)
            if result == 'USER_BANNED':
                flash('Ваш аккаунт заблокирован за нарушение правил')
                return redirect(url_for('community', slug=slug))
            if result == 'BLOCKED':
                flash('Пост отклонён: обнаружен неприемлемый контент. Проверьте личные сообщения.')
                return redirect(url_for('community', slug=slug))

            post = Post(body=body, author=current_user, community=comm, is_community_post=True)
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
                                media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg'} else 'image'
                                media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                                db.session.add(media)
                        else:
                            filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                            file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                            ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg'} else 'image'
                            media = Media(filename=filename, media_type=media_type, post=post)
                            db.session.add(media)
                    except Exception as e:
                        current_app.logger.error(f"Media upload error: {e}")

            db.session.commit()
            flash('Запись опубликована!')
            return redirect(url_for('community', slug=slug))
        return render_template('community_post.html', form=form, community=comm)

    @app.route('/community/<slug>/members')
    def community_members(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        members = comm.members.filter_by(status='approved').order_by(CommunityMember.created_at.desc()).all()
        return render_template('community_members.html', community=comm, members=members)

    @app.route('/community/<slug>/requests')
    @login_required
    def community_requests(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if not current_user.is_admin(comm):
            abort(403)
        requests = comm.members.filter_by(status='pending').order_by(CommunityMember.created_at.desc()).all()
        return render_template('community_requests.html', community=comm, requests=requests)

    @app.route('/community/<slug>/approve/<int:user_id>', methods=['POST'])
    @login_required
    def approve_member(slug, user_id):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if not current_user.is_admin(comm):
            abort(403)
        member = CommunityMember.query.filter_by(community=comm, user_id=user_id, status='pending').first()
        if member:
            member.status = 'approved'
            db.session.commit()
            flash('Участник одобрен')
        return redirect(url_for('community_requests', slug=slug))

    @app.route('/community/<slug>/deny/<int:user_id>', methods=['POST'])
    @login_required
    def deny_member(slug, user_id):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if not current_user.is_admin(comm):
            abort(403)
        member = CommunityMember.query.filter_by(community=comm, user_id=user_id, status='pending').first()
        if member:
            db.session.delete(member)
            db.session.commit()
            flash('Заявка отклонена')
        return redirect(url_for('community_requests', slug=slug))

    @app.route('/community/<slug>/delete', methods=['POST'])
    @login_required
    def delete_community(slug):
        comm = Community.query.filter_by(slug=slug).first_or_404()
        if comm.creator != current_user:
            abort(403)
        db.session.delete(comm)
        db.session.commit()
        flash('Сообщество удалено')
        return redirect(url_for('communities'))

    @app.route('/media/<filename>')
    def uploaded_file(filename):
        current_app.logger.info(f"Looking for file: {filename}")
        return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
