# Davinc-Resolve-Local-Bridge-MCP

<!-- mcp-name: io.github.Airta-Admin/davinc-resolve-local-bridge-mcp -->

<p align="center">
  <img src="https://raw.githubusercontent.com/Airta-Admin/Davinc-Resolve-Local-Bridge-MCP/main/images/software-box.png" alt="DaVinci Resolve Local Bridge MCP" width="400">
</p>

<p align="center">
  <strong>Control DaVinci Resolve from any AI assistant — Claude, Cursor, Devin, and more.</strong>
</p>

<p align="center">
  <strong>218 tools. Resolve API and optional-extension coverage. Works with DaVinci Resolve Free and Studio.</strong>
</p>

---

## What Is This?

**Davinc-Resolve-Local-Bridge-MCP** is a [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that gives AI assistants controlled access to DaVinci Resolve. It exposes **218 tools** covering projects, timelines, media, Fusion, color grading, rendering, and supported optional extensions.

### How It Works

```
Your AI Assistant (Claude, Cursor, Devin, etc.)
       │
       │  talks MCP (stdio)
       ▼
  mcp_server/server.py        ← runs on your machine
       │
       │  talks HTTP (localhost:8787)
       ▼
  DaVinciResolveBridge.py ← runs INSIDE DaVinci Resolve
       │                        (started from the Workflow Integration)
       ▼
  DaVinci Resolve API         ← full read + write access
```

The bridge script runs **inside** DaVinci Resolve's process, giving it full access to the Resolve scripting API — even on the **Free edition** (which blocks external scripting). The MCP server runs as a separate process and proxies tool calls to the bridge over localhost HTTP.

---

## Quick Start

### Prerequisites

- **DaVinci Resolve 18.5+** (Free or Studio)
- **Python 3.10+** on your machine
- An MCP-compatible AI assistant (Claude Desktop, Cursor, Devin, etc.)

### Step 1 — Install the Workflow Integration and Bridge

Run the installer:

```bash
python install.py
```

The installer adds the user-facing launcher under **Workspace → Workflow Integrations** and installs the underlying bridge script. Restart Resolve once after installation so it discovers the integration.

For a manual installation, copy `workflow/DaVinci Resolve Local Bridge MCP Server Connection.py` and the `workflow/assets` directory to Resolve's `Workflow Integration Plugins` directory. Also copy `bridge/Bridge-Connection-Script.py` to Resolve's scripts folder as `DaVinciResolveBridge.py`. The Scripts entry is retained as a fallback, not the normal launch path.

| Platform | Path |
|----------|------|
| **Windows** | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\` |
| **macOS** | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| **Linux** | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/` |

### Step 2 — Install MCP Server Dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Configure Your AI Assistant

Add the MCP server to your assistant's configuration file. The server path is `mcp_server/server.py` in this repo.

#### Claude Desktop

Edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "davinci-resolve-local-bridge": {
      "command": "python",
      "args": ["C:/path/to/Davinc-Resolve-Local-Bridge-MCP/mcp_server/server.py"]
    }
  }
}
```

#### Cursor

Edit `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "davinci-resolve-local-bridge": {
      "command": "python",
      "args": ["C:/path/to/Davinc-Resolve-Local-Bridge-MCP/mcp_server/server.py"]
    }
  }
}
```

#### Devin

Edit `mcp_config.json`:

```json
{
  "mcpServers": {
    "resolve-local-bridge": {
      "command": "python",
      "args": ["C:/path/to/Davinc-Resolve-Local-Bridge-MCP/mcp_server/server.py"]
    }
  }
}
```

#### Claude Code

```bash
claude mcp add davinci-resolve-local-bridge -- python C:/path/to/Davinc-Resolve-Local-Bridge-MCP/mcp_server/server.py
```

#### Any MCP Client (generic)

The server uses **stdio transport**. Launch it with:

```bash
python mcp_server/server.py
```

### Step 4 — Start the Bridge Inside DaVinci Resolve

1. **Open DaVinci Resolve**
2. Go to **Workspace → Workflow Integrations → DaVinci Resolve Local Bridge MCP Server Connection**
3. Click **Start Bridge**
4. Confirm that the panel reports **Running on http://127.0.0.1:8787 (218 actions)**. For diagnostic details, open **Workspace → Console** and look for:

```
[Resolve Bridge] Connected to Resolve 21.0.4.5
[Resolve Bridge] HTTP server running on http://127.0.0.1:8787
[Resolve Bridge] 218 actions available
```

### Step 5 — Start Using It

Ask your AI assistant:

> "Check if DaVinci Resolve is connected"

The assistant will call the `resolve_status` tool and report back. Then try:

> "Create a new 1920x1080 30fps project called 'My Video' and add a timeline"

---

## Architecture

### Bridge Script (`bridge/Bridge-Connection-Script.py`)

A Python script that runs **inside** DaVinci Resolve. The supported Workflow Integration launcher starts it for the user; **Workspace → Scripts → DaVinciResolveBridge** remains available only as a fallback. It:

- Obtains the live `resolve` object from Fusion's globals
- Starts an HTTP server on `127.0.0.1:8787`
- Exposes 3 endpoints:
  - `GET /health` — check if the bridge is alive
  - `GET /actions` — list all available action names
  - `POST /action` — execute an action by name with parameters
- Stays alive with a blocking `serve_forever()` call
- Kills any previous instance on the same port before starting

### MCP Server (`mcp_server/server.py`)

A standalone MCP server that:

- Connects to the bridge over HTTP on localhost
- Auto-discovers all 218 actions from the bridge's `/actions` endpoint
- Exposes each action as an MCP tool with the `resolve_` prefix
- Proxies tool calls to the bridge via `POST /action`
- Stays in sync with the bridge — no manual tool definitions needed

---

## All 218 Tools

The MCP server auto-discovers tools from the bridge. Each tool is prefixed with `resolve_` (e.g., `status` becomes `resolve_status`). Pass parameters as a `params` object.

### Resolve Application (15 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_status` | — | Check bridge connectivity and get current project/timeline info |
| `resolve_get_version` | — | Get Resolve version info |
| `resolve_get_current_page` | — | Get the active page (edit, cut, color, etc.) |
| `resolve_open_page` | `page` | Switch to a page: edit, cut, fusion, color, fairlight, deliver, media |
| `resolve_get_layout_presets` | — | List available layout presets |
| `resolve_load_layout_preset` | `presetName` | Load a layout preset by name |
| `resolve_get_keyframe_mode` | — | Get current keyframe mode |
| `resolve_set_keyframe_mode` | `keyframeMode` | Set keyframe mode |
| `resolve_get_fairlight_presets` | — | List Fairlight audio presets |
| `resolve_get_burnin_presets` | — | List burn-in presets |
| `resolve_import_render_preset` | `presetPath` | Import a render preset from file |
| `resolve_export_render_preset` | `presetName`, `exportPath` | Export a render preset to file |
| `resolve_open_fusion_page` | — | Switch to Fusion page |
| `resolve_open_edit_page` | — | Switch to Edit page |
| `resolve_open_deliver_page` | — | Switch to Deliver page |

