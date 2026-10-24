"""A JavaScript-free, in-process HTML bridge rendered by PyQt5 WebEngine."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qs, urlparse


_SCHEME = b"pitbull"
_HOST = "app"
_SCHEME_REGISTERED = False


@dataclass(frozen=True)
class Request:
    """A plain HTML link or GET form submission received by a Python handler."""

    event: str
    form: Mapping[str, str]
    query: Mapping[str, str]


@dataclass(frozen=True)
class Response:
    """The HTML document to render after a Python handler finishes."""

    body: str = ""
    status: int = 200
    headers: Mapping[str, str] = field(default_factory=dict)


def redirect(path: str) -> Response:
    """Navigate to another ordinary local page or registered route."""
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("redirect paths must be local absolute paths")
    return Response(status=303, headers={"Location": path})


Handler = Callable[[Request], Response | str | None]


class App:
    """Render standard HTML and dispatch regular relative GET navigations to Python.

    HTML authors do not write custom schemes or Pitbull-specific attributes. A regular form such
    as ``<form action="/greet" method="get">`` invokes ``@app.event("greet")``. Relative links,
    stylesheets, images, and ordinary HTML pages are served from ``web_root`` inside the embedded
    WebEngine process; no localhost port or HTTP server is opened.
    """

    def __init__(self, web_root: str | Path, *, start_page: str = "index.html", title: str | None = None):
        self.web_root = Path(web_root).resolve()
        if not self.web_root.is_dir():
            raise ValueError(f"web_root is not a directory: {self.web_root}")
        self.start_page = self._safe_path(start_page)
        self.title = title
        self._routes: dict[str, Handler] = {}
        self._view = None
        self._handler = None

    def event(self, name: str) -> Callable[[Handler], Handler]:
        """Register the handler for the normal HTML path ``/<name>``."""
        if not name or "/" in name or name in {".", ".."}:
            raise ValueError("event names must be a single non-empty path segment")
        return self.route("/" + name)

    def route(self, path: str) -> Callable[[Handler], Handler]:
        """Register a handler for a normal, site-local path such as ``/account/save``."""
        normalized = self._route_path(path)

        def register(handler: Handler) -> Handler:
            if normalized in self._routes:
                raise ValueError(f"route already registered: {normalized}")
            self._routes[normalized] = handler
            return handler

        return register

    def render(self, name: str, /, **values: object) -> Response:
        """Render an HTML file with escaped ``{{ name }}`` placeholders."""
        page = self._read_text(name)
        for key, value in values.items():
            page = page.replace("{{ " + key + " }}", escape(str(value)))
        return Response(page, headers={"Content-Type": "text/html; charset=utf-8"})

    def run(self) -> int:
        """Open the JavaScript-disabled PyQt5 WebEngine window and run its event loop."""
        _register_scheme()
        from PyQt5 import QtWebEngine
        from PyQt5.QtCore import QCoreApplication, Qt
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

        if QApplication.instance() is not None:
            raise RuntimeError("Pitbull must be started before creating a QApplication")
        QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        QtWebEngine.QtWebEngine.initialize()
        qt_app = QApplication([])
        view = QWebEngineView()
        view.setWindowTitle(self.title or "Pitbull")
        view.resize(1024, 720)
        view.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, False)

        page = _BridgePage(self, view)
        view.setPage(page)
        self._handler = _StaticFileHandler(self, view.page().profile())
        view.page().profile().installUrlSchemeHandler(_SCHEME, self._handler)
        self._view = view
        view.setUrl(self._url("/" + self.start_page))
        view.show()
        return qt_app.exec_()

    def _url(self, path: str):
        from PyQt5.QtCore import QUrl

        return QUrl(f"{_SCHEME.decode()}://{_HOST}:8443{path}")

    def _route_path(self, path: str) -> str:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("routes must be local absolute paths")
        parsed = urlparse(path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("routes cannot include an origin, query, or fragment")
        return parsed.path.rstrip("/") or "/"

    def _safe_path(self, requested: str) -> str:
        candidate = (self.web_root / requested.lstrip("/")).resolve()
        try:
            candidate.relative_to(self.web_root)
        except ValueError as error:
            raise ValueError("path escapes web_root") from error
        return candidate.relative_to(self.web_root).as_posix()

    def _read_text(self, requested: str) -> str:
        return (self.web_root / self._safe_path(requested)).read_text(encoding="utf-8")

    def _request_from_url(self, url: str) -> Request:
        parsed = urlparse(url)
        route = self._route_path(parsed.path)
        values = {key: value[-1] for key, value in parse_qs(parsed.query, keep_blank_values=True).items()}
        return Request(event=route.removeprefix("/"), form=values, query=values)

    def _dispatch(self, request: Request) -> Response:
        callback = self._routes.get("/" + request.event)
        if callback is None:
            return Response("Not found", status=404)
        result = callback(request)
        if result is None:
            return redirect("/" + self.start_page)
        if isinstance(result, str):
            return Response(result, headers={"Content-Type": "text/html; charset=utf-8"})
        if not isinstance(result, Response):
            raise TypeError("route handlers must return Response, str, or None")
        return result

    def _read_static(self, path: str) -> tuple[bytes, bytes] | None:
        try:
            file_path = self.web_root / self._safe_path(path)
            if not file_path.is_file():
                return None
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            return content_type.encode(), file_path.read_bytes()
        except (ValueError, OSError):
            return None


def _register_scheme() -> None:
    """Register the private renderer scheme before PyQt creates its application object."""
    global _SCHEME_REGISTERED
    if _SCHEME_REGISTERED:
        return
    from PyQt5.QtWebEngineCore import QWebEngineUrlScheme

    scheme = QWebEngineUrlScheme(_SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.HostAndPort)
    scheme.setDefaultPort(8443)
    scheme.setFlags(
        QWebEngineUrlScheme.SecureScheme
        | QWebEngineUrlScheme.LocalScheme
        | QWebEngineUrlScheme.LocalAccessAllowed
    )
    QWebEngineUrlScheme.registerScheme(scheme)
    _SCHEME_REGISTERED = True


class _BridgePage:
    """Factory proxy so importing Pitbull does not require PyQt5 until ``run`` is called."""

    def __new__(cls, app: App, parent):
        from PyQt5.QtWebEngineWidgets import QWebEnginePage

        class Page(QWebEnginePage):
            def acceptNavigationRequest(self, url, navigation_type, is_main_frame):  # noqa: N802
                if is_main_frame and url.scheme() == _SCHEME.decode() and url.host() == _HOST:
                    request = app._request_from_url(url.toString())
                    if "/" + request.event in app._routes:
                        try:
                            response = app._dispatch(request)
                        except Exception as error:
                            self.setHtml(
                                f"<h1>Python handler failed</h1><pre>{escape(str(error))}</pre>",
                                app._url("/"),
                            )
                            return False
                        location = response.headers.get("Location")
                        if 300 <= response.status < 400 and location:
                            self.setUrl(app._url(location))
                        else:
                            self.setHtml(response.body, app._url("/"))
                        return False
                return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

        return Page(parent)


class _StaticFileHandler:
    """Factory proxy for an in-process static-file scheme handler."""

    def __new__(cls, app: App, parent):
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        from PyQt5.QtWebEngineCore import QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

        class Handler(QWebEngineUrlSchemeHandler):
            def requestStarted(self, job):  # noqa: N802
                if job.requestUrl().host() != _HOST:
                    job.fail(QWebEngineUrlRequestJob.UrlNotFound)
                    return
                static = app._read_static(job.requestUrl().path())
                if static is None:
                    job.fail(QWebEngineUrlRequestJob.UrlNotFound)
                    return
                content_type, data = static
                buffer = QBuffer(job)
                buffer.setData(QByteArray(data))
                buffer.open(QIODevice.ReadOnly)
                job.reply(content_type, buffer)

        return Handler(parent)
