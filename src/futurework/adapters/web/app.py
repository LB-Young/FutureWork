"""Build the browser entry with its packaged static interface."""

from futurework.api.app import create_app as create_core_app


def create_app(home=None, db_path=None):
    """Expose the existing Web endpoints using the shared runtime."""
    return create_core_app(home, db_path, source="web")
