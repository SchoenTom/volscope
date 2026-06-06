"""Pytest bootstrap.

Importing :mod:`volscope` first is mandatory in this environment: the
Anaconda-packaged CPython 3.13.9 emits a ``sys.version`` string with two
``| ... |`` segments that breaks the stdlib ``platform._sys_version()``
parser. ``volscope.__init__`` normalises ``sys.version`` on import, so
pulling it in here — before pytest's terminal reporter calls
``platform.python_version()`` in ``pytest_sessionstart`` — keeps the
whole test session from dying with an ``INTERNALERROR``.
"""
import volscope  # noqa: F401
