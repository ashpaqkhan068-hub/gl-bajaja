from tests.test_base import BaseTestCase
from database import get_db

class TestVerifications(BaseTestCase):
    def test_worker_verification_and_admin_approval(self):
        # 1. Check pending worker (Dinesh Appliance Care, user_id=7 from seed)
        with self.app.app_context():
            db = get_db()
            dinesh = db.execute("""
                SELECT w.id, w.verification_status 
                FROM workers w 
                JOIN users u ON w.user_id = u.id 
                WHERE u.email = 'dinesh.repair@example.com'
            """).fetchone()
            self.assertEqual(dinesh['verification_status'], 'pending')

        # 2. Verify Dinesh is NOT visible in public services list
        res = self.client.get('/services')
        self.assertNotIn(b'Dinesh Appliance Care', res.data)

        # 3. Admin logs in
        self.login('admin@kaamnearby.com', 'Admin@12345')

        # 4. Find Dinesh's pending verification ID
        with self.app.app_context():
            db = get_db()
            v = db.execute("SELECT id FROM verifications WHERE worker_id = ? AND status = 'pending'", (dinesh['id'],)).fetchone()
            verif_id = v['id']

        # 5. Admin approves verification
        csrf = self.get_csrf()
        res = self.client.post(f'/admin/verifications/{verif_id}/review', data={
            'action': 'approve',
            'admin_note': 'Aadhaar ID and ITI technician credentials verified against official database.',
            'csrf_token': csrf
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        # 6. Verify Dinesh's status is now 'approved'
        with self.app.app_context():
            db = get_db()
            dinesh_after = db.execute("SELECT verification_status FROM workers WHERE id = ?", (dinesh['id'],)).fetchone()
            self.assertEqual(dinesh_after['verification_status'], 'approved')

        # 7. Now Dinesh SHOULD appear in public services list!
        res = self.client.get('/services')
        self.assertIn(b'Dinesh Appliance Care', res.data)

