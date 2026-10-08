"""Markdown <-> EasyVista memo HTML conversion: the optional ``content`` extra.

Install it with ``pip install "easyvista-python-client[content]"``. Importing
this subpackage without the extra raises :class:`ImportError` naming that
command. Nothing else in the package imports it, so ``import
easyvista_python_client`` needs none of the extra's dependencies, and
:class:`~easyvista_python_client.EasyvistaContentError` -- the error the
converter raises -- lives in the core package, catchable either way. The
one exception: called from within a few frames of the recursion limit,
the converter can let a bare :class:`RecursionError` through, having no
stack left to report it otherwise (see ``docs/content.rst``).
"""

from __future__ import annotations

from easyvista_python_client.content.conversion import (
    EasyvistaContentConverter,
    Link,
    RewriteLink,
)

__all__ = ["EasyvistaContentConverter", "Link", "RewriteLink"]
