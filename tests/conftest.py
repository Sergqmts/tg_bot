import os
import pytest
from extensions import db as _db
from models import User, Chat, ChatMember, Message

TEST_USER_PW = 'testpass123'

os.environ['CLOUDINARY_CLOUD_NAME'] = ''
os.environ['CLOUDINARY_API_KEY'] = ''
os.environ['CLOUDINARY_API_SECRET'] = ''
os.environ['CLOUDFLARE_TURN_KEY_ID'] = ''
os.environ['CLOUDFLARE_TURN_API_TOKEN'] = ''
os.environ['SECRET_KEY'] = 'test-secret-key'
os.environ['DATABASE_URL'] = ''


@pytest.fixture(scope='session', autouse=True)
def app():
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    flask_app.config['WTF_CSRF_ENABLED'] = False
    with flask_app.app_context():
        _db.create_all()
        yield flask_app


@pytest.fixture(scope='function', autouse=True)
def db(app):
    for tbl in reversed(_db.metadata.sorted_tables):
        _db.session.execute(tbl.delete())
    _db.session.commit()
    yield _db
    for tbl in reversed(_db.metadata.sorted_tables):
        _db.session.execute(tbl.delete())
    _db.session.commit()


@pytest.fixture(scope='function')
def client(app, db):
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='function')
def users(app, db):
    alice = User(username='alice', email='alice@test.com')
    alice.set_password(TEST_USER_PW)
    bob = User(username='bob', email='bob@test.com')
    bob.set_password(TEST_USER_PW)
    _db.session.add_all([alice, bob])
    _db.session.commit()
    return {'alice_id': alice.id, 'bob_id': bob.id,
            'alice': alice, 'bob': bob}


@pytest.fixture(scope='function')
def dm_chat(app, db, users):
    alice = users['alice']
    bob = users['bob']
    chat = Chat(name=f'{alice.username}-{bob.username}', type='dm', creator_id=alice.id)
    _db.session.add(chat)
    _db.session.flush()
    for u in [alice, bob]:
        cm = ChatMember(user_id=u.id, chat_id=chat.id)
        _db.session.add(cm)
    _db.session.commit()
    return chat


@pytest.fixture(scope='function')
def auth_client(app, client, users):
    client.post('/login', data={
        'username': 'alice',
        'password': 'testpass123',
        'csrf_token': '',
    })
    return client
