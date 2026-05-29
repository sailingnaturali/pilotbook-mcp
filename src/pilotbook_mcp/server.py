"""pilotbook-mcp server. Exposes anchorage tools over stdio.

Vault directory comes from PILOTBOOK_VAULT_PATH (default ~/.pilotbook-vault).
"""

from __future__ import annotations

import asyncio
import json
import logging

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from pilotbook_mcp import tools
from pilotbook_mcp.vault import Vault

logger = logging.getLogger(__name__)

_FORECAST_STEP = {
    "type": "object",
    "properties": {
        "time": {"type": "string"},
        "wind_from_deg": {"type": "number"},
        "wind_kn": {"type": "number"},
        "swell_from_deg": {"type": ["number", "null"]},
        "swell_m": {"type": ["number", "null"]},
    },
    "required": ["wind_from_deg", "wind_kn"],
}


def dispatch(vault: Vault, name: str, args: dict) -> dict:
    """Route a tool call to its implementation. Shared by the server and tests."""
    if name == "find_anchorages_near":
        return tools.find_anchorages_near(
            vault, lat=args["lat"], lon=args["lon"], radius_nm=args.get("radius_nm", 10.0)
        )
    if name == "get_anchorage":
        return tools.get_anchorage(vault, name=args["name"])
    if name == "rank_anchorages":
        return tools.rank_anchorages_tool(vault, names=args["names"], forecast=args.get("forecast", []))
    if name == "list_sources":
        return tools.list_sources(vault)
    raise ValueError(f"Unknown tool: {name}")


def build_server(vault: Vault) -> Server:
    server = Server("pilotbook-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="find_anchorages_near",
                description="Anchorages within a radius of a position, nearest first, with exposure summary.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "radius_nm": {"type": "number", "description": "Search radius in nautical miles (default 10)."},
                    },
                    "required": ["lat", "lon"],
                },
            ),
            types.Tool(
                name="get_anchorage",
                description="Full record and verbatim pilot-book prose for one named anchorage.",
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            ),
            types.Tool(
                name="rank_anchorages",
                description=(
                    "Rank named anchorages by overnight comfort against a forecast. "
                    "Fetch the forecast from weather-mcp and pass it as `forecast` "
                    "(a list of steps with wind_from_deg, wind_kn, swell_from_deg, swell_m)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "names": {"type": "array", "items": {"type": "string"}},
                        "forecast": {"type": "array", "items": _FORECAST_STEP},
                    },
                    "required": ["names", "forecast"],
                },
            ),
            types.Tool(
                name="list_sources",
                description="The pilot books ingested into the vault.",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        result = dispatch(vault, name, arguments or {})
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    return server


async def _run() -> None:
    vault = Vault.load()
    logger.info("loaded %d anchorages from %s", len(vault.anchorages), vault.root)
    server = build_server(vault)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