### Project Manager (18 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_create_project` | `name`, `width`, `height`, `fps` | Create a new project |
| `resolve_load_project` | `name` | Load an existing project |
| `resolve_save_project` | — | Save the current project |
| `resolve_close_project` | — | Close the current project |
| `resolve_delete_project` | `name` | Delete a project |
| `resolve_create_folder` | `folderName` | Create a project folder |
| `resolve_delete_folder` | `folderName` | Delete a project folder |
| `resolve_get_project_list` | — | List projects in current folder |
| `resolve_get_folder_list` | — | List subfolders in current folder |
| `resolve_get_current_folder` | — | Get current folder name |
| `resolve_open_folder` | `folderName` | Open a folder |
| `resolve_goto_root_folder` | — | Navigate to root folder |
| `resolve_goto_parent_folder` | — | Navigate to parent folder |
| `resolve_import_project` | `filePath`, `projectName` | Import a .drp project |
| `resolve_export_project` | `projectName`, `filePath`, `withStillsAndLUTs` | Export a project as .drp |
| `resolve_archive_project` | `projectName`, `filePath`, ... | Archive a project |
| `resolve_get_current_database` | — | Get current database name |
| `resolve_get_database_list` | — | List available databases |

### Project Settings (7 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_project_name` | — | Get current project name |
| `resolve_set_project_name` | `name` | Rename the current project |
| `resolve_get_project_setting` | `key` | Get a project setting by key |
| `resolve_set_project_setting` | `key`, `value` | Set a project setting |
| `resolve_get_project_settings` | — | Get all project settings |
| `resolve_get_project_preset_list` | — | List project presets |
| `resolve_set_project_preset` | `presetName` | Apply a project preset |

