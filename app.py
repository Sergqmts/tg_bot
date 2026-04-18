from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
import os
import cloudinary
import cloudinary.uploader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))


@app.context_processor
def inject_stories():
    if current_user.is_authenticated:
        try:
            Story.query.filter(Story.expires_at < datetime.utcnow(), Story.is_saved == False).delete()
            db.session.commit()
            
            followers = current_user.followers.all()
            following = current_user.followed.all()
            follower_ids = [f.id for f in followers]
            following_ids = [f.id for f in following]
            user_ids = [current_user.id] + follower_ids + following_ids
            
            if user_ids:
                story_users = db.session.query(Story.user_id).filter(
                    Story.user_id.in_(user_ids),
                    Story.expires_at > datetime.utcnow()
                ).group_by(Story.user_id).all()
                stories_list = []
                for (uid,) in story_users:
                    s = Story.query.filter(Story.user_id == uid, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
                    if s:
                        stories_list.append(s)
            else:
                stories_list = []
            my_story = Story.query.filter(Story.user_id == current_user.id, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
            has_story = my_story is not None
            return dict(top_stories=stories_list, my_story=my_story, user_has_story=has_story)
        except Exception as e:
            app.logger.error(f"Stories error: {e}")
            return dict(top_stories=[], my_story=None, user_has_story=False)
    return dict(top_stories=[], my_story=None, user_has_story=False)

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+psycopg://', 1)
    elif not DATABASE_URL.startswith('postgresql+'):
        DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///social.db'

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-key-change-in-production-secret-key-fixed'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}

cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
cloud_key = os.environ.get('CLOUDINARY_API_KEY')
cloud_secret = os.environ.get('CLOUDINARY_API_SECRET')
cloudinary_configured = cloud_name and cloud_key
app.logger.info(f"Cloudinary config: cloud_name={cloud_name}, has_key=bool(cloud_key), has_secret=bool(cloud_secret)")
if cloudinary_configured:
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=cloud_key,
        api_secret=cloud_secret,
        secure=True
    )

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа'

# csrf = CSRFProtect(app)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def upload_to_cloudinary(file, folder='social'):
    if not file.filename:
        return None
    if cloudinary_configured:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            resource_type='auto',
            transformation=[{'quality': 'auto', 'fetch_format': 'auto'}]
        )
        return result['secure_url']
    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return filename


def get_cloudinary_url(public_id, resource_type='image'):
    if not public_id:
        return None
    if cloudinary_configured:
        return cloudinary.CloudinaryImage(public_id).build_url(
            width=800,
            crop='scale',
            quality='auto',
            fetch_format='auto'
        )
    return '/media/' + public_id


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


_migration_done = False

