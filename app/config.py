from dotenv import load_dotenv
import os

load_dotenv()

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
MINIO_BUCKET = os.getenv('MINIO_BUCKET')
APP_SECRET = os.getenv('APP_SECRET')
SLACK_HOOK = os.getenv('SLACK_HOOK')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
RECAPTCHA_SITE_KEY = os.getenv('RECAPTCHA_SITE_KEY')
RECAPTCHA_SECRET_KEY = os.getenv('RECAPTCHA_SECRET_KEY')