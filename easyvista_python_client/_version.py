"""The package version, in a leaf module both ``__init__`` and ``config`` import.

``config.py`` builds the default ``User-Agent`` from it and is imported by
``__init__.py`` before ``__init__`` finishes executing, so the version cannot
live only in ``__init__``.
"""

__version__ = "0.2.0"
