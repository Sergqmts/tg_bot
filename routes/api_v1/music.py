from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import MusicTrack, FavoriteTrack, db
from . import api_v1
import requests as req

DEEZER_API = 'https://api.deezer.com'


@api_v1.route('/music/search', methods=['GET'])
@jwt_required()
def music_search():
    q = request.args.get('q', '')
    try:
        r = req.get(f'{DEEZER_API}/search?q={q}&limit=30', timeout=5)
        return jsonify({'ok': True, 'tracks': r.json().get('data', [])})
    except Exception:
        return jsonify({'ok': True, 'tracks': []})


@api_v1.route('/music/favorites', methods=['GET'])
@jwt_required()
def favorites():
    uid = int(get_jwt_identity())
    favs = FavoriteTrack.query.filter_by(user_id=uid).all()
    return jsonify({'ok': True, 'tracks': [
        {
            'id': f.track.id, 'title': f.track.title,
            'artist': f.track.artist,
            'preview_url': f.track.preview_url,
            'cover_url': f.track.cover_url,
        }
        for f in favs if f.track
    ]})


@api_v1.route('/music/favorite/<int:track_id>', methods=['POST'])
@jwt_required()
def toggle_favorite(track_id):
    uid = int(get_jwt_identity())
    fav = FavoriteTrack.query.filter_by(user_id=uid, track_id=track_id).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({'ok': True, 'favorited': False})
    db.session.add(FavoriteTrack(user_id=uid, track_id=track_id))
    db.session.commit()
    return jsonify({'ok': True, 'favorited': True})
