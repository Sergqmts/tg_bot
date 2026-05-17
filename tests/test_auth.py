class TestRegister:
    ENDPOINT = '/register'

    def test_get_form(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_register_redirects_when_logged_in(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_register_success(self, client, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'newuser', 'email': 'new@test.com',
            'password': 'Testpass123', 'confirm': 'Testpass123',
            'csrf_token': '',
        })
        assert resp.status_code == 302
        from models import User
        u = User.query.filter_by(username='newuser').first()
        assert u is not None
        assert u.email == 'new@test.com'

    def test_register_duplicate_username(self, client, users, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'alice', 'email': 'alice2@test.com',
            'password': 'Testpass123', 'confirm': 'Testpass123',
            'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_register_password_mismatch(self, client, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'testuser', 'email': 't@t.com',
            'password': 'Testpass123', 'confirm': 'Different123',
            'csrf_token': '',
        })
        assert resp.status_code == 200


class TestLogin:
    ENDPOINT = '/login'

    def test_get_form(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_login_redirects_when_logged_in(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_login_success(self, client, users, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'alice', 'password': 'testpass123', 'csrf_token': '',
        })
        assert resp.status_code == 302
        with client.session_transaction() as sess:
            assert '_user_id' in sess

    def test_login_wrong_password(self, client, users, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'alice', 'password': 'wrongpass', 'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_login_nonexistent_user(self, client, db):
        resp = client.post(self.ENDPOINT, data={
            'username': 'noone', 'password': 'testpass123', 'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_login_with_next(self, client, users, db):
        resp = client.post(self.ENDPOINT + '?next=/messages', data={
            'username': 'alice', 'password': 'testpass123', 'csrf_token': '',
        })
        assert resp.status_code == 302
        assert '/messages' in resp.location

    def test_login_banned_user(self, client, users, db):
        from models import User
        alice = User.query.get(users['alice'].id)
        alice.is_banned = True
        db.session.commit()
        resp = client.post(self.ENDPOINT, data={
            'username': 'alice', 'password': 'testpass123', 'csrf_token': '',
        })
        assert resp.status_code == 200


class TestLogout:
    ENDPOINT = '/logout'

    def test_logout_requires_auth(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_logout_success(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 302
        with auth_client.session_transaction() as sess:
            assert '_user_id' not in sess


class TestGoogleLogin:
    def test_google_login_not_configured(self, client):
        resp = client.get('/login/google')
        assert resp.status_code == 302

    def test_google_callback_not_configured(self, client):
        resp = client.get('/login/google/callback')
        assert resp.status_code == 302
