import io, base64, os, tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from extensions import db
from models import Story, StoryReaction, StoryComment, User


class TestCreateStory:
    ENDPOINT = '/story/create'

    def test_get_form(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_create_with_media_data_local(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        img_data = base64.b64encode(b'fakeimage').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': data_url, 'csrf_token': '',
        })
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None
        assert story.media_type == 'image'

    def test_create_with_media_data_video(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        img_data = base64.b64encode(b'fakevideo').decode()
        data_url = f'data:video/mp4;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': data_url, 'csrf_token': '',
        })
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None
        assert story.media_type == 'video'

    def test_create_with_cloudinary(self, auth_client, users, db, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        mock_upload = MagicMock(return_value='https://res.cloudinary.com/test/image/upload/v1/story123')
        monkeypatch.setattr(helpers, 'upload_to_cloudinary', mock_upload)
        img_data = base64.b64encode(b'fakeimage').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': data_url, 'csrf_token': '',
        })
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None
        assert story.media_url == 'https://res.cloudinary.com/test/image/upload/v1/story123'

    def test_create_with_uploaded_file_local(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        resp = auth_client.post(self.ENDPOINT, data={
            'media': (io.BytesIO(b'fakeimg'), 'story.jpg'),
            'csrf_token': '',
        }, content_type='multipart/form-data')
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None

    def test_create_with_uploaded_file_cloudinary(self, auth_client, users, db, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        mock_upload = MagicMock(return_value='https://res.cloudinary.com/test/image/upload/v1/story_upload')
        monkeypatch.setattr(helpers, 'upload_to_cloudinary', mock_upload)
        resp = auth_client.post(self.ENDPOINT, data={
            'media': (io.BytesIO(b'fakeimg'), 'story.jpg'),
            'csrf_token': '',
        }, content_type='multipart/form-data')
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None
        assert story.media_url == 'https://res.cloudinary.com/test/image/upload/v1/story_upload'

    def test_invalid_base64(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': 'data:image/jpeg;base64,!!!invalid!!!',
            'csrf_token': '',
        })
        assert resp.status_code == 400

    def test_expires_at_set(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        img_data = base64.b64encode(b'fakeimage').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': data_url, 'csrf_token': '',
        })
        assert resp.status_code == 302
        story = Story.query.filter_by(user_id=users['alice'].id).first()
        assert story is not None
        assert story.expires_at > datetime.utcnow()


class TestStoryActions:
    def test_delete_story(self, auth_client, users, db):
        alice = users['alice']
        story = Story(user_id=alice.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/delete', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert Story.query.get(story.id) is None

    def test_delete_others_story_403(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='bob.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/delete', data={'csrf_token': ''})
        assert resp.status_code == 403

    def test_save_toggle(self, auth_client, users, db):
        alice = users['alice']
        story = Story(user_id=alice.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        assert not story.is_saved
        resp = auth_client.post(f'/story/{story.id}/save', data={'csrf_token': ''})
        assert resp.status_code == 302
        db.session.refresh(story)
        assert story.is_saved

    def test_republish(self, auth_client, users, db):
        alice = users['alice']
        story = Story(user_id=alice.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() - timedelta(hours=1), is_archived=True)
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/republish', data={'csrf_token': ''})
        assert resp.status_code == 302
        db.session.refresh(story)
        assert story.expires_at > datetime.utcnow()
        assert not story.is_archived

    def test_react(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/react', data={
            'emoji': '❤️', 'csrf_token': '',
        })
        assert resp.status_code == 302
        reaction = StoryReaction.query.filter_by(story_id=story.id, user_id=users['alice'].id).first()
        assert reaction is not None

    def test_comment(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/comment', data={
            'body': 'Great story!', 'csrf_token': '',
        })
        assert resp.status_code == 302
        comment = StoryComment.query.filter_by(story_id=story.id).first()
        assert comment is not None
        assert comment.body == 'Great story!'

    def test_react_without_emoji(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/story/{story.id}/react', data={'csrf_token': ''})
        assert resp.status_code == 302


class TestStoriesList:
    def test_stories_page(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='test.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.get('/stories')
        assert resp.status_code == 200

    def test_archives(self, auth_client, users, db):
        alice = users['alice']
        story = Story(user_id=alice.id, media_url='archived.jpg', media_type='image',
                       expires_at=datetime.utcnow() - timedelta(hours=1), is_archived=True)
        db.session.add(story)
        db.session.commit()
        resp = auth_client.get('/stories/archives')
        assert resp.status_code == 200

    def test_user_stories(self, auth_client, users, db):
        alice = users['alice']
        story = Story(user_id=alice.id, media_url='mystory.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.get(f'/stories/user/{alice.username}')
        assert resp.status_code == 200

    def test_hide_stories(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='bobstory.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.post(f'/stories/hide/{bob.username}', data={'csrf_token': ''})
        assert resp.status_code == 302

    def test_view_story(self, auth_client, users, db):
        bob = users['bob']
        story = Story(user_id=bob.id, media_url='viewstory.jpg', media_type='image',
                       expires_at=datetime.utcnow() + timedelta(hours=24))
        db.session.add(story)
        db.session.commit()
        resp = auth_client.get(f'/story/{story.id}')
        assert resp.status_code == 200
