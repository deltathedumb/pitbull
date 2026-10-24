from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from pitbull import App, redirect


@pytest.fixture
def app(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        '<form action="/__pybridge__/events/test" method="post"><button>Send</button></form>',
        encoding="utf-8",
    )
    instance = App(tmp_path)
    instance.start()
    yield instance
    instance.stop()


def test_served_forms_receive_capability_token(app: App):
    with urlopen(app.url) as response:
        page = response.read().decode()
    assert 'name="__pitbull_token"' in page


def test_render_escapes_values_and_keeps_the_token(app: App):
    (app.web_root / "greeting.html").write_text("<p>{{ text }}</p>", encoding="utf-8")
    response = app.render("greeting.html", text="<unsafe>")
    assert response.body == "<p>&lt;unsafe&gt;</p>"


def test_form_post_dispatches_to_python(app: App):
    received = {}

    @app.event("test")
    def handle(request):
        received.update(request.form)
        return "done"

    with urlopen(app.url) as response:
        page = response.read().decode()
    token = page.split('value="', 1)[1].split('"', 1)[0]
    request = Request(
        app.url.rsplit("/", 1)[0] + "/__pybridge__/events/test",
        data=urlencode({"__pitbull_token": token, "name": "Ada"}).encode(),
        method="POST",
    )
    with urlopen(request) as response:
        assert response.read() == b"done"
    assert received == {"name": "Ada"}


def test_redirect_requires_a_local_path():
    with pytest.raises(ValueError):
        redirect("https://example.com")
