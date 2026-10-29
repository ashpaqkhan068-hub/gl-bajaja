import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'kaamnearby-secret-key-prod-random-2026')
    DATABASE = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'instance', 'kaamnearby.db'))
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads', 'verifications'))
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    ITEMS_PER_PAGE = 8

class DevelopmentConfig(Config):
    DEBUG = True

class TestingConfig(Config):
    TESTING = True
    DEBUG = False
    DATABASE = os.path.join(BASE_DIR, 'instance', 'test_kaamnearby.db')
    SECRET_KEY = 'test-secret-key-1234'
    WTF_CSRF_ENABLED = False

class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

