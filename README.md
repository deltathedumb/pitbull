# pitbull

`pitbull` lets ordinary, JavaScript-free HTML talk to Python while rendered in Chromium.
It starts a private localhost server for your HTML, disables JavaScript in Chromium, and maps
normal HTML form posts to Python functions. It is a useful starting point for small desktop tools
where HTML/CSS provides layout and Python owns behavior.

## Install

```bash
pip install pitbull
```

You also need a locally installed Chromium, Chrome, or Edge. Selenium Manager normally finds or
downloads the matching driver automatically.

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

`web/index.html` needs no JavaScript:

```html
<!doctype html>
<title>Hello</title>
<form action="/__pybridge__/events/greet" method="post">
  <label>Name <input name="name" required></label>
  <button>Greet</button>
</form>
<p>{{ message }}</p>
```

## Security model

The bridge listens only on `127.0.0.1`, chooses an ephemeral port, and creates a random token.
Every bridge request must supply that token, which is injected into served bridge forms. Do not
expose this server to a network or put untrusted input directly into an HTML template.

## Scope

JavaScript is disabled through Chromium's managed content setting. This does **not** produce a
custom Chromium binary with V8 physically removed. Building and maintaining such a browser is a
separate Chromium-fork project, not something a normal PyPI wheel can safely distribute.
