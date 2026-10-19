"""Web app factory; no duplicate imports, workers, or configuration side effects."""

import hmac
import os
import secrets
from collections import deque

from flask import Flask, jsonify, render_template, request, session

from . import VERSION
from .service import BusyError


def create_app(service, *, password=None, username=None):
    app = Flask(__name__)
    app.secret_key = secrets.token_bytes(32)
    app.config.update(
        MAX_CONTENT_LENGTH=64 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict"
    )
    password = os.environ.get("WEB_PASSWORD", "") if password is None else password
    username = username or os.environ.get("WEB_USERNAME", "admin")

    @app.before_request
    def protect():
        if request.path == "/healthz":
            return None
        if password:
            auth = request.authorization
            if not auth or not (
                hmac.compare_digest((auth.username or "").encode(), username.encode())
                and hmac.compare_digest((auth.password or "").encode(), password.encode())
            ):
                return (
                    jsonify(error="需要登录"),
                    401,
                    {"WWW-Authenticate": 'Basic realm="Hosts Updater", charset="UTF-8"'},
                )
        if request.method == "POST":
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
            if not expected or not hmac.compare_digest(str(supplied).encode(), expected.encode()):
                return jsonify(error="页面凭证已失效，请刷新后重试"), 403

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(BusyError)
    def busy(error):
        return jsonify(error=str(error)), 409

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", version=VERSION)

    @app.get("/")
    def index():
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "index.html",
            config=service.store.get().public(),
            version=VERSION,
            csrf_token=session["csrf_token"],
            auth_enabled=bool(password),
        )

    @app.get("/api/status")
    def status():
        return jsonify(service.status())

    @app.get("/api/config")
    def config():
        return jsonify(service.store.get().public())

    @app.post("/api/config")
    @app.post("/update_config")
    def update_config():
        values = request.get_json() if request.is_json else request.form.to_dict()
        if not isinstance(values, dict):
            raise ValueError("配置应为 JSON 对象")
        saved = service.save_config(values)
        return jsonify(
            success=True, message="配置已保存，下次任务使用新配置", config=saved.public()
        )

    @app.post("/run_speedtest")
    def run_speedtest():
        return jsonify(service.submit("speedtest")), 202

    @app.post("/update_hosts")
    def update_hosts():
        return jsonify(service.submit("cached")), 202

    @app.get("/api/containers")
    def containers():
        return jsonify(
            containers=[
                service.docker.status(name) for name in service.store.get().target_containers
            ]
        )

    @app.get("/api/hosts")
    def hosts():
        path = service.data_dir / "hosts"
        return jsonify(hosts=path.read_text(encoding="utf-8") if path.exists() else "")

    @app.get("/api/logs")
    def logs():
        count = max(1, min(request.args.get("lines", default=100, type=int), 1000))
        path = service.data_dir / "updater.log"
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                content = "".join(deque(stream, maxlen=count))
        except FileNotFoundError:
            content = "暂无运行日志"
        return jsonify(logs=content)

    return app