### Media Storage (4 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_mounted_volumes` | — | List mounted storage volumes |
| `resolve_get_subfolder_list` | `folderPath` | List subfolders in a path |
| `resolve_get_file_list` | `folderPath` | List files in a folder |
| `resolve_reveal_in_storage` | `path` | Reveal a file in the OS file browser |

### Media Pool (13 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_import_media` | `paths` (list) | Import media files into the pool |
| `resolve_get_media_pool` | — | List all clips in root folder |
| `resolve_get_root_folder` | — | Get root folder info |
| `resolve_add_sub_folder` | `folderName`, `parentFolderName` | Create a subfolder |
| `resolve_set_current_folder` | `folderName` | Set the current folder |
| `resolve_delete_clips` | `clipNames` (list) | Delete clips from pool |
| `resolve_move_clips` | `clipNames`, `targetFolder` | Move clips to a folder |
| `resolve_relink_clips` | `clipNames`, `folderPath` | Relink clips |
| `resolve_unlink_clips` | `clipNames` | Unlink clips |
| `resolve_export_metadata` | `fileName`, `clipNames` | Export metadata CSV |
| `resolve_get_selected_clips` | — | List selected clips |
| `resolve_set_selected_clip` | `clipName` | Select a clip |
| `resolve_add_timeline_mattes` | `paths` (list) | Add matte files |

### Timeline (21 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_create_timeline` | `name` | Create a new empty timeline |
| `resolve_create_timeline_from_clips` | `name`, `clipNames` | Create timeline from clips |
| `resolve_list_timelines` | — | List all timelines |
| `resolve_get_timeline_name` | — | Get current timeline name |
| `resolve_set_timeline_name` | `name` | Rename current timeline |
| `resolve_set_current_timeline` | `timelineIndex` | Switch to timeline by index (1-based) |
| `resolve_duplicate_timeline` | — | Duplicate the current timeline |
| `resolve_delete_timelines` | `timelineNames` | Delete timelines |
| `resolve_get_timeline_start_frame` | — | Get start frame |
| `resolve_get_timeline_end_frame` | — | Get end frame |
| `resolve_get_start_timecode` | — | Get start timecode |
| `resolve_set_start_timecode` | `timecode` | Set start timecode |
| `resolve_get_current_timecode` | — | Get current timecode |
| `resolve_set_current_timecode` | `timecode` | Set current timecode |
| `resolve_detect_scene_cuts` | — | Detect scene cuts |
| `resolve_create_subtitles_from_audio` | `settings` | Auto-generate subtitles |
| `resolve_timeline_export` | `fileName`, `exportType`, `exportSubtype` | Export timeline |
| `resolve_import_timeline_from_file` | `filePath` | Import timeline from file |
| `resolve_append_to_timeline` | `clipNames` | Append clips to timeline |
| `resolve_get_timeline_setting` | `key` | Get a timeline setting |
| `resolve_set_timeline_setting` | `key`, `value` | Set a timeline setting |

