import json
import time
from unittest.mock import patch
from extensions import db
from models import Call, User, Message, Notification
from routes.calls import format_duration, get_turn_credentials


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == '0:00'

    def test_seconds_only(self):
        assert format_duration(45) == '0:45'

    def test_minutes(self):
        assert format_duration(125) == '2:05'

    def test_hour(self):
        assert format_duration(3661) == '61:01'


class TestGetTurnCredentials:
    def test_not_configured(self, app):
        with app.app_context():
            assert get_turn_credentials() is None

    def test_configured(self, app):
        sample_servers = [
            {'urls': 'stun:stun.metered.ca:80'},
            {'urls': 'turn:standard.relay.metered.ca:80', 'username': 'testuser', 'credential': 'testpass'},
        ]
        app.config['METERED_APP_NAME'] = 'testapp'
        app.config['METERED_API_KEY'] = 'test-api-key'
        import urllib.request
        from unittest.mock import patch, MagicMock
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_servers).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        import routes.calls as calls_module
        calls_module._turn_cache['creds'] = None
        calls_module._turn_cache['expires'] = 0
        with patch('urllib.request.urlopen', return_value=mock_response):
            with app.app_context():
                creds = get_turn_credentials()
                assert isinstance(creds, list)
                assert len(creds) > 0
                turn_servers = [s for s in creds if 'turn' in s.get('urls', '').lower()]
                assert len(turn_servers) > 0
                assert 'username' in turn_servers[0]
                assert 'credential' in turn_servers[0]
        app.config['METERED_APP_NAME'] = ''
        app.config['METERED_API_KEY'] = ''
        calls_module._turn_cache['creds'] = None
        calls_module._turn_cache['expires'] = 0


