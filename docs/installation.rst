Installation
============

Requirements
------------

* Python 3.10 or newer.
* Runtime dependencies (installed automatically): ``httpx``, ``pydantic>=2``, ``tenacity``.

From PyPI
---------

.. code-block:: bash

   pip install easyvista-python-client

From source
-----------

.. code-block:: bash

   git clone https://github.com/baraline/easyvista_python_client.git
   cd easyvista_python_client
   pip install -e .

Development and documentation tooling
-------------------------------------

The optional ``dev`` extra installs the linters, type-checker, and test tooling; the ``docs`` extra
installs Sphinx and the theme used to build this site.

.. code-block:: bash

   pip install -e ".[dev]"
   pip install -e ".[docs]"

Building the documentation locally
-----------------------------------

.. code-block:: bash

   pip install -e ".[docs]"
   sphinx-build -b html -W docs docs/_build/html

Then open ``docs/_build/html/index.html`` in a browser. The ``-W`` flag turns warnings into errors,
matching the ReadTheDocs build (``fail_on_warning: true``).
