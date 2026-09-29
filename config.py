import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-this-secret')
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

    # AI API keys
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    GROQ_MODEL = 'llama3-70b-8192'
    GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'

    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    GEMINI_MODEL = 'gemini-1.5-flash'
    GEMINI_API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent'

    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL = 'meta-llama/llama-3.1-8b-instruct:free'
    OPENROUTER_API_URL = 'https://openrouter.ai/api/v1/chat/completions'

    CLAUDE_API_KEY = os.getenv('CLAUDE_API_KEY', '')
    CLAUDE_MODEL = 'claude-sonnet-4-6'