@app.before_request
def run_migrations():
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    
    from sqlalchemy import text
    is_postgres = 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']
    is_sqlite = 'sqlite' in app.config['SQLALCHEMY_DATABASE_URI']
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user'"))
            existing = [row[0] for row in result]
            for col, typ in [('location', 'VARCHAR(100)'), ('website', 'VARCHAR(200)'), ('birthday', 'DATE'), ('interests', 'TEXT'), ('occupation', 'VARCHAR(100)')]:
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {typ}'))
                    db.session.commit()
            
            privacy_cols = [('is_private', 'BOOLEAN DEFAULT FALSE'), ('hide_followers', 'BOOLEAN DEFAULT FALSE'), ('hide_following', 'BOOLEAN DEFAULT FALSE'), ('approve_followers', 'BOOLEAN DEFAULT FALSE')]
            for col, typ in privacy_cols:
                if col not in existing:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {typ}'))
                    db.session.commit()
        elif is_sqlite:
            for col, typ in [('location', 'VARCHAR(100)'), ('website', 'VARCHAR(200)'), ('birthday', 'DATE'), ('interests', 'TEXT'), ('occupation', 'VARCHAR(100)')]:
                try:
                    db.session.execute(text(f'ALTER TABLE user ADD COLUMN {col} {typ}'))
                    db.session.commit()
                except:
                    pass
            for col, typ in [('is_private', 'BOOLEAN DEFAULT 0'), ('hide_followers', 'BOOLEAN DEFAULT 0'), ('hide_following', 'BOOLEAN DEFAULT 0'), ('approve_followers', 'BOOLEAN DEFAULT 0')]:
                try:
                    db.session.execute(text(f'ALTER TABLE user ADD COLUMN {col} {typ}'))
                    db.session.commit()
                except:
                    pass
    except Exception as e:
        app.logger.info(f"User migration: {e}")
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='community'"))
            existing = [row[0] for row in result]
            if 'is_private' not in existing:
                db.session.execute(text('ALTER TABLE "community" ADD COLUMN is_private BOOLEAN DEFAULT FALSE'))
                db.session.commit()
        elif is_sqlite:
            try:
                db.session.execute(text("ALTER TABLE community ADD COLUMN is_private BOOLEAN DEFAULT 0"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Community migration: {e}")
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='community_member'"))
            existing = [row[0] for row in result]
            if 'status' not in existing:
                db.session.execute(text('ALTER TABLE "community_member" ADD COLUMN status VARCHAR(20) DEFAULT \'approved\''))
                db.session.commit()
        elif is_sqlite:
            try:
                db.session.execute(text("ALTER TABLE community_member ADD COLUMN status VARCHAR(20) DEFAULT 'approved'"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Member migration: {e}")
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='post'"))
            existing = [row[0] for row in result]
            if 'is_community_post' not in existing:
                db.session.execute(text('ALTER TABLE "post" ADD COLUMN is_community_post BOOLEAN DEFAULT FALSE'))
                db.session.commit()
        elif is_sqlite:
            try:
                db.session.execute(text("ALTER TABLE post ADD COLUMN is_community_post BOOLEAN DEFAULT 0"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Post migration: {e}")
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='followers'"))
            existing = [row[0] for row in result]
            if 'status' not in existing:
                db.session.execute(text('ALTER TABLE "followers" ADD COLUMN status VARCHAR(20) DEFAULT \'approved\''))
                db.session.commit()
        elif is_sqlite:
            try:
                db.session.execute(text("ALTER TABLE followers ADD COLUMN status VARCHAR(20) DEFAULT 'approved'"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Followers migration: {e}")
    
    try:
        if is_postgres:
            result = db.session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_name='chat'"))
            if not result.fetchone():
                db.session.execute(text('''
                    CREATE TABLE chat (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        creator_id INTEGER REFERENCES "user"(id) NOT NULL,
                        avatar VARCHAR(200) DEFAULT 'chat_default.png'
                    );
                    CREATE TABLE chat_member (
                        id SERIAL PRIMARY KEY,
                        chat_id INTEGER REFERENCES chat(id) ON DELETE CASCADE NOT NULL,
                        user_id INTEGER REFERENCES "user"(id) NOT NULL,
                        role VARCHAR(20) DEFAULT 'member',
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                '''))
                db.session.commit()
            
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='message'"))
            existing = [row[0] for row in result]
            if 'chat_id' not in existing:
                db.session.execute(text('ALTER TABLE message ADD COLUMN chat_id INTEGER'))
                db.session.commit()
            
            db.session.execute(text('ALTER TABLE message ALTER COLUMN recipient_id DROP NOT NULL'))
            db.session.commit()
        elif is_sqlite:
            result = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='chat'"))
            if not result.fetchone():
                db.session.execute(text('''
                    CREATE TABLE chat (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        creator_id INTEGER NOT NULL,
                        avatar VARCHAR(200) DEFAULT 'chat_default.png'
                    );
                    CREATE TABLE chat_member (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        role VARCHAR(20) DEFAULT 'member',
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                '''))
                db.session.commit()
            
            try:
                result = db.session.execute(text("PRAGMA table_info(message)"))
                columns = [row[1] for row in result.fetchall()]
                if 'chat_id' not in columns:
                    db.session.execute(text("ALTER TABLE message ADD COLUMN chat_id INTEGER"))
                    db.session.commit()
            except Exception as e:
                app.logger.info(f"Chat ID column add: {e}")
    except Exception as e:
        app.logger.info(f"Chat migration: {e}")


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


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text)
    avatar = db.Column(db.String(200), default='default.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    location = db.Column(db.String(100), nullable=True)
    website = db.Column(db.String(200), nullable=True)
    birthday = db.Column(db.Date, nullable=True)
    interests = db.Column(db.Text, nullable=True)
    occupation = db.Column(db.String(100), nullable=True)
    
    is_private = db.Column(db.Boolean, default=False)
    hide_followers = db.Column(db.Boolean, default=False)
    hide_following = db.Column(db.Boolean, default=False)
    approve_followers = db.Column(db.Boolean, default=False)
    
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

    def is_member(self, chat):
        return ChatMember.query.filter_by(chat_id=chat.id, user_id=self.id).first() is not None

    def is_admin(self, chat):
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
            app.logger.info(f"unread_messages error: {e}")
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
        member = CommunityMember.query.filter_by(user_id=self.id, community_id=community.id, status='approved').first()
        return member and member.role in ('admin', 'creator')


class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    is_saved = db.Column(db.Boolean, default=False)
    
    user = db.relationship('User', backref='stories')
    
    def is_expired(self):
        return datetime.utcnow() > self.expires_at


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=True)
    is_community_post = db.Column(db.Boolean, default=False)
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    media = db.relationship('Media', backref='post', lazy='dynamic', cascade='all, delete-orphan')

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


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(500))
    media_type = db.Column(db.String(20))
    reply_to_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    
    author = db.relationship('User', foreign_keys=[user_id])
    reply_to = db.relationship('Comment', remote_side=[id], backref='replies')
    
    
class CommentReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])
    comment = db.relationship('Comment', backref='reactions')
    
    
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
    
    medias = db.relationship('MessageMedia', backref='message', lazy='dynamic')
    
    
class MessageReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])
    message = db.relationship('Message', backref='reactions')


class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    avatar = db.Column(db.String(200), default='chat_default.png')
    
    messages = db.relationship('Message', backref='chat', lazy='dynamic')
    members = db.relationship('ChatMember', backref='chat', lazy='dynamic', cascade='all, delete-orphan')


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
    avatar = FileField('Аватар', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Только изображения!')])
    location = StringField('Местоположение', validators=[Length(max=100)])
    website = StringField('Веб-сайт', validators=[Length(max=200)])
    birthday = StringField('Дата рождения (ДД.ММ.ГГГГ)')
    interests = TextAreaField('Интересы', validators=[Length(max=500)])
    occupation = StringField('Род деятельности', validators=[Length(max=100)])
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


class CommunityPostForm(FlaskForm):
    body = TextAreaField('Текст записи')
    media = FileField('Фото/Видео', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'mp4', 'webm', 'mov'], 'Только изображения и видео!')])
    submit = SubmitField('Опубликовать')


