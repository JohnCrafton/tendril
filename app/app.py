from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from minio import Minio
from config import *
import uuid
import logging
import re
import requests
import random
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from flask_session import Session
from redis import Redis
from datetime import datetime, timedelta
from minio.commonconfig import CopySource


# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

app.secret_key = APP_SECRET
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=True
)

# Supported video formats; making sure at least webm, iphone, and common android are represented
SUPPORTED_VIDEO_FORMATS = ['video/webm', 'video/mp4', 'video/quicktime', 'video/3gpp']

app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = Redis(host='redis', port=6379)
Session(app)

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict'  # or 'Lax' if needed
)

def sanitize_email_for_path(email):
    """Convert email to safe path format"""
    return email.replace('@', '_at_').replace('.', '_dot_')

def send_verification_email(email, code):
    message = Mail(
        from_email='your-email@example.com',
        to_emails=email,
        subject='Your Verification Code',
        html_content=f'<strong>Your verification code is {code}</strong>')
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        return response.status_code == 202
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False

def send_to_slack(message):
    slack_message = {
        'text': message
    }
    logger.info(f"Sending message to Slack: {slack_message}")
    try:
        result = requests.post(SLACK_HOOK, json=slack_message)
        logger.info(f"Slack response: {result.text}")
    except Exception as e:
        logger.error(f"Error sending Slack message: {str(e)}")

def send_error_to_slack(error_message, error_metadata=None):
    slack_message = f":rotating_light: <@tonweight>\n*{error_message}*"
    if error_metadata:
        slack_message += f"\n```{error_metadata}```"
    send_to_slack(slack_message)

# def verify_recaptcha(response):
#     payload = {
#         'secret': RECAPTCHA_SECRET_KEY,
#         'response': response
#     }
#     logging.info(f"Verifying reCAPTCHA with payload: {payload}")
#     r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=payload)
#     result = r.json()
#     logging.info(f"reCAPTCHA result: {result}")
#     return result.get('success', False)

@app.route('/')
def index():
    if 'email' not in session:
        return redirect(url_for('email_capture'))

    # render the video.html template with email set to the session email
    return render_template('video.html', email=session['email'])

# @app.route('/send-code', methods=['POST'])
# def send_code():
#     email = request.form.get('email')
#     recaptcha_response = request.form.get('g-recaptcha-response')

#     if not EMAIL_REGEX.match(email):
#         return jsonify({'error': 'Invalid email address'}), 400

#     if not verify_recaptcha(recaptcha_response):
#         return jsonify({'error': 'Invalid reCAPTCHA. Please try again.'}), 400

#     code = random.randint(100000, 999999)
#     session['verification_code'] = code
#     session['email'] = email

#     if send_verification_email(email, code):
#         return jsonify({'success': True})
#     else:
#         return jsonify({'error': 'Failed to send verification email'}), 500

# @app.route('/verify-code', methods=['POST'])
# def verify_code():
#     code = request.form.get('code')
#     if 'verification_code' not in session or str(session['verification_code']) != code:
#         return jsonify({'error': 'Invalid or expired verification code'}), 400

#     session.pop('verification_code', None)
#     return jsonify({'success': True})

@app.route('/email', methods=['GET', 'POST'])
def email_capture():
    if request.method == 'POST':
        email = request.form.get('email')
        # recaptcha_response = request.form.get('g-recaptcha-response')

        if not EMAIL_REGEX.match(email):
            return render_template('email.html', error="Please enter a valid email address", site_key=RECAPTCHA_SITE_KEY)

        # if not verify_recaptcha(recaptcha_response):
        #     return render_template('email.html', error="Invalid reCAPTCHA. Please try again.", site_key=RECAPTCHA_SITE_KEY)

        session['email'] = email

        # send a success message to slack hook
        send_to_slack(f"New login for:  {session['email']}")

        return redirect(url_for('index'))

    return render_template('email.html', site_key=RECAPTCHA_SITE_KEY)

# serve favicon.ico from the static directory
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')

# serve robots.txt from the static directory
@app.route('/robots.txt')
def robots_txt():
    return app.send_static_file('robots.txt')

