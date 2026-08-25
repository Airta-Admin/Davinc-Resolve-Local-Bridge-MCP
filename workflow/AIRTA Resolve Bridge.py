"""Resolve Workflow Integration launcher for the AIRTA MCP bridge."""

import json
import os
import runpy
import threading
import urllib.request


HOST = "127.0.0.1"
PORT = 8787
BASE_URL = "http://%s:%d" % (HOST, PORT)
WINDOW_ID = "net.airta.resolve.bridge.launcher"


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
    runpy.run_path(path, run_name="__airta_resolve_bridge__")


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
            "WindowTitle": "AIRTA Resolve Bridge",
            "Geometry": [1120, 80, 420, 135],
            "StyleSheet": "QWidget { background: #171923; color: #f7fafc; } "
                          "QPushButton { background: #5865F2; border: 0; border-radius: 6px; "
                          "padding: 8px 12px; font-weight: 600; } "
                          "QPushButton:hover { background: #4A9EFF; }",
        },
        ui.VGroup([
            ui.Label({"ID": "Status", "Text": _status_text(), "ToolTip": "AIRTA Resolve MCP bridge status"}),
            ui.HGroup([
                ui.Button({"ID": "Start", "Text": "Start Bridge"}),
                ui.Button({"ID": "Stop", "Text": "Stop Bridge"}),
                ui.Button({"ID": "Refresh", "Text": "Refresh Status"}),
            ]),
            ui.Label({"Text": "Local endpoint: " + BASE_URL}),
        ]),
    )

    def refresh(_event=None):
        win.Find("Status").Text = _status_text()

    def start(_event=None):
        if _status_text() == "Stopped":
            threading.Thread(target=_launch_bridge, name="AIRTAResolveBridge", daemon=True).start()
        win.Find("Status").Text = "Starting..."

    def stop(_event=None):
        try:
            _request("/shutdown")
            win.Find("Status").Text = "Stopping..."
        except Exception:
            win.Find("Status").Text = "Stopped"

    def close(_event=None):
        dispatcher.ExitLoop()

    win.On.Start.Clicked = start
    win.On.Stop.Clicked = stop
    win.On.Refresh.Clicked = refresh
    win.On[WINDOW_ID].Close = close
    win.Show()
    dispatcher.RunLoop()
