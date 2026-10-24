from pathlib import Path

import pytest

from pitbull import App, redirect


@pytest.fixture
def app(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Home</h1>", encoding="utf-8")
    return App(tmp_path)


def test_get_form_values_are_dispatched_to_python(app: App):
    @app.event("greet")
    def greet(request):
        assert request.event == "greet"
        assert request.form == {"name": "Ada"}
        return app.render("index.html")

    response = app._dispatch(app._request_from_url("/greet?name=Ada"))
    assert response.body == "<h1>Home</h1>"


def test_normal_nested_routes_are_supported(app: App):
    @app.route("/account/save")
    def save(request):
        return "saved"

    assert app._dispatch(app._request_from_url("/account/save?draft=yes")).body == "saved"


def test_render_escapes_values(app: App):
    (app.web_root / "greeting.html").write_text("<p>{{ text }}</p>", encoding="utf-8")
    assert app.render("greeting.html", text="<unsafe>").body == "<p>&lt;unsafe&gt;</p>"


def test_redirect_requires_a_local_path():
    assert redirect("/next").status == 303
    with pytest.raises(ValueError):
        redirect("https://example.com")
