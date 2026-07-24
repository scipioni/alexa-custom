"""Web subpackage: the FastAPI ``app`` plus its routes.

Importing this package registers all routes on ``app`` (importing ``routes`` runs
its ``@app.*`` decorators)."""
from .app import app  # noqa: F401
from . import routes  # noqa: F401  (side effect: registers routes on `app`)
