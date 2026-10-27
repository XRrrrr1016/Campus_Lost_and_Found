import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from src.server import make_server
except ImportError:
    make_server = None


class HttpTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(make_server, 'HTTP 服务尚未实现')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = make_server('127.0.0.1', 0, Path(self.tmp.name) / 'http.sqlite3')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.cookie, self.csrf = '', ''

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        final_headers = {'Cookie': self.cookie, 'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf}
        final_headers.update(headers or {})
        connection.request(method, path, json.dumps(data) if data is not None else None, final_headers)
        response = connection.getresponse()
        body, status, response_headers = response.read(), response.status, dict(response.getheaders())
        connection.close()
        if 'application/json' in response_headers.get('Content-Type', ''):
            body = json.loads(body)
        return status, body, response_headers

    def login(self, username='alice', password='demo1234'):
        status, result, headers = self.request('POST', '/api/login', {'username': username, 'password': password})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.csrf = result['data']['csrf']
        return result

    def test_public_api_masks_sensitive_fields(self):
        status, result, _ = self.request('GET', '/api/items')
        self.assertEqual(status, 200)
        self.assertGreater(len(result['data']), 0)
        self.assertNotIn('contact', json.dumps(result))
        self.assertNotIn('secret_hash', json.dumps(result))
        self.assertNotIn('password', json.dumps(result))

    def test_login_cookie_and_csrf_are_enforced(self):
        result = self.login()
        self.assertEqual(result['data']['user']['username'], 'alice')
        self.assertNotIn('token', result['data'])
        status, _, _ = self.request('POST', '/api/items/1/matches', {}, {'X-CSRF-Token': ''})
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/items/1/matches', {})
        self.assertEqual(status, 201)
        status, _, _ = self.request('POST', '/api/logout', {})
        self.assertEqual(status, 200)
        status, _, _ = self.request('GET', '/api/claims')
        self.assertEqual(status, 401)

    def test_permissions_errors_and_input_shape(self):
        self.login()
        status, _, _ = self.request('POST', '/api/rules', {'name': '越权', 'weights': {'text': 1}})
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/items', ['wrong shape'])
        self.assertEqual(status, 400)
        status, body, _ = self.request('GET', '/api/items?date_from=invalid')
        self.assertEqual(status, 400)
        self.assertIn('message', body['error'])
        self.assertIn('request_id', body['error'])

    def test_same_origin_validation(self):
        status, _, _ = self.request('POST', '/api/login', {'username': 'alice', 'password': 'demo1234'},
                                    {'Origin': 'https://evil.example'})
        self.assertEqual(status, 403)

    def test_static_frontend_and_path_boundaries(self):
        status, body, headers = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn('校园拾光'.encode(), body)
        self.assertIn('Content-Security-Policy', headers)
        for path in ('/../config.example', '/%2e%2e/src/service.py', '/data/campus.sqlite3'):
            status, _, _ = self.request('GET', path)
            self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
