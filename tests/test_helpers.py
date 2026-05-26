from unittest.mock import MagicMock, patch
from extensions import db
from models import User, Notification, Chat, ChatMember, ModerationLog


class TestAllowedFile:
    def test_allowed_extensions(self, app):
        from helpers import allowed_file
        with app.app_context():
            assert allowed_file('photo.jpg') is True
            assert allowed_file('photo.jpeg') is True
            assert allowed_file('photo.png') is True
            assert allowed_file('video.mp4') is True
            assert allowed_file('audio.mp3') is True
            assert allowed_file('doc.pdf') is True

    def test_disallowed_extensions(self, app):
        from helpers import allowed_file
        with app.app_context():
            assert allowed_file('script.exe') is False
            assert allowed_file('file.php') is False
            assert allowed_file('.htaccess') is False

    def test_no_extension(self, app):
        from helpers import allowed_file
        with app.app_context():
            assert allowed_file('filewithoutext') is False

    def test_empty_filename(self, app):
        from helpers import allowed_file
        with app.app_context():
            assert allowed_file('') is False


class TestGenerateBotToken:
    def test_token_format(self):
        from helpers import generate_bot_token
        token = generate_bot_token()
        assert ':' in token
        parts = token.split(':')
        assert len(parts) == 2
        assert parts[0].isdigit()

    def test_unique_tokens(self):
        from helpers import generate_bot_token
        t1 = generate_bot_token()
        t2 = generate_bot_token()
        assert t1 != t2


class TestGetAvatarUrl:
    def test_none_user(self):
        from helpers import get_avatar_url
        assert get_avatar_url(None) is None

    def test_cloudinary_avatar(self, app, db):
        from helpers import get_avatar_url
        user = User(username='test', email='test@test.com')
        user.avatar_cloudinary_url = 'https://res.cloudinary.com/test/image/upload/v1/abc'
        assert get_avatar_url(user) == 'https://res.cloudinary.com/test/image/upload/v1/abc'

    def test_local_avatar(self, app, db):
        from helpers import get_avatar_url
        user = User(username='test', email='test@test.com')
        user.avatar = 'avatar.jpg'
        user.avatar_cloudinary_url = None
        with app.test_request_context():
            url = get_avatar_url(user)
        assert url is not None
        assert 'avatar.jpg' in url

    def test_default_avatar(self, app, db):
        from helpers import get_avatar_url
        user = User(username='test', email='test@test.com')
        user.avatar = 'default.png'
        user.avatar_cloudinary_url = None
        assert get_avatar_url(user) is None

    def test_no_avatar(self, app, db):
        from helpers import get_avatar_url
        user = User(username='test', email='test@test.com')
        user.avatar = None
        user.avatar_cloudinary_url = None
        assert get_avatar_url(user) is None


class TestCheckNsfwText:
    def test_clean_text(self):
        from helpers import check_nsfw_text
        assert check_nsfw_text('Hello, this is a normal post') is None

    def test_nsfw_keyword(self):
        from helpers import check_nsfw_text
        result = check_nsfw_text('This contains порно content')
        assert result is not None

    def test_empty_text(self):
        from helpers import check_nsfw_text
        assert check_nsfw_text('') is None
        assert check_nsfw_text(None) is None

    def test_case_insensitive(self):
        from helpers import check_nsfw_text
        assert check_nsfw_text('PORN video') is not None

    def test_multiple_keywords(self):
        from helpers import check_nsfw_text
        result = check_nsfw_text('секс and порно together')
        assert result is not None


class TestModeratePost:
    def test_clean_post_passes(self, app, db):
        from helpers import moderate_post
        user = User(username='testuser', email='test@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.commit()
        result = moderate_post('This is a clean post', user)
        assert result is None

    def test_nsfw_post_blocked(self, app, db):
        from helpers import moderate_post
        user = User(username='nsfwuser', email='nsfw@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.commit()
        result = moderate_post('This has порно content', user)
        assert result == 'BLOCKED'
        log = ModerationLog.query.filter_by(user_id=user.id).first()
        assert log is not None

    def test_banned_user(self, app, db):
        from helpers import moderate_post
        user = User(username='banneduser', email='banned@test.com')
        user.set_password('test')
        user.is_banned = True
        db.session.add(user)
        db.session.commit()
        result = moderate_post('Any text', user)
        assert result == 'USER_BANNED'

    def test_bot_without_creator(self, app, db):
        from helpers import moderate_post
        bot = User(username='testbot', email='bot@test.com', is_bot=True, creator_id=None)
        bot.set_password('test')
        db.session.add(bot)
        db.session.commit()
        result = moderate_post('Any text', bot)
        assert result is None


class TestCreateNotification:
    def test_create_notification(self, app, db):
        from helpers import create_notification
        sender = User(username='sender', email='sender@test.com')
        sender.set_password('test')
        recipient = User(username='recipient', email='recip@test.com')
        recipient.set_password('test')
        db.session.add_all([sender, recipient])
        db.session.commit()
        create_notification(recipient.id, sender.id, 'like', post_id=1)
        notif = Notification.query.filter_by(user_id=recipient.id).first()
        assert notif is not None
        assert notif.type == 'like'
        assert notif.sender_id == sender.id

    def test_self_notification_skipped(self, app, db):
        from helpers import create_notification
        user = User(username='self', email='self@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.commit()
        create_notification(user.id, user.id, 'like')
        notifs = Notification.query.filter_by(user_id=user.id).all()
        assert len(notifs) == 0


class TestGetOrCreateDM:
    def test_existing_dm(self, app, db):
        from helpers import get_or_create_dm
        alice = User(username='alice', email='alice@test.com')
        bob = User(username='bob', email='bob@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.flush()
        chat = Chat(name='DM', type='direct', creator_id=alice.id)
        db.session.add(chat)
        db.session.flush()
        db.session.add(ChatMember(chat_id=chat.id, user_id=alice.id))
        db.session.add(ChatMember(chat_id=chat.id, user_id=bob.id))
        db.session.commit()
        result = get_or_create_dm(alice, bob)
        assert result.id == chat.id

    def test_new_dm(self, app, db):
        from helpers import get_or_create_dm
        alice = User(username='alice2', email='alice2@test.com')
        bob = User(username='bob2', email='bob2@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.commit()
        result = get_or_create_dm(alice, bob)
        assert result is not None
        assert result.type == 'direct'
        members = ChatMember.query.filter_by(chat_id=result.id).all()
        assert len(members) == 2


class TestUploadToCloudinary:
    def test_no_filename(self, app):
        from helpers import upload_to_cloudinary
        from werkzeug.datastructures import FileStorage
        import io
        file = FileStorage(io.BytesIO(b'test'), filename='')
        result = upload_to_cloudinary(file)
        assert result is None

    def test_local_save(self, app, db, monkeypatch):
        import tempfile, os
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        from helpers import upload_to_cloudinary
        from werkzeug.datastructures import FileStorage
        import io
        file = FileStorage(io.BytesIO(b'test'), filename='test.jpg')
        monkeypatch.setattr('helpers.cloudinary_configured', False)
        result = upload_to_cloudinary(file, folder='test')
        assert result is not None
        assert result.endswith('test.jpg')
