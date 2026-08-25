"""
DaVinci Resolve MCP Proxy Bridge
================================
Run this script from inside DaVinci Resolve via:
    Workspace > Scripts > DaVinciResolveBridge

It starts an HTTP server on localhost:8787 inside the Resolve process,
giving external agents (Devin) direct access to the Resolve scripting API.

The local-only architecture is:
    Agent <--HTTP--> This server (inside Resolve) <--Resolve API--> DaVinci Resolve

The server stays running in a background thread until you stop it.
"""

import sys
import os
import json
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Workflow Integrations can inject the live Resolve/Fusion objects before this
# script initializes its own module globals.
_host_resolve = globals().get("resolve")
_host_fusion = globals().get("fusion") or globals().get("fu")
_background_server = bool(globals().get("RESOLVE_BRIDGE_BACKGROUND", False))

# ── Resolve connection (uses the same pattern as Resolve's example scripts) ──

def _load_resolve_module():
    """Import DaVinciResolveScript using the same pattern as Resolve's example scripts."""
    try:
        import DaVinciResolveScript as bmd
        return bmd
    except ImportError:
        # Try the default path
        expectedPath = os.getenv('PROGRAMDATA') + "\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\"
        print("[Resolve Bridge] Trying default path: " + expectedPath)
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("DaVinciResolveScript", expectedPath + "DaVinciResolveScript.py")
            if spec:
                module = importlib.util.module_from_spec(spec)
                sys.modules["DaVinciResolveScript"] = module
                spec.loader.exec_module(module)
                import DaVinciResolveScript as bmd
                return bmd
        except Exception as ex:
            print("[Resolve Bridge] ERROR: Could not import DaVinciResolveScript")
            print("[Resolve Bridge] " + str(ex))
            return None

dvr = _load_resolve_module()

# ── Connection ───────────────────────────────────────────────────────────────

resolve = None
fusion = None
project_manager = None
project = None

def _connect():
    """Connect to Resolve's scripting API from inside the app."""
    global resolve, fusion, project_manager, project
    # Try Fusion globals first (available when run from Workspace > Scripts)
    for attempt in (
        lambda: _host_resolve,
        lambda: _host_fusion.GetResolve(),
        lambda: fu.GetResolve(),           # noqa: F821
        lambda: fusion.GetResolve(),        # noqa: F821
        lambda: bmd.scriptapp("Resolve"),   # noqa: F821
    ):
        try:
            resolve = attempt()
            if resolve:
                break
        except Exception:
            pass
    # Fall back to importing DaVinciResolveScript
    if not resolve and dvr:
        try:
            resolve = dvr.scriptapp("Resolve")
        except Exception:
            pass
    if not resolve:
        print("[Resolve Bridge] ERROR: Could not obtain Resolve object")
        return False
    try:
        fusion = resolve.Fusion()
        project_manager = resolve.GetProjectManager()
        project = project_manager.GetCurrentProject()
        print("[Resolve Bridge] Connected to Resolve " + resolve.GetVersionString())
        return True
    except Exception as e:
        print("[Resolve Bridge] ERROR connecting to Resolve: " + str(e))
        traceback.print_exc()
        return False

# ── API actions ──────────────────────────────────────────────────────────────

def api_status(trackType=None, trackIndex=None, itemIndex=None):
    """Get connection status and current project info."""
    if not resolve:
        if not _connect():
            return {"status": "error", "message": "Could not connect to Resolve"}
    info = {"status": "ok"}
    try:
        info["resolve_version"] = resolve.GetVersion()
    except: pass
    try:
        info["current_page"] = resolve.GetCurrentPage()
    except: pass
    try:
        proj = project_manager.GetCurrentProject()
        if proj:
            info["project"] = {"name": proj.GetName()}
            try:
                info["project"]["width"] = proj.GetSetting("timelineResolutionWidth")
                info["project"]["height"] = proj.GetSetting("timelineResolutionHeight")
                info["project"]["fps"] = proj.GetSetting("timelineFrameRate")
            except: pass
            try:
                timeline = proj.GetCurrentTimeline()
                if timeline:
                    info["timeline"] = {"name": timeline.GetName()}
            except: pass
        else:
            info["project"] = None
    except: pass
    return info

def api_create_project(name, width=1080, height=1920, fps=30):
    """Create a new project with given settings."""
    global project
    if not resolve:
        _connect()
    proj = project_manager.CreateProject(name)
    if not proj:
        return {"status": "error", "message": f"Could not create project '{name}'"}
    proj.SetSetting("timelineResolutionWidth", str(width))
    proj.SetSetting("timelineResolutionHeight", str(height))
    proj.SetSetting("timelineFrameRate", str(fps))
    project = proj
    return {"status": "ok", "project": proj.GetName()}

def api_import_media(file_paths):
    """Import media files into the current project's media pool."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    media_pool = proj.GetMediaPool()
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    clips = media_pool.ImportMedia(file_paths)
    if clips:
        return {
            "status": "ok",
            "imported": len(clips),
            "clips": [{"name": c.GetName(), "type": c.GetClipProperty("Type")} for c in clips],
        }
    return {"status": "error", "message": "No clips imported"}

def api_create_timeline(name, clips=None):
    """Create a new timeline, optionally with clips appended."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    media_pool = proj.GetMediaPool()
    timeline = media_pool.CreateEmptyTimeline(name)
    if not timeline:
        return {"status": "error", "message": f"Could not create timeline '{name}'"}
    proj.SetCurrentTimeline(timeline)
    results = []
    if clips:
        mp_items = media_pool.GetRootFolder().GetClipList()
        for clip_info in clips:
            clip_name = clip_info.get("name") if isinstance(clip_info, dict) else clip_info
            for mpi in mp_items:
                if mpi.GetName() == clip_name:
                    appended = media_pool.AppendToTimeline([mpi])
                    results.append({"clip": mpi.GetName(), "appended": bool(appended)})
                    break
    return {"status": "ok", "timeline": timeline.GetName(), "clips_added": results}

def api_get_media_pool():
    """List all clips in the media pool root folder."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    root = proj.GetMediaPool().GetRootFolder()
    clips = []
    for c in root.GetClipList():
        clips.append({
            "name": c.GetName(),
            "type": c.GetClipProperty("Type"),
            "duration": c.GetClipProperty("Duration"),
        })
    return {"status": "ok", "clips": clips}

def api_create_fusion_comp(name="HandAnimation"):
    """Create a new Fusion composition in the media pool for hand-drawing animation."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    media_pool = proj.GetMediaPool()
    # Create a Fusion composition clip
    comp_clip = media_pool.CreateFusionClip(name)
    if comp_clip:
        return {"status": "ok", "fusion_clip": comp_clip.GetName()}
    return {"status": "error", "message": "Could not create Fusion composition"}

def api_open_fusion_page():
    """Switch to the Fusion page."""
    if not resolve:
        _connect()
    resolve.OpenPage("fusion")
    return {"status": "ok", "page": "fusion"}

def api_open_edit_page():
    """Switch to the Edit page."""
    if not resolve:
        _connect()
    resolve.OpenPage("edit")
    return {"status": "ok", "page": "edit"}

def api_open_deliver_page():
    """Switch to the Deliver page."""
    if not resolve:
        _connect()
    resolve.OpenPage("deliver")
    return {"status": "ok", "page": "deliver"}

def api_get_current_comp():
    """Get the current Fusion composition and its nodes."""
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open"}
    nodes = []
    for tool in comp.GetToolList().values():
        nodes.append({
            "name": tool.Name,
            "type": tool.GetAttrs("TOOLB_VariantID") if hasattr(tool, 'GetAttrs') else str(type(tool)),
        })
    return {"status": "ok", "comp_name": comp.GetAttrs("COMPN_Name"), "nodes": nodes}

def api_fusion_add_node(comp_name, node_type, name=None):
    """Add a node to the current Fusion composition."""
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.AddTool(node_type, -1, False)
    if tool:
        if name:
            tool.SetAttrs("TOOLS_Name", name)
        return {"status": "ok", "node_name": tool.Name, "node_type": node_type}
    return {"status": "error", "message": f"Could not add {node_type} node"}

