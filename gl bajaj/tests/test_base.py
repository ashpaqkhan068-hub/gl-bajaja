import unittest
import os
import tempfile
from app import create_app
import database
from config import TestingConfig

class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        
        class CustomTestConfig(TestingConfig):
            DATABASE = self.db_path
            TESTING = True
            SECRET_KEY = 'test-secret-key-1234'
            WTF_CSRF_ENABLED = False

        self.app = create_app(CustomTestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            database.init_db(self.app)
            database.seed_db(self.app)

    def tearDown(self):
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except PermissionError:
                pass

    def login(self, email, password):
        # Clear any existing session first to allow clean user switching in tests
        self.client.get('/logout')
        res = self.client.get('/login')
        csrf_token = self.get_csrf()

        return self.client.post('/login', data={
            'email': email,
            'password': password,
            'csrf_token': csrf_token
        }, follow_redirects=True)

    def get_csrf(self):
        with self.client.session_transaction() as sess:
            return sess.get('csrf_token', '')
