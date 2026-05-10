from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, emit, join_room, leave_room
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from socket import gethostname, gethostbyname
import os
import cloudinary
import cloudinary.uploader
import tempfile
import io

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

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    import secrets
    app.config['SECRET_KEY'] = secrets.token_hex(32)
    app.logger.warning("SECRET_KEY not set - generating random key. Sessions will reset on restart.")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov', 'mp3', 'wav', 'ogg', 'm4a', 'aac', 'pdf', 'doc', 'docx', 'txt'}

# Custom Jinja2 filters
@app.template_filter('from_json')
def from_json_filter(value):
    import json
    try:
        return json.loads(value) if value else {}
    except:
        return {}


@app.context_processor
def inject_stories():
    if current_user.is_authenticated:
        try:
            followers = current_user.followers.all()
            following = current_user.followed.all()
            follower_ids = [f.id for f in followers]
            following_ids = [f.id for f in following]
            user_ids = [current_user.id] + follower_ids + following_ids
            
            if user_ids:
                story_users = db.session.query(Story.user_id).filter(
                    Story.user_id.in_(user_ids),
                    Story.expires_at > datetime.utcnow()
                ).group_by(Story.user_id).limit(20).all()
                stories_list = []
                for (uid,) in story_users:
                    s = Story.query.filter(Story.user_id == uid, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
                    if s:
                        stories_list.append(s)
            else:
                stories_list = []
            my_story = Story.query.filter(Story.user_id == current_user.id, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
            has_story = my_story is not None
            unread_notifications = Notification.query.filter_by(user_id=current_user.id, read=False).count()
            return dict(top_stories=stories_list, my_story=my_story, user_has_story=has_story, unread_notifications=unread_notifications, active_users=active_users)
        except Exception as e:
            app.logger.error(f"Stories error: {e}")
            return dict(top_stories=[], my_story=None, user_has_story=False, unread_notifications=0, active_users=active_users)
    return dict(top_stories=[], my_story=None, user_has_story=False, unread_notifications=0, active_users=active_users)


def get_avatar_url(user):
    if user.avatar_cloudinary_url:
        return user.avatar_cloudinary_url
    if user.avatar and user.avatar != 'default.png':
        return url_for('uploaded_file', filename=user.avatar)
    return None


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

FREESOUND_API_KEY = os.environ.get('FREESOUND_API_KEY', '')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

def init_db():
    from sqlalchemy import text
    db_url = str(db.engine.url)
    is_postgres = 'postgresql' in db_url or 'psycopg' in db_url

    def column_exists_conn(conn, table, column):
        try:
            if is_postgres:
                result = conn.execute(text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_name = :table AND column_name = :column"
                ), {'table': table, 'column': column})
            else:
                result = conn.execute(text(
                    "SELECT COUNT(*) FROM pragma_table_info(:table) WHERE name=:column"
                ), {'table': table, 'column': column})
            return result.scalar() > 0
        except:
            return False

    for attempt in range(3):
        try:
            with db.engine.connect() as conn:
                if is_postgres:
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = 'message' AND column_name = 'transcription'
                    """))
                    if not result.scalar():
                        conn.execute(text('ALTER TABLE message ADD COLUMN transcription TEXT'))
                        conn.commit()
                    
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM information_schema.columns 
                        WHERE table_name = 'user' AND column_name = 'last_seen'
                    """))
                    if not result.scalar():
                        conn.execute(text('ALTER TABLE "user" ADD COLUMN last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
                        conn.commit()
                    
                    result = conn.execute(text("""
                        SELECT COUNT(*) FROM information_schema.tables 
                        WHERE table_name = 'notification'
                    """))
                    if not result.scalar():
                        db.create_all()
                else:
                    result = conn.execute(text("SELECT COUNT(*) FROM pragma_table_info('message') WHERE name='transcription'"))
                    if not result.scalar():
                        conn.execute(text('ALTER TABLE message ADD COLUMN transcription TEXT'))
                        conn.commit()

                for col in ['is_bot', 'bot_token', 'bot_commands', 'can_join_groups', 'privacy_mode', 'webhook_url', 'creator_id', 'is_banned', 'is_staff']:
                    if not column_exists_conn(conn, 'user', col):
                        if is_postgres:
                            type_map = {
                                'is_bot': 'BOOLEAN DEFAULT FALSE',
                                'bot_token': 'VARCHAR(64)',
                                'bot_commands': "TEXT DEFAULT '[]'",
                                'can_join_groups': 'BOOLEAN DEFAULT TRUE',
                                'privacy_mode': 'BOOLEAN DEFAULT TRUE',
                                'webhook_url': 'VARCHAR(500)',
                                'creator_id': 'INTEGER REFERENCES "user"(id)',
                                'is_banned': 'BOOLEAN DEFAULT FALSE',
                                'is_staff': 'BOOLEAN DEFAULT FALSE',
                            }
                            conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {type_map[col]}'))
                        else:
                            col_type_map = {'creator_id': 'INTEGER', 'is_banned': 'BOOLEAN', 'is_staff': 'BOOLEAN'}
                            col_type = col_type_map.get(col, 'TEXT')
                            conn.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {col_type}'))
                        conn.commit()
                if not column_exists_conn(conn, 'community', 'is_banned'):
                    if is_postgres:
                        conn.execute(text('ALTER TABLE community ADD COLUMN is_banned BOOLEAN DEFAULT FALSE'))
                    else:
                        conn.execute(text('ALTER TABLE community ADD COLUMN is_banned BOOLEAN'))
                    conn.commit()
            app.logger.info("DB init completed successfully")
            return
        except Exception as e:
            app.logger.warning(f"DB init attempt {attempt+1} failed: {e}")
            import time
            time.sleep(2)


def column_exists(table_name, column_name):
    """Проверяет, существует ли колонка в таблице (совместимо с SQLite и PostgreSQL)"""
    from sqlalchemy import text
    try:
        with db.engine.connect() as conn:
            db_url = str(db.engine.url)
            is_postgres = 'postgresql' in db_url or 'psycopg' in db_url
            if is_postgres:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.columns 
                    WHERE table_name = :table AND column_name = :column
                """), {'table': table_name, 'column': column_name})
            else:
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM pragma_table_info(:table) WHERE name=:column
                """), {'table': table_name, 'column': column_name})
            return result.scalar() > 0
    except:
        return False


