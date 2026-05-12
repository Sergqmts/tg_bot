import urllib.request
import urllib.parse
import json
import os
from datetime import datetime

def register_routes(app):
    from flask import render_template, redirect, url_for, flash, request, abort, jsonify, current_app
    from flask_login import login_required, current_user
    from extensions import db
    from models import MusicTrack, ListeningHistory, FavoriteTrack, Playlist, PlaylistItem, User
    from helpers import cloudinary_configured, upload_to_cloudinary, allowed_file, moderate_post, create_notification
    import cloudinary
    import cloudinary.uploader

    DEEZER_API = 'https://api.deezer.com'

    def deezer_search(query, limit=20):
        try:
            url = f'{DEEZER_API}/search?q={urllib.parse.quote(query)}&limit={limit}'
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
            return data.get('data', [])
        except:
            return []

    def deezer_get_track(track_id):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/track/{track_id}', timeout=10) as r:
                return json.loads(r.read())
        except:
            return None

    def deezer_get_album(album_id):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/album/{album_id}', timeout=10) as r:
                return json.loads(r.read())
        except:
            return None

    def deezer_get_artist(artist_id):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/artist/{artist_id}', timeout=10) as r:
                return json.loads(r.read())
        except:
            return None

    def deezer_get_artist_top(artist_id, limit=10):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/artist/{artist_id}/top?limit={limit}', timeout=10) as r:
                return json.loads(r.read()).get('data', [])
        except:
            return []

    def deezer_get_charts(limit=20):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/chart/0/tracks?limit={limit}', timeout=10) as r:
                return json.loads(r.read()).get('data', [])
        except:
            return []

    def deezer_get_playlist(playlist_id):
        try:
            with urllib.request.urlopen(f'{DEEZER_API}/playlist/{playlist_id}', timeout=10) as r:
                return json.loads(r.read())
        except:
            return None

    def track_from_deezer(d):
        existing = MusicTrack.query.filter_by(deezer_id=d['id']).first()
        if existing:
            return existing
        t = MusicTrack(
            title=d.get('title', 'Unknown'),
            artist=d.get('artist', {}).get('name', '') if isinstance(d.get('artist'), dict) else '',
            album=d.get('album', {}).get('title', '') if isinstance(d.get('album'), dict) else '',
            duration=d.get('duration', 0),
            preview_url=d.get('preview'),
            cover_url=d.get('album', {}).get('cover_medium', '') if isinstance(d.get('album'), dict) else '',
            deezer_id=d['id'],
            deezer_url=d.get('link'),
            source='deezer'
        )
        db.session.add(t)
        db.session.commit()
        return t

    @app.route('/music')
    @login_required
    def music_home():
        charts = deezer_get_charts(20)
        recent = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(10).all()
        favs = FavoriteTrack.query.filter_by(user_id=current_user.id).order_by(FavoriteTrack.created_at.desc()).limit(10).all()
        playlists = Playlist.query.filter_by(user_id=current_user.id).all()
        return render_template('music_home.html', charts=charts, recent=recent, favs=favs, playlists=playlists, track_from_deezer=track_from_deezer)

    @app.route('/music/search')
    @login_required
    def music_search():
        q = request.args.get('q', '').strip()
        results = deezer_search(q) if q else []
        return render_template('music_search.html', query=q, results=results, track_from_deezer=track_from_deezer)

    @app.route('/music/album/<int:album_id>')
    @login_required
    def music_album(album_id):
        data = deezer_get_album(album_id)
        if not data:
            flash('Альбом не найден')
            return redirect(url_for('music_home'))
        return render_template('music_album.html', album=data, track_from_deezer=track_from_deezer)

    @app.route('/music/artist/<int:artist_id>')
    @login_required
    def music_artist(artist_id):
        data = deezer_get_artist(artist_id)
        top = deezer_get_artist_top(artist_id, 20)
        if not data:
            flash('Исполнитель не найден')
            return redirect(url_for('music_home'))
        return render_template('music_artist.html', artist=data, top_tracks=top, track_from_deezer=track_from_deezer)

    @app.route('/music/track/<int:track_id>/play')
    @login_required
    def music_play_track(track_id):
        data = deezer_get_track(track_id)
        if not data:
            flash('Трек не найден')
            return redirect(url_for('music_home'))
        track = track_from_deezer(data)
        h = ListeningHistory(user_id=current_user.id, track_id=track.id)
        db.session.add(h)
        db.session.commit()
        return jsonify({
            'id': track.id,
            'title': track.title,
            'artist': track.artist,
            'preview_url': track.preview_url or '',
            'cover_url': track.cover_url or '',
            'duration': track.duration
        })

    @app.route('/music/local/<int:track_id>')
    @login_required
    def music_local_track(track_id):
        track = MusicTrack.query.get_or_404(track_id)
        if track.source == 'upload' and track.file_url:
            h = ListeningHistory(user_id=current_user.id, track_id=track.id)
            db.session.add(h)
            db.session.commit()
            return jsonify({
                'id': track.id,
                'title': track.title,
                'artist': track.artist,
                'file_url': track.file_url,
                'cover_url': track.cover_url or '',
                'duration': track.duration
            })
        return jsonify({'error': 'not found'}), 404

    @app.route('/music/favorite/<int:track_id>', methods=['POST'])
    @login_required
    def music_favorite(track_id):
        track = MusicTrack.query.get_or_404(track_id)
        existing = FavoriteTrack.query.filter_by(user_id=current_user.id, track_id=track.id).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify({'liked': False})
        f = FavoriteTrack(user_id=current_user.id, track_id=track.id)
        db.session.add(f)
        db.session.commit()
        return jsonify({'liked': True})

    @app.route('/music/playlist/create', methods=['GET', 'POST'])
    @login_required
    def music_create_playlist():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name:
                flash('Введите название плейлиста')
                return redirect(url_for('music_create_playlist'))
            p = Playlist(name=name, description=request.form.get('description', ''), user_id=current_user.id)
            db.session.add(p)
            db.session.commit()
            flash('Плейлист создан')
            return redirect(url_for('music_playlist', playlist_id=p.id))
        return render_template('music_create_playlist.html')

    @app.route('/music/playlist/<int:playlist_id>')
    @login_required
    def music_playlist(playlist_id):
        p = Playlist.query.get_or_404(playlist_id)
        if not p.is_public and p.user_id != current_user.id:
            flash('Плейлист приватный')
            return redirect(url_for('music_home'))
        return render_template('music_playlist.html', playlist=p)

    @app.route('/music/playlist/<int:playlist_id>/add', methods=['POST'])
    @login_required
    def music_playlist_add(playlist_id):
        p = Playlist.query.get_or_404(playlist_id)
        if p.user_id != current_user.id:
            return jsonify({'error': 'forbidden'}), 403
        track_id = request.form.get('track_id', type=int)
        if not track_id:
            return jsonify({'error': 'no track'}), 400
        track = MusicTrack.query.get(track_id)
        if not track:
            return jsonify({'error': 'track not found'}), 404
        existing = PlaylistItem.query.filter_by(playlist_id=p.id, track_id=track.id).first()
        if existing:
            return jsonify({'error': 'already in playlist'}), 400
        max_pos = db.session.query(db.func.max(PlaylistItem.position)).filter_by(playlist_id=p.id).scalar() or 0
        item = PlaylistItem(playlist_id=p.id, track_id=track.id, position=max_pos + 1)
        db.session.add(item)
        db.session.commit()
        return jsonify({'ok': True})

    @app.route('/music/playlist/<int:playlist_id>/remove/<int:item_id>', methods=['POST'])
    @login_required
    def music_playlist_remove(playlist_id, item_id):
        p = Playlist.query.get_or_404(playlist_id)
        if p.user_id != current_user.id:
            abort(403)
        item = PlaylistItem.query.get_or_404(item_id)
        db.session.delete(item)
        db.session.commit()
        return redirect(url_for('music_playlist', playlist_id=p.id))

    @app.route('/music/playlist/<int:playlist_id>/delete', methods=['POST'])
    @login_required
    def music_playlist_delete(playlist_id):
        p = Playlist.query.get_or_404(playlist_id)
        if p.user_id != current_user.id:
            abort(403)
        PlaylistItem.query.filter_by(playlist_id=p.id).delete()
        db.session.delete(p)
        db.session.commit()
        flash('Плейлист удалён')
        return redirect(url_for('music_home'))

    @app.route('/music/history')
    @login_required
    def music_history():
        history = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(50).all()
        return render_template('music_history.html', history=history)

    @app.route('/music/favorites')
    @login_required
    def music_favorites():
        favs = FavoriteTrack.query.filter_by(user_id=current_user.id).order_by(FavoriteTrack.created_at.desc()).all()
        return render_template('music_favorites.html', favs=favs)

    @app.route('/music/recommendations')
    @login_required
    def music_recommendations():
        recent_ids = [h.track_id for h in ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(5).all()]
        genres = set()
        for tid in recent_ids:
            t = MusicTrack.query.get(tid)
            if t and t.deezer_id:
                data = deezer_get_track(t.deezer_id)
                if data and data.get('artist', {}).get('id'):
                    genres.add(data['artist']['id'])
        recs = []
        for gid in list(genres)[:3]:
            recs.extend(deezer_get_artist_top(gid, 5))
        if not recs:
            recs = deezer_get_charts(20)
        return render_template('music_recommendations.html', recs=recs, track_from_deezer=track_from_deezer)

    @app.route('/music/upload', methods=['GET', 'POST'])
    @login_required
    def music_upload():
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            artist = request.form.get('artist', '').strip()
            file = request.files.get('file')
            if not file or not title:
                flash('Название и файл обязательны')
                return redirect(url_for('music_upload'))
            if cloudinary_configured:
                result = cloudinary.uploader.upload(file, folder='music', resource_type='video', timeout=30)
                file_url = result['secure_url']
            else:
                from werkzeug.utils import secure_filename
                filename = f'music_{current_user.id}_{int(datetime.utcnow().timestamp())}.mp3'
                file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))
                file_url = url_for('uploaded_file', filename=filename, _external=True)
            track = MusicTrack(title=title, artist=artist, file_url=file_url, source='upload', uploaded_by=current_user.id)
            db.session.add(track)
            db.session.commit()
            flash('Трек загружен')
            return redirect(url_for('music_home'))
        return render_template('music_upload.html')

    @app.route('/music/player')
    @login_required
    def music_player():
        """Returns player data: current queue, etc."""
        history = ListeningHistory.query.filter_by(user_id=current_user.id).order_by(ListeningHistory.listened_at.desc()).limit(20).all()
        tracks = [h.track for h in history if h.track]
        queue = [{'id': t.id, 'title': t.title, 'artist': t.artist, 'preview_url': t.preview_url or '', 'file_url': t.file_url or '', 'cover_url': t.cover_url or '', 'duration': t.duration} for t in tracks]
        return jsonify({'queue': queue})

    @app.route('/music/my_tracks')
    @login_required
    def music_my_tracks():
        favs = FavoriteTrack.query.filter_by(user_id=current_user.id).order_by(FavoriteTrack.created_at.desc()).limit(20).all()
        fav_tracks = [f.track for f in favs if f.track]
        uploads = MusicTrack.query.filter_by(uploaded_by=current_user.id, source='upload').order_by(MusicTrack.created_at.desc()).limit(20).all()
        seen = set()
        tracks = []
        for t in fav_tracks + uploads:
            if t.id not in seen:
                seen.add(t.id)
                tracks.append({
                    'id': t.id,
                    'title': t.title,
                    'artist': t.artist,
                    'cover_url': t.cover_url or '',
                    'duration': t.duration
                })
        return jsonify({'tracks': tracks})
