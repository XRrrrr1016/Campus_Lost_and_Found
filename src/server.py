import hmac
import json
import logging
import re
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .matching import ENGINE_VERSION
from .service import CATEGORIES, DomainError, Service

STATIC = Path(__file__).resolve().parent / 'static'
LOG = logging.getLogger('campus.http')


class Handler(BaseHTTPRequestHandler):
    server_version = 'CampusLostFound/1.0'

    def log_message(self, format, *args):
        pass  # Structured logs are emitted once per request by _handle.

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def _send(self, status, body, content_type='application/json; charset=utf-8', extra=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        return status

    def _json_body(self):
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise DomainError('请使用 application/json', 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            raise DomainError('请求长度无效') from None
        if length < 0 or length > 800_000:
            raise DomainError('请求体不得超过 800KB', 413)
        try:
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeDecodeError):
            raise DomainError('请求体必须为有效的 JSON 对象') from None

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            return ''
        return cookie['campus_session'].value if 'campus_session' in cookie else ''

    def _handle(self):
        request_id = uuid.uuid4().hex[:12]
        status = 500
        path = urlsplit(self.path).path
        try:
            # Reject DNS-rebinding hostnames and cross-origin browser mutations.
            host = self.headers.get('Host', '')
            port = self.server.server_address[1]
            if host not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
                raise DomainError('Host 不在本地允许列表', 403)
            if self.command != 'GET':
                origin = self.headers.get('Origin')
                if origin and origin != f'http://{host}':
                    raise DomainError('不允许跨站请求', 403)
            if not path.startswith('/api/'):
                if self.command != 'GET':
                    raise DomainError('路由不存在', 404)
                files = {'/': ('index.html', 'text/html; charset=utf-8'),
                         '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                         '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
                target = files.get(unquote(path))
                if not target:
                    raise DomainError('资源不存在', 404)
                status = self._send(200, (STATIC / target[0]).read_bytes(), target[1])
                return
            token = self._token()
            user = self.server.service.session(token)
            body = self._json_body() if self.command != 'GET' else {}
            if self.command != 'GET' and path != '/api/login':
                self.server.service._require_user(user)
                if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), user['csrf']):
                    raise DomainError('会话校验失败，请刷新后重试', 403)
            data, code, extra = self._route(path, user, token, body)
            status = self._send(code, {'data': data}, extra=extra)
        except DomainError as exc:
            status = self._send(exc.status, {'error': {'message': str(exc), 'request_id': request_id}})
        except Exception:
            LOG.exception('request_failed request_id=%s', request_id)
            status = self._send(500, {'error': {'message': '服务器内部错误，请根据请求编号查看日志', 'request_id': request_id}})
        finally:
            LOG.info(json.dumps({'request_id': request_id, 'method': self.command, 'path': path, 'status': status}, ensure_ascii=False))

    def _route(self, path, user, token, body):
        s, method = self.server.service, self.command
        extra, code = {}, 200
        if method == 'GET' and path == '/api/health':
            data = {'status': 'ok', 'engine_version': ENGINE_VERSION}
        elif method == 'GET' and path == '/api/meta':
            data = {'categories': CATEGORIES, 'engine_version': ENGINE_VERSION, 'ai_mode': 'offline-simulator'}
        elif method == 'GET' and path == '/api/session':
            data = {'user': {k: v for k, v in user.items() if k != 'csrf'} if user else None,
                    'csrf': user['csrf'] if user else ''}
        elif method == 'POST' and path == '/api/login':
            result = s.login(body.get('username'), body.get('password'))
            data = {'user': result['user'], 'csrf': result['csrf']}
            extra['Set-Cookie'] = f'campus_session={result["token"]}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'
        elif method == 'POST' and path == '/api/logout':
            s.logout(token)
            data = {'ok': True}
            extra['Set-Cookie'] = 'campus_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
        elif method == 'GET' and path == '/api/items':
            query = {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query).items()}
            data = s.list_items(query, user)
        elif method == 'POST' and path == '/api/items':
            data, code = s.create_item(user, body), 201
        elif (match := re.fullmatch(r'/api/items/(\d+)', path)) and method in ('GET', 'DELETE'):
            iid = int(match[1])
            data = s.get_item(iid, user) if method == 'GET' else s.delete_item(user, iid, body.get('reason'))
        elif (match := re.fullmatch(r'/api/items/(\d+)/matches', path)) and method == 'POST':
            data, code = s.recommend(user, int(match[1])), 201
        elif (match := re.fullmatch(r'/api/items/(\d+)/claims', path)) and method == 'POST':
            data, code = s.create_claim(user, int(match[1]), body), 201
        elif method == 'GET' and path == '/api/claims':
            data = s.list_claims(user)
        elif (match := re.fullmatch(r'/api/claims/(\d+)/review', path)) and method == 'POST':
            data = s.review_claim(user, int(match[1]), body.get('decision'), body.get('note', ''))
        elif (match := re.fullmatch(r'/api/claims/(\d+)/complete', path)) and method == 'POST':
            data = s.close_claim(user, int(match[1]))
        elif method == 'GET' and path == '/api/rules':
            data = s.list_rules()
        elif method == 'POST' and path == '/api/rules':
            data, code = s.publish_rule(user, body.get('name'), body.get('weights')), 201
        elif method == 'GET' and path == '/api/recommendations':
            data = s.list_recommendations(user)
        elif (match := re.fullmatch(r'/api/recommendations/(\d+)/recompute', path)) and method == 'POST':
            data = s.recompute(user, int(match[1]))
        elif method == 'GET' and path == '/api/audits':
            data = s.list_audits(user)
        else:
            raise DomainError('路由不存在', 404)
        return data, code, extra


def make_server(host, port, db_path, seed=True):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('演示服务仅允许本地监听 127.0.0.1 或 localhost')
    service = Service(db_path)
    service.initialize(seed=seed)
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.service = service
    return server