def get_table_columns(table_name):
    """Возвращает список колонок таблицы (совместимо с SQLite и PostgreSQL)"""
    from sqlalchemy import text
    db_url = str(db.engine.url)
    is_postgres = 'postgresql' in db_url or 'psycopg' in db_url
    
    try:
        if is_postgres:
            result = db.session.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = :table
            """), {'table': table_name})
        else:
            result = db.session.execute(text("""
                SELECT name FROM pragma_table_info(:table)
            """), {'table': table_name})
        return [row[0] for row in result]
    except:
        return []


def generate_bot_token():
    import secrets
    return f"{secrets.randbelow(900000000) + 100000000}:{secrets.token_urlsafe(32)}"


NSFW_KEYWORDS = [
    'порно', 'porn', 'секс', 'sex', 'xxx', '18+', 'nsfw', 'эротика', 'erotica',
    'писька', 'писюн', 'член', 'хуй', 'хуя', 'пизда', 'пизд', 'ебал', 'ебат',
    'ебля', 'выеб', 'заеб', 'нахуй', 'похуй', 'сосать', 'соси', 'минета',
    'минет', 'анал', 'anus', 'asshole', 'bdsm', 'биде', 'вагина', 'vagin',
    'гениталии', 'genital', 'грудь', 'tits', 'titty', 'сиськи', 'сиськ',
    'дрочить', 'дрочк', 'дупа', 'жопа', 'жоп', 'залупа', 'извращ',
    'клитор', 'clitor', 'конча', 'кончить', 'лижут', 'лизать', 'мастурб',
    'masturb', 'мошонк', 'мудак', 'мудил', 'мужлан', 'негр', 'ниггер',
    'naked', 'nude', 'обнажен', 'оголен', 'орал', 'oral', 'оргазм', 'orgasm',
    'педик', 'петух', 'петуша', 'попка', 'попа', 'проститут', 'prostitut',
    'pubic', 'разврат', 'секс-', 'slut', 'сперм', 'sperm', 'squirt',
    'страпон', 'stripper', 'strip', 'сука', 'сучар', 'трахат', 'трахн',
    'траx', 'фистинг', 'fisting', 'фетиш', 'fetish', 'fuck', 'fucking',
    'fucked', 'handjob', 'blowjob', 'cum', 'cock', 'cocks', 'dick',
    'dildo', 'domina', 'ejacul', 'erotic', 'escort', 'gangbang',
    'hentai', 'horny', 'incest', 'jerk', 'kink', 'kinky', 'lesbian',
    'licking', 'milf', 'nipple', 'nudity', 'orgy', 'penis', 'pornstar',
    'pussy', 'rape', 'rapist', 'seduce', 'semen', 'sex toy', 'sexting',
    'sexual', 'slave', 'sucking', 'threesome', 'urethra', 'vibrator',
    'voyeur', 'whore', 'wank', 'шалава', 'шлюха', 'щель',
]


def check_nsfw_text(text):
    if not text:
        return None
    text_lower = text.lower()
    for kw in NSFW_KEYWORDS:
        if kw in text_lower:
            return kw
    return None


MODERATION_BOT_USERNAME = 'ModeratorBot'
WARNING_LIMIT = 5


def get_moderation_bot():
    bot = User.query.filter_by(username=MODERATION_BOT_USERNAME, is_bot=True).first()
    if not bot:
        bot = User(
            username=MODERATION_BOT_USERNAME,
            email=f'bot_{MODERATION_BOT_USERNAME}@localhost',
            is_bot=True,
            bot_token=generate_bot_token(),
            bot_commands='[]',
            bio='Content Moderation Bot — проверяет контент на нарушения',
            creator_id=None,
        )
        bot.set_password(os.urandom(32).hex())
        db.session.add(bot)
        db.session.flush()
    return bot


def moderate_post(body, author, community=None):
    if author.is_bot and author.creator_id is None:
        return None
    if author.is_banned:
        return 'USER_BANNED'

    matched = check_nsfw_text(body)
    if not matched:
        return None

    warning_count = ModerationLog.query.filter_by(user_id=author.id).count() + 1
    log = ModerationLog(
        user_id=author.id,
        community_id=community.id if community else None,
        post_id=None,
        reason=f'NSFW content detected (keyword: {matched})',
    )
    db.session.add(log)
    db.session.commit()

    bot = get_moderation_bot()
    dm = get_or_create_dm(author, bot)
    msg = (
        f'⚠️ Warning #{warning_count}/{WARNING_LIMIT}\n\n'
        f'Your post was rejected: NSFW content detected.\n'
        f'Reason: inappropriate language ("{matched}")\n\n'
    )
    if warning_count >= WARNING_LIMIT:
        author.is_banned = True
        db.session.commit()
        msg += '🚫 Your account has been permanently banned for repeated violations.'
    else:
        msg += f'After {WARNING_LIMIT} warnings your account will be permanently banned.'

    message = Message(
        sender_id=bot.id,
        recipient_id=author.id,
        chat_id=dm.id,
        body=msg,
    )
    db.session.add(message)
    db.session.commit()

    return 'BLOCKED'


with app.app_context():
    init_db()

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа'

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False, async_mode='threading')

active_users = {}  # user_id -> sid


@app.after_request
def process_webhooks(response):
    if _webhook_queue:
        import threading
        t = threading.Thread(target=process_webhook_queue, daemon=True)
        t.start()
    return response


@app.route('/api/unread-count')
@login_required
def unread_notification_count():
    count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    return {'count': count}

@socketio.on('connect')
def handle_connect():
    from flask import request as flask_request
    if current_user.is_authenticated:
        active_users[current_user.id] = flask_request.sid
        join_room(f'user_{current_user.id}')
        current_user.last_seen = datetime.utcnow()
        try:
            db.session.commit()
        except:
            pass
        emit('user_online', {'user_id': current_user.id}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated and current_user.id in active_users:
        del active_users[current_user.id]
        emit('user_offline', {'user_id': current_user.id}, broadcast=True)

@socketio.on('send_message')
def handle_message(data):
    if current_user.is_authenticated:
        recipient_id = data.get('recipient_id')
        chat_id = data.get('chat_id')
        message_body = data.get('body', '')
        
        emit('new_message', {
            'sender_id': current_user.id,
            'sender_username': current_user.username,
            'body': message_body,
            'chat_id': chat_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'user_{recipient_id}')

csrf = CSRFProtect(app)


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
            timeout=30,
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


@app.before_request
def update_last_seen():
    if current_user.is_authenticated:
        try:
            current_user.last_seen = datetime.utcnow()
            db.session.commit()
        except:
            pass


def create_notification(user_id, sender_id, notif_type, post_id=None, comment_id=None, message_id=None):
    try:
        if user_id == sender_id:
            return
        notification = Notification(
            user_id=user_id,
            sender_id=sender_id,
            type=notif_type,
            post_id=post_id,
            comment_id=comment_id,
            message_id=message_id
        )
        db.session.add(notification)
        db.session.commit()
    except Exception as e:
        app.logger.error(f"Notification error: {e}")


_migration_done = False

@app.before_request
def run_migrations():
    global _migration_done
    if _migration_done:
        return
    _migration_done = True
    
    from sqlalchemy import text
    
    try:
        existing = get_table_columns('user')
        for col, typ in [('location', 'VARCHAR(100)'), ('website', 'VARCHAR(200)'), ('birthday', 'DATE'), ('interests', 'TEXT'), ('occupation', 'VARCHAR(100)')]:
            if col not in existing:
                try:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {typ}'))
                    db.session.commit()
                except:
                    pass
        privacy_cols = [('is_private', 'BOOLEAN DEFAULT 0'), ('hide_followers', 'BOOLEAN DEFAULT 0'), ('hide_following', 'BOOLEAN DEFAULT 0'), ('approve_followers', 'BOOLEAN DEFAULT 0')]
        for col, typ in privacy_cols:
            if col not in existing:
                try:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {typ}'))
                    db.session.commit()
                except:
                    pass
        phone_cols = [('phone', 'VARCHAR(20)'), ('phone_verified', 'BOOLEAN DEFAULT 0'), ('phone_otp', 'VARCHAR(6)'), ('phone_otp_expires', 'TIMESTAMP')]
        for col, typ in phone_cols:
            if col not in existing:
                try:
                    db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {col} {typ}'))
                    db.session.commit()
                except:
                    pass
    except Exception as e:
        app.logger.info(f"User migration: {e}")
    
    try:
        if not column_exists('community', 'is_private'):
            try:
                db.session.execute(text('ALTER TABLE community ADD COLUMN is_private BOOLEAN DEFAULT 0'))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Community migration: {e}")
    
    try:
        if not column_exists('community_member', 'status'):
            try:
                db.session.execute(text("ALTER TABLE community_member ADD COLUMN status VARCHAR(20) DEFAULT 'approved'"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Member migration: {e}")
    
    try:
        if not column_exists('post', 'is_community_post'):
            try:
                db.session.execute(text("ALTER TABLE post ADD COLUMN is_community_post BOOLEAN DEFAULT 0"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Post migration: {e}")
    
    try:
        if not column_exists('followers', 'status'):
            try:
                db.session.execute(text("ALTER TABLE followers ADD COLUMN status VARCHAR(20) DEFAULT 'approved'"))
                db.session.commit()
            except:
                pass
    except Exception as e:
        app.logger.info(f"Followers migration: {e}")
    
    try:
        # Проверка существования таблицы (совместимо с SQLite и PostgreSQL)
        db_url = str(db.engine.url)
        is_postgres = 'postgresql' in db_url or 'psycopg' in db_url
        
        if is_postgres:
            result = db.session.execute(text("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name = 'chat'
            """))
        else:
            result = db.session.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='chat'"))
        
        if not result.scalar():
            db_url = str(db.engine.url)
            is_postgres = 'postgresql' in db_url or 'psycopg' in db_url
            
            if is_postgres:
                # PostgreSQL syntax
                db.session.execute(text('''
                    CREATE TABLE chat (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        creator_id INTEGER NOT NULL,
                        avatar VARCHAR(200) DEFAULT 'chat_default.png',
                        background_type VARCHAR(20) DEFAULT 'default',
                        background_value VARCHAR(500) DEFAULT ''
                    )
                '''))
                db.session.execute(text('''
                    CREATE TABLE chat_member (
                        id SERIAL PRIMARY KEY,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        role VARCHAR(20) DEFAULT 'member',
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
            else:
                # SQLite syntax
                db.session.execute(text('''
                    CREATE TABLE chat (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(100) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        creator_id INTEGER NOT NULL,
                        avatar VARCHAR(200) DEFAULT 'chat_default.png',
                        background_type VARCHAR(20) DEFAULT 'default',
                        background_value VARCHAR(500) DEFAULT ''
                    )
                '''))
                db.session.execute(text('''
                    CREATE TABLE chat_member (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        user_id INTEGER NOT NULL,
                        role VARCHAR(20) DEFAULT 'member',
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                '''))
            db.session.commit()
        
        # Add background columns to chat table if they don't exist
        chat_columns = get_table_columns('chat')
        if 'background_type' not in chat_columns:
            try:
                db.session.execute(text("ALTER TABLE chat ADD COLUMN background_type VARCHAR(20) DEFAULT 'default'"))
                db.session.commit()
            except:
                pass
        if 'background_value' not in chat_columns:
            try:
                db.session.execute(text("ALTER TABLE chat ADD COLUMN background_value VARCHAR(500) DEFAULT ''"))
                db.session.commit()
            except:
                pass
        
        columns = get_table_columns('message')
        if 'chat_id' not in columns:
            try:
                db.session.execute(text("ALTER TABLE message ADD COLUMN chat_id INTEGER"))
                db.session.commit()
            except:
                pass
        
        try:
            story_cols = get_table_columns('story')
            if 'is_archived' not in story_cols:
                db.session.execute(text("ALTER TABLE story ADD COLUMN is_archived INTEGER DEFAULT 0"))
                db.session.commit()
            if 'reposted_at' not in story_cols:
                db.session.execute(text("ALTER TABLE story ADD COLUMN reposted_at TIMESTAMP"))
                db.session.commit()
        except Exception as e:
            app.logger.info(f"Story columns add: {e}")
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

story_hidden = db.Table('story_hidden',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('story_id', db.Integer, db.ForeignKey('story.id'), primary_key=True)
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
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
    is_staff = db.Column(db.Boolean, default=False)
    
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


class ShortsAudio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    duration = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    user = db.relationship('User', backref='uploaded_shorts_audios')


class MusicTrack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), default='')
    album = db.Column(db.String(200), default='')
    duration = db.Column(db.Integer, default=0)
    preview_url = db.Column(db.String(500))
    cover_url = db.Column(db.String(500))
    deezer_id = db.Column(db.Integer, unique=True, nullable=True)
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
    audio_id = db.Column(db.Integer, db.ForeignKey('shorts_audio.id'), nullable=True)
    caption = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    views = db.Column(db.Integer, default=0)
    likes = db.relationship('ShortsLike', backref='shorts', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('ShortsComment', backref='shorts', lazy='dynamic', cascade='all, delete-orphan')
    
    user = db.relationship('User', backref='shorts_videos')
    audio = db.relationship('ShortsAudio', backref='shorts_videos')
    
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
    
    medias = db.relationship('MessageMedia', backref='message')


_webhook_queue = []


def enqueue_webhook_dispatch(message_id):
    _webhook_queue.append(message_id)


def process_webhook_queue():
    while _webhook_queue:
        msg_id = _webhook_queue.pop(0)
        try:
            with app.app_context():
                msg = Message.query.get(msg_id)
                if not msg:
                    continue
                sender = User.query.get(msg.sender_id)
                if sender and sender.is_bot:
                    continue
                chat = Chat.query.get(msg.chat_id) if msg.chat_id else None
                if not chat and msg.recipient_id:
                    recipient = User.query.get(msg.recipient_id)
                    if recipient and recipient.is_bot and recipient.webhook_url:
                        _send_webhook_payload(recipient, msg, sender, None, recipient=recipient)
                    continue
                if not chat:
                    continue
                bot_members = ChatMember.query.filter_by(chat_id=chat.id).all()
                for member in bot_members:
                    bot = User.query.get(member.user_id)
                    if bot and bot.is_bot and bot.webhook_url and bot.id != msg.sender_id:
                        _send_webhook_payload(bot, msg, sender, chat)
        except Exception as e:
            app.logger.error(f"Webhook dispatch error for msg {msg_id}: {e}")


def _send_webhook_payload(bot, message, sender, chat, recipient=None):
    import json, urllib.request, urllib.error
    update = {
        'update_id': message.id,
        'message': {
            'message_id': message.id,
            'date': int(message.created_at.timestamp()) if message.created_at else 0,
            'text': message.body or '',
            'from': {
                'id': sender.id,
                'username': sender.username,
                'is_bot': sender.is_bot if sender else False,
            } if sender else None,
            'chat': {
                'id': chat.id if chat else (recipient.id if recipient else 0),
                'type': chat.type if chat else 'private',
                'name': chat.name if chat else (recipient.username if recipient else ''),
            },
        }
    }
    if chat is None and recipient:
        update['message']['chat'] = {
            'id': recipient.id,
            'type': 'private',
            'username': recipient.username,
            'first_name': recipient.username,
        }

    payload = json.dumps(update).encode('utf-8')
    try:
        req = urllib.request.Request(
            bot.webhook_url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        app.logger.warning(f"Webhook to {bot.webhook_url} failed: {e}")


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
    # background_type: 'default', 'color', 'gradient', 'image'
    # background_value: JSON string {"light": "...", "dark": "..."}
    background_type = db.Column(db.String(20), default='default')
    background_value = db.Column(db.String(500), default='{"light": "", "dark": ""}')
    
    messages = db.relationship('Message', backref='chat', lazy='dynamic')
    members = db.relationship('ChatMember', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_background(self, theme='light'):
        import json
        try:
            data = json.loads(self.background_value) if self.background_value else {}
            return data.get(theme, '')
        except:
            return ''

    def get_background_data(self):
        import json
        try:
            return json.loads(self.background_value) if self.background_value else {}
        except:
            return {}

    def set_background(self, light_val='', dark_val=''):
        import json
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


@app.route('/favicon.ico')
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="url(#g)"/><linearGradient id="g" x1="0" y1="0" x2="32" y2="32"><stop offset="0%" stop-color="#FF3CAC"/><stop offset="100%" stop-color="#2B86C5"/></linearGradient><text x="16" y="23" text-anchor="middle" font-size="20" fill="white" font-family="sans-serif">V</text></svg>'
    from flask import Response
    return Response(svg, mimetype='image/svg+xml')


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
            if user.is_banned:
                flash('Ваш аккаунт заблокирован за нарушение правил')
                return render_template('login.html', form=form)
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
            
            is_draft = request.args.get('draft') == '1'
            if is_draft:
                media_data = request.form.get('media_data')
                draft = Draft(user_id=current_user.id, media_data=media_data, caption=body)
                db.session.add(draft)
                db.session.commit()
                flash('Черновик сохранён')
                return redirect(url_for('drafts'))
            
            result = moderate_post(body, current_user)
            if result == 'USER_BANNED':
                flash('Ваш аккаунт заблокирован за нарушение правил')
                return redirect(url_for('index'))
            if result == 'BLOCKED':
                flash('Пост отклонён: обнаружен неприемлемый контент. Проверьте личные сообщения.')
                return redirect(url_for('index'))
            
            media_data = request.form.get('media_data')
            
            post = Post(body=body, author=current_user)
            db.session.add(post)
            db.session.flush()
            
            import re
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
                import base64
                import io
                from werkzeug.datastructures import FileStorage
                
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
                if file.filename and allowed_file(file.filename):
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    if ext in {'mp4', 'webm', 'mov'}:
                        media_type = 'video'
                    elif ext in {'mp3', 'wav', 'ogg', 'm4a', 'aac'}:
                        media_type = 'audio'
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


# ─── Music Player ──────────────────────────────────────────────────

DEEZER_API = 'https://api.deezer.com'


def deezer_search(query, limit=20):
    import urllib.request, urllib.parse, json
    try:
        url = f'{DEEZER_API}/search?q={urllib.parse.quote(query)}&limit={limit}'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return data.get('data', [])
    except: return []


def deezer_get_track(track_id):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/track/{track_id}', timeout=10) as r:
            return json.loads(r.read())
    except: return None


def deezer_get_album(album_id):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/album/{album_id}', timeout=10) as r:
            return json.loads(r.read())
    except: return None


def deezer_get_artist(artist_id):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/artist/{artist_id}', timeout=10) as r:
            return json.loads(r.read())
    except: return None


def deezer_get_artist_top(artist_id, limit=10):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/artist/{artist_id}/top?limit={limit}', timeout=10) as r:
            return json.loads(r.read()).get('data', [])
    except: return []


def deezer_get_charts(limit=20):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/chart/0/tracks?limit={limit}', timeout=10) as r:
            return json.loads(r.read()).get('data', [])
    except: return []


def deezer_get_playlist(playlist_id):
    import urllib.request, json
    try:
        with urllib.request.urlopen(f'{DEEZER_API}/playlist/{playlist_id}', timeout=10) as r:
            return json.loads(r.read())
    except: return None


def track_from_deezer(d):
    existing = MusicTrack.query.filter_by(deezer_id=d['id']).first()
    if existing: return existing
    t = MusicTrack(
        title=d.get('title', 'Unknown'),
        artist=d.get('artist', {}).get('name', '') if isinstance(d.get('artist'), dict) else '',
        album=d.get('album', {}).get('title', '') if isinstance(d.get('album'), dict) else '',
        duration=d.get('duration', 0),
        preview_url=d.get('preview'),
        cover_url=d.get('album', {}).get('cover_medium', '') if isinstance(d.get('album'), dict) else '',
        deezer_id=d['id'],
        deezer_url=d.get('link'),
        source='deezer'
    )
    db.session.add(t)
    db.session.commit()
    return t


@app.route('/music')
@login_required
def music_home():
    charts = deezer_get_charts(20)
    recent = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(10).all()
    favs = FavoriteTrack.query.filter_by(user_id=current_user.id).order_by(FavoriteTrack.created_at.desc()).limit(10).all()
    playlists = Playlist.query.filter_by(user_id=current_user.id).all()
    return render_template('music_home.html', charts=charts, recent=recent, favs=favs, playlists=playlists, track_from_deezer=track_from_deezer)


@app.route('/music/search')
@login_required
def music_search():
    q = request.args.get('q', '').strip()
    results = deezer_search(q) if q else []
    return render_template('music_search.html', query=q, results=results, track_from_deezer=track_from_deezer)


@app.route('/music/album/<int:album_id>')
@login_required
def music_album(album_id):
    data = deezer_get_album(album_id)
    if not data:
        flash('Альбом не найден')
        return redirect(url_for('music_home'))
    return render_template('music_album.html', album=data, track_from_deezer=track_from_deezer)


@app.route('/music/artist/<int:artist_id>')
@login_required
def music_artist(artist_id):
    data = deezer_get_artist(artist_id)
    top = deezer_get_artist_top(artist_id, 20)
    if not data:
        flash('Исполнитель не найден')
        return redirect(url_for('music_home'))
    return render_template('music_artist.html', artist=data, top_tracks=top, track_from_deezer=track_from_deezer)


@app.route('/music/track/<int:track_id>/play')
@login_required
def music_play_track(track_id):
    data = deezer_get_track(track_id)
    if not data:
        flash('Трек не найден')
        return redirect(url_for('music_home'))
    track = track_from_deezer(data)
    h = ListeningHistory(user_id=current_user.id, track_id=track.id)
    db.session.add(h)
    db.session.commit()
    return jsonify({
        'id': track.id,
        'title': track.title,
        'artist': track.artist,
        'preview_url': track.preview_url or '',
        'cover_url': track.cover_url or '',
        'duration': track.duration
    })


@app.route('/music/local/<int:track_id>')
@login_required
def music_local_track(track_id):
    track = MusicTrack.query.get_or_404(track_id)
    if track.source == 'upload' and track.file_url:
        h = ListeningHistory(user_id=current_user.id, track_id=track.id)
        db.session.add(h)
        db.session.commit()
        return jsonify({
            'id': track.id,
            'title': track.title,
            'artist': track.artist,
            'file_url': track.file_url,
            'cover_url': track.cover_url or '',
            'duration': track.duration
        })
    return jsonify({'error': 'not found'}), 404


@app.route('/music/favorite/<int:track_id>', methods=['POST'])
@login_required
def music_favorite(track_id):
    track = MusicTrack.query.get_or_404(track_id)
    existing = FavoriteTrack.query.filter_by(user_id=current_user.id, track_id=track.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'liked': False})
    f = FavoriteTrack(user_id=current_user.id, track_id=track.id)
    db.session.add(f)
    db.session.commit()
    return jsonify({'liked': True})


# ─── Playlists ─────────────────────────────────────────────────────

@app.route('/music/playlist/create', methods=['GET', 'POST'])
@login_required
def music_create_playlist():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Введите название плейлиста')
            return redirect(url_for('music_create_playlist'))
        p = Playlist(name=name, description=request.form.get('description', ''), user_id=current_user.id)
        db.session.add(p)
        db.session.commit()
        flash('Плейлист создан')
        return redirect(url_for('music_playlist', playlist_id=p.id))
    return render_template('music_create_playlist.html')


@app.route('/music/playlist/<int:playlist_id>')
@login_required
def music_playlist(playlist_id):
    p = Playlist.query.get_or_404(playlist_id)
    if not p.is_public and p.user_id != current_user.id:
        flash('Плейлист приватный')
        return redirect(url_for('music_home'))
    return render_template('music_playlist.html', playlist=p)


@app.route('/music/playlist/<int:playlist_id>/add', methods=['POST'])
@login_required
def music_playlist_add(playlist_id):
    p = Playlist.query.get_or_404(playlist_id)
    if p.user_id != current_user.id:
        return jsonify({'error': 'forbidden'}), 403
    track_id = request.form.get('track_id', type=int)
    if not track_id:
        return jsonify({'error': 'no track'}), 400
    track = MusicTrack.query.get(track_id)
    if not track:
        return jsonify({'error': 'track not found'}), 404
    existing = PlaylistItem.query.filter_by(playlist_id=p.id, track_id=track.id).first()
    if existing:
        return jsonify({'error': 'already in playlist'}), 400
    max_pos = db.session.query(db.func.max(PlaylistItem.position)).filter_by(playlist_id=p.id).scalar() or 0
    item = PlaylistItem(playlist_id=p.id, track_id=track.id, position=max_pos + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/music/playlist/<int:playlist_id>/remove/<int:item_id>', methods=['POST'])
@login_required
def music_playlist_remove(playlist_id, item_id):
    p = Playlist.query.get_or_404(playlist_id)
    if p.user_id != current_user.id:
        abort(403)
    item = PlaylistItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('music_playlist', playlist_id=p.id))


@app.route('/music/playlist/<int:playlist_id>/delete', methods=['POST'])
@login_required
def music_playlist_delete(playlist_id):
    p = Playlist.query.get_or_404(playlist_id)
    if p.user_id != current_user.id:
        abort(403)
    PlaylistItem.query.filter_by(playlist_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    flash('Плейлист удалён')
    return redirect(url_for('music_home'))


@app.route('/music/history')
@login_required
def music_history():
    history = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(50).all()
    return render_template('music_history.html', history=history)


@app.route('/music/favorites')
@login_required
def music_favorites():
    favs = FavoriteTrack.query.filter_by(user_id=current_user.id).order_by(FavoriteTrack.created_at.desc()).all()
    return render_template('music_favorites.html', favs=favs)


@app.route('/music/recommendations')
@login_required
def music_recommendations():
    recent_ids = [h.track_id for h in ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(5).all()]
    genres = set()
    for tid in recent_ids:
        t = MusicTrack.query.get(tid)
        if t and t.deezer_id:
            data = deezer_get_track(t.deezer_id)
            if data and data.get('artist', {}).get('id'):
                genres.add(data['artist']['id'])
    recs = []
    for gid in list(genres)[:3]:
        recs.extend(deezer_get_artist_top(gid, 5))
    if not recs:
        recs = deezer_get_charts(20)
    return render_template('music_recommendations.html', recs=recs, track_from_deezer=track_from_deezer)


@app.route('/music/upload', methods=['GET', 'POST'])
@login_required
def music_upload():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        artist = request.form.get('artist', '').strip()
        file = request.files.get('file')
        if not file or not title:
            flash('Название и файл обязательны')
            return redirect(url_for('music_upload'))
        if cloudinary_configured:
            result = cloudinary.uploader.upload(file, folder='music', resource_type='video', timeout=30)
            file_url = result['secure_url']
        else:
            filename = f'music_{current_user.id}_{int(datetime.utcnow().timestamp())}.mp3'
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            file_url = url_for('uploaded_file', filename=filename, _external=True)
        track = MusicTrack(title=title, artist=artist, file_url=file_url, source='upload', uploaded_by=current_user.id)
        db.session.add(track)
        db.session.commit()
        flash('Трек загружен')
        return redirect(url_for('music_home'))
    return render_template('music_upload.html')


@app.route('/music/player')
@login_required
def music_player():
    """Returns player data: current queue, etc."""
    history = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(20).all()
    tracks = [h.track for h in history if h.track]
    queue = [{'id': t.id, 'title': t.title, 'artist': t.artist, 'preview_url': t.preview_url or '', 'file_url': t.file_url or '', 'cover_url': t.cover_url or '', 'duration': t.duration} for t in tracks]
    return jsonify({'queue': queue})

@app.route('/photo_editor', methods=['GET', 'POST'])
@login_required
def photo_editor():
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
        from PIL import Image, ImageEnhance, ImageFilter
        import io
        import base64
        
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


@app.route('/video_editor', methods=['GET', 'POST'])
@login_required
def video_editor():
    if request.method == 'POST':
        video_url = request.form.get('video_url')
        if video_url:
            return redirect(url_for('create') + '?video=' + video_url)
    return render_template('video_editor.html', editing=True)


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
    posts = [pt.post for pt in post_tags if pt.post]
    return render_template('tag_posts.html', tag=tag, posts=posts)


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
                    # Notify followers
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
                # Notify followers
                followers = current_user.followers.filter_by(status='approved').all()
                for follower in followers:
                    create_notification(follower.id, current_user.id, 'new_story')
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
                # Notify followers
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
            create_notification(post.user_id, current_user.id, 'comment', post_id=post.id, comment_id=comment.id)
            # Notify parent comment author if this is a reply
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


@app.route('/user/<username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    blocked_by_user = current_user.is_authenticated and current_user.is_blocking(user)
    
    if blocked_by_user:
        posts = []
        user_reposts = []
        can_view = False
    elif user.is_private and user != current_user:
        can_view = current_user.is_authenticated and (current_user.is_following(user) or current_user.is_staff)
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
    
    user_shorts = Shorts.query.filter_by(user_id=user.id).order_by(Shorts.created_at.desc()).all()
    shorts_likes = {s.id: s.likes.count() for s in user_shorts}
    shorts_comments = {s.id: s.comments.count() for s in user_shorts}
    
    return render_template('profile.html', user=user, posts=posts, user_reposts=user_reposts, repost_counts=repost_counts, is_following=is_following, is_blocked=is_blocked, is_pending=is_pending, can_view=can_view, pending_count=pending_count, user_shorts=user_shorts, shorts_likes=shorts_likes, shorts_comments=shorts_comments)


@app.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    user = User.query.filter_by(username=username).first_or_404()
    if user != current_user:
        if user.approve_followers:
            current_user.follow(user)
            db.session.commit()
            create_notification(user.id, current_user.id, 'follow_request')
            flash(f'Запрос на подписку отправлен {user.username}. Ожидайте одобрения.')
        else:
            current_user.follow(user)
            db.session.commit()
            create_notification(user.id, current_user.id, 'follow')
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
    create_notification(user.id, current_user.id, 'follow_approved')
    flash(f'Вы одобрили подписку {user.username}')
    return redirect(url_for('follower_requests'))


@app.route('/followers/reject/<username>', methods=['POST'])
@login_required
def reject_follower(username):
    user = User.query.filter_by(username=username).first_or_404()
    current_user.reject_follower(user)
    flash(f'Запрос на подписку от {user.username} отклонён')
    return redirect(url_for('follower_requests'))


@app.route('/notifications')
@login_required
def notifications():
    page = request.args.get('page', 1, type=int)
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    unread_count = Notification.query.filter_by(user_id=current_user.id, read=False).count()
    return render_template('notifications.html', notifications=notifications, unread_count=unread_count)


@app.route('/notifications/read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    notification.read = True
    db.session.commit()
    return redirect(request.referrer or url_for('notifications'))


@app.route('/notifications/read_all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, read=False).update({'read': True})
    db.session.commit()
    return redirect(request.referrer or url_for('notifications'))


@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm()
    if form.validate_on_submit():
        new_username = form.username.data.strip().lstrip('@')
        
        existing_user = User.query.filter(User.username == new_username, User.id != current_user.id).first()
        if existing_user:
            flash('Этот username уже занят другим пользователем')
            return redirect(url_for('edit_profile'))
        
        current_user.username = new_username
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
            
            if cloudinary_configured:
                url = upload_to_cloudinary(file, folder='avatars')
                if url:
                    current_user.avatar_cloudinary_url = url
                    current_user.avatar = url.split('/')[-1].split('.')[0]
            else:
                filename = secure_filename(f"{datetime.now().timestamp}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.avatar = filename
                current_user.avatar_cloudinary_url = None
        
        if form.birthday.data:
            try:
                current_user.birthday = datetime.strptime(form.birthday.data, '%d.%m.%Y').date()
            except ValueError:
                flash('Неверный формат даты. Используйте ДД.ММ.ГГГГГ')
                return render_template('edit_profile.html', form=form)
        
        if form.phone.data:
            phone = ''.join(c for c in form.phone.data if c.isdigit())
            if phone and phone != (current_user.phone or '').replace('+', '').replace(' ', '').replace('-', ''):
                if len(phone) >= 10:
                    import random
                    otp = str(random.randint(100000, 999999))
                    current_user.phone_otp = otp
                    current_user.phone_otp_expires = datetime.utcnow() + timedelta(minutes=5)
                    current_user.phone = phone
                    flash(f'Код подтверждения отправлен на {phone}. Введите код на странице подтверждения.')
                else:
                    flash('Номер телефона слишком короткий')
        
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
        form.phone.data = current_user.phone
        if current_user.birthday:
            form.birthday.data = current_user.birthday.strftime('%d.%m.%Y')
    return render_template('edit_profile.html', form=form)


@app.route('/verify_phone', methods=['GET', 'POST'])
@login_required
def verify_phone():
    if request.method == 'POST':
        otp = request.form.get('otp', '')
        if current_user.phone_otp and current_user.phone_otp == otp:
            if current_user.phone_otp_expires and current_user.phone_otp_expires > datetime.utcnow():
                current_user.phone_verified = True
                current_user.phone_otp = None
                current_user.phone_otp_expires = None
                db.session.commit()
                flash('Номер телефона подтверждён!')
            else:
                flash('Код истёк. Запросите новый код.')
        else:
            flash('Неверный код')
        return redirect(url_for('verify_phone'))
    
    if current_user.phone and not current_user.phone_verified:
        import random
        otp = str(random.randint(100000, 999999))
        current_user.phone_otp = otp
        current_user.phone_otp_expires = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit()
        flash(f'Код {otp} отправлен (демо-режим: код показан в flash-сообщении)')
    
    return render_template('verify_phone.html')


@app.route('/explore')
@app.route('/search')
def explore():
    search_query = request.args.get('q', '')
    search_type = request.args.get('type', 'users')  # users, tags, posts, communities
    blocked_ids = []
    if current_user.is_authenticated:
        blocked_ids = [u.id for u in current_user.blocked]
    
    users = []
    tags = []
    posts = []
    communities = []
    
    if search_query.lstrip('#'):
        if search_type == 'tags':
            tags = Tag.query.filter(
                Tag.name.ilike(f'%{search_query.lstrip("#")}%')
            ).order_by(Tag.created_at.desc()).limit(50).all()
        elif search_type == 'communities':
            communities = Community.query.filter(
                Community.name.ilike(f'%{search_query}%')
            ).order_by(Community.created_at.desc()).limit(50).all()
        elif search_type == 'posts':
            posts = Post.query.filter(
                Post.user_id.notin_(blocked_ids) if blocked_ids else True,
                Post.body.ilike(f'%#{search_query.lstrip("#")}%')
            ).order_by(Post.created_at.desc()).limit(50).all()
            if search_query.lstrip('#'):
                tags = Tag.query.filter(
                    Tag.name.ilike(f'%{search_query.lstrip("#")}%')
                ).order_by(Tag.created_at.desc()).limit(20).all()
        else:
            users = User.query.filter(
                ~User.id.in_(blocked_ids) if blocked_ids else True,
                User.id != current_user.id if current_user.is_authenticated else True,
                User.username.ilike(f'%{search_query.lstrip("@")}%')
            ).order_by(User.created_at.desc()).limit(50).all()
            if search_query.lstrip('#'):
                tags = Tag.query.filter(
                    Tag.name.ilike(f'%{search_query.lstrip("#")}%')
                ).order_by(Tag.created_at.desc()).limit(20).all()
    else:
        if search_type == 'communities':
            communities = Community.query.order_by(Community.created_at.desc()).limit(20).all()
        else:
            users = User.query.filter(
                ~User.id.in_(blocked_ids) if blocked_ids else True,
                User.id != current_user.id if current_user.is_authenticated else True
            ).order_by(User.created_at.desc()).limit(20).all()
    
    return render_template('explore.html', users=users, tags=tags, posts=posts, communities=communities, search_query=search_query, search_type=search_type)


@app.route('/shorts')
@app.route('/sharts')
def shorts():
    shorts_list = Shorts.query.order_by(Shorts.created_at.desc()).limit(20).all()
    audios = ShortsAudio.query.order_by(ShortsAudio.created_at.desc()).limit(20).all()
    return render_template('shorts.html', shorts_list=shorts_list, audios=audios)


@app.route('/shorts/create', methods=['GET', 'POST'])
@login_required
def create_shorts():
    if request.method == 'POST':
        video = request.files.get('video')
        media_data = request.form.get('media_data')
        caption = request.form.get('body') or request.form.get('caption', '')
        audio_id = request.form.get('audio_id')
        
        if media_data:
            import base64, io
            from werkzeug.datastructures import FileStorage
            header, data = media_data.split(',', 1)
            binary = base64.b64decode(data)
            file = FileStorage(io.BytesIO(binary), filename=f'shorts_{datetime.now().timestamp()}.jpg', content_type='image/jpeg')
            if cloudinary_configured:
                url = upload_to_cloudinary(file, folder='shorts')
            else:
                filename = secure_filename(f"shorts_{current_user.id}_{int(datetime.utcnow().timestamp())}.jpg")
                with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'wb') as f:
                    f.write(binary)
                url = url_for('uploaded_file', filename=filename, _external=True)
            shorts = Shorts(video_url=url, caption=caption, user_id=current_user.id, audio_id=int(audio_id) if audio_id else None)
            db.session.add(shorts)
            db.session.commit()
            flash('Shorts опубликован!')
            return redirect(url_for('shorts'))
        
        if not video or video.filename == '':
            flash('Выберите видео')
            return redirect(url_for('create_shorts'))
        
        try:
            ext = video.filename.rsplit('.', 1)[-1].lower() if '.' in video.filename else 'mp4'
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    video, folder='shorts', resource_type='video',
                    timeout=30
                )
                video_url = result['secure_url']
            else:
                filename = f'shorts_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}'
                video.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                video_url = url_for('uploaded_file', filename=filename)
            
            shorts = Shorts(
                video_url=video_url,
                caption=caption,
                user_id=current_user.id,
                audio_id=int(audio_id) if audio_id else None
            )
            db.session.add(shorts)
            db.session.commit()
            flash('Shorts опубликован!')
            return redirect(url_for('shorts'))
        except Exception as e:
            app.logger.error(f"Error creating shorts: {e}")
            flash('Ошибка при загрузке видео')
            return redirect(url_for('create_shorts'))
    
    audios = ShortsAudio.query.order_by(ShortsAudio.created_at.desc()).all()
    return render_template('create_shorts.html', audios=audios)


@app.route('/shorts/<int:shorts_id>', methods=['GET', 'POST'])
def view_shorts(shorts_id):
    shorts_video = Shorts.query.get_or_404(shorts_id)
    
    if request.method == 'POST' and current_user.is_authenticated:
        comment_body = request.form.get('body')
        if comment_body:
            comment = ShortsComment(
                body=comment_body,
                user_id=current_user.id,
                shorts_id=shorts_id
            )
            db.session.add(comment)
            db.session.commit()
    
    comments = shorts_video.comments.order_by(ShortsComment.created_at.desc()).all()
    return render_template('view_shorts.html', shorts=shorts_video, comments=comments)


@app.route('/shorts/like/<int:shorts_id>', methods=['POST'])
@login_required
def like_shorts(shorts_id):
    shorts_video = Shorts.query.get_or_404(shorts_id)
    existing_like = ShortsLike.query.filter_by(user_id=current_user.id, shorts_id=shorts_id).first()
    
    if existing_like:
        db.session.delete(existing_like)
    else:
        like = ShortsLike(user_id=current_user.id, shorts_id=shorts_id)
        db.session.add(like)
    
    db.session.commit()
    return jsonify({'likes': shorts_video.likes.count()})


@app.route('/shorts/<int:shorts_id>/react', methods=['POST'])
@login_required
def react_shorts(shorts_id):
    shorts_video = Shorts.query.get_or_404(shorts_id)
    emoji = request.form.get('emoji', '❤️')
    
    existing = ShortsReaction.query.filter_by(user_id=current_user.id, shorts_id=shorts_id, emoji=emoji).first()
    if existing:
        db.session.delete(existing)
    else:
        reaction = ShortsReaction(user_id=current_user.id, shorts_id=shorts_id, emoji=emoji)
        db.session.add(reaction)
    
    db.session.commit()
    return jsonify({'status': 'ok'})


@app.route('/shorts/<int:shorts_id>/delete', methods=['POST'])
@login_required
def delete_shorts(shorts_id):
    shorts_video = Shorts.query.get_or_404(shorts_id)
    if shorts_video.user_id != current_user.id:
        abort(403)
    try:
        ShortsLike.query.filter_by(shorts_id=shorts_id).delete()
        ShortsComment.query.filter_by(shorts_id=shorts_id).delete()
        ShortsReaction.query.filter_by(shorts_id=shorts_id).delete()
        db.session.delete(shorts_video)
        db.session.commit()
        flash('Shorts удалён')
    except Exception as e:
        app.logger.error(f"Delete shorts error: {e}")
        db.session.rollback()
        flash('Ошибка при удалении')
    return redirect(request.referrer or url_for('user_profile', username=current_user.username))


@app.route('/shorts/audio/upload', methods=['GET', 'POST'])
@login_required
def upload_shorts_audio():
    if request.method == 'POST':
        audio = request.files.get('audio')
        title = request.form.get('title', 'Original audio')
        
        if audio:
            if cloudinary_configured:
                result = cloudinary.uploader.upload(
                    audio, folder='shorts_audio', resource_type='video',
                    timeout=30
                )
                audio_url = result['secure_url']
            else:
                filename = f'saudio_{current_user.id}_{int(datetime.utcnow().timestamp())}.mp3'
                audio.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                audio_url = url_for('uploaded_file', filename=filename)
            
            shorts_audio = ShortsAudio(
                title=title,
                audio_url=audio_url,
                user_id=current_user.id
            )
            db.session.add(shorts_audio)
            db.session.commit()
            return redirect(url_for('create_shorts'))
    
    return render_template('upload_shorts_audio.html')


@app.route('/shorts/audio/search_freesound')
@login_required
def search_freesound():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 2:
        return jsonify({'results': []})
    
    import urllib.request
    import urllib.parse
    import json
    
    try:
        url = f'https://freesound.org/apiv2/search/text/?query={urllib.parse.quote(query)}&token={FREESOUND_API_KEY}&page=1&page_size=12&fields=id,name,previews,duration,username,tags,description'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        results = []
        for s in data.get('results', []):
            previews = s.get('previews', {})
            preview_url = previews.get('preview-hq-mp3') or previews.get('preview-lq-mp3')
            if preview_url:
                results.append({
                    'id': s['id'],
                    'name': s['name'],
                    'username': s.get('username', ''),
                    'duration': s.get('duration', 0),
                    'preview_url': preview_url,
                    'tags': s.get('tags', [])[:5],
                    'description': s.get('description', '')[:200]
                })
        return jsonify({'results': results})
    except Exception as e:
        app.logger.error(f"FreeSound search error: {e}")
        return jsonify({'error': str(e), 'results': []}), 500


@app.route('/shorts/audio/add_freesound', methods=['POST'])
@login_required
def add_freesound_audio():
    name = request.form.get('name', '').strip()
    preview_url = request.form.get('preview_url', '').strip()
    duration = request.form.get('duration', 0, type=int)
    
    if not name or not preview_url:
        return jsonify({'error': 'Missing fields'}), 400
    
    existing = ShortsAudio.query.filter_by(audio_url=preview_url).first()
    if existing:
        return jsonify({'id': existing.id, 'title': existing.title, 'message': 'Уже добавлено'})
    
    audio = ShortsAudio(
        title=name,
        audio_url=preview_url,
        duration=duration,
        user_id=current_user.id
    )
    db.session.add(audio)
    db.session.commit()
    
    return jsonify({'id': audio.id, 'title': audio.title, 'message': 'Добавлено!'})


@app.route('/photos')
@login_required
def photos():
    user_media = Media.query.join(Post).filter(Post.user_id == current_user.id).order_by(Post.created_at.desc()).all()
    return render_template('photos.html', user_media=user_media)


@app.route('/recommendations')
@login_required
def recommendations():
    blocked_ids = [u.id for u in current_user.blocked]
    following_ids = [u.id for u in current_user.followed]
    
    user_interests = set(current_user.interests.lower().split()) if current_user.interests else set()
    
    recommended_users = []
    for user in User.query.filter(
        ~User.id.in_(blocked_ids),
        ~User.id.in_(following_ids),
        User.id != current_user.id
    ).limit(50).all():
        score = 0
        user_interests_set = set(user.interests.lower().split()) if user.interests else set()
        common_interests = user_interests & user_interests_set
        score += len(common_interests) * 10
        
        for follower in user.followers.all():
            if follower.id in following_ids:
                score += 5
        
        if score > 0:
            recommended_users.append((score, user))
    
    recommended_users.sort(key=lambda x: x[0], reverse=True)
    recommended_users = [u for _, u in recommended_users[:10]]
    
    member_communities = [cm.community_id for cm in current_user.community_memberships.filter_by(status='approved').all()]
    
    recommended_communities = []
    for comm in Community.query.filter(
        ~Community.id.in_(member_communities) if member_communities else True
    ).limit(30).all():
        score = 0
        comm_interests = set(comm.description.lower().split()) if comm.description else set()
        common = user_interests & comm_interests
        score += len(common) * 10
        score += comm.members.count()
        
        if score > 0:
            recommended_communities.append((score, comm))
    
    recommended_communities.sort(key=lambda x: x[0], reverse=True)
    recommended_communities = [c for _, c in recommended_communities[:5]]
    
    interest_posts = []
    if user_interests:
        for post in Post.query.filter(
            Post.user_id.notin_(blocked_ids + [current_user.id]),
            Post.community_id == None
        ).limit(100).all():
            if post.body:
                post_words = set(post.body.lower().split())
                common = user_interests & post_words
                if common:
                    interest_posts.append((len(common), post))
    
    interest_posts.sort(key=lambda x: x[0], reverse=True)
    interest_posts = [p for _, p in interest_posts[:10]]
    
    saved_posts_user_ids = [s.post.user_id for s in SavedPost.query.filter(
        SavedPost.user_id != current_user.id
    ).all() if s.post]
    from collections import Counter
    user_counter = Counter(saved_posts_user_ids)
    similar_users = [User.query.get(uid) for uid, _ in user_counter.most_common(5) if uid not in blocked_ids and uid != current_user.id]
    
    saved_tags = [pt.tag.name for s in SavedPost.query.filter_by(user_id=current_user.id).all() if s.post]
    tag_post_scores = []
    for post in Post.query.filter(
        Post.user_id.notin_(blocked_ids + [current_user.id])
    ).limit(100).all():
        if post.body:
            post_tags = set(re.findall(r'#(\w+)', post.body.lower()))
            saved_tags_set = set(saved_tags)
            common = post_tags & saved_tags_set
            if common:
                tag_post_scores.append((len(common), post))
    
    tag_post_scores.sort(key=lambda x: x[0], reverse=True)
    posts_from_saved_tags = [p for _, p in tag_post_scores[:10]]
    
    return render_template('recommendations.html', 
                        recommended_users=recommended_users,
                        recommended_communities=recommended_communities,
                        interest_posts=interest_posts,
                        similar_users=similar_users,
                        posts_from_saved_tags=posts_from_saved_tags)


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
    
    # Групповые чаты
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
    
    # Filter out conversations with deleted users
    conversations = [c for c in conversations if c.get('user')]
    
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
    
    # Find direct chat between current_user and other_user
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
        
        app.logger.info(f"Files: {request.files}")
        
        if 'media' in request.files:
            file = request.files['media']
            app.logger.info(f"File: {file.filename}")
            if file.filename and allowed_file(file.filename):
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
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
                enqueue_webhook_dispatch(msg.id)
                create_notification(other_user.id, current_user.id, 'message', message_id=msg.id)
                app.logger.info(f"Message saved with media: {media_url}")
            except Exception as e:
                app.logger.error(f"Message error: {e}")
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
        app.logger.error(f"Load messages error: {e}")
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
    
    followed_ids = [u.id for u in current_user.followed]
    bot_ids = [u.id for u in User.query.filter_by(is_bot=True).all()]
    user_ids = set(followed_ids + bot_ids)
    user_ids.discard(current_user.id)
    users = User.query.filter(User.id.in_(user_ids)).all()
    return render_template('create_chat.html', users=users)


from faster_whisper import WhisperModel
import tempfile

model = None

def get_whisper_model():
    global model
    if model is None:
        model = WhisperModel("base", device="cpu", compute_type="int8")
    return model


@app.route('/messages/<username>/voice', methods=['POST'])
@login_required
def send_voice(username):
    other_user = User.query.filter_by(username=username).first_or_404()
    
    if current_user.is_blocking(other_user) or other_user.is_blocking(current_user):
        return 'Blocked', 403
    
    app.logger.info(f"Voice message from {current_user.username} to {username}")
    app.logger.info(f"Files: {request.files}")
    app.logger.info(f"Voice file: {request.files.get('voice')}")
    
    if 'voice' not in request.files:
        app.logger.error("No voice file in request")
        return {'error': 'No voice file'}, 400
    
    voice_file = request.files['voice']
    if not voice_file.filename:
        app.logger.error("Empty filename")
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
            voice_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        app.logger.error(f"Voice message error: {e}")
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
            video_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        app.logger.error(f"Video message error: {e}")
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
        
        app.logger.info(f"Files in request: {list(request.files.keys())}")
        
        if 'media' in request.files:
                file = request.files['media']
                file_len = file.seek(0, 2)
                file.seek(0)
                app.logger.info(f"File: '{file.filename}', content_type: {file.content_type}, size: {file_len}, allowed: {allowed_file(file.filename) if file.filename else False}")
                if file.filename and file_len > 0 and allowed_file(file.filename):
                    try:
                        media_url = None
                        # Determine media type based on file extension
                        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                        if ext in {'mp4', 'webm', 'mov'}:
                            media_type = 'video'
                        elif ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
                            media_type = 'image'
                        else:
                            media_type = 'document'
                        
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
                            filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
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
                enqueue_webhook_dispatch(msg.id)
                app.logger.warning(f"Message and media saved successfully!")
            except Exception as e:
                app.logger.error(f"Chat message error: {e}")
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
            voice_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        app.logger.error(f"Chat voice message error: {e}")
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
            video_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        app.logger.error(f"Chat video message error: {e}")
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
    
    media_type = request.args.get('type', 'photos')  # photos, docs, links
    
    photos_videos = []
    documents = []
    links = []
    
    # Get all messages in chat
    messages = Message.query.filter_by(chat_id=chat_id).all()
    
    for msg in messages:
        # Check for media attachments
        if msg.medias:
            for media in msg.medias:
                if media.media_type in ['image', 'video']:
                    photos_videos.append({'media': media, 'message': msg})
                else:
                    documents.append({'media': media, 'message': msg})
        
        # Check for links in message body
        if msg.body:
            import re
            urls = re.findall(r'(https?://[^\s]+)', msg.body)
            for url in urls:
                links.append({'url': url, 'message': msg})
    
    # Remove duplicates from links
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
    
    # Check if they have a direct chat
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
    
    # Get messages between these two users
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
    
    # Find direct chat between current_user and other_user
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
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
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
        
        # Handle background
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
                # Handle image uploads for both themes
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
                                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                                bg_data[theme] = filename
                # Fallback to text input for existing URLs
                light_val = request.form.get('background_value_light', '').strip()
                dark_val = request.form.get('background_value_dark', '').strip()
                if light_val:
                    bg_data['light'] = light_val
                if dark_val:
                    bg_data['dark'] = dark_val
            else:
                # color or gradient
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
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    chat.avatar = filename
        
        db.session.commit()
        flash('Чат обновлён')
        return redirect(url_for('chat_view', chat_id=chat_id))
    
    return render_template('chat_edit.html', chat=chat, bg_data=chat.get_background_data() if chat else {})


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
                        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg'} else 'image'
                        media = Media(filename=filename, media_type=media_type, post=post)
                        db.session.add(media)
                except Exception as e:
                    app.logger.error(f"Media upload error: {e}")
        
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
        columns = get_table_columns('user')
        
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
        if not column_exists('message', 'post_id'):
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


@app.route('/bots')
@login_required
def my_bots():
    bots = User.query.filter_by(is_bot=True, creator_id=current_user.id).all()
    return render_template('bots.html', bots=bots)


@app.route('/bot-docs')
def bot_docs():
    return render_template('bot_docs.html')


def staff_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_staff:
            abort(403)
        return f(*args, **kwargs)
    return decorated


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
        import json
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
            from werkzeug.utils import secure_filename
            file = form.avatar.data
            filename = f"bot_{bot.id}_{secure_filename(file.filename)}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
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


# ─── Bot API ────────────────────────────────────────────────────────

def bot_json_response(data, status=200):
    return jsonify({"ok": status == 200, "result": data} if status == 200 else {"ok": False, "error_code": status, "description": data}), status


def resolve_chat(chat_id):
    """chat_id может быть int (id чата) или str с @ (username пользователя)"""
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
    """Находит или создаёт direct chat между двумя пользователями"""
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


def resolve_community(slug_or_id):
    """community_id может быть slug (строка) или id (число)"""
    if isinstance(slug_or_id, str) and not slug_or_id.isdigit():
        return Community.query.filter_by(slug=slug_or_id).first()
    return Community.query.get(int(slug_or_id))


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
                        media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg'} else 'image'
                        media = Media(filename=filename, cloudinary_url=url, media_type=media_type, post=post)
                        db.session.add(media)
                else:
                    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    media_type = 'video' if ext in {'mp4', 'webm', 'mov'} else 'audio' if ext in {'mp3', 'wav', 'ogg'} else 'image'
                    media = Media(filename=filename, media_type=media_type, post=post)
                    db.session.add(media)
            except Exception as e:
                app.logger.error(f"Bot sendPost media upload error: {e}")
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


if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, host='0.0.0.0', allow_unsafe_werkzeug=True)


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
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        
        stream = ffmpeg.input(input_path, ss=start_time)
        
        if duration:
            stream = ffmpeg.output(stream, output_path, t=duration, **{'preset': quality})
        else:
            stream = ffmpeg.output(stream, output_path, **{'preset': quality})
        
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        
        return output_filename
    except Exception as e:
        app.logger.error(f"Video processing error: {e}")
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
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        
        stream = ffmpeg.input(video_path, ss=timestamp)
        stream = ffmpeg.output(stream, output_path, vframes=1, format='image2', vcodec='mjpeg')
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)
        
        return output_filename
    except Exception as e:
        app.logger.error(f"Thumbnail generation error: {e}")
        return None


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
        app.logger.error(f"Video process route error: {e}")
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
        app.logger.error(f"Thumbnail route error: {e}")
        return jsonify({'error': str(e)}), 500


with app.app_context():
    try:
        from sqlalchemy import text
        
        if not column_exists('user', 'avatar_cloudinary_url'):
            db.session.execute(text('ALTER TABLE user ADD COLUMN avatar_cloudinary_url VARCHAR(500)'))
            db.session.commit()
    except Exception as e:
        app.logger.info(f"Migration avatar_cloudinary_url: {e}")
    
    try:
        admin = User.query.filter_by(username='botadmin').first()
        if admin and not admin.is_staff:
            admin.is_staff = True
            db.session.commit()
            app.logger.info("Promoted botadmin to staff")
    except Exception as e:
        app.logger.info(f"Staff promotion: {e}")

    try:
        user = User.query.filter_by(username='Sergqmts').first()
        if user and not user.is_staff:
            user.is_staff = True
            db.session.commit()
            app.logger.info("Promoted Sergqmts to staff")
    except Exception as e:
        app.logger.info(f"Staff promotion Sergqmts: {e}")


@app.context_processor
def inject_utils():
    def get_avatar_url(user):
        if user is None:
            return None
        if hasattr(user, 'avatar_cloudinary_url') and user.avatar_cloudinary_url:
            return user.avatar_cloudinary_url
        if hasattr(user, 'avatar') and user.avatar and user.avatar != 'default.png':
            return url_for('uploaded_file', filename=user.avatar)
        return None
    return dict(get_avatar_url=get_avatar_url)


@app.template_filter('avatar_url')
def avatar_url_filter(user):
    if user is None:
        return None
    if hasattr(user, 'avatar_cloudinary_url') and user.avatar_cloudinary_url:
        return user.avatar_cloudinary_url
    if hasattr(user, 'avatar') and user.avatar and user.avatar != 'default.png':
        return url_for('uploaded_file', filename=user.avatar)
    return None

@app.template_filter('timeago')
def timeago_filter(dt):
    if dt is None:
        return ''
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return 'только что'
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f'{minutes} мин назад'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours} ч назад'
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f'{days} дн назад'
    else:
        return dt.strftime('%d %b %Y')


# Manually exempt specific AJAX endpoints from CSRF protection
# These endpoints receive CSRF token in FormData from JavaScript
csrf._exempt_views.add('send_voice')
csrf._exempt_views.add('send_chat_voice')
csrf._exempt_views.add('forward_post')
csrf._exempt_views.add('forward_message')
