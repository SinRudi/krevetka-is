#!/usr/bin/env python3
"""Production entry point: init/migrate DB, then serve with waitress."""
import os

os.environ.setdefault('SUSHI_SKIP_INIT', '1')
from app import app, init_db  # noqa: E402

if __name__ == '__main__':
    init_db()
    from waitress import serve

    port = int(os.environ.get('SUSHI_PORT', '5000'))
    serve(app, host='0.0.0.0', port=port, threads=8)