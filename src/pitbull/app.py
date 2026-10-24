"""The localhost form bridge and Chromium launcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_urlsafe
from threading import Thread
from typing import Callable, Mapping
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class Request:
    """A normal HTML form submission received by a Python event handler."""

    event: str
    form: Mapping[str, str]
    query: Mapping[str, str]


@dataclass(frozen=True)
class Response:
    """An HTTP response returned from a Python event handler."""

    body: str = ""
    status: int = HTTPStatus.OK
    headers: Mapping[str, str] = field(default_factory=dict)


def redirect(path: str) -> Response:
    """Return a browser redirect after a successful form submission."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("redirect paths must be local absolute paths")
    return Response(status=HTTPStatus.SEE_OTHER, headers={"Location": path})


Handler = Callable[[Request], Response | str | None]


class App:
    """Serve an HTML directory and dispatch special form endpoints to Python.

    To invoke an event, use a standard HTML form with an action of
    ``/__pybridge__/events/<event-name>``. The bridge injects its capability token into forms it
    serves, so no JavaScript or handwritten authentication field is needed.
    """

    def __init__(self, web_root: str | Path, *, start_page: str = "index.html", title: str | None = None):
        self.web_root = Path(web_root).resolve()
        if not self.web_root.is_dir():
            raise ValueError(f"web_root is not a directory: {self.web_root}")
        self.start_page = self._safe_path(start_page)
        self.title = title
        self._token = token_urlsafe(32)
        self._events: dict[str, Handler] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._driver = None

    def event(self, name: str) -> Callable[[Handler], Handler]:
        """Register a Python handler for a JavaScript-free HTML form event."""
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError("event names must be a single non-empty path segment")

        def register(handler: Handler) -> Handler:
            if name in self._events:
                raise ValueError(f"event already registered: {name}")
            self._events[name] = handler
            return handler

        return register

    def render(self, name: str, /, **values: object) -> Response:
        """Render a page with escaped ``{{ name }}`` placeholders."""
        page = self._read_page(name)
        for key, value in values.items():
            page = page.replace("{{ " + key + " }}", escape(str(value)))
        return Response(
            self._inject_token(page), headers={"Content-Type": "text/html; charset=utf-8"}
        )

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("App is not running")
        return f"http://127.0.0.1:{self._server.server_port}/{self.start_page}"

    def start(self) -> None:
        """Start the private bridge server without launching a browser."""
        if self._server is not None:
            return
        app = self

        class BridgeHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                app._serve(self)

            def do_POST(self) -> None:  # noqa: N802
                app._post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), BridgeHandler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True, name="pitbull")
        self._thread.start()

    def run(self) -> None:
        """Start the bridge, launch Chromium with JavaScript disabled, and wait for exit."""
        self.start()
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.add_experimental_option(
            "prefs", {"profile.managed_default_content_settings.javascript": 2}
        )
        options.add_argument(f"--app={self.url}")
        self._driver = webdriver.Chrome(options=options)
        try:
            input("Press Enter to close pitbull... ")
        finally:
            self.stop()

    def stop(self) -> None:
        """Close the browser and private server. Safe to call more than once."""
        if self._driver is not None:
            self._driver.quit()
            self._driver = None
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _safe_path(self, requested: str) -> str:
        candidate = (self.web_root / requested.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.web_root)
        except ValueError as error:
            raise ValueError("path escapes web_root") from error
        return candidate.relative_to(self.web_root).as_posix()

    def _read_page(self, requested: str) -> str:
        path = self.web_root / self._safe_path(requested)
        return path.read_text(encoding="utf-8")

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        requested = parsed.path.lstrip("/") or self.start_page
        try:
            page = self._read_page(requested)
        except (ValueError, FileNotFoundError, IsADirectoryError):
            self._send(handler, Response("Not found", HTTPStatus.NOT_FOUND))
            return
        content_type = "text/html; charset=utf-8" if requested.endswith((".html", ".htm")) else "text/plain; charset=utf-8"
        if content_type.startswith("text/html"):
            page = self._inject_token(page)
        self._send(handler, Response(page, headers={"Content-Type": content_type}))

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        prefix = "/__pybridge__/events/"
        if not parsed.path.startswith(prefix):
            self._send(handler, Response("Not found", HTTPStatus.NOT_FOUND))
            return
        length = int(handler.headers.get("Content-Length", "0"))
        posted = parse_qs(handler.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        token = posted.pop("__pitbull_token", [""])[0]
        if token != self._token:
            self._send(handler, Response("Forbidden", HTTPStatus.FORBIDDEN))
            return
        event = parsed.path.removeprefix(prefix)
        callback = self._events.get(event)
        if callback is None or "/" in event:
            self._send(handler, Response("Not found", HTTPStatus.NOT_FOUND))
            return
        form = {key: value[-1] for key, value in posted.items()}
        query = {key: value[-1] for key, value in parse_qs(parsed.query).items()}
        try:
            result = callback(Request(event, form, query))
            response = redirect("/" + self.start_page) if result is None else result
            if isinstance(response, str):
                response = Response(response, headers={"Content-Type": "text/html; charset=utf-8"})
            if not isinstance(response, Response):
                raise TypeError("event handlers must return Response, str, or None")
        except Exception:
            self._send(handler, Response("Python event handler failed", HTTPStatus.INTERNAL_SERVER_ERROR))
            raise
        self._send(handler, response)

    def _inject_token(self, page: str) -> str:
        marker = 'action="/__pybridge__/events/'
        hidden = f'<input type="hidden" name="__pitbull_token" value="{self._token}">'
        sections = page.split("</form>")
        return "</form>".join(
            section + (hidden if marker in section.lower() else "") for section in sections[:-1]
        ) + sections[-1]

    @staticmethod
    def _send(handler: BaseHTTPRequestHandler, response: Response) -> None:
        data = response.body.encode("utf-8")
        handler.send_response(response.status)
        handler.send_header("Content-Length", str(len(data)))
        for key, value in response.headers.items():
            handler.send_header(key, value)
        handler.end_headers()
        handler.wfile.write(data)
