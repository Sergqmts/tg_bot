def register_routes(app):
    import base64, io, os
    from flask import render_template, redirect, url_for, flash, request, abort
    from flask_login import login_required, current_user
    from werkzeug.utils import secure_filename
    from werkzeug.datastructures import FileStorage
    from datetime import datetime, timedelta
    from extensions import db
    from models import Story, StoryReaction, StoryComment, User, Message

    @app.route('/story/create', methods=['GET', 'POST'])
    @login_required
    def create_story():
        if request.method == 'POST':
            media_data = request.form.get('media_data')
            
            if media_data:
                header, data = media_data.split(',', 1)
                if 'image/jpeg' in header or 'image/png' in header or 'image/jpg' in header:
                    ext = 'jpg'
                    media_type = 'image'
                elif 'video/mp4' in header or 'video/webm' in header or 'video/quicktime' in header:
                    ext = 'mp4'
                    media_type = 'video'
                else:
                    ext = 'jpg'
                    media_type = 'image'
                
                try:
                    binary = base64.b64decode(data)
                except:
                    return 'Invalid base64 data', 400
                
                filename = f'story_{datetime.now().timestamp()}.{ext}'
                file = FileStorage(io.BytesIO(binary), filename=filename, content_type=f'image/{ext}' if media_type == 'image' else f'video/{ext}')
                
                from helpers import cloudinary_configured, upload_to_cloudinary, create_notification
                if cloudinary_configured:
                    url = upload_to_cloudinary(file, folder='stories')
                    if url:
                        story = Story(
                            user_id=current_user.id,
                            media_url=url,
                            media_type=media_type,
                            expires_at=datetime.utcnow() + timedelta(hours=24)
                        )
                        db.session.add(story)
                        db.session.commit()
                        followers = current_user.followers.filter_by(status='approved').all()
                        for follower in followers:
                            create_notification(follower.id, current_user.id, 'new_story')
                        return redirect(url_for('index'))
                else:
                    filename_save = secure_filename(filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename_save)
                    with open(filepath, 'wb') as f:
                        f.write(binary)
                    story = Story(
                        user_id=current_user.id,
                        media_url=filename_save,
                        media_type=media_type,
                        expires_at=datetime.utcnow() + timedelta(hours=24)
                    )
                    db.session.add(story)
                    db.session.commit()
                    followers = current_user.followers.filter_by(status='approved').all()
                    for follower in followers:
                        create_notification(follower.id, current_user.id, 'new_story')
                    return redirect(url_for('index'))
            
            file = request.files.get('media')
            from helpers import allowed_file
            if file and allowed_file(file.filename):
                if cloudinary_configured:
                    url = upload_to_cloudinary(file, folder='stories')
                    if url:
                        ext = file.filename.rsplit('.', 1)[1].lower()
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                        story = Story(
                            user_id=current_user.id,
                            media_url=url,
                            media_type=media_type,
                            expires_at=datetime.utcnow() + timedelta(hours=24)
                        )
                        db.session.add(story)
                        db.session.commit()
                        return redirect(url_for('index'))
                else:
                    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    ext = filename.rsplit('.', 1)[1].lower()
                    media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                    story = Story(
                        user_id=current_user.id,
                        media_url=filename,
                        media_type=media_type,
                        expires_at=datetime.utcnow() + timedelta(hours=24)
                    )
                    db.session.add(story)
                    db.session.commit()
                    followers = current_user.followers.filter_by(status='approved').all()
                    for follower in followers:
                        create_notification(follower.id, current_user.id, 'new_story')
                    return redirect(url_for('index'))
        
        return render_template('create_story.html')

    @app.route('/story/<int:story_id>/delete', methods=['POST'])
    @login_required
    def delete_story(story_id):
        story = Story.query.get_or_404(story_id)
        if story.user_id != current_user.id:
            abort(403)
        db.session.delete(story)
        db.session.commit()
        flash('История удалена')
        return redirect(url_for('index'))

    @app.route('/story/<int:story_id>/save', methods=['POST'])
    @login_required
    def save_story(story_id):
        story = Story.query.get_or_404(story_id)
        story.is_saved = not story.is_saved
        db.session.commit()
        return redirect(request.referrer or url_for('index'))

    @app.route('/story/<int:story_id>/republish', methods=['POST'])
    @login_required
    def republish_story(story_id):
        story = Story.query.get_or_404(story_id)
        if story.user_id != current_user.id:
            abort(403)
        
        story.expires_at = datetime.utcnow() + timedelta(hours=24)
        story.is_archived = False
        story.reposted_at = datetime.utcnow()
        db.session.commit()
        flash('История опубликована снова')
        return redirect(url_for('user_stories', username=current_user.username))

    @app.route('/story/<int:story_id>/react', methods=['POST'])
    @login_required
    def react_story(story_id):
        story = Story.query.get_or_404(story_id)
        emoji = request.form.get('emoji')
        if not emoji:
            return redirect(request.referrer or url_for('index'))
        
        existing = StoryReaction.query.filter_by(story_id=story.id, user_id=current_user.id, emoji=emoji).first()
        if existing:
            db.session.delete(existing)
        else:
            reaction = StoryReaction(story_id=story.id, user_id=current_user.id, emoji=emoji)
            db.session.add(reaction)
        db.session.commit()
        
        if story.user_id != current_user.id:
            msg = Message(sender_id=current_user.id, recipient_id=story.user_id, body=f"Отреагировал на историю: {emoji}")
            db.session.add(msg)
            db.session.commit()
        
        return redirect(request.referrer or url_for('index'))

    @app.route('/story/<int:story_id>/comment', methods=['POST'])
    @login_required
    def comment_story(story_id):
        story = Story.query.get_or_404(story_id)
        body = request.form.get('body', '').strip()
        if not body:
            return redirect(request.referrer or url_for('index'))
        
        comment = StoryComment(story_id=story.id, user_id=current_user.id, body=body)
        db.session.add(comment)
        db.session.commit()
        
        if story.user_id != current_user.id:
            msg = Message(sender_id=current_user.id, recipient_id=story.user_id, body=f"Прокомментировал историю: {body}")
            db.session.add(msg)
            db.session.commit()
        
        return redirect(request.referrer or url_for('index'))

    @app.route('/stories')
    @login_required
    def stories_route():
        Story.query.filter(Story.expires_at < datetime.utcnow(), Story.is_saved == False, Story.is_archived == False).update({Story.is_archived: True})
        db.session.commit()
        user_ids = [current_user.id] + [f.id for f in current_user.followers.all()] + [f.id for f in current_user.followed.all()]
        blocked_ids = [b.blocked_id for b in current_user.blocked.all()]
        exclude_ids = list(set(user_ids + blocked_ids))
        stories_list = Story.query.filter(
            Story.user_id.in_(exclude_ids),
            Story.expires_at > datetime.utcnow()
        ).order_by(Story.created_at.desc()).all()
        return render_template('stories.html', stories=stories_list)

    @app.route('/stories/archives')
    @login_required
    def stories_archives():
        archived = Story.query.filter(Story.user_id == current_user.id, Story.is_archived == True).order_by(Story.created_at.desc()).all()
        return render_template('stories_archives.html', stories=archived)

    @app.route('/stories/user/<username>')
    @login_required
    def user_stories(username):
        user = User.query.filter_by(username=username).first_or_404()
        stories = Story.query.filter(Story.user_id == user.id, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).all()
        if not stories and not Story.query.filter(Story.user_id == user.id, Story.is_saved == True).first():
            if user.id != current_user.id or not Story.query.filter(Story.user_id == user.id, Story.is_archived == True).first():
                abort(404)
        saved_stories = Story.query.filter(Story.user_id == user.id, Story.is_saved == True).order_by(Story.created_at.desc()).all()
        all_stories = stories + saved_stories
        return render_template('user_stories.html', stories=all_stories, user=user)

    @app.route('/stories/hide/<username>', methods=['POST'])
    @login_required
    def hide_story(username):
        user = User.query.filter_by(username=username).first_or_404()
        for story in Story.query.filter(Story.user_id == user.id, Story.expires_at > datetime.utcnow()).all():
            if current_user not in story.hidden_for:
                story.hidden_for.append(current_user)
        db.session.commit()
        flash('Истории пользователя скрыты')
        return redirect(url_for('index'))

    @app.route('/story/<int:story_id>')
    @login_required
    def view_story(story_id):
        story = Story.query.get_or_404(story_id)
        if story.is_expired() and not story.is_saved and not (story.is_archived and story.user_id == current_user.id):
            abort(404)
        reactions = story.reactions.all()
        comments = story.comments.order_by(StoryComment.created_at.desc()).all()
        user_stories = Story.query.filter(
            Story.user_id == story.user_id,
            Story.expires_at > datetime.utcnow()
        ).order_by(Story.created_at.desc()).all()
        all_stories = [{'id': s.id} for s in user_stories]
        current_index = next((i for i, s in enumerate(user_stories) if s.id == story.id), 0)
        return render_template('view_story.html', story=story, reactions=reactions, comments=comments, all_stories=all_stories, current_index=current_index)
