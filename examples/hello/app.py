from pathlib import Path

from pitbull import App


app = App(Path(__file__).parent / "web", title="Python says hello")


@app.event("greet")
def greet(request):
    name = request.form.get("name", "friend")
    return app.render("index.html", message=f"Hello, {name}!")


app.run()
