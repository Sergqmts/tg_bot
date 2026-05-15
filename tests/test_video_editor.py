import json
from extensions import db
from models import ShortsAudio


CLOUD_NAME = 'testcloud'


def build_transform_url(public_id, version, start_offset, end_offset,
                        effect, speed, audio_public_id=None):
    tx_parts = []
    if start_offset > 0:
        tx_parts.append(f'so_{start_offset}')
    if end_offset > 0:
        tx_parts.append(f'eo_{end_offset}')

    filter_map = {
        'grayscale': 'e_grayscale',
        'sepia': 'e_sepia',
        'vintage': 'e_art:vintage',
        'cinematic': 'e_contrast:40,e_brightness:-20',
        'vivid': 'e_saturation:50',
        'cool': 'e_hue:200',
        'warm': 'e_hue:-10',
    }
    if effect and effect in filter_map and effect != 'original':
        tx_parts.append(filter_map[effect])
    if speed and speed != 1:
        tx_parts.append(f'e_accelerate:{speed}')
    if audio_public_id:
        tx_parts.append(f'l_audio:{audio_public_id.replace("/", ":")},fl_layer_apply')
    if tx_parts:
        tx_str = '/'.join(tx_parts)
        if version:
            return f'https://res.cloudinary.com/{CLOUD_NAME}/video/upload/{tx_str}/v{version}/{public_id}'
        else:
            return f'https://res.cloudinary.com/{CLOUD_NAME}/video/upload/{tx_str}/{public_id}'
    else:
        return f'https://res.cloudinary.com/{CLOUD_NAME}/video/upload/v{version}/{public_id}'



class TestVideoEditorUpload:
    ENDPOINT = '/video_editor'

    def test_get_editor(self, auth_client):
        resp = auth_client.get(self.ENDPOINT)
        assert resp.status_code == 200

    def test_upload_no_file(self, auth_client):
        resp = auth_client.post(self.ENDPOINT,
                                content_type='application/json',
                                data=json.dumps({}))
        assert resp.status_code == 400

    def test_upload_no_cloudinary_file(self, auth_client, app, monkeypatch):
        import io
        class FakeUploadResult(dict):
            def __init__(self):
                super().__init__(
                    public_id='test_public_id',
                    version=12345,
                    secure_url='https://res.cloudinary.com/test/video/upload/v12345/test.mp4',
                )
            __getattr__ = dict.get

        def mock_upload(*args, **kwargs):
            return FakeUploadResult()

        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        import cloudinary.uploader as cu
        monkeypatch.setattr(cu, 'upload', mock_upload)

        resp = auth_client.post(
            self.ENDPOINT,
            data={
                'video': (io.BytesIO(b'fake video data'), 'test.mp4'),
            },
            content_type='multipart/form-data',
        )
        result = resp.get_json()
        assert resp.status_code == 200, f'Expected 200, got {resp.status_code}: {result}'
        assert result['success'] is True
        assert result['public_id'] == 'test_public_id'


class TestBuildTransformUrl:
    def test_no_transforms(self):
        url = build_transform_url('abc123', 1, 0, 0, '', 1)
        assert 'abc123' in url
        assert 'so_' not in url
        assert 'eo_' not in url
        assert 'e_' not in url

    def test_trim(self):
        url = build_transform_url('abc123', 1, 10, 20, '', 1)
        assert 'so_10' in url
        assert 'eo_20' in url

    def test_grayscale_filter(self):
        url = build_transform_url('abc123', 1, 0, 0, 'grayscale', 1)
        assert 'e_grayscale' in url

    def test_sepia(self):
        url = build_transform_url('abc123', 1, 0, 0, 'sepia', 1)
        assert 'e_sepia' in url

    def test_cinematic(self):
        url = build_transform_url('abc123', 1, 0, 0, 'cinematic', 1)
        assert 'e_contrast:40' in url
        assert 'e_brightness:-20' in url

    def test_speed(self):
        url = build_transform_url('abc123', 1, 0, 0, '', 2)
        assert 'e_accelerate:2' in url

    def test_slow_motion(self):
        url = build_transform_url('abc123', 1, 0, 0, '', 0.5)
        assert 'e_accelerate:0.5' in url

    def test_filter_and_speed(self):
        url = build_transform_url('abc123', 1, 0, 0, 'vivid', 1.5)
        assert 'e_saturation:50' in url
        assert 'e_accelerate:1.5' in url

    def test_all_transforms(self):
        url = build_transform_url('abc123', 1, 5, 15, 'cool', 2)
        assert 'so_5' in url
        assert 'eo_15' in url
        assert 'e_hue:200' in url
        assert 'e_accelerate:2' in url

    def test_audio_overlay(self):
        url = build_transform_url('abc123', 1, 0, 0, '', 1,
                                  audio_public_id='shorts_audio/abc123')
        assert 'l_audio:shorts_audio:abc123,fl_layer_apply' in url

    def test_unknown_filter_falls_through(self):
        url = build_transform_url('abc123', 1, 0, 0, 'nonexistent', 1)
        assert 'e_' not in url.split('/upload/')[1]

    def test_original_filter_ignored(self):
        url = build_transform_url('abc123', 1, 0, 0, 'original', 1)
        assert 'e_' not in url.split('/upload/')[1]

    def test_url_without_version(self):
        url = build_transform_url('abc123', None, 10, 0, '', 1)
        assert 'so_10' in url
        assert '/vNone/' not in url


class TestVideoEditorApi:
    ENDPOINT = '/video_editor'

    def test_build_url_from_public_id(self, auth_client, app, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        monkeypatch.setattr(helpers, 'cloud_name', CLOUD_NAME)

        resp = auth_client.post(
            self.ENDPOINT,
            content_type='application/json',
            data=json.dumps({
                'public_id': 'shorts/abc123',
                'version': 123,
                'start_offset': 5,
                'end_offset': 20,
                'filter': 'vintage',
                'speed': 1.5,
            })
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['success'] is True
        assert 'cloudinary' in data['url']
        assert 'e_art:vintage' in data['url']
        assert 'so_5' in data['url']
        assert 'eo_20' in data['url']
        assert 'e_accelerate:1.5' in data['url']

    def test_no_transforms_returns_original(self, auth_client, app, monkeypatch):
        import helpers
        monkeypatch.setattr(helpers, 'cloudinary_configured', True)
        monkeypatch.setattr(helpers, 'cloud_name', CLOUD_NAME)

        resp = auth_client.post(
            self.ENDPOINT,
            content_type='application/json',
            data=json.dumps({
                'public_id': 'shorts/abc123',
                'version': 123,
                'original_url': 'https://res.cloudinary.com/test/video/upload/v123/shorts/abc123.mp4',
            })
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['url'] != ''

    def test_original_url_fallback(self, auth_client):
        resp = auth_client.post(
            self.ENDPOINT,
            content_type='application/json',
            data=json.dumps({
                'original_url': 'https://example.com/video.mp4',
            })
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data['url'] == 'https://example.com/video.mp4'
