from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm, CSRFProtect
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os

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

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа'

csrf = CSRFProtect(app)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id')),
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

    def unread_messages(self):
        return self.messages_received.filter_by(read=False).count()

    def join_community(self, community):
        if not self.is_member(community):
            member = CommunityMember(user=self, community=community)
            db.session.add(member)

    def leave_community(self, community):
        member = CommunityMember.query.filter_by(user=self, community=community).first()
        if member:
            db.session.delete(member)

    def is_member(self, community):
        return CommunityMember.query.filter_by(user=self, community=community).first() is not None

    def is_admin(self, community):
        member = CommunityMember.query.filter_by(user=self, community=community).first()
        return member and member.role in ('admin', 'creator')


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=True)
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    media = db.relationship('Media', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    def liked_by(self, user):
        return self.likes.filter_by(user_id=user.id).first() is not None


class Community(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(200), default='community_default.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    creator = db.relationship('User', backref='created_communities')
    posts = db.relationship('Post', backref='community', lazy='dynamic', cascade='all, delete-orphan')
    members = db.relationship('CommunityMember', backref='community', lazy='dynamic', cascade='all, delete-orphan')


class CommunityMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False)
    role = db.Column(db.String(20), default='member')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='community_memberships')
    
    __table_args__ = (db.UniqueConstraint('user_id', 'community_id', name='unique_membership'),)


class Media(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
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


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


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
    submit = SubmitField('Сохранить')


class CommunityForm(FlaskForm):
    name = StringField('Название', validators=[DataRequired(), Length(min=3, max=50)])
    description = TextAreaField('Описание', validators=[Length(max=500)])
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
    try:
        posts = Post.query.order_by(Post.created_at.desc()).all()
    except Exception as e:
        app.logger.error(f"DB Error: {e}")
        posts = []
    return render_template('index.html', posts=posts)


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
    form = PostForm()
    if form.validate_on_submit():
        post = Post(body=form.body.data, author=current_user)
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
        flash('Пост опубликован!')
        return redirect(url_for('index'))
    return render_template('create.html', form=form)


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
    post = Post.query.get_or_404(post_id)
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data, author=current_user, post=post)
        db.session.add(comment)
        db.session.commit()
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


@app.route('/delete/<int:post_id>', methods=['POST'])
@login_required
def delete(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user:
        abort(403)
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
    posts = user.posts.order_by(Post.created_at.desc()).all()
    is_following = current_user.is_authenticated and current_user.is_following(user)
    return render_template('profile.html', user=user, posts=posts, is_following=is_following)


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


@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.bio = form.bio.data
        if form.avatar.data:
            file = form.avatar.data
            filename = secure_filename(f"avatar_{current_user.id}.{file.filename.rsplit('.', 1)[1].lower()}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            current_user.avatar = filename
        db.session.commit()
        flash('Профиль обновлён')
        return redirect(url_for('user_profile', username=current_user.username))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.bio.data = current_user.bio
    return render_template('edit_profile.html', form=form)


@app.route('/explore')
def explore():
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    return render_template('explore.html', users=users)


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
    
    Message.query.filter_by(sender=other_user, recipient=current_user, read=False).update({'read': True})
    db.session.commit()
    
    if request.method == 'POST':
        body = request.form.get('body')
        if body:
            msg = Message(body=body, sender=current_user, recipient=other_user)
            db.session.add(msg)
            db.session.commit()
    
    messages = Message.query.filter(
        ((Message.sender == current_user) & (Message.recipient == other_user)) |
        ((Message.sender == other_user) & (Message.recipient == current_user))
    ).order_by(Message.created_at.asc()).all()
    
    return render_template('conversation.html', other_user=other_user, messages=messages)


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
            creator=current_user
        )
        
        if form.image.data:
            file = form.image.data
            filename = secure_filename(f"community_{slug}.{file.filename.rsplit('.', 1)[1].lower()}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            community.image = filename
        
        db.session.add(community)
        db.session.flush()
        
        member = CommunityMember(user=current_user, community=community, role='creator')
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
    if not current_user.is_member(comm):
        current_user.join_community(comm)
        db.session.commit()
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
    if not current_user.is_member(comm):
        flash('Вы должны быть участником сообщества')
        return redirect(url_for('community', slug=slug))
    
    form = CommunityPostForm()
    if form.validate_on_submit():
        post = Post(body=form.body.data, author=current_user, community=comm)
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
    members = comm.members.order_by(CommunityMember.created_at.desc()).all()
    return render_template('community_members.html', community=comm, members=members)


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
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


with app.app_context():
    db.create_all()


if __name__ == '__main__':
    app.run(debug=True)
