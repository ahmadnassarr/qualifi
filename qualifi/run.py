"""Start Qualifi on your own computer (development):  python run.py
For the live website use serve.py (or gunicorn wsgi:app on Linux hosting)."""
import os

from qualifi import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Qualifi is running: open http://localhost:{port} in your browser\n")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