### Timeline Tracks (11 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_track_count` | `trackType` | Count tracks (video/audio/subtitle) |
| `resolve_add_track` | `trackType` | Add a track |
| `resolve_delete_track` | `trackType`, `trackIndex` | Delete a track |
| `resolve_set_track_enable` | `trackType`, `trackIndex`, `enabled` | Enable/disable a track |
| `resolve_get_track_enable` | `trackType`, `trackIndex` | Check if track is enabled |
| `resolve_set_track_lock` | `trackType`, `trackIndex`, `locked` | Lock/unlock a track |
| `resolve_get_track_lock` | `trackType`, `trackIndex` | Check if track is locked |
| `resolve_get_track_name` | `trackType`, `trackIndex` | Get track name |
| `resolve_set_track_name` | `trackType`, `trackIndex`, `name` | Set track name |
| `resolve_get_items_in_track` | `trackType`, `index` | List clips on a track |
| `resolve_get_timeline_selected_clips` | — | List selected timeline clips |

### Timeline Items (66 tools)

All item actions accept optional `trackType`, `trackIndex`, `itemIndex` to target a specific clip, or operate on the first selected clip if omitted.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_item_name` | `trackType?`, `trackIndex?`, `itemIndex?` | Get clip name |
| `resolve_set_item_name` | `name`, `trackType?`, ... | Rename a clip |
| `resolve_get_item_duration` | `trackType?`, ... | Get clip duration |
| `resolve_get_item_start` | `trackType?`, ... | Get clip start frame |
| `resolve_get_item_end` | `trackType?`, ... | Get clip end frame |
| `resolve_get_item_property` | `key?`, `trackType?`, ... | Get a clip property |
| `resolve_set_item_property` | `key`, `value`, `trackType?`, ... | Set a clip property |
| `resolve_get_item_enabled` | `trackType?`, ... | Check if clip is enabled |
| `resolve_set_item_enabled` | `enabled`, `trackType?`, ... | Enable/disable a clip |
| `resolve_set_item_color` | `colorName`, `trackType?`, ... | Set clip color |
| `resolve_get_item_color` | `trackType?`, ... | Get clip color |
| `resolve_clear_item_color` | `trackType?`, ... | Clear clip color |
| `resolve_add_item_flag` | `color`, `trackType?`, ... | Add a flag |
| `resolve_get_item_flags` | `trackType?`, ... | Get flags |
| `resolve_clear_item_flags` | `color`, `trackType?`, ... | Clear flags |
| `resolve_add_item_marker` | `frameId`, `color`, `name`, `note?`, ... | Add a marker |
| `resolve_get_item_markers` | `trackType?`, ... | Get markers |
| `resolve_insert_generator` | `generatorName` | Insert a generator |
| `resolve_insert_fusion_generator` | `generatorName` | Insert a Fusion generator |
| `resolve_insert_fusion_composition` | — | Insert a Fusion composition |
| `resolve_insert_ofx_generator` | `generatorName` | Insert an OFX generator |
| `resolve_insert_title` | `titleName` | Insert a title |
| `resolve_insert_fusion_title` | `titleName` | Insert a Fusion title |
| `resolve_grab_still` | — | Grab a still from current frame |
| `resolve_grab_all_stills` | — | Grab stills from all clips |
| `resolve_create_compound_clip` | `name` | Create a compound clip |
| `resolve_create_fusion_clip` | — | Create a Fusion clip |
| `resolve_import_into_timeline` | `filePath`, `importOptions?` | Import into timeline |
| `resolve_stabilize` | `trackType?`, ... | Stabilize a clip |
| `resolve_smart_reframe` | `trackType?`, ... | Smart Reframe a clip |
| `resolve_create_magic_mask` | `mode`, `trackType?`, ... | Create a Magic Mask |
| `resolve_regenerate_magic_mask` | `trackType?`, ... | Regenerate Magic Mask |
| `resolve_get_item_track_info` | `trackType?`, ... | Get track info for a clip |
| `resolve_get_linked_items` | `trackType?`, ... | Get linked items |
| `resolve_set_item_cdl` | `cdl`, `trackType?`, ... | Set CDL values |
| `resolve_add_take` | `mediaPoolItemName`, `startFrame?`, `endFrame?` | Add a take |
| `resolve_get_takes_count` | `trackType?`, ... | Count takes |
| `resolve_select_take_by_index` | `idx`, `trackType?`, ... | Select a take |
| `resolve_finalize_take` | `trackType?`, ... | Finalize the current take |
| `resolve_copy_grades` | `targetItemNames`, `trackType?`, ... | Copy grades to other clips |
| `resolve_export_lut` | `exportType`, `path`, `trackType?`, ... | Export a LUT |
| `resolve_set_color_output_cache` | `cache_value`, `trackType?`, ... | Set color output cache |
| `resolve_set_fusion_output_cache` | `cache_value`, `trackType?`, ... | Set Fusion output cache |
| `resolve_get_clip_metadata` | `metadataType?` | Get clip metadata |
| `resolve_set_clip_metadata` | `metadataType`, `metadataValue` | Set clip metadata |
| `resolve_get_clip_property` | `propertyName?` | Get clip property |
| `resolve_set_clip_property` | `propertyName`, `propertyValue` | Set clip property |
| `resolve_link_proxy_media` | `proxyMediaFilePath` | Link proxy media |
| `resolve_unlink_proxy_media` | — | Unlink proxy media |
| `resolve_replace_clip` | `filePath` | Replace clip with file |
| `resolve_add_clip_marker` | `frameId`, `color`, `name`, `note?` | Add a clip marker |
| `resolve_get_clip_markers` | — | Get clip markers |
| `resolve_set_clip_color` | `colorName` | Set clip color (media pool) |
| `resolve_add_clip_flag` | `color` | Add a clip flag |
| `resolve_transcribe_clip_audio` | `useSpeakerDetection?` | Transcribe audio |
| `resolve_set_clip_mark_inout` | `markIn`, `markOut`, `type` | Set mark in/out |
| `resolve_clear_clip_mark_inout` | `type` | Clear mark in/out |
| `resolve_add_timeline_marker` | `frameId`, `color`, `name`, `note?` | Add timeline marker |
| `resolve_get_timeline_markers` | — | Get timeline markers |
| `resolve_delete_timeline_markers_by_color` | `color` | Delete markers by color |
| `resolve_delete_timeline_marker_at_frame` | `frameNum` | Delete marker at frame |
| `resolve_export_current_frame` | `filePath` | Export current frame as still |
| `resolve_apply_fairlight_preset` | `name` | Apply Fairlight preset |
| `resolve_get_quick_export_presets` | — | List quick export presets |

### Fusion Compositions (14 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_create_fusion_comp` | `name` | Create a Fusion composition |
| `resolve_add_fusion_comp` | `trackType?`, ... | Add a Fusion comp to a clip |
| `resolve_import_fusion_comp` | `path`, `trackType?`, ... | Import a .comp file |
| `resolve_export_fusion_comp` | `path`, `compIndex?`, `trackType?`, ... | Export a Fusion comp |
| `resolve_load_fusion_comp_by_name` | `compName`, `trackType?`, ... | Load a comp by name |
| `resolve_delete_fusion_comp_by_name` | `compName`, `trackType?`, ... | Delete a comp by name |
| `resolve_rename_fusion_comp` | `oldName`, `newName`, `trackType?`, ... | Rename a comp |
| `resolve_get_item_fusion_comp_count` | `trackType?`, ... | Count Fusion comps on a clip |
| `resolve_get_item_fusion_comp_names` | `trackType?`, ... | List Fusion comp names |
| `resolve_get_current_comp` | — | Get current Fusion composition |
| `resolve_fusion_get_comp_list` | — | List all open comps |
| `resolve_fusion_new_comp` | — | Create a new Fusion comp |
| `resolve_fusion_save_comp` | `filePath` | Save current comp |
| `resolve_fusion_load_comp` | `filePath` | Load a comp file |
| `resolve_fusion_close_comp` | — | Close current comp |
| `resolve_fusion_render_comp` | — | Render current comp |

