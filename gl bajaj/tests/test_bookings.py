from tests.test_base import BaseTestCase
from database import get_db

class TestBookings(BaseTestCase):
    def test_customer_create_booking(self):
        self.login('rahul.customer@example.com', 'Customer@12345')

        with self.app.app_context():
            db = get_db()
            worker = db.execute("SELECT id FROM workers WHERE category = 'Electrical Services'").fetchone()
            worker_id = worker['id']

        csrf = self.get_csrf()
        res = self.client.post(f'/customer/book/{worker_id}', data={
            'service': 'Electrical Services',
            'service_date': '2026-11-05',
            'service_time': 'Morning (9 AM - 12 PM)',
            'address': 'Tower 4, Flat 301, Sector 62, Noida',
            'description': 'Fan regulator burning smell and needs replacement.',
            'initial_offer': '380',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'submitted successfully', res.data)

        with self.app.app_context():
            db = get_db()
            booking = db.execute("SELECT * FROM bookings WHERE customer_id = 2 ORDER BY id DESC LIMIT 1").fetchone()
            self.assertIsNotNone(booking)
            self.assertEqual(booking['service'], 'Electrical Services')
            self.assertEqual(booking['initial_offer'], 380.0)
            self.assertEqual(booking['status'], 'pending')

            # Initial offer record exists
            offer = db.execute("SELECT * FROM offers WHERE booking_id = ?", (booking['id'],)).fetchone()
            self.assertIsNotNone(offer)
            self.assertEqual(offer['amount'], 380.0)

    def test_unauthorized_user_cannot_view_booking(self):
        # Create second customer
        self.client.get('/register')
        csrf = self.get_csrf()
        self.client.post('/register', data={
            'role': 'customer',
            'name': 'Other Customer',
            'email': 'other.cust@example.com',
            'city': 'Delhi',
            'password': 'Password@123',
            'confirm_password': 'Password@123',
            'agree_terms': '1',
            'csrf_token': csrf
        }, follow_redirects=True)

        # Login as second customer
        self.login('other.cust@example.com', 'Password@123')

        # Try to view first customer's booking #1 (from seeded database)
        res = self.client.get('/customer/bookings/1')
        self.assertEqual(res.status_code, 404)

