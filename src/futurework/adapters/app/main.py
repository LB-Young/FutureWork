"""Run the shared Web adapter inside an optional pywebview desktop shell."""

import threading
import time

import uvicorn

from futurework.adapters.web.app import create_app
from futurework.config import load_config
from futurework.home import ensure_home


def launch(home=None):
    """Start a local-only API and display the same interface in a native window."""
    try:
        import webview
    except ImportError as error:
        raise RuntimeError("desktop App requires the optional pywebview package") from error
    selected_home = ensure_home(home)
    config = load_config(selected_home)
    host = "127.0.0.1"
    port = config["server"]["port"]
    server = uvicorn.Server(uvicorn.Config(create_app(selected_home), host=host, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("desktop App could not start its local service")
    try:
        webview.create_window("FutureWork", f"http://{host}:{port}/")
        webview.start()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
