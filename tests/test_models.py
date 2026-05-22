from datetime import datetime, timedelta
from extensions import db
from models import (
    User, Post, Story, Media, Comment, Tag, PostTag, Draft,
    Reaction, Like, SavedPost, Repost, Shorts, MusicTrack,
    Notification, Chat, ChatMember, Message, MessageReaction,
    followers, Community, CommunityMember, ModerationLog,
)


class TestUser:
    def test_create_user(self, db):
        user = User(username='newuser', email='new@test.com')
        user.set_password('secret123')
        db.session.add(user)
        db.session.commit()
        assert user.id is not None
        assert user.username == 'newuser'
        assert user.check_password('secret123') is True
        assert user.check_password('wrong') is False

    def test_follow_user(self, db):
        alice = User(username='alice', email='alice@test.com')
        bob = User(username='bob', email='bob@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.commit()
        alice.follow(bob)
        db.session.commit()
        assert alice.is_following(bob) is True
        alice.unfollow(bob)
        db.session.commit()
        assert alice.is_following(bob) is False

    def test_block_user(self, db):
        alice = User(username='alice_b', email='aliceb@test.com')
        bob = User(username='bob_b', email='bobb@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.commit()
        alice.blocked.append(bob)
        db.session.commit()
        assert bob in alice.blocked.all()

    def test_like_post(self, db):
        user = User(username='liker', email='liker@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='Likeable post', user_id=user.id)
        db.session.add(post)
        db.session.commit()
        user.like_post(post)
        db.session.commit()
        assert user.has_liked(post) is True
        user.unlike_post(post)
        db.session.commit()
        assert user.has_liked(post) is False

    def test_repost(self, db):
        user = User(username='reposter', email='rep@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='Repostable', user_id=user.id)
        db.session.add(post)
        db.session.commit()
        user.repost(post)
        db.session.commit()
        assert user.has_reposted(post) is True
        user.unrepost(post)
        db.session.commit()
        assert user.has_reposted(post) is False


class TestPost:
    def test_create_post(self, db):
        user = User(username='poster', email='post@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='Hello world', author=user)
        db.session.add(post)
        db.session.commit()
        assert post.id is not None
        assert post.body == 'Hello world'
        assert post.author == user

    def test_post_with_media(self, db):
        user = User(username='mediaposter', email='media@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='With media', user_id=user.id)
        db.session.add(post)
        db.session.flush()
        media = Media(filename='test.jpg', media_type='image', post_id=post.id)
        db.session.add(media)
        db.session.commit()
        assert post.media.count() == 1
        assert post.media.first().filename == 'test.jpg'

    def test_post_with_hashtags(self, db):
        user = User(username='tagposter', email='tag@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='#cool #fun', user_id=user.id)
        db.session.add(post)
        db.session.flush()
        for name in ['cool', 'fun']:
            tag = Tag(name=name)
            db.session.add(tag)
            db.session.flush()
            pt = PostTag(post_id=post.id, tag_id=tag.id)
            db.session.add(pt)
        db.session.commit()
        assert PostTag.query.filter_by(post_id=post.id).count() == 2


class TestStory:
    def test_create_story(self, db):
        user = User(username='storyteller', email='story@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        story = Story(
            user_id=user.id,
            media_url='https://example.com/story.jpg',
            media_type='image',
            expires_at=datetime.utcnow() + timedelta(hours=24)
        )
        db.session.add(story)
        db.session.commit()
        assert story.id is not None
        assert story.is_expired() is False

    def test_expired_story(self, db):
        user = User(username='oldstory', email='old@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        story = Story(
            user_id=user.id,
            media_url='old.jpg',
            media_type='image',
            expires_at=datetime.utcnow() - timedelta(hours=1)
        )
        db.session.add(story)
        db.session.commit()
        assert story.is_expired() is True


class TestShorts:
    def test_create_shorts(self, db):
        user = User(username='shortsmaker', email='shorts@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        track = MusicTrack(title='Song', artist='Artist', preview_url='http://example.com/audio.mp3')
        db.session.add(track)
        db.session.flush()
        shorts = Shorts(
            video_url='https://example.com/shorts.mp4',
            caption='My shorts',
            user_id=user.id,
            audio_id=track.id
        )
        db.session.add(shorts)
        db.session.commit()
        assert shorts.id is not None
        assert shorts.video_url == 'https://example.com/shorts.mp4'


class TestComment:
    def test_create_comment(self, db):
        user = User(username='commenter', email='comment@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='Commented post', user_id=user.id)
        db.session.add(post)
        db.session.flush()
        comment = Comment(body='Nice!', author=user, post=post)
        db.session.add(comment)
        db.session.commit()
        assert comment.id is not None
        assert comment.body == 'Nice!'
        assert comment in post.comments

    def test_reply_to_comment(self, db):
        user = User(username='replier', email='reply@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        post = Post(body='Reply chain', user_id=user.id)
        db.session.add(post)
        db.session.flush()
        parent = Comment(body='Parent', author=user, post=post)
        db.session.add(parent)
        db.session.flush()
        reply = Comment(body='Reply', author=user, post=post, reply_to_id=parent.id)
        db.session.add(reply)
        db.session.commit()
        assert reply.reply_to_id == parent.id


class TestChat:
    def test_create_dm(self, db):
        alice = User(username='alice_chat', email='alicec@test.com')
        bob = User(username='bob_chat', email='bobc@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.flush()
        chat = Chat(name='DM', type='direct', creator_id=alice.id)
        db.session.add(chat)
        db.session.flush()
        for u in [alice, bob]:
            db.session.add(ChatMember(chat_id=chat.id, user_id=u.id))
        db.session.commit()
        assert chat.members.count() == 2

    def test_send_message(self, db):
        alice = User(username='alice_msg', email='alicemsg@test.com')
        bob = User(username='bob_msg', email='bobmsg@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.flush()
        chat = Chat(name='DM', type='direct', creator_id=alice.id)
        db.session.add(chat)
        db.session.flush()
        msg = Message(body='Hello!', sender_id=alice.id, chat_id=chat.id)
        db.session.add(msg)
        db.session.commit()
        assert msg.id is not None
        assert msg.body == 'Hello!'


class TestNotification:
    def test_create_notification(self, db):
        alice = User(username='alice_notif', email='alicen@test.com')
        bob = User(username='bob_notif', email='bobn@test.com')
        alice.set_password('test')
        bob.set_password('test')
        db.session.add_all([alice, bob])
        db.session.flush()
        notif = Notification(
            user_id=alice.id,
            sender_id=bob.id,
            type='follow'
        )
        db.session.add(notif)
        db.session.commit()
        assert notif.id is not None
        assert notif.type == 'follow'
        assert notif.read is False


class TestMusicTrack:
    def test_create_track(self, db):
        track = MusicTrack(
            title='Test Song',
            artist='Test Artist',
            duration=180,
            preview_url='http://example.com/preview.mp3',
            source='deezer'
        )
        db.session.add(track)
        db.session.commit()
        assert track.id is not None
        assert track.title == 'Test Song'


class TestDraft:
    def test_create_draft(self, db):
        user = User(username='draftuser', email='draft@test.com')
        user.set_password('test')
        db.session.add(user)
        db.session.flush()
        draft = Draft(
            user_id=user.id,
            media_data='data:image/jpeg;base64,abc',
            caption='My draft'
        )
        db.session.add(draft)
        db.session.commit()
        assert draft.id is not None
        assert draft.caption == 'My draft'
