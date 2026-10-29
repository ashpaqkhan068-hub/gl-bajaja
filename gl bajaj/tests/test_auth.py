from tests.test_base import BaseTestCase
from database import get_db

class TestAuth(BaseTestCase):
    def test_customer_registration(self):
        self.client.get('/register')
        csrf = self.get_csrf()

        res = self.client.post('/register', data={
            'role': 'customer',
            'name': 'Pooja Sharma',
            'email': 'pooja.sharma@example.com',
            'phone': '9876543211',
            'city': 'Greater Noida',
            'password': 'SecurePassword@123',
            'confirm_password': 'SecurePassword@123',
            'agree_terms': '1',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Welcome to KaamNearby', res.data)

        with self.app.app_context():
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = 'pooja.sharma@example.com'").fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user['role'], 'customer')

    def test_worker_registration(self):
        self.client.get('/register')
        csrf = self.get_csrf()

        res = self.client.post('/register', data={
            'role': 'worker',
            'name': 'Vijay Mistri',
            'email': 'vijay.worker@example.com',
            'phone': '9876543212',
            'city': 'Noida',
            'category': 'Carpentry',
            'starting_price': '450',
            'experience_years': '4',
            'service_area': 'Sector 62',
            'bio': 'Woodwork and doors repair specialist',
            'password': 'SecurePassword@123',
            'confirm_password': 'SecurePassword@123',
            'agree_terms': '1',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            db = get_db()
            user = db.execute("SELECT * FROM users WHERE email = 'vijay.worker@example.com'").fetchone()
            self.assertIsNotNone(user)
            self.assertEqual(user['role'], 'worker')

            worker = db.execute("SELECT * FROM workers WHERE user_id = ?", (user['id'],)).fetchone()
            self.assertIsNotNone(worker)
            self.assertEqual(worker['category'], 'Carpentry')
            self.assertEqual(worker['verification_status'], 'pending')

    def test_duplicate_registration_rejected(self):
        self.client.get('/register')
        csrf = self.get_csrf()

        # Existing customer email seeded in database
        res = self.client.post('/register', data={
            'role': 'customer',
            'name': 'Duplicate Person',
            'email': 'rahul.customer@example.com',
            'city': 'Noida',
            'password': 'Password@123',
            'confirm_password': 'Password@123',
            'agree_terms': '1',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertIn(b'already exists', res.data)

    def test_login_success_and_logout(self):
        res = self.login('rahul.customer@example.com', 'Customer@12345')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Welcome back, Rahul Verma!', res.data)

        # Logout
        res = self.client.get('/logout', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'signed out safely', res.data)

    def test_invalid_login_rejected(self):
        res = self.login('rahul.customer@example.com', 'WrongPassword123')
        self.assertIn(b'Invalid email or password', res.data)