### Fusion Tools (11 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_fusion_get_tool_list` | — | List all tools/nodes in current comp |
| `resolve_fusion_find_tool` | `name` | Find a tool by name |
| `resolve_fusion_delete_tool` | `name` | Delete a tool |
| `resolve_fusion_get_attrs` | `name` | Get tool attributes |
| `resolve_fusion_set_attrs` | `name`, `attrs` | Set tool attributes |
| `resolve_fusion_add_node` | `nodeType`, `name` | Add a node (Background, Paint, Merge, etc.) |
| `resolve_fusion_connect` | `fromNode`, `toNode`, `input` | Connect two nodes |
| `resolve_fusion_set_input` | `node`, `input`, `value`, `frame?` | Set a node input (can keyframe) |
| `resolve_fusion_get_input` | `node`, `input` | Get a node input value |
| `resolve_fusion_set_current_frame` | `frame` | Set the current frame |
| `resolve_fusion_get_current_frame` | — | Get the current frame |

### Gallery (4 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_gallery_still_albums` | — | List gallery still albums |
| `resolve_get_gallery_powergrade_albums` | — | List PowerGrade albums |
| `resolve_create_gallery_still_album` | — | Create a still album |
| `resolve_create_powergrade_album` | — | Create a PowerGrade album |

### Color / Nodes (7 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_node_count` | — | Get node count on current clip |
| `resolve_get_node_label` | `nodeIndex` | Get a node label |
| `resolve_get_node_lut` | `nodeIndex` | Get a node's LUT |
| `resolve_set_node_lut` | `nodeIndex`, `lutPath` | Set a LUT on a node |
| `resolve_set_node_enabled` | `nodeIndex`, `isEnabled` | Enable/disable a node |
| `resolve_reset_all_grades` | — | Reset all grades |
| `resolve_refresh_lut_list` | — | Refresh the LUT list |