@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    try:
        followed_ids = [u.id for u in current_user.followed]
        blocked_ids = [u.id for u in current_user.blocked]
        member_communities = [cm.community_id for cm in current_user.community_memberships.filter_by(status='approved').all()]
        
        posts = Post.query.filter(
            db.or_(
                Post.user_id.in_(followed_ids),
                Post.community_id.in_(member_communities) if member_communities else False,
                Post.user_id == current_user.id
            ),
            ~Post.user_id.in_(blocked_ids)
        ).order_by(Post.created_at.desc()).all()
        
        repost_counts = {p.id: Repost.query.filter_by(post_id=p.id).count() for p in posts}
    except Exception as e:
        app.logger.error(f"DB Error: {e}")
        posts = []
        repost_counts = {}
    return render_template('index.html', posts=posts, repost_counts=repost_counts)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Регистрация прошла успешно! Войдите в аккаунт.')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        flash('Неверное имя пользователя или пароль')
    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        try:
            body = request.form.get('body', '').strip()
            post = Post(body=body, author=current_user)
            db.session.add(post)
            db.session.flush()
            
            files = request.files.getlist('media')
            app.logger.info(f"Files count: {len(files)}")
            for file in files:
                app.logger.info(f"Processing file: {file.filename}")
                if file.filename and allowed_file(file.filename):
                    if cloudinary_configured:
                        url = upload_to_cloudinary(file, folder='posts')
                        if url:
                            filename = url.split('/')[-1].split('.')[0]
                            ext = file.filename.rsplit('.', 1)[1].lower()
                            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                            media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                            db.session.add(media)
                    else:
                        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                        app.logger.info(f"Saving file: {filename}")
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        ext = filename.rsplit('.', 1)[1].lower()
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
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


