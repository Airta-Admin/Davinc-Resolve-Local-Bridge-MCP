#!/usr/bin/env python3
"""
Installation helper for Davinc-Resolve-Local-Bridge-MCP.

Copies the bridge script to DaVinci Resolve's Scripts/Utility folder
and prints MCP configuration for popular AI harnesses.
"""

import os
import sys
import shutil
import platform

def get_resolve_scripts_dir():
    """Get the DaVinci Resolve scripts directory for this platform."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "Roaming", "Blackmagic Design",
                          "DaVinci Resolve", "Support", "Fusion", "Scripts", "Utility")
    elif system == "Darwin":
        return os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility")
    else:  # Linux
        return os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts/Utility")

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bridge_src = os.path.join(script_dir, "bridge", "Bridge-Connection-Script.py")

    if not os.path.exists(bridge_src):
        print("ERROR: Bridge-Connection-Script.py not found in bridge/ folder")
        sys.exit(1)

    scripts_dir = get_resolve_scripts_dir()

    print("=" * 60)
    print("Davinc-Resolve-Local-Bridge-MCP - Installation")
    print("=" * 60)
    print()

    # Step 1: Copy bridge script
    print("Step 1: Install bridge script into Resolve")
    print(f"  Source: {bridge_src}")

    if os.path.exists(scripts_dir):
        dest = os.path.join(scripts_dir, "Bridge-Connection-Script.py")
        shutil.copy2(bridge_src, dest)
        print(f"  Copied to: {dest}")
        print("  OK!")
    else:
        print(f"  WARNING: Resolve scripts directory not found at:")
        print(f"  {scripts_dir}")
        print(f"  Please copy Bridge-Connection-Script.py manually.")
    print()

    # Step 2: Install MCP server
    print("Step 2: Install MCP server dependencies")
    print("  Run: pip install -r requirements.txt")
    print()

    # Step 3: Print MCP config
    server_path = os.path.join(script_dir, "mcp_server", "server.py")
    print("Step 3: Add MCP configuration to your AI harness")
    print()
    print("For Claude Desktop (claude_desktop_config.json):")
    print(f'''{{
  "mcpServers": {{
    "davinci-resolve-local-bridge": {{
      "command": "python",
      "args": ["{server_path}"]
    }}
  }}
}}''')
    print()
    print("For Cursor (.cursor/mcp.json):")
    print(f'''{{
  "mcpServers": {{
    "davinci-resolve-local-bridge": {{
      "command": "python",
      "args": ["{server_path}"]
    }}
  }}
}}''')
    print()
    print("For Devin (mcp_config.json):")
    print(f'''{{
  "mcpServers": {{
    "resolve-local-bridge": {{
      "command": "python",
      "args": ["{server_path}"]
    }}
  }}
}}''')
    print()

    # Step 4: Instructions
    print("Step 4: Start the bridge inside DaVinci Resolve")
    print("  1. Open DaVinci Resolve")
    print("  2. Go to Workspace > Scripts > Bridge-Connection-Script")
    print("  3. You should see '[Resolve Bridge] HTTP server running on http://127.0.0.1:8787'")
    print()
    print("Done! Your AI assistant can now control DaVinci Resolve.")

if __name__ == "__main__":
    main()
