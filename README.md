# pitbull

`pitbull` lets ordinary, JavaScript-free HTML talk to Python while rendered in PyQt5 WebEngine
(Chromium). It maps normal relative links and GET form submissions to Python functions in-process:
no localhost server, browser automation driver, JavaScript, or custom URL syntax in your HTML.

## Install

```bash
pip install pitbull
```

PyQt5 WebEngine is installed automatically as a package dependency.

## Example

```python
from pathlib import Path
from pitbull import App

app = App(Path("web"), title="Hello")

@app.event("greet")
def greet(request):
    name = request.form.get("name", "friend")
    return app.render("index.html", message=f"Hello, {name}!")

app.run()
```

## JavaScript toggle

JavaScript is disabled by default. Opt in at startup with
`App(Path("web"), javascript_enabled=True)`, or change it at runtime:

```python
app.set_javascript_enabled(True)  # Reloads the current page by default.
```

To preserve the JavaScript-free model, only enable it for pages you trust.

`web/index.html` needs no JavaScript:

```html
<!doctype html>
<title>Hello</title>
<form action="/greet" method="get">
  <label>Name <input name="name" required></label>
  <button>Greet</button>
</form>
<p>{{ message }}</p>
```

## Security model

Pitbull has no listening socket. It creates an internal renderer-only URL scheme and restricts
static files to `web_root`. Templates escape values supplied to `app.render`; do not put untrusted
input directly into raw HTML strings returned from a handler.

## Plain HTML constraint

Use ordinary relative links and GET forms. For example, `action="/greet"` calls
`@app.event("greet")`, and `href="/settings.html"` opens a file in `web_root`. PyQt5 does not
reliably expose POST form bodies through its navigation callback, so use `method="get"` for Python
events. No `pitbull://` URL needs to appear in authored HTML.

## Scope

JavaScript is disabled through Chromium's managed content setting. This does **not** produce a
custom Chromium binary with V8 physically removed. Building and maintaining such a browser is a
separate Chromium-fork project, not something a normal PyPI wheel can safely distribute.