@app.route('/upload', methods=['POST'])
def upload_video():
    if 'email' not in session:
        send_error_to_slack('No email in session', 'Session expired')
        return jsonify({'error': 'Session expired'}), 401

    if 'video' not in request.files:
        send_error_to_slack('No video file in request', f"User: {session.get('email')}")
        return jsonify({'error': 'No video file'}), 400

    file_type = 'video/webm'
    file_type_extension = 'webm'
    video_file = request.files['video']

    # check the filetype (for uploaded instead of recorded videos)
    if video_file.mimetype != 'video/webm':
        # if in accepted formats:
        if video_file.mimetype not in SUPPORTED_VIDEO_FORMATS:
            send_error_to_slack('Invalid file type', f"User: {session.get('email')}")
            return jsonify({'error': 'Invalid file type'}), 400
        else:
            logger.info(f"Accepted file type: {video_file.mimetype}")
            file_type = video_file.mimetype
            file_type_extension = video_file.filename.split('.')[-1]

    # Check file size
    video_file.seek(0, 2)
    file_size = video_file.tell()
    video_file.seek(0)

    if file_size == 0:
        send_error_to_slack('Received empty file', f"User: {session.get('email')}")
        return jsonify({'error': 'Empty file'}), 400

    logger.info(f'Uploading file of size: {file_size} bytes')

    video_id = str(uuid.uuid4())
    email_path = sanitize_email_for_path(session['email'])
    object_path = f"videos/{email_path}/{video_id}.{file_type_extension.lower()}"

    try:
        minio_client.put_object(
            MINIO_BUCKET,
            object_path,
            video_file,
            file_size,
            file_type
        )
        logger.info(f'Successfully uploaded video {object_path}')

        # send a success message to slack hook
        slack_message = {
            'text': f"New video uploaded by {session['email']}: {object_path}"
        }
        requests.post(SLACK_HOOK, json=slack_message)

        return jsonify({'success': True, 'video': object_path})
    except Exception as e:
        error_message = f'Upload failed: {str(e)}'
        error_metadata = f"User: {session.get('email')}\nFile size: {file_size} bytes\nStack trace:\n{traceback.format_exc()}"
        logger.error(error_message)
        send_error_to_slack(error_message, error_metadata)
        return jsonify({'error': error_message}), 500

@app.route('/my-videos')
def my_videos():
    if 'email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    email_path = sanitize_email_for_path(session['email'])
    videos = []

    try:
        # List objects in user's directory
        objects = minio_client.list_objects(MINIO_BUCKET, f"videos/{email_path}/")
        for obj in objects:
            logger.debug(f"Object: {obj.object_name}, Size: {obj.size}, Last Modified: {obj.last_modified}, Type: {type(obj.last_modified)}")
            # if the object name ends with a supported video format
            if obj.object_name.endswith(tuple(['webm', 'mp4', 'mov', '3gpp'])):
                # Generate presigned URL for video access
                url = minio_client.presigned_get_object(
                    MINIO_BUCKET,
                    obj.object_name,
                    expires=timedelta(hours=1)
                )
                name = obj.object_name.split('/')[-1]

                logger.info(f"Name: {name}")
                logger.info(f"Presigned URL for {obj.object_name}: {url}")

                videos.append({
                    'name': name,
                    'url': url,
                    'date': obj.last_modified.isoformat() if hasattr(obj.last_modified, 'isoformat') else str(obj.last_modified)
                })
    except Exception as e:
        logger.error(f"Error listing videos: {str(e)}")
        return jsonify({'error': str(e)}), 500

    return jsonify(videos)

@app.route('/delete-video/<video_id>')
def delete_video(video_id):
    if 'email' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    email_path = sanitize_email_for_path(session['email'])
    source_path = f"videos/{email_path}/{video_id}"
    archive_path = f"archive/{email_path}/{video_id}"

    try:
        # Copy to archive
        copy_source = CopySource(MINIO_BUCKET, source_path)
        minio_client.copy_object(
            MINIO_BUCKET,
            archive_path,
            copy_source
        )
        # Delete original
        minio_client.remove_object(MINIO_BUCKET, source_path)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting video: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)