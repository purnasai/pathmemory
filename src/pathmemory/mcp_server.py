"""MCP server: any agent (Claude Code, a browser agent, ...) can use PathMemory's FalkorDB memory.

    uv run python -m pathmemory.mcp_server        (stdio)

Read tools answer "where am I, where should I go, how do I get there"; write tools let the agent teach
memory a verified navigation step or report one that broke. Every tool runs fixed, parameterised Cypher;
no tool accepts Cypher, and only navigation clicks (links, tabs, menu items) can be stored.
"""

import functools
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from pathmemory.service import InvalidArgument, PathMemoryService


def _clear_errors(fn):
    """Return validation messages to the model so it can fix its arguments."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except InvalidArgument as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def build(graph_name: str = "pathmemory") -> MCPServer:
    svc = PathMemoryService(graph_name)
    server = MCPServer(
        name="pathmemory",
        instructions=(
            "Procedural memory of a website (a Gitea instance), stored in FalkorDB as page templates "
            "(e.g. /:owner/:repo/settings/collaboration) linked by verified navigation clicks. "
            "Typical use: resolve_url for the current page, list_pages to pick a destination, find_route to get "
            "the clicks, then report_failure for any click that no longer works and call find_route again with "
            "that step in `avoid`. Placeholders like {repo} in click names are filled with the task's values."
        ),
        log_level="ERROR",
    )

    @server.tool()
    @_clear_errors
    def list_pages() -> list[dict]:
        """Every known page template, its example title, and the past tasks that did their work there."""
        return svc.pages()

    @server.tool()
    @_clear_errors
    def resolve_url(url: str) -> dict:
        """Map a concrete URL to its page template and placeholder values, and say whether memory knows it."""
        return svc.resolve(url)

    @server.tool()
    @_clear_errors
    def page_memory(page: str) -> dict:
        """What memory knows about one page template: past tasks done there, their steps, and the verified clicks that leave it."""
        return svc.page_memory(page)

    @server.tool()
    @_clear_errors
    def find_route(from_page: str, to_page: str, avoid: list[str] | None = None) -> dict:
        """Up to 3 verified click routes between two page templates (shortest, least-failed first).
        Pass step ids in `avoid` to route around steps that are broken. Routes may combine steps learned in different tasks."""
        return svc.find_route(from_page, to_page, avoid)

    @server.tool()
    @_clear_errors
    def record_step(from_url: str, role: str, name: str, to_url: str) -> dict:
        """Teach memory one verified navigation click: on from_url, clicking the element (role link/tab/menuitem,
        accessible name) led to to_url. Names and URLs are templated automatically."""
        return svc.record_step(from_url, role, name, to_url)

    @server.tool()
    @_clear_errors
    def report_failure(step_id: str) -> dict:
        """Record that a remembered step (eid from find_route) did not work, so routes prefer alternatives."""
        return svc.report_failure(step_id)

    return server


def main():
    build(os.environ.get("PATHMEMORY_GRAPH", "pathmemory")).run()


if __name__ == "__main__":
    main()
