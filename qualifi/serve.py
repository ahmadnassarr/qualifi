"""Run Qualifi with a production server (Waitress, works on Windows, macOS and Linux):  python serve.py
Settings come from environment variables or the .env file (see .env.example)."""
import os

from waitress import serve

from wsgi import app

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  Qualifi (production server) listening on http://{host}:{port}\n")
    serve(app, host=host, port=port, threads=int(os.environ.get("QUALIFI_THREADS", 8)))
