"""End-to-end MCP smoke over STDIO — the transport the Agno agents will use.

Spawns `concept-omcp serve --transport stdio` as a subprocess, performs the JSON-RPC
initialize handshake, lists the tools, and calls each one. This validates the full
server.py path over the wire (tool registration + ConceptStore + JSON serialization)
and proves stdout stays clean JSON-RPC (any stray print would break the handshake).

    .venv/bin/python eval/mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# The model loads lazily on the first search; give that call room to warm up.
_TIMEOUT = timedelta(seconds=180)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "concept_omcp.cli", "serve", "--transport", "stdio"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            print("\nsearch_concepts('type 2 diabetes mellitus', Condition):")
            res = await session.call_tool(
                "search_concepts",
                {"query_text": "type 2 diabetes mellitus", "domain_filter": "Condition", "top_k": 3},
                read_timeout_seconds=_TIMEOUT,
            )
            hits = json.loads(res.content[0].text)
            for m in hits:
                print(f"  [{m['similarity_score']:.3f}] {m['concept_id']} {m['concept_name']} ({m['domain_id']})")

            print("\nget_concept_by_id(201826):")
            res = await session.call_tool("get_concept_by_id", {"concept_id": 201826}, read_timeout_seconds=_TIMEOUT)
            one = json.loads(res.content[0].text)
            if one:
                print(f"  {one['concept_name']} ({one['domain_id']}) parent={one['parent_concept_id']}")
            else:
                print("  (not found)")

            print("\nfind_concepts_by_relationship(['Is a'], limit=3):")
            res = await session.call_tool(
                "find_concepts_by_relationship",
                {"relationship_types": ["Is a"], "limit": 3},
                read_timeout_seconds=_TIMEOUT,
            )
            rel = json.loads(res.content[0].text)
            print(f"  {len(rel)} concepts: {[m['concept_id'] for m in rel]}")

    print("\n=== MCP stdio smoke OK ===")


if __name__ == "__main__":
    asyncio.run(main())
