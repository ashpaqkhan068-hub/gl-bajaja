from tests.test_base import BaseTestCase
from database import get_db

class TestSupport(BaseTestCase):
    def test_support_message_creation_and_admin_notification(self):
        # 1. Customer visits contact page and submits a support message
        self.login('rahul.customer@example.com', 'Customer@12345')
        csrf = self.get_csrf()

        res = self.client.post('/contact', data={
            'name': 'Rahul Verma',
            'email': 'rahul.customer@example.com',
            'subject': 'Billing Query regarding AC Service',
            'message': 'I would like to clarify if materials are included in the initial estimate.',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Your message has been received and routed', res.data)

        # 2. Verify support message is saved with status 'open'
        with self.app.app_context():
            db = get_db()
            msg = db.execute("SELECT * FROM support_messages WHERE email = 'rahul.customer@example.com'").fetchone()
            self.assertIsNotNone(msg)
            self.assertEqual(msg['status'], 'open')
            self.assertEqual(msg['subject'], 'Billing Query regarding AC Service')
            msg_id = msg['id']

            # 3. Verify notification was created for Admin
            admin = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()
            admin_notif = db.execute("""
                SELECT * FROM notifications 
                WHERE user_id = ? AND link LIKE ?
            """, (admin['id'], f"%/admin/support/{msg_id}%")).fetchone()
            self.assertIsNotNone(admin_notif)
            self.assertIn("New Support Inquiry", admin_notif['title'])

        # 4. Admin logs in and views the support queue
        self.login('admin@kaamnearby.com', 'Admin@12345')
        res = self.client.get('/admin/support')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Billing Query regarding AC Service', res.data)
        self.assertIn(b'Rahul Verma', res.data)

        # 5. Admin opens the specific ticket detail page
        res = self.client.get(f'/admin/support/{msg_id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'I would like to clarify if materials are included', res.data)

        # 6. Admin updates status to 'resolved' with admin notes
        csrf = self.get_csrf()
        res = self.client.post(f'/admin/support/{msg_id}/update', data={
            'status': 'resolved',
            'admin_notes': 'Contacted customer via telephone and explained material pricing policy.',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b'marked as resolved', res.data)

        # 7. Verify ticket status is now 'resolved'
        with self.app.app_context():
            db = get_db()
            updated_msg = db.execute("SELECT * FROM support_messages WHERE id = ?", (msg_id,)).fetchone()
            self.assertEqual(updated_msg['status'], 'resolved')
            self.assertEqual(updated_msg['admin_notes'], 'Contacted customer via telephone and explained material pricing policy.')
            self.assertEqual(updated_msg['resolved_by'], admin['id'])

    def test_non_admin_cannot_access_support_management(self):
        # Customer cannot access /admin/support
        self.login('rahul.customer@example.com', 'Customer@12345')
        res = self.client.get('/admin/support')
        self.assertEqual(res.status_code, 403)