def api_fusion_connect(src_node, dst_node, src_output="Output", dst_input="Input"):
    """Connect two Fusion nodes."""
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open"}
    src = comp.FindTool(src_node)
    dst = comp.FindTool(dst_node)
    if not src or not dst:
        return {"status": "error", "message": f"Could not find nodes {src_node} or {dst_node}"}
    dst.SetInput(dst_input, src, src_output)
    return {"status": "ok", "connected": f"{src_node}.{src_output} -> {dst_node}.{dst_input}"}

def api_fusion_set_input(node_name, input_name, value):
    """Set an input on a Fusion node."""
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(node_name)
    if not tool:
        return {"status": "error", "message": f"Node {node_name} not found"}
    tool.SetInput(input_name, value)
    return {"status": "ok", "node": node_name, "input": input_name, "value": value}

def api_fusion_get_input(node_name, input_name):
    """Get an input value from a Fusion node."""
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(node_name)
    if not tool:
        return {"status": "error", "message": f"Node {node_name} not found"}
    val = tool.GetInput(input_name)
    return {"status": "ok", "node": node_name, "input": input_name, "value": val}

def api_render(output_path, format="mp4", codec="H264", preset_name=None):
    """Add a render job and start rendering."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    resolve.OpenPage("deliver")
    # Set render settings
    settings = {
        "ExportVideo": True,
        "ExportAudio": True,
        "FormatWidth": 1080,
        "FormatHeight": 1920,
        "VideoFormat": format,
        "VideoCodec": codec,
        "TargetDir": output_path.rsplit("\\", 1)[0] if "\\" in output_path else os.path.expanduser("~\\Desktop"),
        "CustomName": output_path.rsplit("\\", 1)[-1].rsplit(".", 1)[0] if "\\" in output_path else "render",
    }
    if preset_name:
        proj.LoadRenderPreset(preset_name)
    proj.SetRenderSettings(settings)
    job_id = proj.AddRenderJob()
    if not job_id:
        return {"status": "error", "message": "Could not add render job"}
    proj.StartRendering(job_id)
    # Wait for completion
    while proj.IsRenderingInProgress():
        import time
        time.sleep(1)
    status = proj.GetRenderJobStatus(job_id)
    return {"status": "ok", "job_id": job_id, "render_status": status}

def api_get_render_status(job_id):
    """Get render job status."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    return proj.GetRenderJobStatus(job_id)

# ── Hand & Pencil Animation (from Daniel Batal tutorial) ─────────────────────

def api_create_hand_animation(shape="circle", duration_frames=40, hand_image_path=None):
    """
    Create a hand-drawing animation following the Daniel Batal tutorial:
    https://www.youtube.com/watch?v=ofCXLFv9yTk

    Steps from the tutorial:
    1. Create a Fusion composition
    2. Add a Background node with alpha at 0 (transparent)
    3. Add a Paint node with a polyline stroke (circle or custom shape)
    4. Smooth the stroke points
    5. Keyframe the WriteOnEnd from 0 to 1 over duration_frames
    6. Duplicate the Paint node
    7. On the second Paint node, set brush to Image mode
    8. Load a hand-with-pencil image as the brush
    9. Set WriteOnStart to 0.999 and WriteOnEnd to 0.001
    10. Adjust center X/Y so pencil tip aligns with the stroke
    11. Ease keyframes via spline (flatten)
    """
    if not resolve:
        _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp:
        return {"status": "error", "message": "No Fusion composition open. Create one first."}

    results = []

    # Step 2: Background node with alpha = 0
    bg = comp.AddTool("Background", -1, False)
    bg.SetAttrs("TOOLS_Name", "HandDrawBG")
    bg.SetInput("Alpha", 0.0)
    results.append("Created Background node 'HandDrawBG' with alpha=0")

    # Step 3: Paint node with polyline stroke
    paint1 = comp.AddTool("Paint", -1, False)
    paint1.SetAttrs("TOOLS_Name", "HandDrawStroke")
    # Connect background to paint input
    paint1.SetInput("Input", bg, "Output")
    results.append("Created Paint node 'HandDrawStroke'")

    # Set up the stroke - use polyline mode
    # The Paint node's StrokeType should be polyline
    paint1.SetInput("StrokeType", 1)  # Polyline stroke

    # Step 5: Keyframe WriteOnEnd
    # At frame 0, WriteOnEnd = 0
    comp.SetCurrentFrame(0)
    paint1.SetInput("WriteOnEnd", 0.0)
    # Set keyframe by setting the input with time
    paint1.SetInput("WriteOnEnd", 0.0, 0)  # frame 0

    # At frame duration_frames, WriteOnEnd = 1
    paint1.SetInput("WriteOnEnd", 1.0, duration_frames)  # frame N
    results.append(f"Keyframed WriteOnEnd: 0 at frame 0, 1 at frame {duration_frames}")

    # Step 6: Duplicate the paint node
    paint2 = comp.AddTool("Paint", -1, False)
    paint2.SetAttrs("TOOLS_Name", "HandDrawImage")
    paint2.SetInput("Input", paint1, "Output")
    results.append("Created second Paint node 'HandDrawImage'")

    # Step 7: Set brush to Image mode
    # BrushType: 0=Line, 1=Image (varies by version - we try setting it)
    try:
        paint2.SetInput("BrushType", 1)  # Image mode
    except:
        results.append("WARNING: Could not set BrushType to Image - may need manual step")

    # Step 8: Load hand image if provided
    if hand_image_path:
        try:
            paint2.SetInput("SourceClip", hand_image_path)
        except:
            results.append(f"WARNING: Could not load hand image {hand_image_path} - may need manual step")

    # Step 9: Set WriteOnStart and WriteOnEnd for the image paint node
    paint2.SetInput("WriteOnStart", 0.999, 0)
    paint2.SetInput("WriteOnEnd", 0.001, 0)
    results.append("Set HandDrawImage WriteOnStart=0.999, WriteOnEnd=0.001")

    # Step 10: Adjust center X/Y (these need manual tweaking per layout)
    # Default offsets - user can adjust
    paint2.SetInput("CenterX", 0.5)
    paint2.SetInput("CenterY", 0.5)

    # Connect to MediaOut
    media_out = None
    for tool in comp.GetToolList().values():
        if tool.GetAttrs("TOOLS_Name") == "MediaOut1" or "MediaOut" in tool.GetAttrs("TOOLS_Name"):
            media_out = tool
            break
    if media_out:
        media_out.SetInput("Input", paint2, "Output")
        results.append("Connected HandDrawImage to MediaOut")

    results.append("NOTE: You need to manually draw the polyline shape on the viewer")
    results.append("NOTE: Smooth the points by selecting all and clicking Smooth")
    results.append("NOTE: Adjust Center X/Y so pencil tip aligns with stroke")

    return {"status": "ok", "steps": results}

def api_list_timelines():
    """List all timelines in the current project."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    timelines = []
    for i in range(proj.GetTimelineCount()):
        tl = proj.GetTimelineByIndex(i + 1)
        timelines.append({
            "name": tl.GetName(),
            "start_frame": tl.GetStartFrame() if hasattr(tl, 'GetStartFrame') else None,
            "end_frame": tl.GetEndFrame() if hasattr(tl, 'GetEndFrame') else None,
            "is_current": proj.GetCurrentTimeline() == tl,
        })
    return {"status": "ok", "timelines": timelines}

def api_set_project_setting(key, value):
    """Set a project setting."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    ok = proj.SetSetting(key, str(value))
    return {"status": "ok" if ok else "error", "key": key, "value": value}

def api_get_project_settings():
    """Get all project settings."""
    if not resolve:
        _connect()
    proj = project_manager.GetCurrentProject()
    if not proj:
        return {"status": "error", "message": "No project open"}
    settings = proj.GetSetting()
    return {"status": "ok", "settings": settings}

# ── Resolve-level actions ─────────────────────────────────────────────────────

def api_get_version():
    if not resolve: _connect()
    return {"status": "ok", "version": resolve.GetVersion(), "version_string": resolve.GetVersionString(), "product": resolve.GetProductName()}

