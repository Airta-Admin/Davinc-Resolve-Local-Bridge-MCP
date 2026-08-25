"""Workflow Integration launcher for DaVinci Resolve Local Bridge MCP."""

import json
import os
import runpy
import sys
import threading
import urllib.request
import webbrowser


HOST = "127.0.0.1"
PORT = 8787
BASE_URL = "http://%s:%d" % (HOST, PORT)
WINDOW_ID = "io.github.resolve.local.bridge.mcp.connection"
TIP_URL = "https://buy.stripe.com/9B6eVd3vP3Et5465MI7bW05"


def _tip_icon_path():
    """Resolve's Workflow Integration runtime may not define __file__."""
    candidates = []
    script_file = globals().get("__file__")
    if script_file:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(script_file)), "assets", "tip-jar.png"))
    if sys.argv and sys.argv[0]:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "assets", "tip-jar.png"))
    candidates.append(os.path.join(
        os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
        "Blackmagic Design", "DaVinci Resolve", "Support",
        "Workflow Integration Plugins", "assets", "tip-jar.png",
    ))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[-1]


def _bridge_path():
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "Blackmagic Design", "DaVinci Resolve", "Support", "Fusion",
        "Scripts", "Utility", "DaVinciResolveBridge.py",
    )


def _request(path, timeout=2):
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _status_text():
    try:
        health = _request("/health")
        actions = _request("/actions")
        if health.get("status") == "ok":
            return "Running on %s (%d actions)" % (BASE_URL, len(actions.get("actions", [])))
    except Exception:
        pass
    return "Stopped"


def _launch_bridge():
    path = _bridge_path()
    if not os.path.isfile(path):
        raise RuntimeError("Bridge script not found: " + path)
    runpy.run_path(path, run_name="__davinci_resolve_local_bridge__")


try:
    import DaVinciResolveScript as bmd
except ImportError:
    pass  # Resolve supplies bmd when the script is launched internally.

ui = fusion.UIManager
dispatcher = bmd.UIDispatcher(ui)
existing = ui.FindWindow(WINDOW_ID)
if existing:
    existing.Show()
    existing.Raise()
else:
    win = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "DaVinci Resolve Local Bridge MCP Server Connection",
            "Geometry": [980, 80, 560, 170],
            "StyleSheet": "QWidget { background: #171923; color: #f7fafc; } "
                          "QPushButton { background: #5865F2; border: 0; border-radius: 6px; "
                          "padding: 8px 12px; font-weight: 600; } "
                          "QPushButton:hover { background: #4A9EFF; } "
                          "#TipPanel { background: #202330; border: 1px solid #3c4257; "
                          "border-radius: 8px; padding: 8px; } "
                          "#TipButton { background: #635BFF; }",
        },
        ui.HGroup([
            ui.VGroup({"Weight": 3}, [
                ui.Label({"ID": "Status", "Text": _status_text(), "ToolTip": "DaVinci Resolve Local Bridge MCP status"}),
                ui.HGroup([
                    ui.Button({"ID": "Start", "Text": "Start Bridge"}),
                    ui.Button({"ID": "Stop", "Text": "Stop Bridge"}),
                    ui.Button({"ID": "Refresh", "Text": "Refresh Status"}),
                ]),
                ui.Label({"Text": "Local endpoint: " + BASE_URL}),
            ]),
            ui.VGroup({"ID": "TipPanel", "Weight": 1}, [
                ui.Button({
                    "ID": "TipButton",
                    "Text": "$5 Developer Tip",
                    "Icon": ui.Icon({"File": _tip_icon_path()}),
                    "IconSize": [72, 72],
                    "ToolTip": "Open secure Stripe checkout for an optional one-time $5 developer tip",
                }),
                ui.Label({"Text": "Optional · One time", "Alignment": {"AlignHCenter": True}}),
            ]),
        ]),
    )

    def refresh(_event=None):
        win.Find("Status").Text = _status_text()

    def start(_event=None):
        if _status_text() == "Stopped":
            threading.Thread(target=_launch_bridge, name="DaVinciResolveLocalBridge", daemon=True).start()
        win.Find("Status").Text = "Starting..."

    def stop(_event=None):
        try:
            _request("/shutdown")
            win.Find("Status").Text = "Stopping..."
        except Exception:
            win.Find("Status").Text = "Stopped"

    def close(_event=None):
        dispatcher.ExitLoop()

    def open_tip(_event=None):
        webbrowser.open(TIP_URL, new=2)

    win.On.Start.Clicked = start
    win.On.Stop.Clicked = stop
    win.On.Refresh.Clicked = refresh
    win.On.TipButton.Clicked = open_tip
    win.On[WINDOW_ID].Close = close
    win.Show()
    dispatcher.RunLoop()
    win.Hide()