@app.route('/post/<int:post_id>/repost', methods=['POST'])
@login_required
def repost(post_id):
    post = Post.query.get_or_404(post_id)
    if current_user.has_reposted(post):
        current_user.unrepost(post)
    else:
        current_user.repost(post)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/story/create', methods=['GET', 'POST'])
@login_required
def create_story():
    if request.method == 'POST':
        media_data = request.form.get('media_data')
        
        if media_data:
            import base64
            import io
            from werkzeug.datastructures import FileStorage
            
            header, data = media_data.split(',', 1)
            if 'image/jpeg' in header:
                ext = 'jpg'
                media_type = 'image'
            elif 'video/webm' in header:
                ext = 'webm'
                media_type = 'video'
            else:
                ext = 'jpg'
                media_type = 'image'
            
            binary = base64.b64decode(data)
            file = FileStorage(io.BytesIO(binary), filename=f'story.{ext}', content_type=f'image/{ext}' if media_type == 'image' else f'video/{ext}')
            
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
                    return redirect(url_for('index'))
            else:
                filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                    f.write(binary)
                story = Story(
                    user_id=current_user.id,
                    media_url=filename,
                    media_type=media_type,
                    expires_at=datetime.utcnow() + timedelta(hours=24)
                )
                db.session.add(story)
                db.session.commit()
                return redirect(url_for('index'))
        
        file = request.files.get('media')
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
                return redirect(url_for('index'))
        else:
            flash('Выберите файл')
            return redirect(request.url)
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


@app.route('/stories')
@login_required
def stories_route():
    Story.query.filter(Story.expires_at < datetime.utcnow(), Story.is_saved == False).delete()
    db.session.commit()
    user_ids = [current_user.id] + [f.id for f in current_user.followers.all()] + [f.id for f in current_user.followed.all()]
    stories_list = Story.query.filter(Story.user_id.in_(user_ids), Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).all()
    return render_template('stories.html', stories=stories_list)


@app.route('/stories/user/<username>')
@login_required
def user_stories(username):
    user = User.query.filter_by(username=username).first_or_404()
    stories = Story.query.filter(Story.user_id == user.id, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).all()
    if not stories and not Story.query.filter(Story.user_id == user.id, Story.is_saved == True).first():
        abort(404)
    saved_stories = Story.query.filter(Story.user_id == user.id, Story.is_saved == True).order_by(Story.created_at.desc()).all()
    all_stories = stories + saved_stories
    return render_template('user_stories.html', stories=all_stories, user=user)


@app.route('/story/<int:story_id>')
@login_required
def view_story(story_id):
    story = Story.query.get_or_404(story_id)
    if story.is_expired() and not story.is_saved:
        abort(404)
    return render_template('view_story.html', story=story)


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
            db.session.commit()
            flash(f'Пост отправлен пользователю {user.username}')
            return redirect(url_for('index'))
        else:
            flash('Пользователь не найден')
    
    users = User.query.filter(User.id != current_user.id).all()
    user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
    chats = [Chat.query.get(cm.chat_id) for cm in user_chats]
    return render_template('forward_post.html', post=post, users=users, chats=chats)


