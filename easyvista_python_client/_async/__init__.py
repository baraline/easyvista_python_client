"""The client tree: one hand-written async surface, one generated sync twin.

This package exists twice, once per surface. Every module in it except
``_concurrency.py`` and ``tests/test_concurrency.py`` has a counterpart in the
other tree that ``unasync_build.py`` produces from the async one -- so the
async copy is the only place a change belongs, and the sync copy must never be
edited by hand. Run ``python unasync_build.py`` after any edit; CI's
``--check`` fails if the two trees have drifted.
"""

from easyvista_python_client._async.client import AsyncEasyvistaClient

__all__ = ["AsyncEasyvistaClient"]
