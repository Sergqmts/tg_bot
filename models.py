from datetime import datetime
import json
from flask import current_app
from flask_login import UserMixin
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('created_at', db.DateTime, default=datetime.utcnow),
    db.Column('status', db.String(20), default='approved')
)

blocked = db.Table('blocked',
    db.Column('blocker_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('blocked_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)

story_hidden = db.Table('story_hidden',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('story_id', db.Integer, db.ForeignKey('story.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    google_id = db.Column(db.String(200), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text)
    avatar = db.Column(db.String(200), default='default.png')
    avatar_cloudinary_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    location = db.Column(db.String(100), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    birthday = db.Column(db.Date, nullable=True)
    interests = db.Column(db.Text, nullable=True)
    occupation = db.Column(db.String(100), nullable=True)
    
    is_private = db.Column(db.Boolean, default=False)
    hide_followers = db.Column(db.Boolean, default=False)
    hide_following = db.Column(db.Boolean, default=False)
    approve_followers = db.Column(db.Boolean, default=False)
    
    phone = db.Column(db.String(20), nullable=True)
    phone_verified = db.Column(db.Boolean, default=False)
    phone_otp = db.Column(db.String(6), nullable=True)
    phone_otp_expires = db.Column(db.DateTime, nullable=True)
    
    is_bot = db.Column(db.Boolean, default=False)
    bot_token = db.Column(db.String(64), unique=True, nullable=True)
    bot_commands = db.Column(db.Text, default='[]')
    can_join_groups = db.Column(db.Boolean, default=True)
    privacy_mode = db.Column(db.Boolean, default=True)
    webhook_url = db.Column(db.String(500), nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_banned = db.Column(db.Boolean, default=False)

    # Password reset
    reset_token = db.Column(db.String(64), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    # Onboarding
    onboarding_done = db.Column(db.Boolean, default=False)

    is_staff = db.Column(db.Boolean, default=False)
    is_business = db.Column(db.Boolean, default=False)
    
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    likes = db.relationship('Like', backref='user', lazy='dynamic')
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'),
        lazy='dynamic'
    )
    
    blocked = db.relationship(
        'User', secondary=blocked,
        primaryjoin=(blocked.c.blocker_id == id),
        secondaryjoin=(blocked.c.blocked_id == id),
        backref=db.backref('blocked_by', lazy='dynamic'),
        lazy='dynamic'
    )
    
    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic')
    messages_received = db.relationship('Message', foreign_keys='Message.recipient_id', backref='recipient', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def warning_count(self):
        return ModerationLog.query.filter_by(user_id=self.id).count()

    def like_post(self, post):
        if not self.has_liked(post):
            like = Like(user_id=self.id, post_id=post.id)
            db.session.add(like)

    def unlike_post(self, post):
        like = Like.query.filter_by(user_id=self.id, post_id=post.id).first()
        if like:
            db.session.delete(like)

    def has_liked(self, post):
        return Like.query.filter_by(user_id=self.id, post_id=post.id).first() is not None

    def follow(self, user):
        if not self.is_following(user) and not self.is_pending(user):
            stmt = followers.insert().values(
                follower_id=self.id,
                followed_id=user.id,
                status='pending' if user.approve_followers else 'approved'
            )
            db.session.execute(stmt)
            db.session.commit()

    def unfollow(self, user):
        if self.is_following(user) or self.is_pending(user):
            from sqlalchemy import and_
            stmt = followers.delete().where(
                and_(followers.c.follower_id == self.id, followers.c.followed_id == user.id)
            )
            db.session.execute(stmt)
            db.session.commit()

    def get_pending_followers(self):
        try:
            from sqlalchemy import and_
            result = db.session.execute(
                followers.select().where(
                    and_(followers.c.followed_id == self.id, followers.c.status == 'pending')
                )
            ).fetchall()
            return [User.query.get(r.follower_id) for r in result]
        except Exception:
            return []

    def approve_follower(self, user):
        from sqlalchemy import and_
        stmt = followers.update().where(
            and_(followers.c.follower_id == user.id, followers.c.followed_id == self.id)
        ).values(status='approved')
        db.session.execute(stmt)
        db.session.commit()

    def reject_follower(self, user):
        from sqlalchemy import and_
        stmt = followers.delete().where(
            and_(followers.c.follower_id == user.id, followers.c.followed_id == self.id)
        )
        db.session.execute(stmt)
        db.session.commit()

    def is_following(self, user):
        result = self.followed.filter(followers.c.followed_id == user.id).first()
        if result and hasattr(result, 'status'):
            return result.status == 'approved'
        return result is not None

    def is_pending(self, user):
        try:
            result = self.followed.filter(followers.c.followed_id == user.id).first()
            if result and hasattr(result, 'status'):
                return result.status == 'pending'
            return False
        except Exception:
            return False

    def is_chat_member(self, chat):
        return ChatMember.query.filter_by(chat_id=chat.id, user_id=self.id).first() is not None

    def is_chat_admin(self, chat):
        member = ChatMember.query.filter_by(chat_id=chat.id, user_id=self.id).first()
        return member and member.role == 'admin'

    def block(self, user):
        if not self.is_blocking(user):
            self.blocked.append(user)
            if self.is_following(user):
                self.unfollow(user)

    def unblock(self, user):
        if self.is_blocking(user):
            self.blocked.remove(user)

    def is_blocking(self, user):
        return self.blocked.filter(blocked.c.blocked_id == user.id).first() is not None

    def unread_messages(self):
        try:
            return Message.query.filter_by(recipient_id=self.id, read=False).count()
        except Exception as e:
            current_app.logger.info(f"unread_messages error: {e}")
            return 0

    def join_community(self, community):
        existing = CommunityMember.query.filter_by(user_id=self.id, community_id=community.id).first()
        if existing:
            return
        if community.is_private:
            member = CommunityMember(user_id=self.id, community_id=community.id, status='pending')
        else:
            member = CommunityMember(user_id=self.id, community_id=community.id, status='approved')
        db.session.add(member)

    def leave_community(self, community):
        member = CommunityMember.query.filter_by(user_id=self.id, community_id=community.id).first()
        if member:
            db.session.delete(member)

    def is_member(self, community):
        return CommunityMember.query.filter_by(user_id=self.id, community_id=community.id, status='approved').first() is not None

    def is_pending(self, community):
        return CommunityMember.query.filter_by(user_id=self.id, community_id=community.id, status='pending').first() is not None

    def is_approved_member(self, community):
        return CommunityMember.query.filter_by(user_id=self.id, community_id=community.id, status='approved').first() is not None

    def has_reposted(self, post):
        return Repost.query.filter_by(user_id=self.id, post_id=post.id).first() is not None

    def repost(self, post):
        if not self.has_reposted(post):
            repost = Repost(user_id=self.id, post_id=post.id)
            db.session.add(repost)

    def unrepost(self, post):
        repost = Repost.query.filter_by(user_id=self.id, post_id=post.id).first()
        if repost:
            db.session.delete(repost)

    def is_admin(self, community):
        if self.is_staff and community.creator and community.creator.is_bot:
            return True
        member = CommunityMember.query.filter_by(user_id=self.id, community_id=community.id, status='approved').first()
        return member and member.role in ('admin', 'creator')


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    type = db.Column(db.String(50), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=True)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='notifications')
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post', backref='notifications')
    comment = db.relationship('Comment', backref='notifications')
    message = db.relationship('Message', backref='notifications')


class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    is_saved = db.Column(db.Boolean, default=False)
    is_archived = db.Column(db.Boolean, default=False)
    reposted_at = db.Column(db.DateTime)
    
    user = db.relationship('User', backref='stories')
    reactions = db.relationship('StoryReaction', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('StoryComment', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    views = db.relationship('StoryView', backref='story', lazy='dynamic', cascade='all, delete-orphan')
    hidden_for = db.relationship('User', secondary=story_hidden, lazy='dynamic')
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at


class StoryReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='story_reactions')


class StoryComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='story_comments')


class StoryView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='story_views')
    __table_args__ = (db.UniqueConstraint('story_id', 'user_id', name='unique_story_view'),)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=True)
    is_community_post = db.Column(db.Boolean, default=False)
    music_track_id = db.Column(db.Integer, db.ForeignKey('music_track.id'), nullable=True)
    music_track = db.relationship('MusicTrack', backref='posts')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    media = db.relationship('Media', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    reactions = db.relationship('Reaction', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    saved_by = db.relationship('SavedPost', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    def liked_by(self, user):
        return self.likes.filter_by(user_id=user.id).first() is not None

    def reposted_by(self, user):
        return Repost.query.filter_by(user_id=user.id, post_id=self.id).first() is not None


class Community(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(200), default='community_default.png')
    is_private = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_banned = db.Column(db.Boolean, default=False)
    
    creator = db.relationship('User', backref='created_communities')
    posts = db.relationship('Post', backref='community', lazy='dynamic', cascade='all, delete-orphan')
    members = db.relationship('CommunityMember', backref='community', lazy='dynamic', cascade='all, delete-orphan',
                           primaryjoin="CommunityMember.community_id==Community.id",
                           foreign_keys='CommunityMember.community_id',
                           viewonly=True)


class CommunityMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False)
    role = db.Column(db.String(20), default='member')
    status = db.Column(db.String(20), default='approved')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('community_memberships', lazy='dynamic'))
    
    __table_args__ = (db.UniqueConstraint('user_id', 'community_id', name='unique_membership'),)


class ModerationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    reason = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    offender = db.relationship('User', foreign_keys=[user_id], backref='moderation_warnings')
    post = db.relationship('Post', backref='moderation_logs')
    community = db.relationship('Community', foreign_keys=[community_id], backref='moderation_warnings')


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    target_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reporter = db.relationship('User', foreign_keys=[reporter_id], backref='reports_made')
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='reports_received')
    target_post = db.relationship('Post', backref='reports')


class CommunityEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_archived = db.Column(db.Boolean, default=False)
    
    community = db.relationship('Community', backref='events')
    creator = db.relationship('User', backref='created_events')
    attendees = db.relationship('EventAttendee', backref='event', lazy='dynamic', cascade='all, delete-orphan')
    
    def attendee_count(self):
        return self.attendees.filter_by(status='going').count()
    
    def is_attending(self, user):
        return self.attendees.filter_by(user_id=user.id, status='going').first() is not None
    
    def is_past(self):
        return self.event_date < datetime.utcnow()
    
    def archive_if_expired(self):
        if self.event_date < datetime.utcnow() and not self.is_archived:
            self.is_archived = True
            db.session.commit()


class EventAttendee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('community_event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='going')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='event_attendances')
    
    __table_args__ = (db.UniqueConstraint('event_id', 'user_id', name='unique_attendance'),)


class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    cloudinary_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Reaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class SavedPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Draft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    media_data = db.Column(db.Text, nullable=True)
    caption = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PostTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), nullable=False)


class MusicTrack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), default='')
    album = db.Column(db.String(200), default='')
    duration = db.Column(db.Integer, default=0)
    preview_url = db.Column(db.String(500))
    cover_url = db.Column(db.String(500))
    deezer_id = db.Column(db.BigInteger, unique=True, nullable=True)
    deezer_url = db.Column(db.String(500))
    source = db.Column(db.String(20), default='deezer')
    file_url = db.Column(db.String(500))
    uploaded_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(500))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='playlists')
    tracks = db.relationship('PlaylistItem', backref='playlist', lazy='dynamic', cascade='all, delete-orphan', order_by='PlaylistItem.position')


class PlaylistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('music_track.id'), nullable=False)
    position = db.Column(db.Integer, default=0)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    track = db.relationship('MusicTrack')


class ListeningHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('music_track.id'), nullable=False)
    listened_at = db.Column(db.DateTime, default=datetime.utcnow)
    track = db.relationship('MusicTrack')


class FavoriteTrack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('music_track.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    track = db.relationship('MusicTrack')


class Shorts(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_url = db.Column(db.String(500), nullable=False)
    audio_id = db.Column(db.Integer, db.ForeignKey('music_track.id'), nullable=True)
    caption = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    views = db.Column(db.Integer, default=0)
    likes = db.relationship('ShortsLike', backref='shorts', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('ShortsComment', backref='shorts', lazy='dynamic', cascade='all, delete-orphan')
    saved_by = db.relationship('ShortsSaved', backref='shorts_ref', lazy='dynamic', cascade='all, delete-orphan')

    user = db.relationship('User', backref='shorts_videos')
    audio = db.relationship('MusicTrack', backref='shorts_videos')
    
    def liked_by(self, user):
        return self.likes.filter_by(user_id=user.id).first() is not None


class ShortsLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shorts_id = db.Column(db.Integer, db.ForeignKey('shorts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ShortsReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shorts_id = db.Column(db.Integer, db.ForeignKey('shorts.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ShortsComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shorts_id = db.Column(db.Integer, db.ForeignKey('shorts.id'), nullable=False)

    author = db.relationship('User', foreign_keys=[user_id])


class ShortsSaved(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    shorts_id = db.Column(db.Integer, db.ForeignKey('shorts.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id])
    shorts = db.relationship('Shorts', foreign_keys=[shorts_id])


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    reply_to_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20))
    
    author = db.relationship('User', foreign_keys=[user_id])


class CommentMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20))
    reply_to_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    
    author = db.relationship('User', foreign_keys=[user_id])


class CommentReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])
    
    
class Repost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='reposts')
    post = db.relationship('Post', backref='reposts')


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=True)
    transcription = db.Column(db.Text, nullable=True)
    forwarded_from_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    medias = db.relationship('MessageMedia', backref='message')
    forwarded_from = db.relationship('User', foreign_keys=[forwarded_from_id])


class MessageReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), default='direct')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    avatar = db.Column(db.String(200), default='chat_default.png')
    background_type = db.Column(db.String(20), default='default')
    background_value = db.Column(db.String(500), default='{"light": "", "dark": ""}')
    
    messages = db.relationship('Message', backref='chat', lazy='dynamic')
    members = db.relationship('ChatMember', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_background(self, theme='light'):
        try:
            data = json.loads(self.background_value) if self.background_value else {}
            return data.get(theme, '')
        except:
            return ''

    def get_background_data(self):
        try:
            return json.loads(self.background_value) if self.background_value else {}
        except:
            return {}

    def set_background(self, light_val='', dark_val=''):
        data = {'light': light_val, 'dark': dark_val}
        self.background_value = json.dumps(data)


class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), default='member')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='chat_memberships')


class MessageMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20))


class ProfileVisit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    visitor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile = db.relationship('User', foreign_keys=[profile_id], backref='profile_visits')
    visitor = db.relationship('User', foreign_keys=[visitor_id])


class PostView(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    post = db.relationship('Post', backref=db.backref('post_views', lazy='dynamic'))
    viewer = db.relationship('User', foreign_keys=[viewer_id])


class AccountGroup(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', foreign_keys=[owner_id], backref='owned_account_groups')
    members = db.relationship('AccountGroupMember', backref='group', lazy='dynamic', cascade='all, delete-orphan')


class AccountGroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('account_group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_type = db.Column(db.String(20), default='personal')
    role = db.Column(db.String(20), default='member')
    business_name = db.Column(db.String(100), nullable=True)
    business_category = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('group_memberships', lazy='dynamic'))
    __table_args__ = (db.UniqueConstraint('group_id', 'user_id', name='unique_group_user'),)


class Call(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    callee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    call_type = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='ringing')
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    caller = db.relationship('User', foreign_keys=[caller_id], backref='outgoing_calls')
    callee = db.relationship('User', foreign_keys=[callee_id], backref='incoming_calls')


class FeatureAnnouncement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    icon = db.Column(db.String(20), default='🚀')
    is_posted = db.Column(db.Boolean, default=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def post_to_news(self):
        from flask import current_app
        bot = User.query.filter_by(username='NewsBot').first()
        comm = Community.query.filter_by(slug='news').first()
        if not bot or not comm:
            return False
        try:
            text = f"{self.icon} **{self.title}**\n\n{self.body}\n\n#фича #обновление"
            post = Post(body=text, author=bot, community=comm, is_community_post=True)
            db.session.add(post)
            self.is_posted = True
            self.posted_at = datetime.utcnow()
            db.session.commit()
            current_app.logger.info(f"Feature announced: {self.title}")
            return True
        except Exception as e:
            current_app.logger.error(f"Feature announcement error: {e}")
            db.session.rollback()
            return False


# WTForms

class RegistrationForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField('Повторите пароль', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Регистрация')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Это имя занято')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Этот email уже зарегистрирован')


class LoginForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    remember = BooleanField('Запомнить меня')
    submit = SubmitField('Войти')


class PostForm(FlaskForm):
    body = TextAreaField('Что нового?')
    media = FileField('Фото/Видео', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm', 'mov'], 'Только изображения и видео!')])
    submit = SubmitField('Опубликовать')


class CommentForm(FlaskForm):
    body = StringField('Комментарий', validators=[DataRequired()])
    media = FileField('Фото/Видео', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm', 'mov'], 'Только изображения и видео!')])
    submit = SubmitField('Отправить')


class EditProfileForm(FlaskForm):
    username = StringField('Имя пользователя', validators=[DataRequired(), Length(min=3, max=50)])
    bio = StringField('О себе', validators=[Length(max=200)])
    avatar = FileField('Аватар', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm'], 'Только изображения или видео!')])
    location = StringField('Местоположение', validators=[Length(max=100)])
    website = StringField('Веб-сайт', validators=[Length(max=200)])
    birthday = StringField('Дата рождения (ДД.ММ.ГГГГ)')
    interests = TextAreaField('Интересы', validators=[Length(max=500)])
    occupation = StringField('Род деятельности', validators=[Length(max=100)])
    phone = StringField('Номер телефона', validators=[Length(max=20)])
    is_private = BooleanField('Закрытый профиль')
    hide_followers = BooleanField('Скрыть подписчиков')
    hide_following = BooleanField('Скрыть подписки')
    approve_followers = BooleanField('Одобрять подписчиков')
    submit = SubmitField('Сохранить')


class CommunityForm(FlaskForm):
    name = StringField('Название', validators=[DataRequired(), Length(min=3, max=50)])
    description = TextAreaField('Описание', validators=[Length(max=500)])
    is_private = BooleanField('Закрытое сообщество')
    image = FileField('Обложка', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')])
    submit = SubmitField('Создать')

    def validate_name(self, name):
        slug = name.data.lower().replace(' ', '-').replace('_', '-')
        slug = ''.join(c for c in slug if c.isalnum() or c == '-')
        community = Community.query.filter_by(slug=slug).first()
        if community:
            raise ValidationError('Сообщество с таким названием уже существует')


class BotForm(FlaskForm):
    name = StringField('Имя бота', validators=[DataRequired(), Length(min=1, max=100)])
    username = StringField('Username бота (без @)', validators=[DataRequired(), Length(min=3, max=50)])
    description = TextAreaField('Описание', validators=[Length(max=500)])
    avatar = FileField('Аватар', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')])
    commands = TextAreaField('Команды (JSON, опционально)')
    submit = SubmitField('Создать бота')

    def validate_username(self, username):
        if not username.data.endswith('bot'):
            raise ValidationError('Username бота должен заканчиваться на "bot"')
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Этот username занят')


class CommunityPostForm(FlaskForm):
    body = TextAreaField('Текст записи')
    media = FileField('Фото/Видео', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm', 'mov'], 'Только изображения и видео!')])
    submit = SubmitField('Опубликовать')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Отправить ссылку')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Новый пароль', validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField('Подтвердите пароль', validators=[DataRequired(), EqualTo('password', message='Пароли не совпадают')])
    submit = SubmitField('Сохранить пароль')
