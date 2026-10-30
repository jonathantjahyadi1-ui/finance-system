"""Exercise reimburse uploads without connecting to production services."""

import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.datastructures import FileStorage

from extensions import db
from models import User
from reimburse.models import ReimburseItem, ReimburseRequest

with patch.dict(os.environ, {
    'SUPABASE_URL': 'https://example.supabase.co',
    'SUPABASE_SERVICE_ROLE_KEY': 'test-key',
}), patch('supabase.create_client', return_value=Mock()):
    from reimburse import routes


class ReimbursePDFTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(
            __name__, template_folder=str(Path(__file__).resolve().parents[1] / 'templates')
        )
        self.app.config.update(
            TESTING=True, SECRET_KEY='test', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:'
        )
        db.init_app(self.app)
        self.app.register_blueprint(routes.reimburse_bp, url_prefix='/reimburse')
        for endpoint in ('change_system', 'logout_view', 'main_dashboard'):
            self.app.add_url_rule('/' + endpoint, endpoint, lambda: '')
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        db.create_all()
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        self.user = User(username='Employee', password='test', role='karyawan')
        self.director = User(username='Director', password='test', role='direktur')
        self.other = User(username='Other', password='test', role='karyawan')
        db.session.add_all([self.user, self.director, self.other])
        db.session.commit()
        self.client = self.app.test_client()
        self.storage = Mock()
        self.bucket = self.storage.storage.from_.return_value
        self.bucket.create_signed_url.return_value = {
            'signedURL': 'https://example.supabase.co/signed/receipt.pdf'
        }
        self.storage_patch = patch.object(routes, 'supabase', self.storage)
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)

    def login(self, user):
        with self.client.session_transaction() as session:
            session['user_id'] = user.id

    def submit_receipts(self, *filenames):
        self.login(self.user)
        return self.client.post('/reimburse/submit', data={
            'item_name[]': ['Expense'] * len(filenames),
            'price[]': ['15000'] * len(filenames),
            'qty[]': ['2'] * len(filenames),
            'receipt[]': [(io.BytesIO(b'%PDF-1.4\n'), name) for name in filenames],
        }, content_type='multipart/form-data')

    def test_pdf_and_photo_receipts_can_be_submitted_together(self):
        response = self.submit_receipts('nota.PDF', 'photo.jpg', 'scan.png')
        self.assertEqual(response.status_code, 302)
        reimb = ReimburseRequest.query.one()
        self.assertEqual(reimb.total_amount, 90000)
        self.assertEqual(len(reimb.items), 3)
        self.assertEqual(self.bucket.upload.call_count, 3)
        mime_types = [call.kwargs['file_options']['content-type']
                      for call in self.bucket.upload.call_args_list]
        self.assertEqual(mime_types, ['application/pdf', 'image/jpeg', 'image/png'])
        html = self.client.get(f'/reimburse/detail/{reimb.id}').get_data(as_text=True)
        self.assertIn('Buka PDF', html)
        self.assertIn('receipt-thumb', html)
        self.assertNotIn(f'src="/reimburse/file/{reimb.items[0].receipt_photo}"', html)

    def test_pdf_content_type_overrides_generic_browser_type(self):
        file = FileStorage(
            stream=io.BytesIO(b'%PDF-1.4\n'), filename='scan.PDF',
            content_type='application/octet-stream',
        )
        path = routes.upload_reimburse_to_supabase(file, 'receipt')
        self.assertTrue(path.startswith('reimburse/receipt/'))
        self.assertEqual(
            self.bucket.upload.call_args.kwargs['file_options']['content-type'],
            'application/pdf',
        )

    def test_unsupported_file_is_rejected(self):
        response = self.submit_receipts('nota.html')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ReimburseRequest.query.count(), 0)
        self.bucket.upload.assert_not_called()
        with self.client.session_transaction() as session:
            self.assertIn('PDF', session['_flashes'][0][1])

    def test_director_can_upload_pdf_payment_proof(self):
        self.submit_receipts('nota.pdf')
        reimb = ReimburseRequest.query.one()
        self.login(self.director)
        form = self.client.get(f'/reimburse/detail/{reimb.id}').get_data(as_text=True)
        self.assertIn('application/pdf', form)
        response = self.client.post(f'/reimburse/detail/{reimb.id}', data={
            'payment_proof': (io.BytesIO(b'%PDF-1.4\n'), 'payment.pdf'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(reimb.status, 'paid')
        self.assertIsNotNone(reimb.paid_at)
        html = self.client.get(f'/reimburse/detail/{reimb.id}').get_data(as_text=True)
        self.assertIn('Buka bukti pembayaran (PDF)', html)
        self.assertNotIn('<img ', html)

    def test_pdf_file_access_remains_restricted(self):
        self.submit_receipts('nota.pdf')
        path = ReimburseItem.query.one().receipt_photo
        url = '/reimburse/file/' + path
        self.assertEqual(self.client.get(url).location,
                         'https://example.supabase.co/signed/receipt.pdf')
        self.bucket.create_signed_url.reset_mock()
        self.login(self.other)
        self.assertEqual(self.client.get(url).location, '/reimburse/list')
        self.bucket.create_signed_url.assert_not_called()
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get(url).location, '/login')

    def test_legacy_pdf_receipt_and_form(self):
        self.login(self.user)
        form = self.client.get('/reimburse/submit').get_data(as_text=True)
        self.assertIn('application/pdf', form)
        reimb = ReimburseRequest(user_id=self.user.id, receipt_photo='old.PDF')
        reimb.items.append(ReimburseItem(item_name='Old expense', price=1000, qty=1))
        db.session.add(reimb)
        db.session.commit()
        html = self.client.get(f'/reimburse/detail/{reimb.id}').get_data(as_text=True)
        self.assertIn('href="/uploads/old.PDF"', html)
        self.assertIn('Buka PDF', html)
        self.assertNotIn('<img ', html)


if __name__ == '__main__':
    unittest.main()