class TestInitiateCall:
    ENDPOINT = '/api/calls/initiate'

    def test_unauthenticated(self, client):
        resp = client.post(self.ENDPOINT, json={'callee_id': 1})
        assert resp.status_code in (302, 401)

    def test_missing_callee(self, auth_client, users):
        resp = auth_client.post(self.ENDPOINT, json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert 'callee_id required' in data.get('error', '')

    def test_self_call(self, auth_client, users):
        resp = auth_client.post(self.ENDPOINT, json={
            'callee_id': users['alice'].id
        })
        data = resp.get_json()
        assert resp.status_code == 400
        assert 'cannot call yourself' in data.get('error', '')

    def test_nonexistent_user(self, auth_client, users):
        resp = auth_client.post(self.ENDPOINT, json={'callee_id': 9999})
        assert resp.status_code == 404

    def test_successful_audio_initiate(self, auth_client, users):
        bob = users['bob']
        resp = auth_client.post(self.ENDPOINT, json={
            'callee_id': bob.id, 'call_type': 'audio'
        })
        data = resp.get_json()
        assert resp.status_code == 201
        assert data['call_type'] == 'audio'
        assert data['status'] == 'ringing'
        assert data['callee_id'] == bob.id
        call = db.session.get(Call, data['call_id'])
        assert call is not None
        assert call.caller_id == users['alice'].id

    def test_successful_video_initiate(self, auth_client, users):
        bob = users['bob']
        resp = auth_client.post(self.ENDPOINT, json={
            'callee_id': bob.id, 'call_type': 'video'
        })
        data = resp.get_json()
        assert resp.status_code == 201
        assert data['call_type'] == 'video'

    def test_duplicate_call_rejected(self, auth_client, users):
        bob = users['bob']
        auth_client.post(self.ENDPOINT, json={
            'callee_id': bob.id, 'call_type': 'audio'
        })
        resp = auth_client.post(self.ENDPOINT, json={
            'callee_id': bob.id, 'call_type': 'audio'
        })
        assert resp.status_code == 409

    def test_stale_call_cleaned_on_initiate(self, auth_client, users, app):
        from datetime import datetime, timedelta
        bob = users['bob']
        alice = users['alice']
        old = Call(
            caller_id=bob.id, callee_id=alice.id,
            call_type='audio', status='ringing',
            created_at=datetime.utcnow() - timedelta(seconds=60)
        )
        db.session.add(old)
        db.session.commit()
        resp = auth_client.post(self.ENDPOINT, json={
            'callee_id': bob.id, 'call_type': 'audio'
        })
        assert resp.status_code == 201
        db.session.refresh(old)
        assert old.status == 'missed'


class TestCallStatus:
    def test_forbidden(self, auth_client, users, db):
        call = Call(caller_id=99999, callee_id=99998,
                    call_type='audio', status='ringing')
        db.session.add(call)
        db.session.commit()
        resp = auth_client.get(f'/api/calls/{call.id}/status')
        assert resp.status_code == 403

    def test_own_call_status(self, auth_client, users, db):
        call = Call(caller_id=users['alice'].id, callee_id=users['bob'].id,
                    call_type='video', status='ringing')
        db.session.add(call)
        db.session.commit()
        resp = auth_client.get(f'/api/calls/{call.id}/status')
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['status'] == 'ringing'
        assert data['call_type'] == 'video'


class TestAnswerCall:
    def test_answer_ringing(self, auth_client, users, db):
        call = Call(caller_id=users['bob'].id, callee_id=users['alice'].id,
                    call_type='audio', status='ringing')
        db.session.add(call)
        db.session.commit()
        resp = auth_client.post(f'/api/calls/{call.id}/answer')
        assert resp.status_code == 200
        db.session.refresh(call)
        assert call.status == 'ongoing'
        assert call.started_at is not None

    def test_forbidden(self, auth_client, users, db):
        call = Call(caller_id=users['bob'].id, callee_id=9998,
                    call_type='audio', status='ringing')
        db.session.add(call)
        db.session.commit()
        resp = auth_client.post(f'/api/calls/{call.id}/answer')
        assert resp.status_code == 403


class TestEndCall:
    def test_end_ongoing_creates_message(self, auth_client, users, db):
        from datetime import datetime
        call = Call(
            caller_id=users['alice'].id, callee_id=users['bob'].id,
            call_type='audio', status='ongoing',
            started_at=datetime.utcnow()
        )
        db.session.add(call)
        db.session.commit()
        resp = auth_client.post(f'/api/calls/{call.id}/end')
        assert resp.status_code == 200
        db.session.refresh(call)
        assert call.status == 'ended'
        msgs = Message.query.all()
        assert len(msgs) == 1
        assert '📞' in msgs[0].body
        assert 'Аудиозвонок' in msgs[0].body

    def test_end_ringing_creates_missed_message(self, auth_client, users, db):
        call = Call(
            caller_id=users['alice'].id, callee_id=users['bob'].id,
            call_type='video', status='ringing'
        )
        db.session.add(call)
        db.session.commit()
        resp = auth_client.post(f'/api/calls/{call.id}/end')
        assert resp.status_code == 200
        msgs = Message.query.all()
        assert len(msgs) == 1
        assert '📹' in msgs[0].body
        assert 'Пропущенный' in msgs[0].body

    def test_end_ringing_creates_notification(self, auth_client, users, db):
        call = Call(
            caller_id=users['alice'].id, callee_id=users['bob'].id,
            call_type='audio', status='ringing'
        )
        db.session.add(call)
        db.session.commit()
        auth_client.post(f'/api/calls/{call.id}/end')
        notifs = Notification.query.filter_by(type='call_missed').all()
        assert len(notifs) > 0


class TestTurnCredentialsEndpoint:
    ENDPOINT = '/api/turn/credentials'

    def test_unauthenticated(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code in (302, 401, 501)

    def test_not_configured(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 501

    def test_configured(self, auth_client, app):
        app.config['CLOUDFLARE_TURN_KEY_ID'] = 'test-key'
        app.config['CLOUDFLARE_TURN_API_TOKEN'] = 'test-token'
        resp = auth_client.get(self.ENDPOINT)
        data = resp.get_json()
        assert resp.status_code == 200
        assert 'username' in data
        assert 'credential' in data
        app.config['CLOUDFLARE_TURN_KEY_ID'] = ''
        app.config['CLOUDFLARE_TURN_API_TOKEN'] = ''


class TestCallHistory:
    def test_empty_history(self, auth_client):
        resp = auth_client.get('/api/calls/history')
        data = resp.get_json()
        assert resp.status_code == 200
        assert data == []

    def test_history(self, auth_client, users, db):
        alice = users['alice']
        bob = users['bob']
        calls = [
            Call(caller_id=alice.id, callee_id=bob.id, call_type='audio', status='ended'),
            Call(caller_id=bob.id, callee_id=alice.id, call_type='video', status='missed'),
        ]
        db.session.add_all(calls)
        db.session.commit()
        resp = auth_client.get('/api/calls/history')
        data = resp.get_json()
        assert len(data) == 2
        assert data[0]['direction'] in ('outgoing', 'incoming')


class TestCreateCallDmMessage:
    def test_create_audio_message(self, app, db, users, dm_chat):
        from routes.calls import create_call_dm_message
        alice = users['alice']
        bob = users['bob']
        msg = create_call_dm_message(alice, bob, 'audio', duration_sec=90)
        db.session.commit()
        assert msg is not None
        assert '📞' in msg.body
        assert '1:30' in msg.body
        assert msg.sender_id == alice.id
        assert msg.recipient_id == bob.id

    def test_create_video_message(self, app, db, users, dm_chat):
        from routes.calls import create_call_dm_message
        alice = users['alice']
        bob = users['bob']
        msg = create_call_dm_message(alice, bob, 'video', duration_sec=300)
        db.session.commit()
        assert '📹' in msg.body
        assert '5:00' in msg.body

    def test_create_missed(self, app, db, users, dm_chat):
        from routes.calls import create_call_dm_message
        alice = users['alice']
        bob = users['bob']
        msg = create_call_dm_message(alice, bob, 'audio', missed=True)
        db.session.commit()
        assert '📞' in msg.body
        assert 'Пропущенный' in msg.body
