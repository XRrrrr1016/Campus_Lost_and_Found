"""Run: python app.py (Python 3.11+, no third-party dependencies)."""
import argparse
import logging
import os
from pathlib import Path

from src.server import make_server

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='校园拾光 · 失物招领与智能匹配系统')
    parser.add_argument('--host', default=os.environ.get('CAMPUS_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('CAMPUS_PORT', '8000')))
    parser.add_argument('--db', default=os.environ.get('CAMPUS_DB', str(ROOT / 'data' / 'campus.sqlite3')))
    parser.add_argument('--init-only', action='store_true', help='仅幂等初始化数据库和样例')
    parser.add_argument('--no-seed', action='store_true', help='不添加样例物品，仍初始化演示账号和基础规则')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.init_only:
        from src.service import Service
        Service(args.db).initialize(seed=not args.no_seed)
        print('Database initialized.')
        return
    try:
        server = make_server(args.host, args.port, args.db, seed=not args.no_seed)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Cannot start service: {exc}\n')
    print(f'Campus Lost & Found: http://{args.host}:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