def api_get_current_page():
    if not resolve: _connect()
    return {"status": "ok", "page": resolve.GetCurrentPage()}

def api_open_page(page):
    if not resolve: _connect()
    resolve.OpenPage(page)
    return {"status": "ok", "page": page}

def api_get_layout_presets():
    if not resolve: _connect()
    return {"status": "ok", "presets": resolve.GetLayoutPresetList()}

def api_load_layout_preset(presetName):
    if not resolve: _connect()
    resolve.LoadLayoutPreset(presetName)
    return {"status": "ok", "preset": presetName}

def api_get_keyframe_mode():
    if not resolve: _connect()
    return {"status": "ok", "mode": resolve.GetKeyframeMode()}

def api_set_keyframe_mode(keyframeMode):
    if not resolve: _connect()
    try:
        resolve.SetKeyframeMode(keyframeMode)
        return {"status": "ok", "keyframeMode": keyframeMode}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_get_fairlight_presets():
    if not resolve: _connect()
    return {"status": "ok", "presets": resolve.GetFairlightPresets()}

def api_get_burnin_presets():
    if not resolve: _connect()
    return {"status": "ok", "presets": resolve.GetBurnInPresetList()}

def api_import_render_preset(presetPath):
    if not resolve: _connect()
    resolve.ImportRenderPreset(presetPath)
    return {"status": "ok"}

def api_export_render_preset(presetName, exportPath):
    if not resolve: _connect()
    resolve.ExportRenderPreset(presetName, exportPath)
    return {"status": "ok"}

# ── ProjectManager actions ────────────────────────────────────────────────────

def api_load_project(projectName):
    if not resolve: _connect()
    proj = project_manager.LoadProject(projectName)
    if proj:
        return {"status": "ok", "project": proj.GetName()}
    return {"status": "error", "message": f"Could not load project '{projectName}'"}

def api_save_project():
    if not resolve: _connect()
    project_manager.SaveProject()
    return {"status": "ok"}

def api_close_project():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if proj:
        project_manager.CloseProject(proj)
        return {"status": "ok"}
    return {"status": "error", "message": "No project open"}

def api_delete_project(projectName):
    if not resolve: _connect()
    project_manager.DeleteProject(projectName)
    return {"status": "ok"}

def api_create_folder(folderName):
    if not resolve: _connect()
    project_manager.CreateFolder(folderName)
    return {"status": "ok"}

def api_delete_folder(folderName):
    if not resolve: _connect()
    project_manager.DeleteFolder(folderName)
    return {"status": "ok"}

def api_get_project_list():
    if not resolve: _connect()
    return {"status": "ok", "projects": project_manager.GetProjectListInCurrentFolder()}

def api_get_folder_list():
    if not resolve: _connect()
    return {"status": "ok", "folders": project_manager.GetFolderListInCurrentFolder()}

def api_get_current_folder():
    if not resolve: _connect()
    return {"status": "ok", "folder": project_manager.GetCurrentFolder()}

def api_open_folder(folderName):
    if not resolve: _connect()
    project_manager.OpenFolder(folderName)
    return {"status": "ok"}

def api_goto_root_folder():
    if not resolve: _connect()
    project_manager.GotoRootFolder()
    return {"status": "ok"}

def api_goto_parent_folder():
    if not resolve: _connect()
    project_manager.GotoParentFolder()
    return {"status": "ok"}

def api_import_project(filePath, projectName=None):
    if not resolve: _connect()
    project_manager.ImportProject(filePath, projectName)
    return {"status": "ok"}

def api_export_project(projectName, filePath, withStillsAndLUTs=True):
    if not resolve: _connect()
    project_manager.ExportProject(projectName, filePath, withStillsAndLUTs)
    return {"status": "ok"}

def api_archive_project(projectName, filePath, isArchiveSrcMedia=True, isArchiveRenderCache=True, isArchiveProxyMedia=False):
    if not resolve: _connect()
    project_manager.ArchiveProject(projectName, filePath, isArchiveSrcMedia, isArchiveRenderCache, isArchiveProxyMedia)
    return {"status": "ok"}

def api_get_current_database():
    if not resolve: _connect()
    return {"status": "ok", "database": project_manager.GetCurrentDatabase()}

def api_get_database_list():
    if not resolve: _connect()
    return {"status": "ok", "databases": project_manager.GetDatabaseList()}

# ── Project actions ───────────────────────────────────────────────────────────

def api_get_project_name():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "name": proj.GetName()}

def api_set_project_name(name):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    try:
        proj.SetName(name)
        return {"status": "ok", "name": name}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_get_project_setting(key):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "key": key, "value": proj.GetSetting(key)}

def api_get_render_formats():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "formats": proj.GetRenderFormats()}

def api_get_render_codecs(renderFormat):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "codecs": proj.GetRenderCodecs(renderFormat)}

def api_get_current_render_format_codec():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "info": proj.GetCurrentRenderFormatAndCodec()}

def api_set_render_format_codec(format, codec):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.SetCurrentRenderFormatAndCodec(format, codec)
    return {"status": "ok"}

def api_get_render_mode():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "mode": proj.GetCurrentRenderMode()}

def api_set_render_mode(renderMode):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    try:
        proj.SetCurrentRenderMode(renderMode)
        return {"status": "ok", "renderMode": renderMode}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_get_render_resolutions(format=None, codec=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    if format and codec:
        return {"status": "ok", "resolutions": proj.GetRenderResolutions(format, codec)}
    return {"status": "ok", "resolutions": proj.GetRenderResolutions()}

def api_get_render_preset_list():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "presets": proj.GetRenderPresetList()}

def api_load_render_preset(presetName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.LoadRenderPreset(presetName)
    return {"status": "ok"}

def api_save_as_new_render_preset(presetName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.SaveAsNewRenderPreset(presetName)
    return {"status": "ok"}

def api_delete_render_preset(presetName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.DeleteRenderPreset(presetName)
    return {"status": "ok"}

def api_set_render_settings(settings):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.SetRenderSettings(settings)
    return {"status": "ok", "settings": settings}

def api_add_render_job():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    job_id = proj.AddRenderJob()
    return {"status": "ok" if job_id else "error", "job_id": job_id}

def api_delete_render_job(jobId):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.DeleteRenderJob(jobId)
    return {"status": "ok"}

def api_delete_all_render_jobs():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.DeleteAllRenderJobs()
    return {"status": "ok"}

def api_get_render_job_list():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "jobs": proj.GetRenderJobList()}

def api_start_rendering(jobIds=None, isInteractiveMode=False):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    if jobIds:
        if isinstance(jobIds, list):
            proj.StartRendering(jobIds, isInteractiveMode)
            return {"status": "ok"}
        proj.StartRendering(jobIds)
        return {"status": "ok"}
    proj.StartRendering(isInteractiveMode)
    return {"status": "ok"}

def api_stop_rendering():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.StopRendering()
    return {"status": "ok"}

def api_is_rendering_in_progress():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "rendering": proj.IsRenderingInProgress()}

def api_get_quick_export_presets():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "presets": proj.GetQuickExportRenderPresets()}

def api_render_with_quick_export(preset_name, params):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "result": proj.RenderWithQuickExport(preset_name, params)}

def api_get_project_preset_list():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    return {"status": "ok", "presets": proj.GetPresetList()}