### Rendering (22 tools)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_get_render_formats` | — | List render formats |
| `resolve_get_render_codecs` | `renderFormat` | List codecs for a format |
| `resolve_get_current_render_format_codec` | — | Get current format/codec |
| `resolve_set_render_format_codec` | `format`, `codec` | Set render format and codec |
| `resolve_get_render_mode` | — | Get render mode |
| `resolve_set_render_mode` | `renderMode` | Set render mode |
| `resolve_get_render_resolutions` | `format`, `codec` | List render resolutions |
| `resolve_get_render_preset_list` | — | List render presets |
| `resolve_load_render_preset` | `presetName` | Load a render preset |
| `resolve_save_as_new_render_preset` | `presetName` | Save a new render preset |
| `resolve_delete_render_preset` | `presetName` | Delete a render preset |
| `resolve_set_render_settings` | `settings` | Set render settings (TargetDir, CustomName, etc.) |
| `resolve_add_render_job` | — | Add a render job |
| `resolve_delete_render_job` | `jobId` | Delete a render job |
| `resolve_delete_all_render_jobs` | — | Delete all render jobs |
| `resolve_get_render_job_list` | — | List render jobs |
| `resolve_start_rendering` | `jobIds?`, `isInteractiveMode?` | Start rendering |
| `resolve_stop_rendering` | — | Stop rendering |
| `resolve_is_rendering_in_progress` | — | Check if rendering |
| `resolve_get_render_status` | `jobId` | Get render job status |
| `resolve_render_with_quick_export` | `presetName` | Quick export |
| `resolve_render` | `settings?` | Add job and start rendering |

