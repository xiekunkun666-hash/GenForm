# GenForm

[中文](README.md) | [English](README.en.md)

Designed by **泛化智能科技公司 (Fanhua Intelligent Technology)**.

GenForm is parametric 3D modeling software for collaboration between people and AI. Users can draw sketches, create features, and change dimensions in the graphical interface; AI or scripts can execute modeling commands, query models, save documents, and export geometry through MCP and local interfaces.

The project builds its desktop interface with **Python + PySide6 + QML + OpenGL** and uses **OpenCascade (cadquery-ocp)** for geometric computation. Models are generated from an ordered feature history. Changing upstream parameters recomputes subsequent features.

The project is currently under development. The desktop window uses native Win32 window behavior, so **Windows** is recommended. Model lengths are measured in **millimeters (mm)**, and the world coordinate system is **Z-up**.

## Contents

- [Main Features](#main-features)
- [Requirements and Installation](#requirements-and-installation)
- [Startup and Configuration](#startup-and-configuration)
- [Your First Part](#your-first-part)
- [Mouse Controls and Keyboard Shortcuts](#mouse-controls-and-keyboard-shortcuts)
- [Documents and Export](#documents-and-export)
- [AI and Scripting Integration](#ai-and-scripting-integration)
- [Project Structure and Development](#project-structure-and-development)
- [Testing](#testing)
- [Current Limitations](#current-limitations)
- [Troubleshooting](#troubleshooting)

## Main Features

| Category | Current Capabilities |
| --- | --- |
| 2D sketching | Lines, centerlines, rectangles, polygons, circles, arcs, ellipses, straight slots, arc slots, splines, equation-driven curves, points, and text |
| Sketch editing | Snapping, box selection, dragging, trimming, extending, fillets, offsets, mirroring, moving, linear and circular patterns, dimension editing, and sketch repair |
| Solid modeling | Extrudes, revolves, sweeps, lofts, boundary bosses, and their corresponding additive and cut operations |
| Feature modifications | Fillets, chamfers, holes, advanced holes, studs, physical threads, ribs, drafts, shells, wraps, and split lines |
| Patterns and mirrors | Linear, circular, curve-driven, sketch-driven, table-driven, fill, and variable patterns, plus mirrors |
| Curves and reference geometry | Helices, coordinate curves, projected curves, composite curves, reference planes, reference axes, coordinate systems, reference points, centers of mass, and bounding boxes |
| Feature history | Parameter changes, renaming, deletion, suppression and restoration, rollback, undo, and redo |
| 3D view | Face and edge picking, standard views, panning, rotation, zooming, display styles, sections, perspective, appearance, and materials |
| Files and automation | `.gform` documents, STEP/STL export, view screenshots, a local TCP interface, and MCP tool calls |

Some features use simplified implementations. For example, sketch geometric relations are not solved continuously, and boundary bosses currently handle profiles in only one direction. Read [Current Limitations](#current-limitations) before use.

## Requirements and Installation

### Requirements

- A Windows desktop environment; the current GUI includes Win32-specific code.
- Python: the local development environment uses **3.13.0**; Python 3.13 is recommended.
- A graphics card and driver supporting **OpenGL 3.3 Core Profile**. The application uses OpenGL to render the QML scene and 3D view.
- Git, for obtaining the source code and synchronizing changes.

The project currently has no installer, `requirements.txt`, or `pyproject.toml`. The installation commands below list the dependencies directly used by the source code. The dependency table gives the actual versions in the local development environment; it does not mean that all version combinations have been verified.

| Dependency | Purpose | Local Development Version |
| --- | --- | --- |
| PySide6 | Qt windows, QML, and interface control | 6.9.1 |
| numpy | Camera, picking, and geometry data calculations | 2.5.3 |
| PyOpenGL | OpenGL rendering | 3.1.10 |
| cadquery-ocp | OpenCascade Python bindings providing the `OCP` module | 8.0.1.0.0 |

### Obtain the Source and Install Dependencies

Run in PowerShell:

```powershell
git clone git@github.com:xiekunkun666-hash/GenForm.git
cd GenForm
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install PySide6 numpy PyOpenGL cadquery-ocp
```

Cloning over SSH requires GitHub SSH authentication to be configured beforehand. HTTPS is also available:

```powershell
git clone https://github.com/xiekunkun666-hash/GenForm.git
```

All commands below invoke Python from the virtual environment directly, so activation is unnecessary. Run commands from the project root.

## Startup and Configuration

### Open the Desktop Window

```powershell
.\.venv\Scripts\python.exe main.py
```

By default, startup also enables the local AI interface at `127.0.0.1:9631`. The GUI's geometry kernel runs in a separate process, and recomputed results are passed to the interface for display.

You can open an existing document at startup:

```powershell
.\.venv\Scripts\python.exe main.py "C:\models\part.gform"
```

### Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `GENFORM_PORT` | `9631` | Port for the desktop's local interface; setting it to `0` disables the interface. The MCP server connecting to the window also reads this variable |
| `GENFORM_SETTINGS` | `%APPDATA%\GenForm\settings.json` | Custom settings file location, useful for isolating test configurations |

For example, change the local interface port:

```powershell
$env:GENFORM_PORT = "9632"
.\.venv\Scripts\python.exe main.py
```

Use `$env:GENFORM_PORT = "0"` to disable the interface. These PowerShell assignments affect only the current terminal and the processes it starts. Run `Remove-Item Env:GENFORM_PORT` to restore the default port. An MCP process connecting to the window must use the same port as the window.

Keyboard shortcuts and the right-button gesture wheel can be customized in Settings. User settings are saved separately from part documents.

## Your First Part

The following example creates a rectangular base with a circular through-hole:

1. Start GenForm and select the **Top reference plane (XY)** in the design tree on the left or in the 3D view.
2. Click "Sketch", or select the rectangle tool directly to enter sketch editing.
3. Draw a rectangle and use "Smart Dimension" to set its width and height, for example `60 × 40 mm`.
4. Click "Finish Sketch", select "Extruded Boss/Base", enter `12 mm`, and confirm. You can also select extrude directly while editing a sketch; the software saves the sketch before opening the parameter panel.
5. Create another sketch on the XY reference plane, draw a circle with a radius of `8 mm`, and finish the sketch.
6. Select "Extruded Cut" and cut `12 mm` in the direction entering the solid. The default XY normal is +Z, so a cut along +Z from a sketch on the bottom passes through this base.
7. Select the edges to modify and add fillets or chamfers.
8. Save as `.gform`; export STEP or STL when sending the model to another CAD application or slicing software.

Double-click an existing sketch feature to edit it again. Changing feature parameters recomputes the model in history order. Features with errors are marked red in the design tree with an explanation; you can change their parameters or undo.

Only **closed profiles** in a sketch participate in extrusion. Inner closed profiles are treated as holes. Open lines and construction lines can remain as references but do not generate extruded solids. "Discard Sketch" does not write the current edits to the document history.

## Mouse Controls and Keyboard Shortcuts

### Mouse Controls

| Action | Function |
| --- | --- |
| Left click | Select objects; draw or select geometry while editing a sketch |
| Ctrl + left click | Add objects to the selection |
| Drag in an empty area of a sketch | Box-select geometry |
| Middle-button drag | Rotate the view |
| Ctrl / Shift + middle-button drag | Pan the view |
| Scroll wheel | Zoom toward the cursor |
| Right-button drag | Open the eight-direction gesture wheel and execute the action in the corresponding direction |

Modeling and sketch editing each have their own gesture wheel, customizable in Settings. Return the gesture to the center before releasing to cancel.

### Common Default Keyboard Shortcuts

| Shortcut | Function | Shortcut | Function |
| --- | --- | --- | --- |
| Ctrl + N | New part | Ctrl + O | Open document |
| Ctrl + S | Save document | Ctrl + , | Open Settings |
| Ctrl + Z | Undo | Ctrl + Y | Redo |
| Delete | Delete selected objects | S | Enter sketch mode |
| L / R / C / A | Line / Rectangle / Circle / Arc | D | Smart Dimension |
| T / O / M | Trim / Offset / Move | E / F | Extrude / Fillet |
| Z | Fit all | Ctrl + 7 | Isometric view |
| Ctrl + 1 / 2 | Front / Back view | Ctrl + 3 / 4 | Left / Right view |
| Ctrl + 5 / 6 | Top / Bottom view | Ctrl + 8 | Normal to |

Undo during sketch editing operates on snapshots of sketch geometry. Document-level undo operates on committed feature history.

## Documents and Export

| Format | Purpose | Preserved Content |
| --- | --- | --- |
| `.gform` | Editable GenForm document | Feature history, parameters, and part properties in JSON format; geometry is recomputed when opened |
| `.step` / `.stp` | Exchange models with other CAD applications | Exact geometry |
| `.stl` | Mesh workflows such as slicing | Triangle mesh |
| `.gasm` | GenForm assembly ("New → Assembly", or save from "Assembly Check" on the Simulation page) | JSON: relative paths to part files, their positions and rotation angles, and assembly sequence; part geometry remains in the individual files |
| `.gdrw` | GenForm drawing ("New → Drawing") | JSON: relative path to the part file, sheets, scale, view positions, manually annotated dimensions, and title block; supports PDF / DXF / SVG / PNG export |
| `.png` | Record or inspect a view | Image of the 3D view saved with the screenshot command |

Save a `.gform` document if you need to keep editing dimensions. STEP/STL exports do not preserve GenForm's parametric feature history.

You can drag multiple `.step` / `.stp` / `.stl` / `.gform` files into the window together, or use Ctrl / Shift to select multiple files in the Open dialog. Multiple files automatically form an assembly; if an assembly is already open, they are appended in a batch. Each file becomes an independent component that can be selected, moved, rotated, hidden, isolated, and deleted. Source-file coordinates are preserved; components are not automatically spaced apart or fused. If the current part contains a solid, it is retained as the first part in the assembly. "Insert Part" in an assembly also supports multiple selection. Files that fail to load show an error while the remaining files continue to display.

A single STEP file is still imported as a new part that supports further modeling; a single STL opens as an assembly mesh component. Both ASCII and binary STL are supported and read in millimeters, for display and placement. STL does not support exact solid measurement, interference checking, Boolean modeling, or STEP export. Assemblies containing STL can be saved as `.gasm`, which references source-file paths; include the source files when moving the project.

## AI and Scripting Integration

The GUI and AI modify documents through the same set of commands. Modification commands wait for geometry recomputation before returning results containing feature status and model dimensions. Query commands can read features, edges, faces, and the user's current selection.

### MCP: Connect to a Running Window

Start GenForm first, then have a client supporting MCP stdio launch:

```powershell
.\.venv\Scripts\python.exe -m genform.api.mcp_server
```

The repository's `.mcp.json` already contains a configuration, but its Python path and project directory are absolute paths on the development machine. On other machines, update them to the actual locations, for example:

```json
{
  "mcpServers": {
    "genform": {
      "command": "C:\\projects\\GenForm\\.venv\\Scripts\\python.exe",
      "args": ["-B", "-m", "genform.api.mcp_server"],
      "cwd": "C:\\projects\\GenForm"
    }
  }
}
```

To avoid managing the working directory, use the `genform_mcp.py` launcher in the root directory. The configuration then needs only two absolute paths (it is equivalent to `-m genform.api.mcp_server` and also accepts `--headless`):

```json
{
  "mcpServers": {
    "genform": {
      "command": "C:\\projects\\GenForm\\.venv\\Scripts\\python.exe",
      "args": ["C:\\projects\\GenForm\\genform_mcp.py"]
    }
  }
}
```

In Claude Code, connect with one command:

```powershell
claude mcp add genform -- "C:\projects\GenForm\.venv\Scripts\python.exe" "C:\projects\GenForm\genform_mcp.py"
```

In the application, click the gear on the right of the title bar → "AI Interface" to copy these configuration snippets with paths filled in for your machine.

This mode operates on the document in the current window, so users can see model changes. It is recommended to have the AI inspect the current contents with `get_model` before making modifications.

### MCP: Headless Modeling

```powershell
.\.venv\Scripts\python.exe -m genform.api.mcp_server --headless
```

Headless mode maintains an independent document inside the MCP process and does not require the desktop window. It is suitable for generating models and exporting files. Window-dependent commands such as `screenshot` and `set_view` are unavailable. The headless flag belongs to the MCP module, not to the startup arguments of `main.py`.

The MCP adapter transports JSON-RPC over standard input and output, declares protocol version `2024-11-05`, and supports initialization, tool listing, and tool calls. Logs go to standard error; waiting for input after launching it directly in a terminal is normal.

### Cancellation, Timeouts, and Disconnections

- MCP continues receiving input while executing tools. When the client stops a request, it should send `notifications/cancelled` with parameters `{"requestId": original_request_id}`. Closing MCP standard input also cancels unfinished requests. If a WebUI only changes a button's state without sending cancellation or closing the connection, GenForm cannot know that the user pressed Stop.
- Window mode disconnects the waiting connection for that request and tells the GUI to stop kernel work **belonging to that request**. If necessary, it terminates and recreates the separate kernel process without closing the main window, clearing the document, or canceling work from other connections.
- TCP requests may include a unique string `request_id` and `timeout_s` (greater than 0 and at most 300 seconds). Send `{"cmd":"cancel_request","request_id":"original_request_id"}` over another connection to cancel; disconnecting the request connection also triggers cancellation. If omitted, the interface generates a request ID and uses a 300-second total time limit.
- MCP window mode passes a 285-second total time limit to TCP, while the MCP request itself is limited to 290 seconds. The kernel also has a 120-second per-step watchdog and a 300-second whole-task watchdog. Progress messages reset only the per-step timer, not the total time limit.
- Cancellation or timeout **is not a transaction rollback**. Features may already have been written to the document. Use `get_model` to inspect `busy`, `model_stale`, `progress`, and `query_progress` before deciding whether to change parameters or undo. Modification commands are not automatically resent after disconnection, avoiding duplicate features.
- Headless mode still uses a synchronous in-process kernel: cancellation ends the protocol-level wait and discards late replies, but cannot guarantee interruption of an ongoing native OpenCascade call. Use window mode for automation that must be forcibly stoppable while retaining the window's document. This fix also does not replace the host WebUI's own forwarding of stop requests.

### Local TCP Interface

The desktop interface listens on `127.0.0.1:9631`, uses UTF-8, and exchanges **one JSON request per line and one JSON response per line**. This is a raw TCP protocol and cannot be accessed in a browser as an HTTP address.

```json
{"cmd": "tools"}
{"cmd": "get_model", "args": {}}
{"cmd": "sketch", "args": {"plane": "XY", "shapes": [{"type": "rect", "cx": 0, "cy": 0, "w": 60, "h": 40}]}}
{"cmd": "extrude", "args": {"distance": 12}}
```

The following Python example connects to a running window, creates a base, fillets its vertical edges, and saves a document and STEP file. It adds features to the current document, so running it in a blank document is recommended.

```python
import json
import os
import socket
from pathlib import Path


def call(command, **args):
    port = int(os.environ.get("GENFORM_PORT", "9631"))
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.settimeout(320)
        with connection.makefile("rwb") as stream:
            request = {"cmd": command, "args": args}
            stream.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            stream.flush()
            result = json.loads(stream.readline().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "GenForm 命令失败"))
    return result


sketch = call("sketch", plane="XY", shapes=[
    {"type": "rect", "cx": 0, "cy": 0, "w": 60, "h": 40}
])
call("extrude", sketch=sketch["id"], distance=12)
call("fillet", edges="|Z", radius=3)
print(json.dumps(call("get_model"), ensure_ascii=False, indent=2))

output = Path("build/example").resolve()
output.mkdir(parents=True, exist_ok=True)
call("save_document", path=str(output / "base.gform"))
call("export", path=str(output / "base.step"))
```

### Design Checks and View Operations

- Design checks are triggered manually: after modeling, click "Evaluate → Design Check". Opening an assembly or inserting or moving parts does not automatically run checks; "Log" in the status bar only expands existing results.
- "Clear Log" at the top right of the log clears errors, warnings, counts, and red crosses/highlights in the scene. Older results still being returned will not reappear. Clearing the log does not change geometry or mean that problems are fixed; click "Design Check" again to rerun checks.
- After the model changes, existing check results are marked stale and old scene error markers are removed. Checks are not recomputed in the background.
- When a part or assembly enters isolation mode, an "Exit Isolation" button appears at the top of the view. Exiting restores the previous hidden state.
- Drag a selection box with the left button from left to right to select objects fully inside it, or from right to left to select objects intersecting it. Assemblies support selecting multiple components, with Ctrl adding to the selection. Hidden components are excluded from box selection, and property editing still applies to the primary selected component.
- Rotating, panning, or zooming with the mouse preserves the selected display style. Shaded-with-edges mode does not temporarily switch to plain shading during movement.

### Common Commands

| Purpose | Commands |
| --- | --- |
| Get tools and parameter schemas | TCP request `tools`; MCP request `tools/list` |
| Create features | `sketch`, `extrude`, `fillet`, `chamfer`, and other commands registered in the feature specifications |
| Edit history | `edit_feature`, `delete_feature`, `rename_feature`, `suppress_feature`, `rollback`, `undo`, `redo` |
| Query the model | `get_model`, `list_edges`, `list_faces`, `get_selection` |
| Documents and export | `new_document`, `open_document`, `save_document`, `export` |
| Appearance and views | `set_material`, `set_appearance`, `set_view`, `screenshot` |

Use the JSON Schema in the tool list as the authoritative parameter specification. Lengths are in millimeters and sketch angles in degrees. Sketch coordinates use the selected plane's 2D coordinate system. The XY normal is +Z, the XZ normal is -Y, and the YZ normal is +X.

Edges can be specified with selectors such as `"all"`, `"|Z"`, `">Z"`, and `"<Z"`. Alternatively, call `list_edges` to obtain midpoints and then pass `[{"point": [x, y, z]}]`. Example of editing a feature:

```json
{"cmd": "edit_feature", "args": {"id": "f2", "params": {"distance": 20}}}
```

When `ok: false` is returned, inspect `error` and the model state. Features whose geometry fails usually remain in the history and require parameter changes or `undo`; a failed response does not mean that the step was never written to the document. `new_document` clears the document, so save anything you need to keep before calling it.

## Project Structure and Development

```text
GenForm/
├── main.py                 # Lightweight entry point; handles multiprocessing startup
├── ARCHITECTURE.md         # Layers, threads, feature references, and implementation details
├── .mcp.json               # MCP client configuration; adjust paths for your machine
├── genform/
│   ├── bootstrap.py        # Wires up the window, session, kernel, and local interface
│   ├── app.py              # Interface controller
│   ├── actions.py          # Actions, default shortcuts, and gesture wheels
│   ├── forms.py            # Parameter panel data
│   ├── commands.py         # Command registration and parameter schemas
│   ├── features.py         # Feature definitions and reference geometry calculations
│   ├── document.py         # Feature history, undo/redo, and document I/O
│   ├── session.py          # Command execution, recomputation, and result notifications
│   ├── sketcher.py         # Sketch editor
│   ├── sketchgeom.py       # 2D geometry and algorithms
│   ├── api/                # TCP server, MCP adapter, and JSON encoding
│   ├── kernel/             # OpenCascade geometry computation and worker process
│   └── view/               # Camera, picking, and OpenGL rendering
├── qml/                    # Window, toolbars, design tree, parameter panels, and themes
└── tests/                  # Unit tests and desktop smoke tests
```

Main data flow:

```text
UI actions / MCP / TCP
        ↓
commands → session → document
               ↓
        Geometry kernel recomputation
               ↓
        Model state / 3D display / Command response
```

Documents store feature data; solids are generated by recomputing features. The GUI uses a separate kernel process, while tests and headless MCP use a synchronous kernel. The 3D view redraws on demand to avoid continuous refresh while idle.

Adding a feature typically requires registering its parameters in `SPECS` in `genform/features.py`, implementing and registering a computation function in `genform/kernel/features.py`, and adding corresponding geometry tests. See [ARCHITECTURE.md](ARCHITECTURE.md) for further implementation rules.

## Testing

### Unit Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -t .
```

Tests cover the geometry kernel, features, command sessions, sketch editing, and some view mathematics. Unit tests do not launch the main desktop window, but kernel tests require the OpenCascade dependency to be installed.

### Desktop Smoke Tests

```powershell
.\.venv\Scripts\python.exe tests\smoke_gui.py
.\.venv\Scripts\python.exe tests\smoke_ui.py
.\.venv\Scripts\python.exe tests\smoke_features.py
.\.venv\Scripts\python.exe tests\smoke_sketch.py
.\.venv\Scripts\python.exe tests\smoke_sketch2.py
.\.venv\Scripts\python.exe tests\smoke_quit.py
```

- `smoke_gui.py`: verifies modeling, error handling, undo, dimension changes, screenshots, export, and saving through the local interface.
- `smoke_ui.py`: simulates mouse operations and captures images of the actual window.
- `smoke_features.py`: checks interactions on the Features page and with reference geometry.
- `smoke_sketch.py` / `smoke_sketch2.py`: check interactions with sketch tools and editing operations.
- `smoke_quit.py`: checks that the application exits normally after modeling.

These scripts launch real windows. Scripts using the mouse and screen capture require an interactive desktop; avoid covering the test window or using the mouse at the same time. Default output goes to `build/smoke/` and includes screenshots, logs, and exported files. `smoke_gui.py` also accepts a custom output directory. `build/` is ignored by Git.

## Current Limitations

- **Sketches do not have continuous constraint solving.** "Add Geometric Relation" adjusts geometry once according to the relation. Smart Dimension changes geometry parameters without retaining driving dimension annotations. Offset, mirror, pattern, and converted references produce copies as they exist at that moment.
- **Modeling currently uses a single solid.** There is no multi-body management. Assemblies only have "Assembly Check" on the Simulation page (positioning parts, checking interference, and checking assembly sequences), without mates. `op: common` intersects with the current solid.
- **Sketching on faces.** Select a planar face on the part and click "Sketch". Axis-aligned faces use the corresponding reference plane with an offset; an inclined face automatically creates a reference plane feature first.
- **Simulation provides estimates.** Static analysis divides the part into small cubes to solve it (stress accuracy is approximately ±20%, with underestimation at sharp corners). Drag is calculated only from frontal area and a drag coefficient, rather than a flow-field simulation. Assembly sequencing tests straight-line insertion only in the six directions ±X, ±Y, and ±Z. Modal, thermal, and fatigue analyses are not yet available.
- **Topological references use a simplified implementation.** Coordinate-based edge and face references rely on nearby geometry matching. Large upstream dimension changes may require references to be selected again.
- **Some features have limited scope.** Boundary bosses currently use a loft algorithm; wraps support cylindrical faces only; ribs support extension parallel to the sketch only; draft uses a neutral plane.
- **Patterns and mirrors have object restrictions.** Copying selected features requires tool bodies generated by those features, such as extrudes, revolves, sweeps, lofts, holes, and studs. Modifying features such as fillets and shells cannot be copied in the same way.
- **3D sketches currently use coordinate input.** `sketch3d` and surface curves are not drawn directly with the mouse in the 3D view.
- **Threads generate physical geometry.** Computation may be slow; cosmetic thread lines are not yet available.
- STL loads as a mesh reference and is not converted to an editable exact solid. A view cube and installer have not yet been implemented.

## Troubleshooting

| Symptom | Checks and Actions |
| --- | --- |
| `ModuleNotFoundError` | Make sure you are using the same Python where the dependencies are installed; the `OCP` module is provided by `cadquery-ocp` |
| Window fails to start or the 3D view behaves incorrectly | Inspect Qt/OpenGL logs in the terminal, and check graphics drivers and OpenGL 3.3 support; remote desktop or virtual graphics environments require separate verification |
| MCP cannot connect to GenForm | Start the window first and ensure the window and MCP use the same `GENFORM_PORT`; use `--headless` for independent modeling |
| Local AI interface is not enabled | Check whether the port is occupied or `GENFORM_PORT` is `0`; if the window starts but interface binding fails, no TCP service is provided |
| Extrude does not produce a solid | Check that the profile is closed, that it does not consist entirely of construction lines, and inspect the feature error message |
| Fillet or chamfer fails | Try a smaller size and check the selected edges; correct parameters with `edit_feature` or undo the failed feature |
| Cannot take screenshots in headless mode | Screenshot and view commands depend on the GUI; use MCP mode connected to a window |
| Exported files cannot continue to be edited parametrically | Also save a `.gform` document; STEP/STL exchange geometry and do not preserve this project's feature history |
