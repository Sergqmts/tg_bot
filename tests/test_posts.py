import io, base64, os, tempfile
from unittest.mock import MagicMock
from extensions import db
from models import Post, Media, Draft, Tag, PostTag, Comment, CommentReaction, SavedPost, Repost, Reaction, MusicTrack


class TestIndex:
    ENDPOINT = '/'

    def test_anon_redirects_login(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_feed_loads(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_feed_shows_posts(self, auth_client, users, db):
        alice = users['alice']
        post = Post(body='Hello feed', author=alice)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200
        assert b'Hello feed' in resp.data

    def test_feed_excludes_blocked(self, auth_client, users, db):
        alice, bob = users['alice'], users['bob']
        alice.blocked.append(bob)
        db.session.commit()
        post = Post(body='Bob post', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.get(self.ENDPOINT)
        assert b'Bob post' not in resp.data


class TestCreatePost:
    ENDPOINT = '/create'

    def test_get_form(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_create_text_only(self, auth_client, users, db):
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'My first post', 'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='My first post').first()
        assert post is not None
        assert post.author == users['alice']

    def test_create_with_hashtags(self, auth_client, db):
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Post with #hello and #world', 'csrf_token': '',
        })
        assert resp.status_code == 302
        hello = Tag.query.filter_by(name='hello').first()
        world = Tag.query.filter_by(name='world').first()
        assert hello is not None
        assert world is not None

    def test_create_with_media_data(self, auth_client, db, app, monkeypatch):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        img_data = base64.b64encode(b'fakeimage').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Post with image',
            'media_data': data_url,
            'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Post with image').first()
        assert post is not None
        media = Media.query.filter_by(post_id=post.id).first()
        assert media is not None
        assert media.media_type == 'image'

    def test_create_with_cloudinary(self, auth_client, db, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        mock_upload = MagicMock(return_value='https://res.cloudinary.com/test/image/upload/v1/abc123')
        monkeypatch.setattr(helpers, 'upload_to_cloudinary', mock_upload)
        img_data = base64.b64encode(b'fakeimage').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Cloudinary post',
            'media_data': data_url,
            'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Cloudinary post').first()
        assert post is not None
        media = Media.query.filter_by(post_id=post.id).first()
        assert media is not None
        assert media.cloudinary_url is not None

    def test_create_with_uploaded_file_local(self, auth_client, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Upload test',
            'media': (io.BytesIO(b'fakeimg'), 'test.jpg'),
            'csrf_token': '',
        }, content_type='multipart/form-data')
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Upload test').first()
        assert post is not None

    def test_create_with_uploaded_file_cloudinary(self, auth_client, db, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        mock_upload = MagicMock(return_value='https://res.cloudinary.com/test/video/upload/v1/abc')
        monkeypatch.setattr(helpers, 'upload_to_cloudinary', mock_upload)
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Cloudinary upload',
            'media': (io.BytesIO(b'fakeimg'), 'photo.jpg'),
            'csrf_token': '',
        }, content_type='multipart/form-data')
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Cloudinary upload').first()
        assert post is not None

    def test_create_draft(self, auth_client, db):
        resp = auth_client.post(self.ENDPOINT + '?draft=1', data={
            'body': 'Draft post',
            'media_data': 'data:image/jpeg;base64,xyz',
            'csrf_token': '',
        })
        assert resp.status_code == 302
        draft = Draft.query.filter_by(caption='Draft post').first()
        assert draft is not None

    def test_create_moderation_blocked(self, auth_client, db):
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Check this порно content', 'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Check this порно content').first()
        assert post is None

    def test_music_track(self, auth_client, db):
        track = MusicTrack(title='Test', artist='Artist', preview_url='http://example.com/audio.mp3')
        db.session.add(track)
        db.session.commit()
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'Post with music',
            'music_track_id': str(track.id),
            'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='Post with music').first()
        assert post is not None
        assert post.music_track_id == track.id

    def test_create_unbanned_user_moderation_ok(self, auth_client, users, db):
        alice = users['alice']
        alice.is_banned = True
        db.session.commit()
        resp = auth_client.post(self.ENDPOINT, data={
            'body': 'I am banned', 'csrf_token': '',
        })
        assert resp.status_code == 302
        post = Post.query.filter_by(body='I am banned').first()
        assert post is None


