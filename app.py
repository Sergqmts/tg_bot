from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
import os
import cloudinary
import cloudinary.uploader

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, 
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))

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
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}

cloudinary_configured = os.environ.get('CLOUDINARY_CLOUD_NAME') and os.environ.get('CLOUDINARY_API_KEY')
if cloudinary_configured:
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
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
    return url_for('uploaded_file', filename=public_id)


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
        elif is_sqlite:
            for col, typ in [('location', 'VARCHAR(100)'), ('website', 'VARCHAR(200)'), ('birthday', 'DATE'), ('interests', 'TEXT'), ('occupation', 'VARCHAR(100)')]:
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


followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
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
    
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    likes = db.relationship('Like', backref='user', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    
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
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).first() is not None

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
        return self.messages_received.filter_by(read=False).count()

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)


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
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    
    medias = db.relationship('MessageMedia', backref='message', lazy='dynamic')


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
        username = request.form.get('username', '').strip()
        user = User.query.filter_by(username=username).first()
        if user:
            app.logger.info(f"Forwarding post {post.id} to user {user.username}")
            app.logger.info(f"Post body: {post.body}")
            message_body = f"Репост от @{post.author.username}"
            if post.body:
                message_body += f":\n\n{post.body}"
            msg = Message(body=message_body, sender=current_user, recipient=user, post_id=post.id)
            db.session.add(msg)
            db.session.commit()
            app.logger.info(f"Message saved with post_id={msg.post_id}")
            flash(f'Пост отправлен пользователю {user.username}')
            return redirect(url_for('index'))
        else:
            flash('Пользователь не найден')
    users = User.query.filter(User.id != current_user.id).all()
    return render_template('forward_post.html', post=post, users=users)


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
    app.logger.info(f"Comment body: {body}")
    if body:
        try:
            comment = Comment(body=body, author=current_user, post=post)
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
    else:
        posts = user.posts.order_by(Post.created_at.desc()).all()
        user_reposts = []
        if user.id:
            user_reposts = Repost.query.filter_by(user_id=user.id).order_by(Repost.created_at.desc()).all()
    
    repost_counts = {}
    for p in posts:
        repost_counts[p.id] = Repost.query.filter_by(post_id=p.id).count() if p.id else 0
    is_following = current_user.is_authenticated and current_user.is_following(user)
    is_blocked = current_user.is_authenticated and current_user.is_blocking(user)
    return render_template('profile.html', user=user, posts=posts, user_reposts=user_reposts, repost_counts=repost_counts, is_following=is_following, is_blocked=is_blocked)


@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
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
        
        if form.avatar.data:
            file = form.avatar.data
            filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
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
        if current_user.birthday:
            form.birthday.data = current_user.birthday.strftime('%d.%m.%Y')
    return render_template('edit_profile.html', form=form)


@app.route('/explore')
def explore():
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    return render_template('explore.html', users=users)


@app.route('/photos')
@login_required
def photos():
    user_media = Media.query.join(Post).filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).all()
    return render_template('photos.html', user_media=user_media)


@app.route('/messages')
@login_required
def messages():
    conversations = {}
    for msg in current_user.messages_received:
        if msg.sender_id not in conversations:
            conversations[msg.sender_id] = {'user': msg.sender, 'last': msg, 'unread': 0}
        if not msg.read:
            conversations[msg.sender_id]['unread'] += 1
    
    for msg in current_user.messages_sent:
        if msg.recipient_id not in conversations:
            conversations[msg.recipient_id] = {'user': msg.recipient, 'last': msg, 'unread': 0}
    
    conversations = sorted(conversations.values(), key=lambda x: x['last'].created_at, reverse=True)
    suggested = [u for u in User.query.order_by(User.created_at.desc()).all() 
                 if u != current_user and u.id not in conversations]
    return render_template('messages.html', conversations=conversations, suggested_users=suggested)


@app.route('/messages/<username>', methods=['GET', 'POST'])
@login_required
def conversation(username):
    other_user = User.query.filter_by(username=username).first_or_404()
    
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
                    media_url = url_for('uploaded_file', filename=filename)
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
        messages = Message.query.filter(
            ((Message.sender == current_user) & (Message.recipient == other_user)) |
            ((Message.sender == other_user) & (Message.recipient == current_user))
        ).order_by(Message.created_at.asc()).all()
    except Exception as e:
        app.logger.error(f"Load messages error: {e}")
        messages = []
    
    return render_template('conversation.html', other_user=other_user, messages=messages, Post=Post)


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


@app.route('/uploads/<filename>')
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
