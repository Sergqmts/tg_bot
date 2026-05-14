def register_routes(app):
    from flask import render_template, redirect, url_for, flash, request, session as flask_session, jsonify
    from flask_login import login_user, logout_user, login_required, current_user
    from extensions import db
    from models import User, AccountGroup, AccountGroupMember, ProfileVisit, PostView, Post, Message, followers, Notification
    from wtforms import StringField, SubmitField
    from wtforms.validators import DataRequired, Length
    from flask_wtf import FlaskForm
    from datetime import datetime, timedelta
    from sqlalchemy import func
    import secrets

    class BusinessAccountForm(FlaskForm):
        business_name = StringField('Название бизнеса', validators=[DataRequired(), Length(min=2, max=100)])
        business_category = StringField('Категория', validators=[Length(max=100)])
        submit = SubmitField('Создать бизнес-аккаунт')

    def get_linked_accounts(user):
        memberships = AccountGroupMember.query.filter_by(user_id=user.id).all()
        group_ids = [m.group_id for m in memberships]
        if not group_ids:
            return []
        all_members = AccountGroupMember.query.filter(
            AccountGroupMember.group_id.in_(group_ids)
        ).order_by(AccountGroupMember.account_type.desc()).all()
        return all_members

    @app.route('/accounts')
    @login_required
    def accounts_list():
        linked = get_linked_accounts(current_user)
        return render_template('accounts.html', linked_accounts=linked)

    @app.route('/accounts/create', methods=['GET', 'POST'])
    @login_required
    def create_business_account():
        # Check if user already has a personal membership in a group
        personal_membership = AccountGroupMember.query.filter_by(
            user_id=current_user.id, account_type='personal'
        ).first()

        form = BusinessAccountForm()
        if form.validate_on_submit():
            name = form.business_name.data.strip()
            category = form.business_category.data.strip() if form.business_category.data else ''

            base_username = name.lower().replace(' ', '_').replace('-', '_')
            base_username = ''.join(c for c in base_username if c.isalnum() or c == '_')[:40]
            if not base_username:
                base_username = 'business'

            username = base_username
            attempt = 1
            while User.query.filter_by(username=username).first():
                suffix = secrets.token_hex(2)
                username = f'{base_username[:38]}_{suffix}'
                attempt += 1
                if attempt > 10:
                    username = f'business_{secrets.token_hex(4)}'
                    break

            password = secrets.token_urlsafe(32)
            business_user = User(
                username=username,
                email=f'{username}@business.local',
                is_business=True,
            )
            business_user.set_password(password)
            db.session.add(business_user)
            db.session.flush()

            if personal_membership:
                group_id = personal_membership.group_id
            else:
                group = AccountGroup(owner_id=current_user.id, name=f'{current_user.username}_group')
                db.session.add(group)
                db.session.flush()
                group_id = group.id

                personal_member = AccountGroupMember(
                    group_id=group_id,
                    user_id=current_user.id,
                    account_type='personal',
                    role='owner'
                )
                db.session.add(personal_member)

            business_member = AccountGroupMember(
                group_id=group_id,
                user_id=business_user.id,
                account_type='business',
                role='member',
                business_name=name,
                business_category=category,
            )
            db.session.add(business_member)
            db.session.commit()

            flash(f'Бизнес-аккаунт "{name}" создан! Username: {username}')
            return redirect(url_for('accounts_list'))

        return render_template('create_business_account.html', form=form)

    @app.route('/accounts/switch/<int:account_id>')
    @login_required
    def switch_account(account_id):
        if account_id == current_user.id:
            flash('Вы уже используете этот аккаунт')
            return redirect(request.referrer or url_for('index'))

        target_user = User.query.get_or_404(account_id)

        current_memberships = AccountGroupMember.query.filter_by(user_id=current_user.id).all()
        current_group_ids = [m.group_id for m in current_memberships]

        target_member = AccountGroupMember.query.filter(
            AccountGroupMember.user_id == target_user.id,
            AccountGroupMember.group_id.in_(current_group_ids)
        ).first()

        if not target_member:
            flash('Нет доступа к этому аккаунту')
            return redirect(url_for('index'))

        flask_session['owner_account_id'] = current_user.id
        login_user(target_user)
        flash(f'Переключено на {target_member.business_name or target_user.username}')
        return redirect(url_for('index'))

    @app.route('/accounts/switch-back')
    @login_required
    def switch_back_account():
        owner_id = flask_session.pop('owner_account_id', None)
        if not owner_id:
            flash('Нет аккаунта для возврата')
            return redirect(url_for('index'))

        owner = User.query.get(owner_id)
        if not owner:
            flash('Аккаунт не найден')
            return redirect(url_for('index'))

        current_memberships = AccountGroupMember.query.filter_by(user_id=current_user.id).all()
        current_group_ids = [m.group_id for m in current_memberships]

        owner_member = AccountGroupMember.query.filter(
            AccountGroupMember.user_id == owner.id,
            AccountGroupMember.group_id.in_(current_group_ids)
        ).first()

        if not owner_member:
            flash('Нет доступа к этому аккаунту')
            return redirect(url_for('index'))

        login_user(owner)
        flash(f'Возврат на {owner.username}')
        return redirect(url_for('index'))

    def get_business_membership(user):
        return AccountGroupMember.query.filter_by(
            user_id=user.id, account_type='business'
        ).first()

    @app.route('/accounts/analytics')
    @login_required
    def business_analytics():
        membership = get_business_membership(current_user)
        if not membership:
            flash('Аналитика доступна только для бизнес-аккаунтов')
            return redirect(url_for('accounts_list'))

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        def days_ago(n):
            return today_start - timedelta(days=n)

        # Profile visits
        visits_total = ProfileVisit.query.filter_by(profile_id=current_user.id).count()
        visits_today = ProfileVisit.query.filter(
            ProfileVisit.profile_id == current_user.id,
            ProfileVisit.created_at >= today_start
        ).count()
        visits_7d = ProfileVisit.query.filter(
            ProfileVisit.profile_id == current_user.id,
            ProfileVisit.created_at >= days_ago(7)
        ).count()
        visits_30d = ProfileVisit.query.filter(
            ProfileVisit.profile_id == current_user.id,
            ProfileVisit.created_at >= days_ago(30)
        ).count()

        # Post views
        post_ids = [p.id for p in Post.query.filter_by(user_id=current_user.id).all()]
        post_views_total = PostView.query.filter(PostView.post_id.in_(post_ids)).count() if post_ids else 0
        post_views_today = PostView.query.filter(
            PostView.post_id.in_(post_ids),
            PostView.created_at >= today_start
        ).count() if post_ids else 0
        post_views_7d = PostView.query.filter(
            PostView.post_id.in_(post_ids),
            PostView.created_at >= days_ago(7)
        ).count() if post_ids else 0
        post_views_30d = PostView.query.filter(
            PostView.post_id.in_(post_ids),
            PostView.created_at >= days_ago(30)
        ).count() if post_ids else 0

        # Per-post views
        posts_data = []
        for p in Post.query.filter_by(user_id=current_user.id).order_by(Post.created_at.desc()).limit(10).all():
            pv = PostView.query.filter_by(post_id=p.id).count()
            posts_data.append({'post': p, 'views': pv})

        # Messages
        all_messages = Message.query.filter_by(recipient_id=current_user.id)
        total_messages = all_messages.count()
        messages_30d = all_messages.filter(Message.created_at >= days_ago(30)).count()

        first_time_senders = set()
        returning_senders = set()
        thirty_days_ago = days_ago(30)
        recent_msgs = all_messages.filter(Message.created_at >= thirty_days_ago).all()
        for msg in recent_msgs:
            first_msg = Message.query.filter_by(
                recipient_id=current_user.id, sender_id=msg.sender_id
            ).order_by(Message.created_at.asc()).first()
            if first_msg and first_msg.id == msg.id:
                first_time_senders.add(msg.sender_id)
            else:
                returning_senders.add(msg.sender_id)

        # New followers
        def count_followers_since(since):
            stmt = followers.select().where(
                followers.c.followed_id == current_user.id,
                followers.c.created_at >= since,
                followers.c.status == 'approved'
            )
            return db.session.execute(stmt).rowcount

        followers_week = count_followers_since(days_ago(7))
        followers_month = count_followers_since(days_ago(30))
        followers_quarter = count_followers_since(days_ago(90))
        followers_half = count_followers_since(days_ago(180))
        followers_year = count_followers_since(days_ago(365))

        return render_template('business_analytics.html',
            membership=membership,
            visits_total=visits_total, visits_today=visits_today,
            visits_7d=visits_7d, visits_30d=visits_30d,
            post_views_total=post_views_total,
            post_views_today=post_views_today,
            post_views_7d=post_views_7d, post_views_30d=post_views_30d,
            posts_data=posts_data,
            total_messages=total_messages, messages_30d=messages_30d,
            new_message_senders=len(first_time_senders),
            returning_message_senders=len(returning_senders),
            followers_week=followers_week, followers_month=followers_month,
            followers_quarter=followers_quarter, followers_half=followers_half,
            followers_year=followers_year,
        )

    @app.route('/accounts/analytics/chart-data')
    @login_required
    def analytics_chart_data():
        membership = get_business_membership(current_user)
        if not membership:
            return jsonify({'error': 'Not a business account'}), 403

        now = datetime.utcnow()
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        post_ids = [p.id for p in Post.query.filter_by(user_id=current_user.id).all()]

        months = []
        for m in range(1, 13):
            ms = year_start.replace(month=m)
            me = ms.replace(month=m+1) if m < 12 else year_start.replace(year=year_start.year+1, month=1)

            visits = ProfileVisit.query.filter(
                ProfileVisit.profile_id == current_user.id,
                ProfileVisit.created_at >= ms,
                ProfileVisit.created_at < me
            ).count()

            pv = PostView.query.filter(
                PostView.post_id.in_(post_ids),
                PostView.created_at >= ms,
                PostView.created_at < me
            ).count() if post_ids else 0

            fw = db.session.execute(
                followers.select().where(
                    followers.c.followed_id == current_user.id,
                    followers.c.created_at >= ms,
                    followers.c.created_at < me,
                    followers.c.status == 'approved'
                )
            ).rowcount

            msgs = Message.query.filter(
                Message.recipient_id == current_user.id,
                Message.created_at >= ms,
                Message.created_at < me
            ).count()

            months.append({
                'month': m,
                'label': ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'][m-1],
                'visits': visits,
                'post_views': pv,
                'followers': fw,
                'messages': msgs,
            })

        return jsonify({'months': months, 'year': now.year})
