import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


class Config:
    DEBUG = _env_bool('DEBUG', False)
    _raw_secret = os.getenv('SECRET_KEY')
    if DEBUG:
        SECRET_KEY = _raw_secret or 'dev-secret-key-change-me'
    else:
        if not _raw_secret or len(_raw_secret) < 32 or _raw_secret in {'change-this-secret', 'dev-secret-key-change-me'}:
            raise RuntimeError('SECRET_KEY must be set to a secure value (32+ chars) when DEBUG=False.')
        SECRET_KEY = _raw_secret

    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'SchoolSync')
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'pdf', 'docx', 'png', 'jpg', 'jpeg', 'zip'}
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USERNAME = ''
    MAIL_PASSWORD = ''
    OTP_EXPIRY_MINUTES = 10
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = not DEBUG
    SESSION_COOKIE_SAMESITE = 'Lax'

    # AI API keys
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    GROQ_MODEL = 'llama3-70b-8192'
    GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'

    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.8-flash')
    GEMINI_API_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent'

    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', 'meta-llama/llama-3.1-8b-instruct')
    OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'

    CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '')
    CLAUDE_API_URL = 'https://api.anthropic.com/v1/messages'
    CLAUDE_MODEL = 'claude-sonnet-4-6'