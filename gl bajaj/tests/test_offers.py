from tests.test_base import BaseTestCase
from database import get_db

class TestPriceNegotiation(BaseTestCase):
    def test_multi_round_negotiation_workflow(self):
        # Step 1: Customer creates booking with initial offer 400
        self.login('rahul.customer@example.com', 'Customer@12345')
        
        with self.app.app_context():
            db = get_db()
            worker = db.execute("SELECT id FROM workers WHERE category = 'Electrical Services'").fetchone()
            worker_id = worker['id']

        csrf = self.get_csrf()
        res = self.client.post(f'/customer/book/{worker_id}', data={
            'service': 'Electrical Services',
            'service_date': '2026-11-10',
            'service_time': 'Evening (3 PM - 7 PM)',
            'address': 'Plot 44, Alpha 1, Greater Noida',
            'description': 'Kitchen geyser wire loose and sparking.',
            'initial_offer': '400',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            db = get_db()
            b = db.execute("SELECT id FROM bookings WHERE description LIKE '%Kitchen geyser%'").fetchone()
            booking_id = b['id']

        # Step 2: Worker logs in and counters with 520
        self.login('suresh.electrician@example.com', 'Worker@12345')
        csrf = self.get_csrf()

        res = self.client.post(f'/worker/bookings/{booking_id}/offer', data={
            'amount': '520',
            'note': 'Geyser rewiring requires ceramic connector and insulation tape.',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Counter-offer of \xe2\x82\xb9520 sent', res.data)

        with self.app.app_context():
            db = get_db()
            booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            self.assertEqual(booking['status'], 'countered')
            self.assertEqual(booking['current_offer'], 520.0)

        # Step 3: Customer logs in and counters with 470
        self.login('rahul.customer@example.com', 'Customer@12345')
        csrf = self.get_csrf()

        res = self.client.post(f'/customer/bookings/{booking_id}/offer', data={
            'amount': '470',
            'note': 'Can you do 470? I already have high-grade insulation tape.',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Counter-offer of \xe2\x82\xb9470 sent', res.data)

        with self.app.app_context():
            db = get_db()
            booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            self.assertEqual(booking['status'], 'countered')
            self.assertEqual(booking['current_offer'], 470.0)

        # Step 4: Worker logs in and accepts customer's 470 offer
        self.login('suresh.electrician@example.com', 'Worker@12345')
        csrf = self.get_csrf()

        res = self.client.post(f'/worker/bookings/{booking_id}/accept', data={
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Booking is confirmed at \xe2\x82\xb9470', res.data)

        # Step 5: Verify booking is now Confirmed with agreed_price = 470
        with self.app.app_context():
            db = get_db()
            booking = db.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
            self.assertEqual(booking['status'], 'confirmed')
            self.assertEqual(booking['agreed_price'], 470.0)

            # Check offers history
            offers = db.execute("SELECT * FROM offers WHERE booking_id = ? ORDER BY id ASC", (booking_id,)).fetchall()
            self.assertEqual(len(offers), 3)
            self.assertEqual(offers[0]['amount'], 400.0)
            self.assertEqual(offers[0]['status'], 'superseded')
            self.assertEqual(offers[1]['amount'], 520.0)
            self.assertEqual(offers[1]['status'], 'superseded')
            self.assertEqual(offers[2]['amount'], 470.0)
            self.assertEqual(offers[2]['status'], 'accepted')

        # Step 6: Verify no new offer is accepted once confirmed
        res = self.client.post(f'/worker/bookings/{booking_id}/offer', data={
            'amount': '600',
            'csrf_token': csrf
        }, follow_redirects=True)
        self.assertIn(b'no longer in negotiation', res.data)

