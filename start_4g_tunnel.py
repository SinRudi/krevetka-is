import os
import re
import time
import sqlite3
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "sushi.db")

def save_url(url):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15.0)
        conn.execute("INSERT INTO settings (key, value) VALUES ('public_tunnel_url', ?) ON CONFLICT(key) DO UPDATE SET value=?", (url, url))
        conn.commit()
        conn.close()
    except Exception:
        pass

while True:
    try:
        proc = subprocess.Popen(
            ["ssh", "-T", "-o", "StrictHostKeyChecking=no", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=20", "-R", "80:127.0.0.1:5000", "nokey@localhost.run"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        for line in proc.stdout:
            print(line, end="", flush=True)
            m = re.search(r"(https://[a-zA-Z0-9.-]+\.lhr\.life)", line)
            if m:
                save_url(m.group(1))
        proc.wait()
    except Exception as e:
        print("Tunnel error:", e, flush=True)
    time.sleep(3)
