import json
from extensions import db
from models import Post, Story, Shorts, Draft, Media, User


class TestEditorPublish:
    ENDPOINT = '/api/editor/publish'

    def _headers(self):
        return {'X-Service-Token': 'test-service-token-123'}

    def test_missing_token_403(self, client):
        resp = client.post(self.ENDPOINT, json={})
        assert resp.status_code == 403

    def test_wrong_token_403(self, client):
        resp = client.post(self.ENDPOINT, json={},
                           headers={'X-Service-Token': 'wrong-token'})
        assert resp.status_code == 403

    def test_missing_fields_400(self, client):
        resp = client.post(self.ENDPOINT, json={},
                           headers=self._headers())
        assert resp.status_code == 400

    def test_publish_feed(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/photo.jpg',
            'caption': 'Editor post',
            'target': 'feed',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'post_id' in data
        post = Post.query.get(data['post_id'])
        assert post is not None
        assert post.body == 'Editor post'
        media = Media.query.filter_by(post_id=post.id).first()
        assert media is not None

    def test_publish_story(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/story.jpg',
            'target': 'story',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'post_id' in data
        story = Story.query.get(data['post_id'])
        assert story is not None
        assert story.media_url == 'https://example.com/story.jpg'

    def test_publish_shorts(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/shorts.mp4',
            'caption': 'Shorts caption',
            'target': 'shorts',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'post_id' in data
        shorts = Shorts.query.get(data['post_id'])
        assert shorts is not None
        assert shorts.caption == 'Shorts caption'

    def test_publish_draft(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/draft.jpg',
            'caption': 'Draft caption',
            'target': 'draft',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'post_id' in data
        draft = Draft.query.get(data['post_id'])
        assert draft is not None
        assert draft.caption == 'Draft caption'

    def test_invalid_target_400(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/x.jpg',
            'target': 'invalid',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 400

    def test_return_url_in_response(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'image_url': 'https://example.com/photo.jpg',
            'target': 'feed',
            'user_id': users['alice'].id,
            'return_url': '/story/create',
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('redirect_url') == '/story/create'


class TestEditorPublishVideo:
    ENDPOINT = '/api/editor/publish-video'

    def _headers(self):
        return {'X-Service-Token': 'test-service-token-123'}

    def test_missing_token_403(self, client):
        resp = client.post(self.ENDPOINT, json={})
        assert resp.status_code == 403

    def test_publish_video(self, client, users, db):
        resp = client.post(self.ENDPOINT, json={
            'cloudinary_url': 'https://res.cloudinary.com/test/video.mp4',
            'caption': 'Video shorts',
            'user_id': users['alice'].id,
        }, headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'shorts_id' in data
        shorts = Shorts.query.get(data['shorts_id'])
        assert shorts is not None
        assert shorts.caption == 'Video shorts'


class TestEditorGetDraft:
    ENDPOINT = '/api/editor/draft'

    def _headers(self):
        return {'X-Service-Token': 'test-service-token-123'}

    def test_get_draft(self, client, users, db):
        draft = Draft(user_id=users['alice'].id, media_data='data:image/jpeg;base64,abc',
                       caption='Editor draft')
        db.session.add(draft)
        db.session.commit()
        resp = client.get(f'{self.ENDPOINT}/{draft.id}', headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['caption'] == 'Editor draft'
        assert data['media_data'] == 'data:image/jpeg;base64,abc'

    def test_not_found(self, client, users, db):
        resp = client.get(f'{self.ENDPOINT}/99999', headers=self._headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'error'


class TestProxyRoutes:
    def test_proxy_photo_editor_redirects(self, auth_client):
        resp = auth_client.get('/proxy/edit/photo')
        assert resp.status_code == 302
        assert '/photo_editor' in resp.location

    def test_proxy_photo_editor_passes_params(self, auth_client):
        resp = auth_client.get('/proxy/edit/photo?target=story&return=/story/create')
        assert resp.status_code == 302
        assert 'target=story' in resp.location
        assert 'return=%2Fstory%2Fcreate' in resp.location or 'return=/story/create' in resp.location

    def test_proxy_video_editor_redirects(self, auth_client):
        resp = auth_client.get('/proxy/edit/video')
        assert resp.status_code == 302
        assert '/video_editor' in resp.location
