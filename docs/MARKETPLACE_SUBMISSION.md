# MCP Marketplace Submission Guide

This guide explains how to submit **Davinc-Resolve-Local-Bridge-MCP** to the official MCP Registry so it can be discovered and installed by users of Claude, Cursor, Devin, and other MCP-compatible clients.

## Overview

The **MCP Registry** (hosted at `registry.modelcontextprotocol.io`) is the official, centralized metadata catalog for publicly accessible MCP servers. It is backed by Anthropic, GitHub, PulseMCP, and Microsoft. The registry hosts **metadata** (not code) — it tells clients where to find your server and how to run it.

Downstream directories and marketplaces (like PulseMCP, Smithery, etc.) pull from this registry to provide search, ratings, and discovery for end users.

## Prerequisites

1. **GitHub account** — used for authentication with the registry
2. **PyPI account** — our MCP server is Python-based, so it must be published to PyPI first
3. **The `mcp-publisher` CLI tool** — installed from the registry repo

## Step 1 — Publish the Package to PyPI

The MCP Registry only hosts metadata, not artifacts. The actual package must live on PyPI.

```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# Upload to PyPI
twine upload dist/*
```

Before publishing, ensure the package README contains the ownership verification marker:

```markdown
<!-- mcp-name: io.github.Airta-Admin/davinc-resolve-local-bridge-mcp -->
```

This hidden HTML comment must be in the README that gets included in the PyPI package. The registry validator checks for this string to verify ownership.

## Step 2 — Install the `mcp-publisher` CLI

**Windows (PowerShell):**
```powershell
$arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }
Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"
tar xf mcp-publisher.tar.gz mcp-publisher.exe
rm mcp-publisher.tar.gz
# Move mcp-publisher.exe to a directory in your PATH
```

**macOS (Homebrew):**
```bash
brew install mcp-publisher
```

**Linux:**
```bash
curl -L "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_$(uname -s | tr '[:upper:]' '[:lower:]')_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" | tar xz mcp-publisher && sudo mv mcp-publisher /usr/local/bin/
```

Verify installation:
```bash
mcp-publisher --help
```

## Step 3 — Create `server.json`

A `server.json` file is already included in this repository. It contains:

- The server name (must start with `io.github.<username>/` for GitHub auth)
- Description and repository URL
- Package info (PyPI registry type, transport type: stdio)
- Version number

You can regenerate or edit it with:
```bash
mcp-publisher init
```

## Step 4 — Authenticate with the Registry

```bash
mcp-publisher login github
```

This will print a URL and code. Visit https://github.com/login/device, enter the code, and authorize the app.

## Step 5 — Publish to the Registry

```bash
mcp-publisher publish
```

You should see:
```
Publishing to https://registry.modelcontextprotocol.io...
✓ Successfully published
✓ Server io.github.Airta-Admin/davinc-resolve-local-bridge-mcp version 1.1.1
```

## Step 6 — Verify

Check that your server appears in the registry:

```bash
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=davinc-resolve"
```

## Troubleshooting

| Error | Fix |
|-------|-----|
| "Registry validation failed for package" | Ensure the `mcp-name:` marker is in the PyPI README |
| "Invalid or expired Registry JWT token" | Re-run `mcp-publisher login github` |
| "You do not have permission to publish this server" | Your server name must start with `io.github.your-username/` matching your GitHub auth |

## Additional Marketplaces

Besides the official MCP Registry, consider listing on these community directories:

- **PulseMCP** (https://pulsemcp.com) — community MCP directory
- **Smithery** (https://smithery.ai) — MCP server registry and installer
- **MCP Hub** (https://mcphub.io) — another community directory

Each has its own submission process — typically just providing your GitHub repo URL and server metadata.

## Automating with GitHub Actions

The MCP Registry supports publishing via GitHub Actions. See the [official GitHub Actions guide](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx) for setup details. This allows automatic publishing when you create a new release tag.
