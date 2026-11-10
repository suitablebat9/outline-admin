import json
import smtplib
import time
import unittest
import uuid
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from app import create_app
import mailer
import metrics
import test_admin


class MessageTests(unittest.TestCase):
    def test_actual_profile_attachment_and_personal_key(self):
        msg=mailer.message('sender@example.com','alice@example.com','alice','ssconf://example.com/private.yaml')
        self.assertIn('ssconf://example.com/private.yaml',msg.get_body(preferencelist=('plain',)).get_content())
        attachments=list(msg.iter_attachments())
        self.assertEqual(len(attachments),1)
        self.assertEqual(attachments[0].get_filename(),'outline-dns.mobileconfig')
        self.assertEqual(attachments[0].get_content_type(),'application/x-apple-aspen-config')
        self.assertEqual(attachments[0].get_payload(decode=True),mailer.generate(['example.com']))

    def test_header_injection_and_multiple_recipients_rejected(self):
        for address in ['a@example.com\r\nBcc: b@example.com','a@example.com,b@example.com','Name <a@example.com>']:
            with self.assertRaises(ValueError):mailer.email_address(address)

    def test_tls_login_and_single_recipient_delivery(self):
        config={'host':'smtp.gmail.com','port':465,'security':'ssl','sender':'sender@example.com',
                'username':'sender@example.com','password':'test-only'}
        msg=mailer.message(config['sender'],'alice@example.com','alice','ssconf://example.com/key')
        with patch('mailer.smtplib.SMTP_SSL') as smtp:
            smtp.return_value.send_message.return_value={}
            mailer.send(config,msg)
            self.assertTrue(smtp.call_args.kwargs['context'].check_hostname)
            smtp.return_value.login.assert_called_once_with(config['username'],config['password'])
            smtp.return_value.send_message.assert_called_once_with(msg,from_addr=config['sender'],to_addrs=['alice@example.com'])
            smtp.return_value.close.assert_called_once()


class EmailApiTests(test_admin.Fixture):
    def setUp(self):
        super().setUp()
        self.smtp=self.root/'smtp.json'
        self.smtp.write_text(json.dumps({'sender':'sender@example.com','username':'sender@example.com',
            'password':'test-only-smtp-secret','host':'smtp.gmail.com','port':465,'security':'ssl'}))
        self.db=self.root/'email.sqlite3'
        self.app=create_app({'session_secret':'test','password_hash':generate_password_hash('test-pass'),
          'origin':'https://admin-vpn.example.com','secure_cookie':False,'smtp_config':str(self.smtp),
          'database':str(self.db),'config':str(self.config),'registry':str(self.state),
          'keydir':str(self.keydir),'lock':str(self.root/'lock'),'restart':lambda:None})
        self.app.testing=True
        self.client=self.app.test_client()
        self.csrf=self.client.get('/api/session').json['csrf']

    def login(self):
        result=self.client.post('/api/login',json={'username':'admin','password':'test-pass'},headers=self.headers())
        self.csrf=result.json['csrf']

    def headers(self):return {'X-CSRF-Token':self.csrf,'Origin':'https://admin-vpn.example.com'}

    def send(self,request_id=None,email='alice@example.com'):
        return self.client.post('/api/users/personal/email',json={'email':email,'request_id':request_id or str(uuid.uuid4())},headers=self.headers())

    def test_requires_authentication_and_csrf(self):
        with patch('mailer.send') as delivery:
            self.assertEqual(self.send().status_code,401)
            self.login()
            self.assertEqual(self.client.post('/api/users/personal/email',json={}).status_code,403)
            delivery.assert_not_called()

    def test_success_attachment_and_idempotency(self):
        self.login();request_id=str(uuid.uuid4())
        with patch('mailer.send') as delivery:
            self.assertEqual(self.send(request_id).status_code,200)
            self.assertEqual(self.send(request_id).status_code,200)
            delivery.assert_called_once()
            self.assertEqual(len(list(delivery.call_args.args[1].iter_attachments())),1)
            self.assertEqual(self.send(request_id,'bob@example.com').status_code,409)
        with metrics.connect(self.db) as db:
            text=str([tuple(row) for row in db.execute('SELECT * FROM email_jobs')])
            self.assertNotIn('alice@example.com',text)
            self.assertNotIn('ssconf://',text)

    def test_failed_auth_does_not_leak_secret_or_resend(self):
        self.login();request_id=str(uuid.uuid4())
        with patch('mailer.send',side_effect=smtplib.SMTPAuthenticationError(535,b'private server detail')) as delivery:
            result=self.send(request_id)
            self.assertEqual(result.status_code,502)
            self.assertNotIn('private server detail',result.text)
            self.assertNotIn('test-only-smtp-secret',result.text)
            self.assertEqual(self.send(request_id).status_code,409)
            delivery.assert_called_once()

    def test_missing_setup_and_revoked_key(self):
        self.login()
        with patch('mailer.send') as delivery:
            self.app.extensions['manager'].remove('personal')
            self.assertEqual(self.send().status_code,400)
            self.smtp.unlink()
            self.assertEqual(self.client.get('/api/email/status').json,{'ready':False,'sender':None})
            self.assertEqual(self.send().status_code,503)
            delivery.assert_not_called()

    def test_hourly_send_limit(self):
        self.login()
        with metrics.connect(self.db) as db:
            for i in range(20):
                db.execute('INSERT INTO email_jobs VALUES (?,?,?,?,?)',(str(i),'fingerprint',time.time(),'accepted','ok'))
        with patch('mailer.send') as delivery:
            self.assertEqual(self.send().status_code,429)
            delivery.assert_not_called()
