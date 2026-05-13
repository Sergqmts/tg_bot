from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from flask_socketio import emit, join_room, leave_room

from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from socket import gethostname, gethostbyname
import os
import cloudinary
import cloudinary.uploader
import tempfile
import io

from extensions import db, login_manager, socketio, csrf
from helpers import (
    cloudinary_configured, FREESOUND_API_KEY,
    allowed_file, upload_to_cloudinary, get_cloudinary_url, get_avatar_url,
    generate_bot_token, check_nsfw_text, get_moderation_bot,
    moderate_post, get_or_create_dm, create_notification,
    column_exists, get_table_columns,
    _webhook_queue, enqueue_webhook_dispatch, process_webhook_queue,
)

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


cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
cloud_key = os.environ.get('CLOUDINARY_API_KEY')
cloud_secret = os.environ.get('CLOUDINARY_API_SECRET')
app.logger.info(f"Cloudinary config: cloud_name={cloud_name}, has_key=bool(cloud_key), has_secret=bool(cloud_secret)")
if cloudinary_configured:
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=cloud_key,
        api_secret=cloud_secret,
        secure=True
    )

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
from models import *

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




with app.app_context():
    init_db()

login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите для доступа'

socketio.init_app(app, cors_allowed_origins="*", manage_session=False, async_mode='threading')

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

csrf.init_app(app)



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
        if 'forwarded_from_id' not in columns:
            try:
                db.session.execute(text("ALTER TABLE message ADD COLUMN forwarded_from_id INTEGER REFERENCES user(id)"))
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














@app.route('/favicon.ico')
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="url(#g)"/><linearGradient id="g" x1="0" y1="0" x2="32" y2="32"><stop offset="0%" stop-color="#FF3CAC"/><stop offset="100%" stop-color="#2B86C5"/></linearGradient><text x="16" y="23" text-anchor="middle" font-size="20" fill="white" font-family="sans-serif">V</text></svg>'
    from flask import Response
    return Response(svg, mimetype='image/svg+xml')


# Register all route handlers from routes/ package
from routes import register_all_routes
register_all_routes(app)

























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





if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, host='0.0.0.0', allow_unsafe_werkzeug=True)





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

    try:
        info = db.session.execute(text('SELECT data_type FROM information_schema.columns WHERE table_name = \'music_track\' AND column_name = \'deezer_id\'')).fetchone()
        if info and info[0] == 'integer':
            db.session.execute(text('ALTER TABLE music_track ALTER COLUMN deezer_id TYPE BIGINT'))
            db.session.commit()
            app.logger.info("Migrated music_track.deezer_id from INTEGER to BIGINT")
    except Exception as e:
        app.logger.info(f"Migration deezer_id BIGINT: {e}")

    try:
        if not column_exists('post', 'music_track_id'):
            db.session.execute(text('ALTER TABLE post ADD COLUMN music_track_id INTEGER REFERENCES music_track(id)'))
            db.session.commit()
            app.logger.info("Migrated: added post.music_track_id")
    except Exception as e:
        app.logger.info(f"Migration post.music_track_id: {e}")

    try:
        if not User.query.filter_by(username='NewsBot').first():
            bot = User(
                username='NewsBot',
                email='newsbot@vibe.local',
                password='', is_bot=True,
                bot_token='657313327:peqDnhI7QJEPa3yHzwH_ycugww-0BgNgHbvCyBiTd_A',
                bot_commands='sendPost', can_join_groups=True,
                is_staff=True, email_confirmed=True
            )
            db.session.add(bot)
            db.session.flush()
            app.logger.info("Created NewsBot user")
        else:
            bot = User.query.filter_by(username='NewsBot').first()
    except Exception as e:
        app.logger.info(f"NewsBot creation: {e}")
        bot = None

    try:
        if bot:
            news = Community.query.filter_by(slug='news').first()
            if not news:
                news = Community(name='Новости проекта', slug='news', description='Обновления и нововведения VIBE', creator_id=bot.id, is_private=False)
                db.session.add(news)
                db.session.flush()
                app.logger.info("Created news community")
            member = CommunityMember.query.filter_by(community_id=news.id, user_id=bot.id).first()
            if not member:
                member = CommunityMember(community_id=news.id, user_id=bot.id, role='admin', status='approved')
                db.session.add(member)
                db.session.flush()
                app.logger.info("Added NewsBot as admin of news community")
            db.session.commit()
    except Exception as e:
        app.logger.info(f"News community setup: {e}")


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
