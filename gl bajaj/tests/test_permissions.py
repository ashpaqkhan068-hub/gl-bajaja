from tests.test_base import BaseTestCase

class TestPermissions(BaseTestCase):
    def test_unauthenticated_protected_route_redirects(self):
        res = self.client.get('/customer/dashboard')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers['Location'])

    def test_customer_cannot_access_worker_dashboard(self):
        self.login('rahul.customer@example.com', 'Customer@12345')
        res = self.client.get('/worker/dashboard')
        self.assertEqual(res.status_code, 403)

    def test_customer_cannot_access_admin_dashboard(self):
        self.login('rahul.customer@example.com', 'Customer@12345')
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)

    def test_worker_cannot_access_admin_dashboard(self):
        self.login('suresh.electrician@example.com', 'Worker@12345')
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 403)

    def test_admin_can_access_admin_dashboard(self):
        self.login('admin@kaamnearby.com', 'Admin@12345')
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Platform Operations Overview', res.data)

