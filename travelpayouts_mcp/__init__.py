"""Travelpayouts / Aviasales MCP server.

A dependency-free MCP server exposing Travelpayouts Data API (flight deals,
price calendars, popular directions) and Partner Links API (affiliate links)
to MCP clients: Claude Desktop/Code, Cursor, VS Code, DSH, etc.

Public API:
    __version__  package version
    serve()      run the stdio protocol loop
    main()       console entry point
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "main", "serve"]


def main(argv=None):
    from .server import main as _main

    return _main(argv)


def serve(stdin=None, stdout=None):
    from .server import serve as _serve

    return _serve(stdin=stdin, stdout=stdout)
