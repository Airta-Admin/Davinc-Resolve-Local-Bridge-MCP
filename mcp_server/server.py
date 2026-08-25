"""
Davinc-Resolve-Local-Bridge-MCP
===============================
Standalone MCP server that proxies tool calls to the Resolve Bridge HTTP server
running inside DaVinci Resolve.

Architecture:
    Agent <--MCP--> This Server <--HTTP--> Resolve Bridge (inside Resolve) <--Resolve API--> DaVinci Resolve

The Resolve Bridge script must be running inside DaVinci Resolve first:
    Workspace > Scripts > Bridge-Connection-Script

Usage:
    python -m resolve_mcp.server          # stdio transport (default)

The bridge HTTP server must be running on localhost:8787 for tools to work.

This server auto-discovers available actions from the bridge's /actions endpoint,
so it stays in sync with the bridge without manual tool definitions.
"""

import sys
import os
import json
import logging
import requests

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
)

logger = logging.getLogger("davinc-resolve-local-bridge-mcp")

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8787
BRIDGE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
TIMEOUT = 120


class ResolveBridgeClient:
    """HTTP client that talks to the Resolve Bridge running inside DaVinci Resolve."""

    def __init__(self, host=BRIDGE_HOST, port=BRIDGE_PORT):
        self.base_url = f"http://{host}:{port}"

    def _post(self, action, params=None, timeout=TIMEOUT):
        r = requests.post(
            f"{self.base_url}/action",
            json={"action": action, "params": params or {}},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()

    def _get(self, path, timeout=10):
        r = requests.get(f"{self.base_url}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()

    def health(self):
        try:
            return self._get("/health")
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_actions(self):
        try:
            data = self._get("/actions")
            return data.get("actions", [])
        except Exception:
            return []

    def call(self, action, **params):
        return self._post(action, params)


client = ResolveBridgeClient()

# ── Detect MCP SDK version ───────────────────────────────────────────────────
# MCP 2.x removed the @server.list_tools() / @server.call_tool() decorators
# from the low-level Server class and replaced them with on_* constructor params.
# We detect which API is available and register handlers accordingly.

import mcp as _mcp_module

_mcp_version = getattr(_mcp_module, "__version__", "0.0.0")
_mcp_major = int(_mcp_version.split(".")[0]) if _mcp_version != "0.0.0" else 1
_IS_MCP_V2 = _mcp_major >= 2

logger.info(f"MCP SDK version: {_mcp_version} (major={_mcp_major}, v2={_IS_MCP_V2})")


# ── Tool descriptions for known actions ──────────────────────────────────────
# Maps action names to human-readable descriptions for MCP tool definitions.
# Any action not listed here gets a generic description.

ACTION_DESCRIPTIONS = {
    "status": "Check if DaVinci Resolve bridge is running and get current project/timeline info. Always call this first to verify connectivity. The bridge script must be running inside Resolve via Workspace > Scripts > Bridge-Connection-Script.",
    "get_version": "Get DaVinci Resolve version information.",
    "get_current_page": "Get the currently active page in DaVinci Resolve.",
    "open_page": "Switch to a specific page in DaVinci Resolve. Pages: edit, fusion, color, deliver, media, cut, fairlight.",
    "create_project": "Create a new DaVinci Resolve project with specified resolution and frame rate.",
    "load_project": "Load an existing project by name from the current folder.",
    "save_project": "Save the current project.",
    "close_project": "Close the current project without saving.",
    "delete_project": "Delete a project from the current folder.",
    "import_media": "Import media files (video, audio, images) into the current project's media pool.",
    "get_media_pool": "List all clips in the media pool root folder.",
    "create_timeline": "Create a new empty timeline in the current project.",
    "list_timelines": "List all timelines in the current project.",
    "create_fusion_comp": "Create a new Fusion composition clip in the media pool.",
    "get_current_comp": "Get the current Fusion composition and list all its nodes.",
    "create_hand_animation": "Create a hand-drawing animation in the current Fusion composition following the Daniel Batal tutorial technique (Background transparent + Paint stroke with WriteOn keyframes + hand image Paint node).",
    "render": "Add a render job and start rendering. Switches to Deliver page.",
    "get_render_status": "Get the status of a render job by job ID.",
    "get_project_settings": "Get all settings of the current project.",
    "set_project_setting": "Set a specific project setting by key.",
    "get_render_formats": "Get available render formats.",
    "get_render_codecs": "Get available codecs for a given render format.",
    "set_render_settings": "Set render settings (TargetDir, CustomName, FormatWidth, FormatHeight, etc.).",
    "add_render_job": "Add a render job based on current render settings.",
    "start_rendering": "Start rendering queued jobs. Pass jobIds list or omit to render all.",
    "stop_rendering": "Stop any current rendering.",
    "is_rendering_in_progress": "Check if rendering is in progress.",
    "get_render_job_list": "List all render jobs in the queue.",
    "fusion_add_node": "Add a new node to the current Fusion composition (e.g. Background, Paint, Merge, MediaOut).",
    "fusion_connect": "Connect two Fusion nodes together.",
    "fusion_set_input": "Set an input value on a Fusion node. Can keyframe by passing frame parameter.",
    "fusion_get_input": "Get an input value from a Fusion node.",
    "fusion_get_tool_list": "List all tools/nodes in the current Fusion composition.",
    "fusion_set_current_frame": "Set the current frame in the Fusion composition.",
    "get_extension_status": "Read-only check for supported optional Resolve extensions, currently OpenCaptions and Rembg-Fuse.",
    "open_captions_list_templates": "List Text+ clips in the OpenCaptions 'Captions Templates' media-pool folder.",
    "fusion_add_rembg_node": "Add the installed Rembg-Fuse background-removal node to the current Fusion composition.",
    "generate_speech": "Generate speech audio using DaVinci Resolve's AI speech generation.",
    "create_subtitles_from_audio": "Auto-generate subtitles from timeline audio.",
    "detect_scene_cuts": "Detect and create scene cuts along the timeline.",
    "insert_title": "Insert a title into the timeline.",
    "insert_fusion_title": "Insert a Fusion title into the timeline.",
    "insert_fusion_composition": "Insert a Fusion composition into the timeline.",
    "set_item_property": "Set a property on the selected timeline item (Pan, Tilt, ZoomX, ZoomY, RotationAngle, CropLeft, etc.).",
    "get_item_property": "Get a property from the selected timeline item.",
    "stabilize": "Stabilize the selected clip.",
    "smart_reframe": "Perform Smart Reframe on the selected clip.",
}


def _build_tool_name(action):
    """Convert an action name like 'get_render_formats' to 'resolve_get_render_formats'."""
    if action.startswith("api_"):
        action = action[4:]
    return f"resolve_{action}"


def _build_tools():
    """Build the MCP tool list from the bridge's available actions."""
    tools = []
    actions = client.get_actions()

    if not actions:
        # Bridge not running - return a single health check tool
        tools.append(Tool(
            name="resolve_health",
            description="Check if DaVinci Resolve bridge is running. The bridge script must be "
                        "running inside Resolve via Workspace > Scripts > Bridge-Connection-Script. "
                        "If this returns an error, the bridge is not running.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ))
        return tools

    for action in actions:
        name = _build_tool_name(action)
        desc = ACTION_DESCRIPTIONS.get(action, f"DaVinci Resolve action: {action}")
        tools.append(Tool(
            name=name,
            description=desc,
            inputSchema={
                "type": "object",
                "properties": {
                    "params": {
                        "type": "object",
                        "description": f"Parameters for the '{action}' action. Pass all action parameters as keys in this object.",
                        "additionalProperties": True,
                    },
                },
                "required": [],
            },
        ))
    return tools


# ── Shared handler logic ─────────────────────────────────────────────────────

async def _handle_list_tools():
    """Return the list of available tools. Works with both MCP 1.x and 2.x."""
    tools = _build_tools()
    # MCP 1.x expects ListToolsResult; MCP 2.x expects a bare list
    if _IS_MCP_V2:
        return tools
    else:
        from mcp.types import ListToolsResult
        return ListToolsResult(tools=tools)


async def _handle_call_tool(name: str, arguments: dict):
    """Execute a tool call. Returns a list of TextContent."""
    try:
        # Convert tool name back to action name
        if name.startswith("resolve_"):
            action = name[8:]  # Remove "resolve_" prefix
        else:
            action = name

        # Special case: health check
        if action == "health":
            result = client.health()
        else:
            # Extract params - arguments may contain "params" dict or be the params directly
            params = arguments.get("params", arguments) if arguments else {}
            result = client.call(action, **params)

        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]

    except requests.ConnectionError:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": "Could not connect to Resolve Bridge. Make sure the bridge script is running "
                       "inside DaVinci Resolve via Workspace > Scripts > Bridge-Connection-Script",
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": str(e)}))]


# ── Register handlers with the Server ────────────────────────────────────────

if _IS_MCP_V2:
    # MCP 2.x: use on_* constructor params instead of decorators
    server = Server(
        "davinc-resolve-local-bridge-mcp",
        list_tools_handler=_handle_list_tools,
        call_tool_handler=_handle_call_tool,
    )
else:
    # MCP 1.x: use decorators
    server = Server("davinc-resolve-local-bridge-mcp")

    @server.list_tools()
    async def list_tools():
        return await _handle_list_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        return await _handle_call_tool(name, arguments)


# ── Entry point ──────────────────────────────────────────────────────────────

async def main():
    logging.basicConfig(level=logging.INFO)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run():
    """Console-script entry point."""
    import asyncio
    asyncio.run(main())


if __name__ == "__main__":
    run()