def api_set_project_preset(presetName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.SetPreset(presetName)
    return {"status": "ok"}

def api_set_current_timeline(timelineIndex):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    # Resolve uses 1-based timeline indices
    idx = int(timelineIndex)
    if idx < 1: idx = 1
    tl = proj.GetTimelineByIndex(idx)
    if tl:
        proj.SetCurrentTimeline(tl)
        return {"status": "ok", "timeline": tl.GetName()}
    return {"status": "error", "message": "Timeline " + str(timelineIndex) + " not found"}

def api_refresh_lut_list():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.RefreshLUTList()
    return {"status": "ok"}

def api_export_current_frame(filePath):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.ExportCurrentFrameAsStill(filePath)
    return {"status": "ok"}

def api_apply_fairlight_preset(name):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    proj.ApplyFairlightPresetToCurrentTimeline(name)
    return {"status": "ok"}

# ── MediaStorage actions ──────────────────────────────────────────────────────

def api_get_mounted_volumes():
    if not resolve: _connect()
    ms = resolve.GetMediaStorage()
    return {"status": "ok", "volumes": ms.GetMountedVolumeList()}

def api_get_subfolder_list(folderPath):
    if not resolve: _connect()
    ms = resolve.GetMediaStorage()
    return {"status": "ok", "folders": ms.GetSubFolderList(folderPath)}

def api_get_file_list(folderPath):
    if not resolve: _connect()
    ms = resolve.GetMediaStorage()
    return {"status": "ok", "files": ms.GetFileList(folderPath)}

def api_reveal_in_storage(path):
    if not resolve: _connect()
    ms = resolve.GetMediaStorage()
    ms.RevealInStorage(path)
    return {"status": "ok"}

def api_add_timeline_mattes(paths):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    ms = resolve.GetMediaStorage()
    if isinstance(paths, str): paths = [paths]
    items = ms.AddTimelineMattesToMediaPool(paths)
    return {"status": "ok", "items": [i.GetName() for i in items] if items else []}

# ── MediaPool actions ─────────────────────────────────────────────────────────

def api_get_root_folder():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    root = proj.GetMediaPool().GetRootFolder()
    return {"status": "ok", "name": root.GetName()}

def api_add_sub_folder(folderName, parentFolderName=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if parentFolderName:
        # find parent folder
        parent = None
        for f in [mp.GetRootFolder()] + mp.GetRootFolder().GetSubFolderList():
            if f.GetName() == parentFolderName:
                parent = f
                break
        if not parent: return {"status": "error", "message": f"Parent folder '{parentFolderName}' not found"}
        folder = mp.AddSubFolder(parent, folderName)
    else:
        folder = mp.AddSubFolder(mp.GetRootFolder(), folderName)
    return {"status": "ok" if folder else "error", "folder": folder.GetName() if folder else None}

def api_get_current_folder():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    folder = proj.GetMediaPool().GetCurrentFolder()
    return {"status": "ok", "folder": folder.GetName()}

def api_set_current_folder(folderName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    folder = None
    for f in [mp.GetRootFolder()] + mp.GetRootFolder().GetSubFolderList():
        if f.GetName() == folderName:
            folder = f
            break
    if folder:
        mp.SetCurrentFolder(folder)
        return {"status": "ok"}
    return {"status": "error", "message": f"Folder '{folderName}' not found"}

def api_delete_clips(clipNames):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = []
    for c in mp.GetRootFolder().GetClipList():
        if c.GetName() in clipNames:
            clips.append(c)
    mp.DeleteClips(clips)
    return {"status": "ok", "deleted": len(clips)}

def api_move_clips(clipNames, targetFolderName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    target = None
    for f in [mp.GetRootFolder()] + mp.GetRootFolder().GetSubFolderList():
        if f.GetName() == targetFolderName:
            target = f
            break
    if not target: return {"status": "error", "message": f"Target folder '{targetFolderName}' not found"}
    mp.MoveClips(clips, target)
    return {"status": "ok"}

def api_relink_clips(clipNames, folderPath):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    mp.RelinkClips(clips, folderPath)
    return {"status": "ok"}

def api_unlink_clips(clipNames):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    mp.UnlinkClips(clips)
    return {"status": "ok"}

def api_export_metadata(fileName, clipNames=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    clips = None
    if clipNames:
        if isinstance(clipNames, str): clipNames = [clipNames]
        clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    mp.ExportMetadata(fileName, clips)
    return {"status": "ok"}

def api_get_selected_clips():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    clips = mp.GetSelectedClips()
    return {"status": "ok", "clips": [c.GetName() for c in clips] if clips else []}

def api_set_selected_clip(clipName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    for c in mp.GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            mp.SetSelectedClip(c)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_delete_timelines(timelineNames):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(timelineNames, str): timelineNames = [timelineNames]
    tls = []
    for i in range(proj.GetTimelineCount()):
        tl = proj.GetTimelineByIndex(i + 1)
        if tl.GetName() in timelineNames:
            tls.append(tl)
    mp.DeleteTimelines(tls)
    return {"status": "ok", "deleted": len(tls)}

def api_import_timeline_from_file(filePath, importOptions=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    tl = mp.ImportTimelineFromFile(filePath, importOptions or {})
    return {"status": "ok" if tl else "error", "timeline": tl.GetName() if tl else None}

def api_append_to_timeline(clipNames, clipInfo=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    if clipInfo:
        items = mp.AppendToTimeline(clipInfo)
    else:
        items = mp.AppendToTimeline(clips)
    return {"status": "ok", "items": [i.GetName() for i in items] if items else []}

def api_create_timeline_from_clips(name, clipNames):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    mp = proj.GetMediaPool()
    if isinstance(clipNames, str): clipNames = [clipNames]
    clips = [c for c in mp.GetRootFolder().GetClipList() if c.GetName() in clipNames]
    tl = mp.CreateTimelineFromClips(name, clips)
    return {"status": "ok" if tl else "error", "timeline": tl.GetName() if tl else None}

# ── Timeline actions ──────────────────────────────────────────────────────────

def _get_current_timeline():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return None
    return proj.GetCurrentTimeline()

def api_get_timeline_name():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "name": tl.GetName()}

def api_set_timeline_name(name):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetName(name)
    return {"status": "ok"}

def api_get_timeline_start_frame():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "start_frame": tl.GetStartFrame()}

def api_get_timeline_end_frame():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "end_frame": tl.GetEndFrame()}

def api_get_start_timecode():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "timecode": tl.GetStartTimecode()}

def api_set_start_timecode(timecode):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetStartTimecode(timecode)
    return {"status": "ok"}

def api_get_track_count(trackType):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "count": tl.GetTrackCount(trackType)}

def api_add_track(trackType, subTrackType=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    if subTrackType:
        tl.AddTrack(trackType, subTrackType)
        return {"status": "ok"}
    tl.AddTrack(trackType)
    return {"status": "ok"}

def api_delete_track(trackType, trackIndex):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.DeleteTrack(trackType, trackIndex)
    return {"status": "ok"}

def api_set_track_enable(trackType, trackIndex, enabled):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetTrackEnable(trackType, trackIndex, enabled)
    return {"status": "ok"}

def api_get_track_enable(trackType, trackIndex):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "enabled": tl.GetIsTrackEnabled(trackType, trackIndex)}

def api_set_track_lock(trackType, trackIndex, locked):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetTrackLock(trackType, trackIndex, locked)
    return {"status": "ok"}

def api_get_track_lock(trackType, trackIndex):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "locked": tl.GetIsTrackLocked(trackType, trackIndex)}

def api_get_track_name(trackType, trackIndex):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "name": tl.GetTrackName(trackType, trackIndex)}

def api_set_track_name(trackType, trackIndex, name):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetTrackName(trackType, trackIndex, name)
    return {"status": "ok"}

def api_get_items_in_track(trackType, index):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    items = tl.GetItemListInTrack(trackType, index)
    result = []
    for item in items or []:
        result.append({"name": item.GetName(), "start": item.GetStart(), "end": item.GetEnd(), "duration": item.GetDuration()})
    return {"status": "ok", "items": result}

def api_get_timeline_selected_clips():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    items = tl.GetSelectedClips()
    result = []
    for item in items or []:
        result.append({"name": item.GetName(), "start": item.GetStart(), "end": item.GetEnd()})
    return {"status": "ok", "items": result}

def api_get_current_timecode():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "timecode": tl.GetCurrentTimecode()}

def api_set_current_timecode(timecode):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetCurrentTimecode(timecode)
    return {"status": "ok"}

