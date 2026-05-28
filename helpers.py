import os
import hashlib
import secrets
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename
from extensions import db
from models import User, Notification, Message, Chat, ChatMember, ModerationLog, FeatureAnnouncement

cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME')
cloud_key = os.environ.get('CLOUDINARY_API_KEY')
cloud_secret = os.environ.get('CLOUDINARY_API_SECRET')
cloudinary_configured = cloud_name and cloud_key and cloud_secret

FREESOUND_API_KEY = os.environ.get('FREESOUND_API_KEY', '')

_webhook_queue = []


def send_password_reset_email(user, reset_url):
    """Отправляет письмо со ссылкой сброса пароля через Gmail SMTP."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    mail_sender = os.environ.get('MAIL_SENDER', '')
    mail_password = os.environ.get('MAIL_PASSWORD', '')

    if not mail_sender or not mail_password:
        current_app.logger.warning("MAIL_SENDER / MAIL_PASSWORD not set — password reset email not sent")
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Сброс пароля — Vibe'
        msg['From'] = mail_sender
        msg['To'] = user.email

        html = (
            f'<p>Привет, {user.username}!</p>'
            f'<p>Для сброса пароля перейди по ссылке:</p>'
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
            f'<p>Ссылка действует 24 часа.</p>'
            f'<p>Если ты не запрашивал(а) сброс пароля — просто проигнорируй это письмо.</p>'
        )
        msg.attach(MIMEText(html, 'html', 'utf-8'))

        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(mail_sender, mail_password)
            server.sendmail(mail_sender, user.email, msg.as_string())

        return True
    except Exception as e:
        current_app.logger.error(f"SMTP error: {e}")
        return False


def profile_completion(user):
    """Возвращает процент заполненности профиля (0–100)."""
    fields = [
        user.avatar_cloudinary_url,
        user.bio,
        user.occupation,
        user.location,
        user.interests,
        (user.phone and user.phone_verified),
    ]
    filled = sum(1 for f in fields if f)
    return int(filled / len(fields) * 100)


def generate_bot_token():
    return f"{secrets.randbelow(900000000) + 100000000}:{secrets.token_urlsafe(32)}"


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def upload_to_cloudinary(file, folder='social'):
    if not file.filename:
        return None
    if cloudinary_configured:
        import cloudinary.uploader
        try:
            result = cloudinary.uploader.upload(
                file,
                folder=folder,
                resource_type='auto',
                timeout=120,
            )
            return result['secure_url']
        except Exception as e:
            current_app.logger.error("Cloudinary upload failed (folder=%s): %s", folder, e)
            return None
    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
    file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
    return filename


def get_cloudinary_url(public_id, resource_type='image'):
    if not public_id:
        return None
    if cloudinary_configured:
        import cloudinary
        return cloudinary.CloudinaryImage(public_id).build_url(
            width=800,
            crop='scale',
            quality='auto',
            fetch_format='auto'
        )
    return '/media/' + public_id


def get_avatar_url(user):
    if user is None:
        return None
    if hasattr(user, 'avatar_cloudinary_url') and user.avatar_cloudinary_url:
        return user.avatar_cloudinary_url
    if hasattr(user, 'avatar') and user.avatar and user.avatar != 'default.png':
        from flask import url_for
        return url_for('uploaded_file', filename=user.avatar)
    return None


def column_exists(table_name, column_name):
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


def get_or_create_dm(user_a, user_b):
    from sqlalchemy.orm import aliased
    cm2 = aliased(ChatMember)
    chat = Chat.query.join(ChatMember).filter(ChatMember.user_id == user_a.id).join(cm2, cm2.chat_id == Chat.id).filter(
        cm2.user_id == user_b.id, Chat.type == 'direct'
    ).first()
    if not chat:
        chat = Chat(name="DM", type='direct', creator_id=user_a.id)
        db.session.add(chat)
        db.session.flush()
        for uid in [user_a.id, user_b.id]:
            if not ChatMember.query.filter_by(chat_id=chat.id, user_id=uid).first():
                db.session.add(ChatMember(chat_id=chat.id, user_id=uid, role='member'))
    return chat


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
        current_app.logger.error(f"Notification error: {e}")


def enqueue_webhook_dispatch(message_id):
    _webhook_queue.append(message_id)


def process_webhook_queue():
    while _webhook_queue:
        msg_id = _webhook_queue.pop(0)
        with current_app.app_context():
            try:
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
                current_app.logger.error(f"Webhook dispatch error for msg {msg_id}: {e}")


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
            },
            'chat': {
                'id': chat.id if chat else recipient.id,
                'type': 'private' if recipient else 'group',
            }
        }
    }
    if chat:
        update['message']['chat']['title'] = chat.name
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
        current_app.logger.warning(f"Webhook to {bot.webhook_url} failed: {e}")


def announce_pending_features():
    pending = FeatureAnnouncement.query.filter_by(is_posted=False).all()
    for feature in pending:
        feature.post_to_news()


def send_welcome_dm(new_user):
    """Send a welcome DM from NewsBot to a newly registered user."""
    try:
        bot = User.query.filter_by(username='NewsBot').first()
        if not bot:
            return False

        welcome_text = (
            f"👋 Привет, @{new_user.username}! Добро пожаловать в **VIBE** — социальную сеть нового поколения.\n\n"
            "Вот что ты можешь делать прямо сейчас:\n\n"
            "📝 **Посты** — публикуй фото, видео, текст. Лайки, реакции, репосты, сохранения.\n"
            "📖 **Stories** — исчезающие истории на 24 часа с реакциями и комментариями.\n"
            "🎬 **Shorts** — короткие видео с фоновой музыкой и встроенным редактором.\n"
            "📸 **Фоторедактор** — фильтры, яркость, контраст, рамки и стикеры перед публикацией.\n"
            "💬 **Чаты** — личные и групповые переписки, голосовые и видеосообщения.\n"
            "📞 **Звонки** — голосовые и видеозвонки прямо в приложении (WebRTC).\n"
            "🎶 **Музыка** — плеер с Deezer, плейлисты и рекомендации.\n"
            "👥 **Сообщества** — создавай сообщества, организуй события с RSVP.\n"
            "🤖 **Боты** — создай своего бота с Telegram-совместимым API.\n\n"
            "Если есть вопросы — пиши мне! Команды:\n"
            "/help — список команд\n"
            "/bug — сообщить об ошибке\n"
            "/feedback — оставить отзыв\n\n"
            "Удачи! 🚀"
        )

        # Get or create DM chat between bot and new user
        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(
            ChatMember.user_id == bot.id
        ).join(cm2, cm2.chat_id == Chat.id).filter(
            cm2.user_id == new_user.id, Chat.type == 'direct'
        ).first()

        if not chat:
            chat = Chat(name='DM', type='direct', creator_id=bot.id)
            db.session.add(chat)
            db.session.flush()
            for uid in [bot.id, new_user.id]:
                if not ChatMember.query.filter_by(chat_id=chat.id, user_id=uid).first():
                    db.session.add(ChatMember(chat_id=chat.id, user_id=uid, role='member'))
            db.session.flush()

        msg = Message(body=welcome_text, sender_id=bot.id, recipient_id=new_user.id, chat_id=chat.id)
        db.session.add(msg)
        db.session.commit()
        current_app.logger.info(f"Welcome DM sent to @{new_user.username}")
        return True
    except Exception as e:
        current_app.logger.error(f"send_welcome_dm error: {e}")
        db.session.rollback()
        return False


def handle_newsbot_command(bot, user, text):
    """Process a command or message sent to NewsBot and reply in DM."""
    try:
        text = (text or '').strip()
        cmd = text.split()[0].lower() if text else ''

        if cmd in ('/start', '/help', 'help', 'помощь', 'хелп'):
            reply = (
                "🤖 **NewsBot — помощник VIBE**\n\n"
                "Доступные команды:\n"
                "/help — эта справка\n"
                "/bug [описание] — сообщить об ошибке\n"
                "/feedback [текст] — оставить отзыв или предложение\n\n"
                "Или просто напиши — я передам сообщение команде."
            )
        elif cmd == '/bug':
            desc = text[4:].strip() or '(описание не указано)'
            _forward_to_admins(bot, user, f"🐛 **Баг от @{user.username}:**\n{desc}")
            reply = "✅ Спасибо! Мы получили твой баг-репорт и разберёмся как можно скорее."
        elif cmd == '/feedback':
            desc = text[9:].strip() or '(текст не указан)'
            _forward_to_admins(bot, user, f"💬 **Отзыв от @{user.username}:**\n{desc}")
            reply = "✅ Спасибо за отзыв! Это помогает нам делать VIBE лучше."
        else:
            # Generic message — forward to admins as feedback
            if text:
                _forward_to_admins(bot, user, f"📨 **Сообщение от @{user.username}:**\n{text}")
            reply = (
                "Привет! Я получил твоё сообщение и передам его команде.\n\n"
                "Если хочешь сообщить об ошибке — напиши /bug [описание]\n"
                "Отзыв или предложение — /feedback [текст]"
            )

        # Send reply back to user
        from sqlalchemy.orm import aliased
        cm2 = aliased(ChatMember)
        chat = Chat.query.join(ChatMember).filter(
            ChatMember.user_id == bot.id
        ).join(cm2, cm2.chat_id == Chat.id).filter(
            cm2.user_id == user.id, Chat.type == 'direct'
        ).first()

        if not chat:
            chat = Chat(name='DM', type='direct', creator_id=bot.id)
            db.session.add(chat)
            db.session.flush()
            for uid in [bot.id, user.id]:
                if not ChatMember.query.filter_by(chat_id=chat.id, user_id=uid).first():
                    db.session.add(ChatMember(chat_id=chat.id, user_id=uid, role='member'))
            db.session.flush()

        msg = Message(body=reply, sender_id=bot.id, recipient_id=user.id, chat_id=chat.id)
        db.session.add(msg)
        db.session.commit()
        return True
    except Exception as e:
        current_app.logger.error(f"handle_newsbot_command error: {e}")
        db.session.rollback()
        return False


def _forward_to_admins(bot, from_user, text):
    """Forward a feedback/bug report to all staff users via DM."""
    try:
        admins = User.query.filter_by(is_staff=True, is_bot=False).all()
        for admin in admins:
            from sqlalchemy.orm import aliased
            cm2 = aliased(ChatMember)
            chat = Chat.query.join(ChatMember).filter(
                ChatMember.user_id == bot.id
            ).join(cm2, cm2.chat_id == Chat.id).filter(
                cm2.user_id == admin.id, Chat.type == 'direct'
            ).first()

            if not chat:
                chat = Chat(name='DM', type='direct', creator_id=bot.id)
                db.session.add(chat)
                db.session.flush()
                for uid in [bot.id, admin.id]:
                    if not ChatMember.query.filter_by(chat_id=chat.id, user_id=uid).first():
                        db.session.add(ChatMember(chat_id=chat.id, user_id=uid, role='member'))
                db.session.flush()

            msg = Message(body=text, sender_id=bot.id, recipient_id=admin.id, chat_id=chat.id)
            db.session.add(msg)
        db.session.flush()
        current_app.logger.info(f"Forwarded to {len(admins)} admin(s)")
    except Exception as e:
        current_app.logger.error(f"_forward_to_admins error: {e}")
        raise
