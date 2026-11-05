"""Production entrypoint: Waitress WSGI server instead of the Flask dev server."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app, init_db  # noqa: E402
from waitress import serve  # noqa: E402


def main():
    init_db()
    host = os.environ.get("SUSHI_HOST", "0.0.0.0")
    port = int(os.environ.get("SUSHI_PORT", "5000"))
    threads = int(os.environ.get("SUSHI_THREADS", "8"))
    serve(app, host=host, port=port, threads=threads, ident="KrevetkaIS")


if __name__ == "__main__":
    main()