@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def like(post_id):
    post = Post.query.get_or_404(post_id)
    if post.liked_by(current_user):
        current_user.unlike_post(post)
    else:
        current_user.like_post(post)
    db.session.commit()
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
        if file.filename and allowed_file(file.filename):
            try:
                if cloudinary_configured:
                    media_url = upload_to_cloudinary(file, folder='comments')
                    if media_url:
                        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                else:
                    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    media_url = '/media/' + filename
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
            except Exception as e:
                app.logger.error(f"Media upload error: {e}")
    
    app.logger.info(f"Comment body: {body}")
    if body or media_url:
        try:
            comment = Comment(body=body or '', author=current_user, post=post, media_url=media_url, media_type=media_type, reply_to_id=reply_to_comment_id)
            db.session.add(comment)
            db.session.commit()
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
    if comment.author != current_user:
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


@app.route('/message/<int:message_id>/react', methods=['POST'])
@login_required
def react_message(message_id):
    emoji = request.form.get('emoji', '👍')
    message = Message.query.get_or_404(message_id)
    existing = MessageReaction.query.filter_by(message_id=message_id, user_id=current_user.id, emoji=emoji).first()
    if existing:
        db.session.delete(existing)
    else:
        reaction = MessageReaction(message_id=message_id, user_id=current_user.id, emoji=emoji)
        db.session.add(reaction)
    db.session.commit()
    return redirect(request.referrer or url_for('index'))


@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    repost_count = Repost.query.filter_by(post_id=post.id).count()
    return render_template('post.html', post=post, repost_count=repost_count)


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
    
    try:
        from sqlalchemy import text
        db.session.execute(text("UPDATE message SET post_id = NULL WHERE post_id = :post_id"), {'post_id': post_id})
        db.session.execute(text("DELETE FROM repost WHERE post_id = :post_id"), {'post_id': post_id})
    except: pass
    
    for media in post.media:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], media.filename))
        except: pass
    db.session.delete(post)
    db.session.commit()
    flash('Пост удалён')
    return redirect(url_for('index'))


@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    blocked_by_user = current_user.is_authenticated and current_user.is_blocking(user)
    
    if blocked_by_user:
        posts = []
        user_reposts = []
        can_view = False
    elif user.is_private and user != current_user:
        can_view = current_user.is_authenticated and current_user.is_following(user)
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
    return render_template('profile.html', user=user, posts=posts, user_reposts=user_reposts, repost_counts=repost_counts, is_following=is_following, is_blocked=is_blocked, is_pending=is_pending, can_view=can_view, pending_count=pending_count)


@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        if user.approve_followers:
            flash(f'Запрос на подписку отправлен {user.username}. Ожидайте одобрения.')
        else:
            current_user.follow(user)
            db.session.commit()
            flash(f'Вы подписались на {user.username}')
    return redirect(url_for('user_profile', username=user.username))


@app.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    user = User.query.filter_by(username=username).first_or_404()
    current_user.unfollow(user)
    db.session.commit()
    flash(f'Вы отписались от {user.username}')
    return redirect(url_for('user_profile', username=user.username))


