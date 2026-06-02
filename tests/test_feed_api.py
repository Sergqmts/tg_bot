import pytest


class TestFeedApi:
    ENDPOINT = '/feed'

    def test_requires_login(self, client):
        resp = client.get(self.ENDPOINT + '?before=999')
        assert resp.status_code in (302, 401)

    def test_missing_before_returns_empty(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['html'] == ''
        assert data['has_more'] is False

    def test_returns_json_with_correct_keys(self, auth_client, db):
        from models import Post, User
        user = User.query.filter_by(username='alice').first()
        for i in range(5):
            p = Post(body=f'test post {i}', user_id=user.id)
            db.session.add(p)
        db.session.commit()

        last_post = Post.query.order_by(Post.id.desc()).first()
        resp = auth_client.get(f'{self.ENDPOINT}?before={last_post.id + 1}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'html' in data
        assert 'has_more' in data
        assert 'last_id' in data

    def test_has_more_false_when_fewer_than_20(self, auth_client, db):
        from models import Post, User
        user = User.query.filter_by(username='alice').first()
        Post.query.delete()
        db.session.commit()
        for i in range(5):
            p = Post(body=f'post {i}', user_id=user.id)
            db.session.add(p)
        db.session.commit()

        big_id = Post.query.order_by(Post.id.desc()).first().id + 1
        resp = auth_client.get(f'{self.ENDPOINT}?before={big_id}')
        data = resp.get_json()
        assert data['has_more'] is False

    def test_has_more_true_when_exactly_20(self, auth_client, db):
        from models import Post, User
        user = User.query.filter_by(username='alice').first()
        Post.query.delete()
        db.session.commit()
        for i in range(21):
            p = Post(body=f'post {i}', user_id=user.id)
            db.session.add(p)
        db.session.commit()

        big_id = Post.query.order_by(Post.id.desc()).first().id + 1
        resp = auth_client.get(f'{self.ENDPOINT}?before={big_id}')
        data = resp.get_json()
        assert data['has_more'] is True
