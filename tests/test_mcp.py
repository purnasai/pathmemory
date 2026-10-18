"""End-to-end over stdio against a scratch FalkorDB graph (needs the FalkorDB container)."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pathmemory.graph import GraphMemory
from pathmemory.state import State, Step

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.falkordb]

GRAPH = "pm_test_mcp"


def _seed():
    g = GraphMemory(GRAPH)
    g.clear()
    home, repo, settings_, collab, explore = (State("/", "/"), State("/:owner/:repo", "/:owner/:repo"),
                                              State("/:owner/:repo/settings", "/:owner/:repo/settings"),
                                              State("/:owner/:repo/settings/collaboration", "/:owner/:repo/settings/collaboration"),
                                              State("/explore/repos", "/explore/repos"))
    g.record_transition(home, Step("click", "link", "{owner}/{repo}"), repo)
    g.record_transition(repo, Step("click", "link", "Settings"), settings_)
    g.record_transition(settings_, Step("click", "link", "Collaborators"), collab)
    g.record_transition(home, Step("click", "link", "Explore"), explore)
    return g


async def _session(fn):
    params = StdioServerParameters(command=sys.executable, args=["-m", "pathmemory.mcp_server"],
                                   env={**os.environ, "PATHMEMORY_GRAPH": GRAPH})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return await fn(s)


def _data(res):
    return json.loads(res.content[0].text)


def test_mcp_tools_route_record_and_recover():
    _seed()

    async def go(s):
        names = {t.name for t in (await s.list_tools()).tools}
        assert names == {"list_pages", "resolve_url", "page_memory", "find_route", "record_step", "report_failure"}
        url = _data(await s.call_tool("resolve_url", {"url": "http://localhost:3300/byteblaze/dotfiles/settings"}))
        assert url["key"] == "/:owner/:repo/settings" and url["bindings"]["repo"] == "dotfiles" and url["known"]

        r = _data(await s.call_tool("find_route", {"from_page": "/", "to_page": "/:owner/:repo/settings/collaboration"}))
        first = r["routes"][0]["edges"][0]
        assert [e["name"] for e in r["routes"][0]["edges"]] == ["{owner}/{repo}", "Settings", "Collaborators"]

        # the dashboard link breaks: report it; with no alternative known yet there is no route
        assert _data(await s.call_tool("report_failure", {"step_id": first["eid"]}))["failures"] == 1
        r = _data(await s.call_tool("find_route", {"from_page": "/", "to_page": "/:owner/:repo/settings/collaboration",
                                                   "avoid": [first["eid"]]}))
        assert r["routes"] == []

        # the agent finds a way via Explore and teaches memory that one click; routes now compose
        rec = _data(await s.call_tool("record_step", {"from_url": "http://localhost:3300/explore/repos", "role": "link",
                                                      "name": "dotfiles", "to_url": "http://localhost:3300/byteblaze/dotfiles"}))
        assert rec["name"] == "{repo}"
        r = _data(await s.call_tool("find_route", {"from_page": "/", "to_page": "/:owner/:repo/settings/collaboration",
                                                   "avoid": [first["eid"]]}))
        assert [e["name"] for e in r["routes"][0]["edges"]] == ["Explore", "{repo}", "Settings", "Collaborators"]

        bad = await s.call_tool("record_step", {"from_url": "http://x/", "role": "button", "name": "Delete",
                                                "to_url": "http://x/"})
        assert bad.is_error
        bad = await s.call_tool("find_route", {"from_page": "/nope", "to_page": "/"})
        assert bad.is_error and "unknown page" in bad.content[0].text

    asyncio.run(_session(go))
    GraphMemory(GRAPH).clear()