@app.route('/block/<username>', methods=['POST'])
@login_required
def block_user(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        current_user.block(user)
        db.session.commit()
        flash(f'Вы заблокировали {user.username}')
    return redirect(url_for('user_profile', username=user.username))


@app.route('/unblock/<username>', methods=['POST'])
@login_required
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
    flash(f'Вы одобрили подписку {user.username}')
    return redirect(url_for('follower_requests'))


@app.route('/followers/reject/<username>', methods=['POST'])
@login_required
def reject_follower(username):
    user = User.query.filter_by(username=username).first_or_404()
    current_user.reject_follower(user)
    flash(f'Запрос на подписку от {user.username} отклонён')
    return redirect(url_for('follower_requests'))


@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.username = form.username.data
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
            filename = secure_filename(f"{datetime.now().timestamp}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            current_user.avatar = filename
        
        if form.birthday.data:
            try:
                current_user.birthday = datetime.strptime(form.birthday.data, '%d.%m.%Y').date()
            except ValueError:
                flash('Неверный формат даты. Используйте ДД.ММ.ГГГГГ')
                return render_template('edit_profile.html', form=form)
        
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
        if current_user.birthday:
            form.birthday.data = current_user.birthday.strftime('%d.%m.%Y')
    return render_template('edit_profile.html', form=form)


@app.route('/explore')
def explore():
    blocked_ids = []
    if current_user.is_authenticated:
        blocked_ids = [u.id for u in current_user.blocked]
    
    users = User.query.filter(
        ~User.id.in_(blocked_ids) if blocked_ids else True,
        User.id != current_user.id if current_user.is_authenticated else True
    ).order_by(User.created_at.desc()).limit(20).all()
    
    return render_template('explore.html', users=users)


@app.route('/photos')
@login_required
def photos():
    user_media = Media.query.join(Post).filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).all()
    return render_template('photos.html', user_media=user_media)


@app.route('/messages')
@login_required
def messages():
    blocked_ids = [u.id for u in current_user.blocked]
    
    # Личные переписки
    conversations = {}
    for msg in current_user.messages_received.filter(~Message.sender_id.in_(blocked_ids)):
        if msg.sender_id not in conversations:
            conversations[msg.sender_id] = {'user': msg.sender, 'last': msg, 'unread': 0, 'type': 'private'}
        if not msg.read:
            conversations[msg.sender_id]['unread'] += 1
    
    for msg in current_user.messages_sent.filter(~Message.recipient_id.in_(blocked_ids)):
        if msg.recipient_id not in conversations:
            conversations[msg.recipient_id] = {'user': msg.recipient, 'last': msg, 'unread': 0, 'type': 'private'}
    
    # Групповые чаты
    user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
    group_chats = []
    for member in user_chats:
        chat = Chat.query.get(member.chat_id)
        if chat:
            last_msg = chat.messages.order_by(Message.created_at.desc()).first()
            unread_count = Message.query.filter_by(chat_id=chat.id).filter(Message.sender_id != current_user.id, Message.read == False).count()
            group_chats.append({
                'chat': chat,
                'last': last_msg,
                'unread': unread_count,
                'type': 'group'
            })
    
    conversations = sorted(conversations.values(), key=lambda x: x['last'].created_at if x.get('last') else datetime.min, reverse=True)
    
    # Добавить себя в список диалогов
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
    
    suggested = [u for u in User.query.order_by(User.created_at.desc()).all() 
                 if u != current_user and u.id not in conversations and not current_user.is_blocking(u)]
    return render_template('messages.html', conversations=conversations, group_chats=group_chats, suggested_users=suggested)


@app.route('/messages/<username>', methods=['GET', 'POST'])
@login_required
def conversation(username):
    other_user = User.query.filter_by(username=username).first_or_404()
    
    if username != current_user.username:
        if current_user.is_blocking(other_user) or other_user.is_blocking(current_user):
            flash('Вы не можете отправить сообщение этому пользователю')
            return redirect(url_for('messages'))
    
    try:
        Message.query.filter_by(sender=other_user, recipient=current_user, read=False).update({'read': True})
        db.session.commit()
    except:
        db.session.rollback()
    
    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        media_url = None
        media_type = None
        
        app.logger.info(f"Files: {request.files}")
        
        if 'media' in request.files:
            file = request.files['media']
            app.logger.info(f"File: {file.filename}")
            if file.filename and allowed_file(file.filename):
                if cloudinary_configured:
                    media_url = upload_to_cloudinary(file, folder='messages')
                    if media_url:
                        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                else:
                    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    media_url = '/media/' + filename
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                app.logger.info(f"Media URL: {media_url}, type: {media_type}")
        
        if body or media_url:
            try:
                msg = Message(body=body or '', sender=current_user, recipient=other_user)
                db.session.add(msg)
                db.session.flush()
                
                if media_url:
                    media = MessageMedia(message_id=msg.id, media_url=media_url, media_type=media_type)
                    db.session.add(media)
                
                db.session.commit()
                app.logger.info(f"Message saved with media: {media_url}")
            except Exception as e:
                app.logger.error(f"Message error: {e}")
                db.session.rollback()
    
    try:
        if other_user.id == current_user.id:
            messages = Message.query.filter(
                Message.sender_id == current_user.id,
                Message.recipient_id == current_user.id
            ).order_by(Message.created_at.asc()).all()
        else:
            messages = Message.query.filter(
                ((Message.sender == current_user) & (Message.recipient == other_user)) |
                ((Message.sender == other_user) & (Message.recipient == current_user))
            ).order_by(Message.created_at.asc()).all()
    except Exception as e:
        app.logger.error(f"Load messages error: {e}")
        messages = []
    
    return render_template('conversation.html', other_user=other_user, messages=messages, Post=Post)


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
        
        # Добавить создателя как админа
        member = ChatMember(chat_id=chat.id, user_id=current_user.id, role='admin')
        db.session.add(member)
        
        # Добавить участников
        for member_id in member_ids:
            if int(member_id) != current_user.id:
                member = ChatMember(chat_id=chat.id, user_id=int(member_id), role='member')
                db.session.add(member)
        
        db.session.commit()
        flash(f'Чат "{name}" создан')
        return redirect(url_for('messages'))
    
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('create_chat.html', users=users)


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
        
        app.logger.info(f"Files in request: {list(request.files.keys())}")
        
        if 'media' in request.files:
            file = request.files['media']
            file_len = file.seek(0, 2)
            file.seek(0)
            app.logger.info(f"File: '{file.filename}', content_type: {file.content_type}, size: {file_len}, allowed: {allowed_file(file.filename) if file.filename else False}")
            if file.filename and file_len > 0 and allowed_file(file.filename):
                try:
                    media_url = None
                    media_type = 'image'
                    if cloudinary_configured:
                        app.logger.info("Uploading to cloudinary...")
                        media_url = upload_to_cloudinary(file, folder='messages')
                        app.logger.info(f"Cloudinary result: {media_url}")
                        if media_url:
                            ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                    else:
                        app.logger.warning("Cloudinary not configured, using local storage")
                    
                    app.logger.info(f"Before local save check, media_url: {media_url}")
                    
                    if not media_url:
                        app.logger.info("Entering local save block")
                        filename = secure_filename(f"{datetime.now().timestamp}_{file.filename}")
                        full_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                        app.logger.info(f"Saving to: {full_path}")
                        try:
                            file.save(full_path)
                            app.logger.info(f"File saved, exists: {os.path.exists(full_path)}")
                            list_files = os.listdir(app.config['UPLOAD_FOLDER'])
                            app.logger.info(f"Files in upload dir: {list_files[:5]}")
                        except Exception as e:
                            app.logger.error(f"Save error: {e}")
                        media_url = '/media/' + filename
                        app.logger.info(f"Generated URL: {media_url}")
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
                    app.logger.info(f"Media URL: {media_url}, type: {media_type}")
                except Exception as e:
                    app.logger.error(f"Media upload error: {e}")
            else:
                app.logger.warning(f"File not allowed or empty: filename='{file.filename}', size={file_len}")
        
        app.logger.info(f"body: '{body}', media_url: {media_url}, post_id: {post_id}")
        
        has_content = body or media_url or post_id
        app.logger.warning(f"DEBUG: has_content check - body={bool(body)}, media_url={bool(media_url)}, post_id={bool(post_id)}, result={has_content}")
        
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
                app.logger.warning(f"Message created with id={msg.id}")
                
                if media_url:
                    app.logger.warning(f"Adding media: url={media_url}, type={media_type}")
                    media = MessageMedia(message_id=msg.id, media_url=media_url, media_type=media_type)
                    db.session.add(media)
                
                db.session.commit()
                app.logger.warning(f"Message and media saved successfully!")
            except Exception as e:
                app.logger.error(f"Chat message error: {e}")
                db.session.rollback()
    
    messages = chat.messages.order_by(Message.created_at.asc()).all()
    
    Message.query.filter_by(chat_id=chat_id).filter(Message.sender_id != current_user.id, Message.read == False).update({'read': True})
    db.session.commit()
    
    return render_template('chat.html', chat=chat, messages=messages, Post=Post)


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


@app.route('/message/<int:message_id>/forward')
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
    
    user_chats = ChatMember.query.filter_by(user_id=current_user.id).all()
    chats = [Chat.query.get(cm.chat_id) for cm in user_chats]
    
    other_user = None
    if message.recipient_id and not message.chat_id:
        other_user = User.query.get(message.recipient_id)
    
    return render_template('forward_message.html', message=message, chats=chats, other_user=other_user, Post=Post)


@app.route('/message/<int:message_id>/forward', methods=['POST'])
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
                    post_id=message.post_id
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
                post_id=message.post_id
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
        message.medias.delete()
        db.session.commit()
        flash('Сообщение удалено для вас')
    elif delete_type == 'all':
        if is_sender:
            message.medias.delete()
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
        
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file.filename and allowed_file(file.filename):
                if cloudinary_configured:
                    media_url = upload_to_cloudinary(file, folder='chats')
                    if media_url:
                        chat.avatar = media_url
                else:
                    filename = secure_filename(f"{datetime.now().timestamp}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    chat.avatar = filename
        
        db.session.commit()
        flash('Чат обновлен')
        return redirect(url_for('chat_view', chat_id=chat_id))
    
    return render_template('chat_edit.html', chat=chat)


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


@app.route('/community/<slug>')
def community(slug):
    comm = Community.query.filter_by(slug=slug).first_or_404()
    is_member = current_user.is_authenticated and current_user.is_member(comm)
    is_admin = current_user.is_authenticated and current_user.is_admin(comm)
    posts = comm.posts.order_by(Post.created_at.desc()).all()
    return render_template('community.html', community=comm, posts=posts, is_member=is_member, is_admin=is_admin)


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
    if comm.creator_id != current_user.id:
        flash('Только создатель может публиковать записи')
        return redirect(url_for('community', slug=slug))
    
    form = CommunityPostForm()
    if form.validate_on_submit():
        post = Post(body=form.body.data, author=current_user, community=comm, is_community_post=True)
        db.session.add(post)
        db.session.flush()
        
        if form.media.data:
            file = form.media.data
            filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            ext = filename.rsplit('.', 1)[1].lower()
            media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
            media = Media(filename=filename, media_type=media_type, post=post)
            db.session.add(media)
        
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
    app.logger.info(f"Looking for file: {filename}")
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


with app.app_context():
    db.create_all()
    
    try:
        from sqlalchemy import text
        result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user'"))
        columns = [row[0] for row in result]
        
        if 'avatar_url' in columns:
            db.session.execute(text("ALTER TABLE user DROP COLUMN avatar_url"))
            db.session.commit()
            app.logger.info("Dropped avatar_url column")
    except Exception as e:
        app.logger.info(f"Column check/drop error: {e}")
    
    try:
        db.session.execute(text("CREATE TABLE IF NOT EXISTS repost (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, post_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.info(f"Table repost may already exist: {e}")
    
    try:
        result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='message' AND column_name='post_id'"))
        if result.fetchone() is None:
            db.session.execute(text("ALTER TABLE message ADD COLUMN post_id INTEGER REFERENCES post(id)"))
            db.session.commit()
            app.logger.info("Added post_id column to message")
    except Exception as e:
        db.session.rollback()
        app.logger.info(f"Column post_id in message may already exist: {e}")
    
    try:
        db.session.execute(text("CREATE TABLE IF NOT EXISTS message_media (id SERIAL PRIMARY KEY, message_id INTEGER NOT NULL, media_url VARCHAR(500), media_type VARCHAR(20))"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.info(f"Table message_media may already exist: {e}")
    
    try:
        db.session.execute(text("UPDATE message SET body = COALESCE(body, '')"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.info(f"Error updating bodies: {e}")


if __name__ == '__main__':
    app.run(debug=True)