class TestPhotoEditor:
    ENDPOINT = '/photo_editor'

    def test_get_editor(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_requires_auth(self, client):
        resp = client.get(self.ENDPOINT)
        assert resp.status_code == 302

    def test_save_profile_photo(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        img_data = base64.b64encode(b'fakeavatar').decode()
        data_url = f'data:image/jpeg;base64,{img_data}'
        resp = auth_client.post(self.ENDPOINT, data={
            'media_data': data_url,
            'csrf_token': '',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        db.session.refresh(users['alice'])
        assert users['alice'].avatar is not None

    def test_save_no_data(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={'csrf_token': ''})
        assert resp.status_code == 400

    def test_with_draft(self, auth_client, users, db):
        draft = Draft(user_id=users['alice'].id, caption='Test')
        db.session.add(draft)
        db.session.commit()
        resp = auth_client.get(self.ENDPOINT + f'?draft={draft.id}')
        assert resp.status_code == 200


class TestPhotoTransform:
    ENDPOINT = '/photo_transform'

    def _make_test_data_url(self):
        from PIL import Image
        img = Image.new('RGB', (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, 'JPEG')
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()

    def test_rotate(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={
            'preview_data': self._make_test_data_url(),
            'transform_type': 'rotate',
            'transform_value': '90',
            'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_flip_horizontal(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={
            'preview_data': self._make_test_data_url(),
            'transform_type': 'flip',
            'transform_value': 'h',
            'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_crop(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={
            'preview_data': self._make_test_data_url(),
            'transform_type': 'crop',
            'csrf_token': '',
        })
        assert resp.status_code == 200

    def test_requires_preview_data(self, auth_client):
        resp = auth_client.post(self.ENDPOINT, data={
            'transform_type': 'rotate', 'csrf_token': '',
        })
        assert resp.status_code == 400


class TestDrafts:
    def test_list_drafts(self, auth_client, users, db):
        draft = Draft(user_id=users['alice'].id, caption='My draft')
        db.session.add(draft)
        db.session.commit()
        resp = auth_client.get('/drafts')
        assert resp.status_code == 200
        assert b'My draft' in resp.data

    def test_delete_draft(self, auth_client, users, db):
        draft = Draft(user_id=users['alice'].id, caption='Delete me')
        db.session.add(draft)
        db.session.commit()
        resp = auth_client.post(f'/drafts/{draft.id}/delete', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert Draft.query.get(draft.id) is None

    def test_delete_other_draft_403(self, auth_client, users, db):
        bob = users['bob']
        draft = Draft(user_id=bob.id, caption='Bob draft')
        db.session.add(draft)
        db.session.commit()
        resp = auth_client.post(f'/drafts/{draft.id}/delete', data={'csrf_token': ''})
        assert resp.status_code == 403


class TestPostActions:
    def test_repost_toggle(self, auth_client, users, db):
        alice, bob = users['alice'], users['bob']
        post = Post(body='Repost test', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/repost', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert alice.has_reposted(post)
        resp = auth_client.post(f'/post/{post.id}/repost', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert not alice.has_reposted(post)

    def test_save_toggle(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Save test', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/save', data={'csrf_token': ''})
        assert resp.status_code == 302
        saved = SavedPost.query.filter_by(user_id=users['alice'].id, post_id=post.id).first()
        assert saved is not None

    def test_react_toggle(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='React test', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/react', data={
            'emoji': '🔥', 'csrf_token': '',
        })
        assert resp.status_code == 302
        reaction = Reaction.query.filter_by(post_id=post.id, user_id=users['alice'].id).first()
        assert reaction is not None
        assert reaction.emoji == '🔥'

    def test_like_toggle(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Like test', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/like', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert users['alice'].has_liked(post)

    def test_like_ajax(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='AJAX like', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/like', data={'csrf_token': ''},
                                headers={'X-Requested-With': 'XMLHttpRequest'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['liked'] is True
        assert data['count'] == 1

    def test_view_post(self, auth_client, users, db):
        alice = users['alice']
        post = Post(body='View me', author=alice)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.get(f'/post/{post.id}')
        assert resp.status_code == 200
        assert b'View me' in resp.data


class TestComments:
    def test_add_comment(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Comment post', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/comment', data={
            'body': 'Nice post!', 'csrf_token': '',
        })
        assert resp.status_code == 302
        comment = Comment.query.filter_by(post_id=post.id).first()
        assert comment is not None
        assert comment.body == 'Nice post!'

    def test_add_comment_with_media(self, auth_client, users, db, app):
        tmpdir = tempfile.mkdtemp()
        app.config['UPLOAD_FOLDER'] = tmpdir
        bob = users['bob']
        post = Post(body='Comment media post', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/comment', data={
            'body': 'With image',
            'media': (io.BytesIO(b'fakeimage'), 'comment.jpg'),
            'csrf_token': '',
        }, content_type='multipart/form-data')
        assert resp.status_code == 302

    def test_delete_comment(self, auth_client, users, db):
        alice = users['alice']
        post = Post(body='Delete comment', author=alice)
        db.session.add(post)
        db.session.flush()
        comment = Comment(body='To delete', author=alice, post=post)
        db.session.add(comment)
        db.session.commit()
        resp = auth_client.post(f'/comment/{comment.id}/delete', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert Comment.query.get(comment.id) is None

    def test_react_comment(self, auth_client, users, db):
        alice, bob = users['alice'], users['bob']
        post = Post(body='React comment', author=bob)
        db.session.add(post)
        db.session.flush()
        comment = Comment(body='React to me', author=bob, post=post)
        db.session.add(comment)
        db.session.commit()
        resp = auth_client.post(f'/comment/{comment.id}/react', data={
            'emoji': '👍', 'csrf_token': '',
        })
        assert resp.status_code == 302
        cr = CommentReaction.query.filter_by(comment_id=comment.id, user_id=alice.id).first()
        assert cr is not None


class TestSavedPosts:
    def test_saved_page(self, auth_client, db):
        resp = auth_client.get('/saved')
        assert resp.status_code == 200

    def test_saved_shows_saved_posts(self, auth_client, users, db):
        alice = users['alice']
        post = Post(body='Saved post', author=alice)
        db.session.add(post)
        db.session.flush()
        saved = SavedPost(user_id=alice.id, post_id=post.id)
        db.session.add(saved)
        db.session.commit()
        resp = auth_client.get('/saved')
        assert b'Saved post' in resp.data


class TestTags:
    def test_explore_tags(self, client, db):
        tag = Tag(name='python')
        db.session.add(tag)
        db.session.commit()
        resp = client.get('/explore_tags')
        assert resp.status_code == 200
        assert b'python' in resp.data

    def test_tag_posts(self, client, db):
        tag = Tag(name='flask')
        db.session.add(tag)
        db.session.flush()
        post = Post(body='Flask post', user_id=1)
        db.session.add(post)
        db.session.flush()
        pt = PostTag(post_id=post.id, tag_id=tag.id)
        db.session.add(pt)
        db.session.commit()
        resp = client.get('/tag/flask')
        assert resp.status_code == 200
        assert b'Flask post' in resp.data


class TestDeletePost:
    def test_delete_own_post(self, auth_client, users, db):
        alice = users['alice']
        post = Post(body='Delete me', author=alice)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/delete/{post.id}', data={'csrf_token': ''})
        assert resp.status_code == 302
        assert Post.query.get(post.id) is None

    def test_delete_others_post_403(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Bob post', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/delete/{post.id}', data={'csrf_token': ''})
        assert resp.status_code == 403


class TestForwardPost:
    def test_get_forward_form(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Forward me', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.get(f'/post/{post.id}/forward')
        assert resp.status_code == 200

    def test_forward_to_profile(self, auth_client, users, db):
        bob = users['bob']
        post = Post(body='Forward to profile', author=bob)
        db.session.add(post)
        db.session.commit()
        resp = auth_client.post(f'/post/{post.id}/forward', data={
            'action': 'to_profile', 'csrf_token': '',
        })
        assert resp.status_code == 302
        forwarded = Post.query.filter_by(body='Forward to profile').all()
        assert len(forwarded) == 2
