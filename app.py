from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from flask_socketio import SocketIO, emit, join_room, leave_room
from wtforms import StringField, TextAreaField, SubmitField, PasswordField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from socket import gethostname, gethostbyname
import os
import cloudinary
import cloudinary.uploader
import tempfile
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))


@app.context_processor
def inject_stories():
    if current_user.is_authenticated:
        try:
            followers = current_user.followers.all()
            following = current_user.followed.all()
            follower_ids = [f.id for f in followers]
            following_ids = [f.id for f in following]
            user_ids = [current_user.id] + follower_ids + following_ids
            
            if user_ids:
                story_users = db.session.query(Story.user_id).filter(
                    Story.user_id.in_(user_ids),
                    Story.expires_at > datetime.utcnow()
                ).group_by(Story.user_id).limit(20).all()
                stories_list = []
                for (uid,) in story_users:
                    s = Story.query.filter(Story.user_id == uid, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
                    if s:
                        stories_list.append(s)
            else:
                stories_list = []
            my_story = Story.query.filter(Story.user_id == current_user.id, Story.expires_at > datetime.utcnow()).order_by(Story.created_at.desc()).first()
            has_story = my_story is not None
            return dict(top_stories=stories_list, my_story=my_story, user_has_story=has_story)
        except Exception as e:
            app.logger.error(f"Stories error: {e}")
            return dict(top_stories=[], my_story=None, user_has_story=False)
    return dict(top_stories=[], my_story=None, user_has_story=False)


def get_avatar_url(user):
    if user.avatar_cloudinary_url:
        return user.avatar_cloudinary_url
    if user.avatar and user.avatar != 'default.png':
        return url_for('uploaded_file', filename=user.avatar)
    return None


@app.context_processor
def inject_utils():
    return dict(get_avatar_url=get_avatar_url)


if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000, host='0.0.0.0')


def process_video(file_data, start_time=0, duration=None, quality='medium'):
    if cloudinary_configured and file_data.get('cloudinary_url'):
        public_id = file_data['cloudinary_url']
        transforms = {}
        if start_time:
            transforms['start_offset'] = str(start_time)
        if duration:
            transforms['duration'] = str(duration)
        if quality == 'low':
            transforms['quality'] = 'auto:low'
        elif quality == 'medium':
            transforms['quality'] = 'auto'
        else:
            transforms['quality'] = 'auto:best'
        return cloudinary.CloudinaryImage(public_id).build_url(**transforms)
    
    import ffmpeg
    
    try:
        input_path = file_data.get('temp_path')
        output_filename = f'processed_{datetime.now().timestamp()}.mp4'
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        
        stream = ffmpeg.input(input_path, ss=start_time)
        
        if duration:
            stream = ffmpeg.output(stream, output_path, t=duration, **{'preset': quality})
        else:
            stream = ffmpeg.output(stream, output_path, **{'preset': quality})
        
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        
        return output_filename
    except Exception as e:
        app.logger.error(f"Video processing error: {e}")
        return None


def generate_video_thumbnail(video_path, timestamp=1):
    if cloudinary_configured and video_path.startswith('http'):
        public_id = video_path
        return cloudinary.CloudinaryImage(public_id).build_url(
            start_offset=timestamp,
            format='jpg',
            width=300,
            crop='scale'
        )
    
    import ffmpeg
    
    try:
        output_filename = f'thumb_{datetime.now().timestamp()}.jpg'
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
        
        stream = ffmpeg.input(video_path, ss=timestamp)
        stream = ffmpeg.output(stream, output_path, vframes=1, format='image2', vcodec='mjpeg')
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True)
        
        return output_filename
    except Exception as e:
        app.logger.error(f"Thumbnail generation error: {e}")
        return None


@app.route('/video/process', methods=['POST'])
@login_required
def process_video_route():
    try:
        video = request.files.get('video')
        start_time = float(request.form.get('start_time', 0))
        duration = float(request.form.get('duration')) if request.form.get('duration') else None
        quality = request.form.get('quality', 'medium')
        
        if not video:
            return jsonify({'error': 'No video file'}), 400
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            video.save(tmp.name)
            temp_path = tmp.name
        
        result = process_video({'temp_path': temp_path}, start_time, duration, quality)
        
        try:
            os.unlink(temp_path)
        except:
            pass
        
        if result:
            return jsonify({'video_url': f'/media/{result}'})
        return jsonify({'error': 'Processing failed'}), 500
    except Exception as e:
        app.logger.error(f"Video process route error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/video/thumbnail', methods=['POST'])
@login_required
def video_thumbnail_route():
    try:
        video = request.files.get('video')
        timestamp = float(request.form.get('timestamp', 1))
        
        if not video:
            return jsonify({'error': 'No video file'}), 400
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
            video.save(tmp.name)
            temp_path = tmp.name
        
        thumb = generate_video_thumbnail(temp_path, timestamp)
        
        try:
            os.unlink(temp_path)
        except:
            pass
        
        if thumb:
            return jsonify({'thumbnail': f'/media/{thumb}'})
        return jsonify({'error': 'Thumbnail generation failed'}), 500
    except Exception as e:
        app.logger.error(f"Thumbnail route error: {e}")
        return jsonify({'error': str(e)}), 500


with app.app_context():
    try:
        from sqlalchemy import text
        is_postgres = 'postgresql' in app.config['SQLALCHEMY_DATABASE_URI']
        
        if is_postgres:
            result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='user' AND column_name='avatar_cloudinary_url'"))
            if not result.fetchone():
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN avatar_cloudinary_url VARCHAR(500)'))
                db.session.commit()
                app.logger.info("Added avatar_cloudinary_url column")
    except Exception as e:
        app.logger.info(f"Migration avatar_cloudinary_url: {e}")
