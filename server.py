import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "users.db"
DATA_DIR.mkdir(exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'Learning Explorer',
            interests TEXT DEFAULT '[]',
            avatar TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


init_db()


class AppHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.OK)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._send_json({"status": "ok"})
            return

        if path == "/api/profile":
            username = (query.get("username", [""])[0] or "").strip()
            if not username:
                self._send_json({"error": "username is required"}, status=400)
                return

            user = self._get_user_by_username(username)
            if not user:
                self._send_json({"error": "user not found"}, status=404)
                return

            self._send_json({"user": self._serialize_user(user)})
            return

        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/auth/login":
            self._handle_login()
            return

        if path == "/api/auth/register":
            self._handle_register()
            return

        self._send_json({"error": "not found"}, status=404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/profile":
            self._handle_update_profile()
            return

        self._send_json({"error": "not found"}, status=404)

    def _handle_login(self):
        payload = self._read_json()
        identifier = (payload.get("identifier") or payload.get("username") or "").strip()
        password = (payload.get("password") or "").strip()

        if not identifier or not password:
            self._send_json({"error": "username/email and password are required"}, status=400)
            return

        user = self._get_user_by_username(identifier) or self._get_user_by_email(identifier)
        if not user:
            self._send_json({"error": "user not found"}, status=404)
            return

        if user["password"] != password:
            self._send_json({"error": "invalid password"}, status=401)
            return

        self._send_json({"user": self._serialize_user(user)})

    def _handle_register(self):
        payload = self._read_json()
        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip()
        password = (payload.get("password") or "").strip()
        username = (payload.get("username") or name).strip()
        avatar = (payload.get("avatar") or "").strip()

        if not name or not email or not password or not username:
            self._send_json({"error": "name, email, password, and username are required"}, status=400)
            return

        if self._get_user_by_username(username):
            self._send_json({"error": "username already exists"}, status=409)
            return

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            INSERT INTO users (username, name, email, password, role, interests, avatar, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                username,
                name,
                email,
                password,
                payload.get("role") or "Learning Explorer",
                json.dumps(payload.get("interests") or ["Python", "Web Development", "Data Science"]),
                avatar or None,
            ),
        )
        conn.commit()
        conn.close()

        self._send_json({"message": "account created"}, status=201)

    def _handle_update_profile(self):
        payload = self._read_json()
        username = (payload.get("username") or "").strip()
        if not username:
            self._send_json({"error": "username is required"}, status=400)
            return

        user = self._get_user_by_username(username)
        if not user:
            self._send_json({"error": "user not found"}, status=404)
            return

        name = (payload.get("name") or user["name"]).strip()
        email = (payload.get("email") or user["email"]).strip()
        role = (payload.get("role") or user["role"] or "Learning Explorer").strip()
        interests = payload.get("interests")
        if interests is None:
            interests = json.loads(user["interests"] or "[]")
        else:
            interests = interests if isinstance(interests, list) else [str(interests)]
        avatar = payload.get("avatar")
        if avatar is None:
            avatar = user["avatar"]

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            """
            UPDATE users
            SET name = ?, email = ?, role = ?, interests = ?, avatar = ?
            WHERE username = ?
            """,
            (name, email, role, json.dumps(interests), avatar, username),
        )
        conn.commit()
        conn.close()

        updated = self._get_user_by_username(username)
        self._send_json({"user": self._serialize_user(updated)})

    def _get_user_by_username(self, username):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _get_user_by_email(self, email):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def _serialize_user(self, user):
        return {
            "id": user["id"],
            "username": user["username"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "interests": json.loads(user["interests"] or "[]"),
            "avatar": user["avatar"],
        }

    def _read_json(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, path):
        if path in ("/", ""):
            target = ROOT / "index.html"
        else:
            target = ROOT / path.lstrip("/")

        if not target.exists() or target.is_dir():
            self._send_json({"error": "not found"}, status=404)
            return

        content_type = "text/html"
        if target.suffix == ".css":
            content_type = "text/css"
        elif target.suffix == ".js":
            content_type = "application/javascript"
        elif target.suffix == ".json":
            content_type = "application/json"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(target.read_bytes())

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), AppHandler)
    print("Backend running at http://127.0.0.1:8000")
    server.serve_forever()