def api_duplicate_timeline(timelineName=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    new_tl = tl.DuplicateTimeline(timelineName)
    return {"status": "ok" if new_tl else "error", "timeline": new_tl.GetName() if new_tl else None}

def api_detect_scene_cuts():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.DetectSceneCuts()
    return {"status": "ok"}

def api_create_subtitles_from_audio(settings=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.CreateSubtitlesFromAudio(settings or {})
    return {"status": "ok"}

def api_timeline_export(fileName, exportType, exportSubtype=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.Export(fileName, exportType, exportSubtype)
    return {"status": "ok"}

def api_get_timeline_setting(key):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "key": key, "value": tl.GetSetting(key)}

def api_set_timeline_setting(key, value):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.SetSetting(key, str(value))
    return {"status": "ok", "key": key, "value": value}

def api_insert_generator(generatorName):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertGeneratorIntoTimeline(generatorName)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_insert_fusion_generator(generatorName):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertFusionGeneratorIntoTimeline(generatorName)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_insert_fusion_composition():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertFusionCompositionIntoTimeline()
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_insert_ofx_generator(generatorName):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertOFXGeneratorIntoTimeline(generatorName)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_insert_title(titleName):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertTitleIntoTimeline(titleName)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_insert_fusion_title(titleName):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    item = tl.InsertFusionTitleIntoTimeline(titleName)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_grab_still():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    still = tl.GrabStill()
    return {"status": "ok" if still else "error"}

def api_grab_all_stills(stillFrameSource=1):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    stills = tl.GrabAllStills(stillFrameSource)
    return {"status": "ok", "count": len(stills) if stills else 0}

def api_create_compound_clip(itemNames, clipInfo=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    items = []
    for it in tl.GetSelectedClips() or []:
        if it.GetName() in (itemNames if isinstance(itemNames, list) else [itemNames]):
            items.append(it)
    item = tl.CreateCompoundClip(items, clipInfo or {})
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_create_fusion_clip(itemNames=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    items = tl.GetSelectedClips() if itemNames is None else [it for it in tl.GetSelectedClips() or [] if it.GetName() in (itemNames if isinstance(itemNames, list) else [itemNames])]
    item = tl.CreateFusionClip(items)
    return {"status": "ok" if item else "error", "item": item.GetName() if item else None}

def api_import_into_timeline(filePath, importOptions=None):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.ImportIntoTimeline(filePath, importOptions or {})
    return {"status": "ok"}

def api_add_timeline_marker(frameId, color, name, note="", duration=1, customData=""):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.AddMarker(frameId, color, name, note, duration, customData)
    return {"status": "ok"}

def api_get_timeline_markers():
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    return {"status": "ok", "markers": tl.GetMarkers()}

def api_delete_timeline_markers_by_color(color):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.DeleteMarkersByColor(color)
    return {"status": "ok"}

def api_delete_timeline_marker_at_frame(frameNum):
    tl = _get_current_timeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    tl.DeleteMarkerAtFrame(frameNum)
    return {"status": "ok"}

# ── TimelineItem actions (operate on selected clips or by track/index) ────────

def _get_item(trackType=None, trackIndex=None, itemIndex=None):
    """Get a timeline item - either by track/index or the first selected clip."""
    tl = _get_current_timeline()
    if not tl: return None
    if trackType is not None and trackIndex is not None and itemIndex is not None:
        try:
            items = tl.GetItemListInTrack(trackType, int(trackIndex))
            if items and 0 <= int(itemIndex) < len(items):
                return items[int(itemIndex)]
        except: pass
    items = tl.GetSelectedClips()
    return items[0] if items else None

def api_get_item_name(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "name": item.GetName()}

def api_set_item_name(name, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetName(name)
    return {"status": "ok"}

def api_get_item_duration(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "duration": item.GetDuration()}

def api_get_item_start(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "start": item.GetStart()}

def api_get_item_end(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "end": item.GetEnd()}

def api_get_item_property(key=None, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "property": item.GetProperty(key)}

def api_set_item_property(key, value, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    # SetProperty can cause native crashes on certain properties - use str value
    try:
        result = item.SetProperty(key, str(value))
        return {"status": "ok", "key": key, "value": value, "result": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_get_item_fusion_comp_count(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "count": item.GetFusionCompCount()}

def api_get_item_fusion_comp_names(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "names": item.GetFusionCompNameList()}

def api_add_fusion_comp(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    comp = item.AddFusionComp()
    return {"status": "ok" if comp else "error"}

def api_import_fusion_comp(path, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    comp = item.ImportFusionComp(path)
    return {"status": "ok" if comp else "error"}

def api_export_fusion_comp(path, compIndex=1, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.ExportFusionComp(path, compIndex)
    return {"status": "ok"}

def api_load_fusion_comp_by_name(compName, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    comp = item.LoadFusionCompByName(compName)
    return {"status": "ok" if comp else "error"}

def api_delete_fusion_comp_by_name(compName, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.DeleteFusionCompByName(compName)
    return {"status": "ok"}

def api_rename_fusion_comp(oldName, newName, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.RenameFusionCompByName(oldName, newName)
    return {"status": "ok"}

def api_set_item_enabled(enabled, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetClipEnabled(enabled)
    return {"status": "ok"}

def api_get_item_enabled(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "enabled": item.GetClipEnabled()}

def api_add_item_marker(frameId, color, name, note="", duration=1, customData="", trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.AddMarker(frameId, color, name, note, duration, customData)
    return {"status": "ok"}

def api_get_item_markers(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "markers": item.GetMarkers()}

def api_add_item_flag(color, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.AddFlag(color)
    return {"status": "ok"}

def api_get_item_flags(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "flags": item.GetFlagList()}

def api_clear_item_flags(color, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.ClearFlags(color)
    return {"status": "ok"}

def api_set_item_color(colorName, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetClipColor(colorName)
    return {"status": "ok"}

def api_get_item_color(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "color": item.GetClipColor()}

def api_clear_item_color(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.ClearClipColor()
    return {"status": "ok"}

def api_stabilize(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.Stabilize()
    return {"status": "ok"}

def api_smart_reframe(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SmartReframe()
    return {"status": "ok"}

def api_create_magic_mask(mode, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.CreateMagicMask(mode)
    return {"status": "ok"}

def api_regenerate_magic_mask(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.RegenerateMagicMask()
    return {"status": "ok"}

def api_get_item_track_info(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "track_info": item.GetTrackTypeAndIndex()}

def api_get_linked_items(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    items = item.GetLinkedItems()
    return {"status": "ok", "items": [i.GetName() for i in items] if items else []}

def api_set_item_cdl(cdl, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetCDL(cdl)
    return {"status": "ok"}

def api_add_take(mediaPoolItemName, startFrame=None, endFrame=None, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    proj = project_manager.GetCurrentProject()
    mpi = None
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == mediaPoolItemName:
            mpi = c
            break
    if not mpi: return {"status": "error", "message": f"MediaPoolItem '{mediaPoolItemName}' not found"}
    if startFrame is not None and endFrame is not None:
        return {"status": "ok" if item.AddTake(mpi, startFrame, endFrame) else "error"}
    return {"status": "ok" if item.AddTake(mpi) else "error"}

def api_get_takes_count(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    return {"status": "ok", "count": item.GetTakesCount()}

def api_select_take_by_index(idx, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SelectTakeByIndex(idx)
    return {"status": "ok"}

def api_finalize_take(trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.FinalizeTake()
    return {"status": "ok"}

def api_copy_grades(targetItemNames, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    tl = _get_current_timeline()
    targets = []
    for it in tl.GetSelectedClips() or []:
        if it.GetName() in (targetItemNames if isinstance(targetItemNames, list) else [targetItemNames]):
            targets.append(it)
    item.CopyGrades(targets)
    return {"status": "ok"}

def api_export_lut(exportType, path, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.ExportLUT(exportType, path)
    return {"status": "ok"}

def api_set_color_output_cache(cache_value, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetColorOutputCache(cache_value)
    return {"status": "ok"}

def api_set_fusion_output_cache(cache_value, trackType=None, trackIndex=None, itemIndex=None):
    item = _get_item(trackType, trackIndex, itemIndex)
    if not item: return {"status": "error", "message": "No item selected"}
    item.SetFusionOutputCache(cache_value)
    return {"status": "ok"}

# ── MediaPoolItem actions ─────────────────────────────────────────────────────

def api_get_clip_metadata(clipName, metadataType=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            return {"status": "ok", "metadata": c.GetMetadata(metadataType)}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_set_clip_metadata(clipName, metadataType, metadataValue):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.SetMetadata(metadataType, metadataValue)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_get_clip_property(clipName, propertyName=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            return {"status": "ok", "property": c.GetClipProperty(propertyName)}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_set_clip_property(clipName, propertyName, propertyValue):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.SetClipProperty(propertyName, propertyValue)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_link_proxy_media(clipName, proxyMediaFilePath):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.LinkProxyMedia(proxyMediaFilePath)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_unlink_proxy_media(clipName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.UnlinkProxyMedia()
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_replace_clip(clipName, filePath):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.ReplaceClip(filePath)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_add_clip_marker(clipName, frameId, color, name, note="", duration=1, customData=""):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.AddMarker(frameId, color, name, note, duration, customData)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_get_clip_markers(clipName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            return {"status": "ok", "markers": c.GetMarkers()}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_set_clip_color(clipName, colorName):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.SetClipColor(colorName)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_add_clip_flag(clipName, color):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.AddFlag(color)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_transcribe_clip_audio(clipName, useSpeakerDetection=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            if useSpeakerDetection is not None:
                c.TranscribeAudio(useSpeakerDetection)
                return {"status": "ok"}
            c.TranscribeAudio()
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_set_clip_mark_inout(clipName, markIn, markOut, type="all"):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.SetMarkInOut(markIn, markOut, type)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

def api_clear_clip_mark_inout(clipName, type="all"):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    for c in proj.GetMediaPool().GetRootFolder().GetClipList():
        if c.GetName() == clipName:
            c.ClearMarkInOut(type)
            return {"status": "ok"}
    return {"status": "error", "message": f"Clip '{clipName}' not found"}

# ── Fusion composition actions ────────────────────────────────────────────────

def api_fusion_get_comp_list():
    if not resolve: _connect()
    fu = resolve.Fusion()
    comps = fu.GetCompList()
    result = []
    for c in comps:
        try:
            name = c.GetAttrs("COMPN_Name")
        except:
            name = str(c)
        result.append(name)
    return {"status": "ok", "comps": result}

def api_fusion_new_comp(name=None):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.NewComp()
    if comp and name:
        comp.SetAttrs("COMPN_Name", name)
    return {"status": "ok" if comp else "error", "name": comp.GetAttrs("COMPN_Name") if comp else None}

def api_fusion_set_current_frame(frame):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    comp.SetCurrentFrame(frame)
    return {"status": "ok", "frame": frame}

def api_fusion_get_current_frame():
    if not resolve: _connect()
    fu = resolve.Fusion()
    try:
        comp = fu.GetCurrentComp()
    except:
        return {"status": "error", "message": "No Fusion composition open"}
    if not comp or not hasattr(comp, 'GetCurrentFrame'):
        return {"status": "error", "message": "No Fusion composition open"}
    try:
        return {"status": "ok", "frame": comp.GetCurrentFrame()}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_fusion_get_tool_list():
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tools = comp.GetToolList()
    result = []
    for k, t in tools.items():
        result.append({"id": k, "name": t.Name})
    return {"status": "ok", "tools": result}

def api_fusion_find_tool(name):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(name)
    if tool:
        return {"status": "ok", "name": tool.Name}
    return {"status": "error", "message": f"Tool '{name}' not found"}

def api_fusion_delete_tool(name):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(name)
    if tool:
        tool.Delete()
        return {"status": "ok"}
    return {"status": "error", "message": f"Tool '{name}' not found"}

def api_fusion_get_attrs(name, attrName):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(name)
    if not tool: return {"status": "error", "message": f"Tool '{name}' not found"}
    return {"status": "ok", "attr": attrName, "value": tool.GetAttrs(attrName)}

def api_fusion_set_attrs(name, attrName, value):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.FindTool(name)
    if not tool: return {"status": "error", "message": f"Tool '{name}' not found"}
    tool.SetAttrs(attrName, value)
    return {"status": "ok"}

def api_fusion_save_comp(filePath):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    comp.Save(filePath)
    return {"status": "ok"}

def api_fusion_load_comp(filePath):
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.LoadComp(filePath)
    return {"status": "ok" if comp else "error"}

def api_fusion_close_comp():
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    comp.Close()
    return {"status": "ok"}

def api_fusion_render_comp():
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp()
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    comp.Render()
    return {"status": "ok"}


# ── Optional open-source extensions ─────────────────────────────────────────

def api_get_extension_status():
    """Report supported optional extensions without loading or executing them."""
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    roots = [
        os.path.join(programdata, "Blackmagic Design", "DaVinci Resolve", "Fusion"),
        os.path.join(appdata, "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion"),
    ]
    candidates = {
        "open_captions": [
            os.path.join(root, "Scripts", "Comp", "OpenCaptions.py") for root in roots
        ],
        "rembg_fuse": [
            os.path.join(root, "Fuses", "Rembg", "Rembg.fuse") for root in roots
        ],
    }
    extensions = {}
    for name, paths in candidates.items():
        installed_paths = [path for path in paths if os.path.isfile(path)]
        extensions[name] = {
            "installed": bool(installed_paths),
            "paths": installed_paths,
        }
    return {"status": "ok", "extensions": extensions}


def api_open_captions_list_templates():
    """List Text+ clips in the OpenCaptions 'Captions Templates' media folder."""
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    media_pool = proj.GetMediaPool()
    root = media_pool.GetRootFolder()
    folder = None
    for subfolder in root.GetSubFolderList() or []:
        if subfolder.GetName() == "Captions Templates":
            folder = subfolder
            break
    if not folder:
        return {"status": "ok", "templates": [], "message": "Captions Templates folder not found"}
    templates = []
    for clip in folder.GetClipList() or []:
        name = clip.GetClipProperty("Clip Name")
        if name:
            templates.append(name)
    return {"status": "ok", "templates": sorted(set(templates))}


def api_fusion_add_rembg_node(name="Rembg"):
    """Add the installed Rembg-Fuse node to the current Fusion composition."""
    if not resolve: _connect()
    fu = resolve.Fusion()
    comp = fu.GetCurrentComp() if fu else None
    if not comp: return {"status": "error", "message": "No Fusion composition open"}
    tool = comp.AddTool("Rembg", -1, False)
    if not tool:
        return {"status": "error", "message": "Rembg node unavailable; install Rembg-Fuse and restart Resolve"}
    tool.SetAttrs({"TOOLS_Name": name})
    return {"status": "ok", "name": name, "tool_id": "Rembg"}

# ── Gallery actions ───────────────────────────────────────────────────────────

def api_get_gallery_still_albums():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    gallery = proj.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    return {"status": "ok", "albums": [gallery.GetAlbumName(a) for a in albums] if albums else []}

def api_get_gallery_powergrade_albums():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    gallery = proj.GetGallery()
    albums = gallery.GetGalleryPowerGradeAlbums()
    return {"status": "ok", "albums": [gallery.GetAlbumName(a) for a in albums] if albums else []}

def api_create_gallery_still_album():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    gallery = proj.GetGallery()
    album = gallery.CreateGalleryStillAlbum()
    return {"status": "ok" if album else "error", "name": gallery.GetAlbumName(album) if album else None}

def api_create_powergrade_album():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    gallery = proj.GetGallery()
    album = gallery.CreateGalleryPowerGradeAlbum()
    return {"status": "ok" if album else "error", "name": gallery.GetAlbumName(album) if album else None}

# ── Color / Graph actions ─────────────────────────────────────────────────────

def api_get_node_count():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    return {"status": "ok", "count": graph.GetNumNodes()}

def api_set_node_lut(nodeIndex, lutPath):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    graph.SetLUT(nodeIndex, lutPath)
    return {"status": "ok"}

def api_get_node_lut(nodeIndex):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    return {"status": "ok", "lut": graph.GetLUT(nodeIndex)}

def api_set_node_enabled(nodeIndex, isEnabled):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    try:
        graph.SetNodeEnabled(nodeIndex, isEnabled)
        return {"status": "ok", "nodeIndex": nodeIndex, "enabled": isEnabled}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def api_get_node_label(nodeIndex):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    return {"status": "ok", "label": graph.GetNodeLabel(nodeIndex)}

def api_reset_all_grades():
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    tl = proj.GetCurrentTimeline()
    if not tl: return {"status": "error", "message": "No timeline open"}
    graph = tl.GetNodeGraph()
    if not graph: return {"status": "error", "message": "No node graph"}
    graph.ResetAllGrades()
    return {"status": "ok"}

# ── Speech Generation ─────────────────────────────────────────────────────────

def api_generate_speech(speechSettings, timecode=None):
    if not resolve: _connect()
    proj = project_manager.GetCurrentProject()
    if not proj: return {"status": "error", "message": "No project open"}
    if timecode:
        mpi = proj.GenerateSpeech(speechSettings, timecode)
    else:
        mpi = proj.GenerateSpeech(speechSettings)
    return {"status": "ok" if mpi else "error", "clip": mpi.GetName() if mpi else None}

# ── HTTP Server ──────────────────────────────────────────────────────────────

ACTIONS = {
    # Status / connection
    "status": api_status,
    "get_version": api_get_version,
    "get_current_page": api_get_current_page,
    "open_page": api_open_page,
    # Layout presets
    "get_layout_presets": api_get_layout_presets,
    "load_layout_preset": api_load_layout_preset,
    # Keyframe mode
    "get_keyframe_mode": api_get_keyframe_mode,
    "set_keyframe_mode": api_set_keyframe_mode,
    # Fairlight / burn-in / render presets
    "get_fairlight_presets": api_get_fairlight_presets,
    "get_burnin_presets": api_get_burnin_presets,
    "import_render_preset": api_import_render_preset,
    "export_render_preset": api_export_render_preset,
    # ProjectManager
    "create_project": api_create_project,
    "load_project": api_load_project,
    "save_project": api_save_project,
    "close_project": api_close_project,
    "delete_project": api_delete_project,
    "create_folder": api_create_folder,
    "delete_folder": api_delete_folder,
    "get_project_list": api_get_project_list,
    "get_folder_list": api_get_folder_list,
    "get_current_folder": api_get_current_folder,
    "open_folder": api_open_folder,
    "goto_root_folder": api_goto_root_folder,
    "goto_parent_folder": api_goto_parent_folder,
    "import_project": api_import_project,
    "export_project": api_export_project,
    "archive_project": api_archive_project,
    "get_current_database": api_get_current_database,
    "get_database_list": api_get_database_list,
    # Project
    "get_project_name": api_get_project_name,
    "set_project_name": api_set_project_name,
    "get_project_setting": api_get_project_setting,
    "set_project_setting": api_set_project_setting,
    "get_project_settings": api_get_project_settings,
    "get_project_preset_list": api_get_project_preset_list,
    "set_project_preset": api_set_project_preset,
    "set_current_timeline": api_set_current_timeline,
    "refresh_lut_list": api_refresh_lut_list,
    "export_current_frame": api_export_current_frame,
    "apply_fairlight_preset": api_apply_fairlight_preset,
    "get_render_formats": api_get_render_formats,
    "get_render_codecs": api_get_render_codecs,
    "get_current_render_format_codec": api_get_current_render_format_codec,
    "set_render_format_codec": api_set_render_format_codec,
    "get_render_mode": api_get_render_mode,
    "set_render_mode": api_set_render_mode,
    "get_render_resolutions": api_get_render_resolutions,
    "get_render_preset_list": api_get_render_preset_list,
    "load_render_preset": api_load_render_preset,
    "save_as_new_render_preset": api_save_as_new_render_preset,
    "delete_render_preset": api_delete_render_preset,
    "set_render_settings": api_set_render_settings,
    "add_render_job": api_add_render_job,
    "delete_render_job": api_delete_render_job,
    "delete_all_render_jobs": api_delete_all_render_jobs,
    "get_render_job_list": api_get_render_job_list,
    "start_rendering": api_start_rendering,
    "stop_rendering": api_stop_rendering,
    "is_rendering_in_progress": api_is_rendering_in_progress,
    "get_render_status": api_get_render_status,
    "get_quick_export_presets": api_get_quick_export_presets,
    "render_with_quick_export": api_render_with_quick_export,
    "render": api_render,
    # MediaStorage
    "get_mounted_volumes": api_get_mounted_volumes,
    "get_subfolder_list": api_get_subfolder_list,
    "get_file_list": api_get_file_list,
    "reveal_in_storage": api_reveal_in_storage,
    "add_timeline_mattes": api_add_timeline_mattes,
    # MediaPool
    "import_media": api_import_media,
    "get_media_pool": api_get_media_pool,
    "get_root_folder": api_get_root_folder,
    "add_sub_folder": api_add_sub_folder,
    "set_current_folder": api_set_current_folder,
    "delete_clips": api_delete_clips,
    "move_clips": api_move_clips,
    "relink_clips": api_relink_clips,
    "unlink_clips": api_unlink_clips,
    "export_metadata": api_export_metadata,
    "get_selected_clips": api_get_selected_clips,
    "set_selected_clip": api_set_selected_clip,
    "delete_timelines": api_delete_timelines,
    "import_timeline_from_file": api_import_timeline_from_file,
    "append_to_timeline": api_append_to_timeline,
    "create_timeline_from_clips": api_create_timeline_from_clips,
    # Timeline
    "create_timeline": api_create_timeline,
    "list_timelines": api_list_timelines,
    "get_timeline_name": api_get_timeline_name,
    "set_timeline_name": api_set_timeline_name,
    "get_timeline_start_frame": api_get_timeline_start_frame,
    "get_timeline_end_frame": api_get_timeline_end_frame,
    "get_start_timecode": api_get_start_timecode,
    "set_start_timecode": api_set_start_timecode,
    "get_track_count": api_get_track_count,
    "add_track": api_add_track,
    "delete_track": api_delete_track,
    "set_track_enable": api_set_track_enable,
    "get_track_enable": api_get_track_enable,
    "set_track_lock": api_set_track_lock,
    "get_track_lock": api_get_track_lock,
    "get_track_name": api_get_track_name,
    "set_track_name": api_set_track_name,
    "get_items_in_track": api_get_items_in_track,
    "get_timeline_selected_clips": api_get_timeline_selected_clips,
    "get_current_timecode": api_get_current_timecode,
    "set_current_timecode": api_set_current_timecode,
    "duplicate_timeline": api_duplicate_timeline,
    "detect_scene_cuts": api_detect_scene_cuts,
    "create_subtitles_from_audio": api_create_subtitles_from_audio,
    "timeline_export": api_timeline_export,
    "get_timeline_setting": api_get_timeline_setting,
    "set_timeline_setting": api_set_timeline_setting,
    "insert_generator": api_insert_generator,
    "insert_fusion_generator": api_insert_fusion_generator,
    "insert_fusion_composition": api_insert_fusion_composition,
    "insert_ofx_generator": api_insert_ofx_generator,
    "insert_title": api_insert_title,
    "insert_fusion_title": api_insert_fusion_title,
    "grab_still": api_grab_still,
    "grab_all_stills": api_grab_all_stills,
    "create_compound_clip": api_create_compound_clip,
    "create_fusion_clip": api_create_fusion_clip,
    "import_into_timeline": api_import_into_timeline,
    "add_timeline_marker": api_add_timeline_marker,
    "get_timeline_markers": api_get_timeline_markers,
    "delete_timeline_markers_by_color": api_delete_timeline_markers_by_color,
    "delete_timeline_marker_at_frame": api_delete_timeline_marker_at_frame,
    # TimelineItem
    "get_item_name": api_get_item_name,
    "set_item_name": api_set_item_name,
    "get_item_duration": api_get_item_duration,
    "get_item_start": api_get_item_start,
    "get_item_end": api_get_item_end,
    "get_item_property": api_get_item_property,
    "set_item_property": api_set_item_property,
    "get_item_fusion_comp_count": api_get_item_fusion_comp_count,
    "get_item_fusion_comp_names": api_get_item_fusion_comp_names,
    "add_fusion_comp": api_add_fusion_comp,
    "import_fusion_comp": api_import_fusion_comp,
    "export_fusion_comp": api_export_fusion_comp,
    "load_fusion_comp_by_name": api_load_fusion_comp_by_name,
    "delete_fusion_comp_by_name": api_delete_fusion_comp_by_name,
    "rename_fusion_comp": api_rename_fusion_comp,
    "set_item_enabled": api_set_item_enabled,
    "get_item_enabled": api_get_item_enabled,
    "add_item_marker": api_add_item_marker,
    "get_item_markers": api_get_item_markers,
    "add_item_flag": api_add_item_flag,
    "get_item_flags": api_get_item_flags,
    "clear_item_flags": api_clear_item_flags,
    "set_item_color": api_set_item_color,
    "get_item_color": api_get_item_color,
    "clear_item_color": api_clear_item_color,
    "stabilize": api_stabilize,
    "smart_reframe": api_smart_reframe,
    "create_magic_mask": api_create_magic_mask,
    "regenerate_magic_mask": api_regenerate_magic_mask,
    "get_item_track_info": api_get_item_track_info,
    "get_linked_items": api_get_linked_items,
    "set_item_cdl": api_set_item_cdl,
    "add_take": api_add_take,
    "get_takes_count": api_get_takes_count,
    "select_take_by_index": api_select_take_by_index,
    "finalize_take": api_finalize_take,
    "copy_grades": api_copy_grades,
    "export_lut": api_export_lut,
    "set_color_output_cache": api_set_color_output_cache,
    "set_fusion_output_cache": api_set_fusion_output_cache,
    # MediaPoolItem
    "get_clip_metadata": api_get_clip_metadata,
    "set_clip_metadata": api_set_clip_metadata,
    "get_clip_property": api_get_clip_property,
    "set_clip_property": api_set_clip_property,
    "link_proxy_media": api_link_proxy_media,
    "unlink_proxy_media": api_unlink_proxy_media,
    "replace_clip": api_replace_clip,
    "add_clip_marker": api_add_clip_marker,
    "get_clip_markers": api_get_clip_markers,
    "set_clip_color": api_set_clip_color,
    "add_clip_flag": api_add_clip_flag,
    "transcribe_clip_audio": api_transcribe_clip_audio,
    "set_clip_mark_inout": api_set_clip_mark_inout,
    "clear_clip_mark_inout": api_clear_clip_mark_inout,
    # Fusion
    "create_fusion_comp": api_create_fusion_comp,
    "open_fusion_page": api_open_fusion_page,
    "open_edit_page": api_open_edit_page,
    "open_deliver_page": api_open_deliver_page,
    "get_current_comp": api_get_current_comp,
    "fusion_get_comp_list": api_fusion_get_comp_list,
    "fusion_new_comp": api_fusion_new_comp,
    "fusion_set_current_frame": api_fusion_set_current_frame,
    "fusion_get_current_frame": api_fusion_get_current_frame,
    "fusion_get_tool_list": api_fusion_get_tool_list,
    "fusion_find_tool": api_fusion_find_tool,
    "fusion_delete_tool": api_fusion_delete_tool,
    "fusion_get_attrs": api_fusion_get_attrs,
    "fusion_set_attrs": api_fusion_set_attrs,
    "fusion_save_comp": api_fusion_save_comp,
    "fusion_load_comp": api_fusion_load_comp,
    "fusion_close_comp": api_fusion_close_comp,
    "fusion_render_comp": api_fusion_render_comp,
    "fusion_add_node": api_fusion_add_node,
    "fusion_connect": api_fusion_connect,
    "fusion_set_input": api_fusion_set_input,
    "fusion_get_input": api_fusion_get_input,
    "create_hand_animation": api_create_hand_animation,
    # Optional open-source extensions
    "get_extension_status": api_get_extension_status,
    "open_captions_list_templates": api_open_captions_list_templates,
    "fusion_add_rembg_node": api_fusion_add_rembg_node,
    # Gallery
    "get_gallery_still_albums": api_get_gallery_still_albums,
    "get_gallery_powergrade_albums": api_get_gallery_powergrade_albums,
    "create_gallery_still_album": api_create_gallery_still_album,
    "create_powergrade_album": api_create_powergrade_album,
    # Color / Graph
    "get_node_count": api_get_node_count,
    "set_node_lut": api_set_node_lut,
    "get_node_lut": api_get_node_lut,
    "set_node_enabled": api_set_node_enabled,
    "get_node_label": api_get_node_label,
    "reset_all_grades": api_reset_all_grades,
    # Speech
    "generate_speech": api_generate_speech,
}

class BridgeHandler(BaseHTTPRequestHandler):
    def _send_json(self, code, data):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            print("[Resolve Bridge] DEBUG: do_GET path='" + parsed.path + "'")
            if parsed.path == "/health" or parsed.path == "/alive":
                self._send_json(200, {"status": "ok"})
                return
            if parsed.path == "/shutdown":
                self._send_json(200, {"status": "shutting down"})
                import threading
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if parsed.path == "/actions":
                self._send_json(200, {"actions": list(ACTIONS.keys())})
                return
            self._send_json(404, {"error": "Not found"})
        except Exception as e:
            print("[Resolve Bridge] ERROR in do_GET: " + str(e))
            try:
                self._send_json(500, {"error": str(e)})
            except:
                pass

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path != "/action":
                self._send_json(404, {"error": "Not found. Use POST /action"})
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                req = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            action = req.get("action")
            params = req.get("params", {})

            if action not in ACTIONS:
                self._send_json(400, {"error": f"Unknown action '{action}'."})
                return

            try:
                result = ACTIONS[action](**params) if isinstance(params, dict) else ACTIONS[action](params)
                self._send_json(200, result)
            except TypeError as e:
                self._send_json(400, {"error": f"Bad params for '{action}': {e}"})
            except Exception as e:
                self._send_json(500, {"error": str(e), "traceback": traceback.format_exc()})
        except Exception as e:
            print("[Resolve Bridge] ERROR in do_POST: " + str(e))
            traceback.print_exc()
            try:
                self._send_json(500, {"error": str(e)})
            except:
                pass

    def log_message(self, format, *args):
        try:
            print("[Resolve Bridge] " + (format % args))
        except:
            pass

# ── Start server ─────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 8787

_server = None

def _kill_previous_instance():
    """Try to shut down any previous bridge instance on the same port."""
    try:
        import urllib.request
        urllib.request.urlopen(
            "http://%s:%d/shutdown" % (HOST, PORT), timeout=2
        )
    except Exception:
        pass

def start_server():
    global _server
    if _server:
        print("[Resolve Bridge] Server already running on port %d" % PORT)
        return

    if not _connect():
        print("[Resolve Bridge] ERROR: Could not connect to Resolve API")
        return

    # Try to kill any stale instance first
    print("[Resolve Bridge] Checking for previous instance...")
    _kill_previous_instance()

    try:
        _server = HTTPServer((HOST, PORT), BridgeHandler)
    except OSError as e:
        print("[Resolve Bridge] ERROR: Could not bind to port %d - %s" % (PORT, e))
        print("[Resolve Bridge] Restart DaVinci Resolve and try again.")
        return

    print("[Resolve Bridge] HTTP server running on http://%s:%d" % (HOST, PORT))
    print("[Resolve Bridge] %d actions available" % len(ACTIONS))
    print("[Resolve Bridge] Test with: curl http://%s:%d/health" % (HOST, PORT))
    if _background_server:
        threading.Thread(
            target=_server.serve_forever,
            name="DaVinciResolveBridgeHTTP",
            daemon=True,
        ).start()
        return True
    # Scripts-menu fallback blocks here so the server stays alive.
    _server.serve_forever()

# Auto-start when script is run
try:
    start_server()
except Exception as e:
    print("[Resolve Bridge] FATAL ERROR: " + str(e))
    traceback.print_exc()