### Speech & Subtitles (1 tool)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_generate_speech` | `text`, `voice?` | Generate AI speech audio |

### Special (1 tool)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `resolve_create_hand_animation` | `imagePath`, `...` | Create a hand-drawing animation (Daniel Batal technique) |

---

### Optional open-source extensions (3 tools)

| MCP Tool | Description |
|---|---|
| `resolve_get_extension_status` | Read-only detection for OpenCaptions and Rembg-Fuse |
| `resolve_open_captions_list_templates` | List caption Text+ templates in the current project |
| `resolve_fusion_add_rembg_node` | Add an installed Rembg-Fuse node to the current Fusion comp |

OpenCaptions and Rembg-Fuse are independent third-party projects and are not bundled with this package.

### DaVinci Resolve Local Bridge MCP Server Connection

`install.py` also installs a supported Workflow Integration launcher. After restarting Resolve once, open **Workspace → Workflow Integrations → DaVinci Resolve Local Bridge MCP Server Connection** for Start Bridge, Stop Bridge, Refresh Status, and an optional one-time **$5 Developer Tip** button that opens Stripe-hosted checkout in the default browser. Resolve's public scripting API does not support injecting arbitrary buttons into its native top menu bar; Workflow Integrations is the supported persistent menu surface.

### Support development

<p align="center">
  <a href="https://buy.stripe.com/9B6eVd3vP3Et5465MI7bW05">
    <img src="https://raw.githubusercontent.com/Airta-Admin/Davinc-Resolve-Local-Bridge-MCP/main/workflow/assets/tip-jar.png" alt="Tip jar" width="150">
  </a>
</p>

<p align="center">
  <strong><a href="https://buy.stripe.com/9B6eVd3vP3Et5465MI7bW05">Leave an optional one-time $5 developer tip</a></strong><br>
  Secure checkout is hosted by Stripe. A tip supports continued development and maintenance of this open-source bridge; it is not a charitable donation or tax-deductible contribution.
</p>

## Troubleshooting

### Bridge won't start

- Make sure DaVinci Resolve is running and a project is open
- Open **Workspace → Workflow Integrations → DaVinci Resolve Local Bridge MCP Server Connection** and click **Start Bridge**
- Check the Console (Workspace → Console) for error messages
- Restart DaVinci Resolve after installation — it scans Workflow Integrations at startup
- If the Workflow Integration cannot be opened, use **Workspace → Scripts → DaVinciResolveBridge** as a fallback and report the integration error

### "Could not connect to Resolve Bridge"

- Open **Workspace → Workflow Integrations → DaVinci Resolve Local Bridge MCP Server Connection** and verify that its status says **Running**
- Check that the console shows `[Resolve Bridge] HTTP server running on http://127.0.0.1:8787`
- If the port is already in use, close Resolve and reopen it (stale `fuscript.exe` processes can hold the port)

### Tools return errors

- Call `resolve_status` first to verify connectivity
- Some actions require a project to be open, a timeline to exist, or a clip to be selected
- Error messages from the bridge indicate what's missing

---

## Technical Details

- **Bridge port:** 127.0.0.1:8787 (localhost only, no external access)
- **Transport:** HTTP/1.0 with Connection: close
- **MCP transport:** stdio
- **Dependencies:** `mcp`, `requests` (MCP server only; bridge uses pure stdlib)
- **Resolve version:** 18.5+ (tested on 21.0.4.5)
- **Python:** 3.10+ for MCP server; bridge uses Resolve's embedded Python

---

## License

MIT License — see [LICENSE](LICENSE) file.

---

## Credits

Created by: A Fellow Coder for fellow coders. Inspired by the DaVinci Resolve scripting community.
