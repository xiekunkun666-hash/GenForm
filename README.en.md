# GenForm

[中文](README.md) | [English](README.en.md)

Designed by **泛化智能科技公司 (Fanhua Intelligent Technology)**.

GenForm is parametric 3D modeling software for collaboration between people and AI. The desktop interface, command sessions, geometry kernel, assemblies, domain calculations, MCP service, and example entry points now use **native C++20**. The interface uses **Qt / QML**, and precise geometry uses the **OpenCascade (OCCT) C++ SDK**. A complete compilation and link have been completed locally with Qt 6.9.1, OCCT 7.9, and the MSVC toolchain.

**Running GenForm does not require Python, PySide6, numpy, PyOpenGL, or the OCP Python bindings.** QML, JSON recipes, and models are data read by the native program, not alternative launchers for Python. Lengths are measured in millimeters (mm), and the world coordinate system uses Z as the up axis.

The project is still undergoing migration acceptance: the ability to build and run native executables does not mean that every feature, interaction, and test from the previous implementation has been migrated with equivalent behavior. Also read [Current Limitations](#current-limitations), [Testing and Acceptance Status](#testing-and-acceptance-status), the [architecture documentation](ARCHITECTURE.md), and the [migration record](MIGRATION.md).

## Quick Start: Windows / cmd

Open **cmd.exe** in the project root:

```bat
build-native.cmd
run-native.cmd
```

Open an existing document:

```bat
run-native.cmd "C:\models\part.gform"
```

`build-native.cmd` configures and builds the root `build/` directory, producing the desktop program `build\genform.exe` and the MCP program `build\genform_mcp.exe`. `run-native.cmd` and `run-mcp.cmd` set the Qt / OCCT DLL search paths for their respective entry points and forward arguments. These scripts launch native EXEs and do not launch Python.

The desktop shortcut “GenForm（源码启动）” (“GenForm — Launch from Source”) runs `launch-from-source.cmd`, incrementally building and launching `build\window-native\genform.exe`. This includes native window commands and sketch dimension fixes, while avoiding overwriting older `build\genform.exe` or `build\ui-fix\genform.exe` executables that may still be running. `build-native.cmd`, `run-native.cmd`, and the source-launch script support `GENFORM_BUILD_DIR` to select a build directory; `run-mcp.cmd` still defaults to the root `build` directory. See the [UI audit](migration/UI_AUDIT.md) for interface omissions, completed fixes, and outstanding features as of 2026-11-02.

### Toolchain and SDKs

| Component | Requirement or locally verified environment |
| --- | --- |
| Compiler | C++20 support; locally, Visual Studio 2022 MSVC x64 |
| CMake | 3.24 or newer |
| Generator | Local scripts use Ninja |
| Qt | CMake declares a minimum of 6.5; locally verified with 6.9.1, MSVC x64 SDK |
| OCCT | Locally verified with 7.9 C++ headers, import libraries, and runtime DLLs |
| Desktop | Windows has been verified locally; this does not establish acceptance on other platforms |

Qt requires the Core, Gui, Widgets, Qml, Quick, QuickControls2, Network, Concurrent, OpenGL, Svg, and PrintSupport modules. Linking the Qt OpenGL module does not mean the 3D viewport retains the previous OpenGL engine; see [Current Limitations](#current-limitations).

The default paths in the root scripts are **development-machine settings**, not mandatory installation locations for all users. The local OCCT SDK comes from the `Library` directory of an Anaconda environment; only its C++ headers, libraries, and DLLs are used. **There is no need to activate that environment, and its Python is not run.** ABI-compatible OCCT SDKs from other sources can also be used by configuring the paths.

Before calling the scripts, override the defaults with your actual installation paths. The following paths are examples only:

```bat
set "QT_ROOT=D:\SDK\Qt\6.9.1\msvc2022_64"
set "OCCT_ROOT=D:\SDK\OCCT-7.9"
set "VCVARS=D:\VS2022\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE_EXE=D:\Tools\CMake\bin\cmake.exe"
set "NINJA_EXE=D:\Tools\Ninja\ninja.exe"
build-native.cmd
```

`OCCT_ROOT` should point to an SDK prefix containing `include\opencascade`, `lib`, and `bin`. The architectures and runtime libraries of Qt, OCCT, and the compiler must be compatible. By default, `build-native.cmd --test` uses `ctest.exe` from the directory containing `CMAKE_EXE`. If CTest is installed elsewhere, override it with `CTEST_EXE`, for example `set "CTEST_EXE=D:\Tools\CMake\bin\ctest.exe"`.

### General CMake Build

With the compiler environment configured and `cmake` and `ninja` available:

```bat
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="%QT_ROOT%" -DGENFORM_OCCT_ROOT="%OCCT_ROOT%"
cmake --build build --parallel 4
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
ctest --test-dir build --output-on-failure
build\genform.exe
```

You can also let CMake find a standard SDK configuration through `find_package(OpenCASCADE)` without passing `GENFORM_OCCT_ROOT`. Without OCCT, some document/API code can still be built, but geometry commands explicitly report a dependency error; this is not a substitute for acceptance of a complete CAD build. Application QML, languages, and icons are embedded in the native program through the Qt resource system, so the source resource directories no longer need to accompany it. Qt / OCCT DLLs and Qt plugins must still be deployed correctly, and example recipes still depend on source paths, so copying a single EXE does not constitute a complete distribution package.

## Desktop and Modeling

The native controller connects to the existing QML window, design tree, parameter panel, sketch toolbar, assembly tree, and drawing/simulation panels. The main capabilities are listed below; the scope and precision of each are determined by the actual commands, error messages, and coverage records.

| Module | Native implementation |
| --- | --- |
| Sketching | Shape data, interactive editing, snapping, selection, and 2D geometry editing algorithms |
| Parametric modeling | Feature history and OCCT modeling paths for extrusion, revolution, sweep, loft, holes, fillets, chamfers, patterns, and more |
| Documents | JSON features and properties, parameter editing, suppression, rollback, undo/redo, saving/opening |
| View | Native software rendering of triangle meshes, camera operations, picking, selection, sketch overlays, screenshots |
| Assemblies | C++ modules for assembly documents, part poses, joints/motion, interference and analysis, BOM, and more |
| Domain features | Calculations for materials, manufacturing processes, costs, standard parts, sketch editing, and design checks |
| Files and automation | `.gform`, assembly data, STEP/STL geometry exchange, TCP and MCP command entry points |

A minimal part workflow: select the XY reference plane, create a closed rectangular sketch, finish the sketch and extrude it, check feature status in the design tree, and save a `.gform` file. Recompute after changing dimensions. If an error occurs, correct or undo the failed feature; do not mistake the last successful solid still displayed on screen for a successful modification.

`.gform` is readable JSON that stores feature parameters and document properties; the native kernel rebuilds the geometry. STEP/STL are for geometry exchange and do not preserve GenForm's complete parametric history. Keep the original document as well if further editing is needed. External files used by imported features and assembly references must also be retained; check their paths when moving a project.

## MCP and Local Commands

### Connecting to the Desktop

Start `run-native.cmd` first, then start MCP in another cmd window at the project root:

```bat
run-mcp.cmd
```

`run-mcp.cmd` sets the Qt / OCCT DLL paths. If the SDKs are not in the script's default locations, set `QT_ROOT` / `OCCT_ROOT` in the environment that launches MCP. This entry point is recommended over launching the EXE directly from an ordinary environment without DLL search paths configured. The local environment inside `run-native.cmd` is not passed to another terminal.

By default, MCP forwards tool calls to the desktop session at `127.0.0.1:9631`, so people can see changes to the same document. The root `.mcp.json` now uses the following launch configuration:

```json
{
  "mcpServers": {
    "genform": {
      "command": "cmd",
      "args": ["/d", "/c", "run-mcp.cmd"],
      "cwd": "."
    }
  }
}
```

Here, `cwd: "."` requires the client to use the project root as its working directory. If the client starts elsewhere, change `cwd` to the actual absolute path of GenForm. Pass custom SDK environment variables according to the client's rules; do not rely on another terminal's local environment.

### Headless Modeling and Protocol Checks

```bat
run-mcp.cmd --headless
run-mcp.cmd --help
```

`--headless` uses a native `Session` within the current process and does not connect to the desktop. Tools that depend on a viewport, such as camera views and screenshots, are unavailable. It still uses Qt GUI infrastructure but does not open the main desktop window. In environments without a display service, set `QT_QPA_PLATFORM=offscreen` as appropriate for the actual platform; this does not imply that all graphics plugins have been packaged.

MCP uses **one JSON-RPC object per line** over stdio, with protocol output isolated from diagnostics. The following is a minimal initialization-request check in cmd, not a substitute for a complete MCP client handshake:

```bat
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual-check","version":"1"}}} | run-mcp.cmd --headless
```

Get the actual tool list through MCP `tools/list`, and execute tools with `tools/call`. Do not write desktop TCP `cmd` envelopes directly to MCP stdio.

### Local TCP

The desktop service binds only to the loopback address, with default port `9631`. Set `GENFORM_PORT=9632` to change the port, or set it to `0` to disable the desktop interface. MCP also reads this variable and supports an explicit override with `--port 9632`.

TCP uses newline-delimited UTF-8 JSON objects, for example:

```jsonl
{"cmd":"tools"}
{"cmd":"get_model","args":{"brief":true}}
{"cmd":"sketch","args":{"plane":"XY","shapes":[{"type":"circle","cx":0,"cy":0,"r":10}]}}
```

The feature ID returned by a creation command can be used for a subsequent extrusion. Follow the parameter schema returned by `tools`. Common commands include `new_document`, `open_document`, `save_document`, `edit_feature`, `batch`, `get_model`, `list_edges`, and `list_faces`.

**Cancellation or a timeout does not prove that the kernel has stopped.** Once a synchronous OCCT calculation starts, the interface can report cancellation/a timeout but cannot interrupt the running calculation. After a response with an uncertain outcome, query the document first and, if necessary, wait for the calculation to finish. Do not automatically resend modifying commands. This version provides neither the previous kernel-subprocess watchdog nor a promise of automatic recovery after a crash.

## Native Examples

`examples/native/` provides a unified native program mapping the original 28 example entry points. Entry-point names retain historical module identifiers but do not execute historical scripts:

```bat
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
build\examples\genform_examples.exe --list
build\examples\genform_examples.exe --audit
build\examples\genform_examples.exe button_latch/build all --output build\example-output\button-latch
ctest --test-dir build -R "^examples_" --output-on-failure
```

Recipe generation, validation, comparison, and logging all have native paths. Output usually requires an explicit `--output`; do not point it at the only copy of an original model. See [MIGRATION.md](MIGRATION.md) for entry-point arguments and evidence.

A **native-kernel audit of 52 actual models has been completed: 52 passed / 0 failed**, including the button_latch, button_claw_latch, powder_pump, lance, and powder_pump_fan recipes. This does not prove equivalent acceptance of all business workflows across the 28 entry points. **SKYE is missing 4 source STEP files, and the complete vehicle workflow has not been fully run.** Paths with missing resources or that have not been executed must not be counted as successful.

## Testing and Acceptance Status

Local cmd shortcut:

```bat
build-native.cmd --test
```

You can also run the matching `ctest` independently from PATH. The build script's test entry point supports the `CTEST_EXE` override described above:

```bat
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
ctest --test-dir build -N
ctest --test-dir build --output-on-failure
ctest --test-dir build -R "^(domain_tests|session_tests|migration_tests|protocol_tests|file_io_tests|assembly_tests|kernel_tests|inspect_tests|sketch_tests|viewport_tests|gui_smoke_test)$" --output-on-failure
ctest --test-dir build -R "^examples_" --output-on-failure
```

The desktop smoke test can also be run with `run-native.cmd --gui-smoke-test`. For a noninteractive environment, you can set `QT_QPA_PLATFORM=offscreen` before running it. It verifies limited scenarios involving the native controller and QML; it does not mean that all previous mouse, gesture, and interaction tests have been migrated.

Final clean-build and verification results from 2026-11-02:

- After removing build artifacts, a complete recompile and link succeeded. Running `build-native.cmd --test` produced **16/16 CTest tests passed, 0 failures, in 68.86 seconds**. Internal protocol regression checks passed 42/42 groups; stdout from actual STEP export remained pure JSON-RPC, with OCCT diagnostics kept on stderr.
- The root implementation causes of 4 migration regression issues were fixed; the result is now **18/18 groups passed**. Kernel inspect self-tests using real rule-pair / proof checks passed **18 checks**, and Chinese/emoji file I/O passed **423 checks**.
- GUI smoke tests passed **65 checks**, including Chinese/English languages and settings, with `QMLWarnings=[]`. Sketch self-tests passed **63 checks**, viewport **17 checks**, and domain **1880 checks**. These are internal check counts within their respective subsets and must not be added to the CTest count.
- The example subset passed **5/5**, including **52/52** actual-model audit checks. The unverified boundaries for SKYE and vehicles remain. Partial or missing coverage of the original 62 tests' semantics continues to be tracked in [tests/COVERAGE.md](tests/COVERAGE.md).

The active tree contains 0 `.py`, `.pyw`, and `.pyc` files. The original 234 Python source files have been verified individually and archived. Passing tests represents only the current native suite; it does not mean that all original features and previous test semantics have been migrated with equivalent behavior item by item. The coverage ledger remains the reference for the full limitations.

## Current Limitations

- **Synchronous kernel and recovery boundaries:** Geometry calculations can still block the session/interface; an OCCT request that has started cannot be forcibly interrupted. The previous process watchdog is no longer used, and there is no incremental disk checkpointing or guarantee of automatic recovery of unsaved work. In-memory undo snapshots and atomic saving are not a crash-recovery system.
- **The software viewport is not the previous OpenGL engine:** The current native viewport draws triangle meshes through `QQuickPaintedItem` / `QPainter`. Display, occlusion, transparency, picking, and performance cannot be claimed to be fully equivalent to the previous renderer; on-screen outlines do not represent precise hidden-line results.
- **Sketches and reference geometry:** There is no continuous constraint solving. Sketching on arbitrary inclined planes and related coordinate transformations/interactions should not be considered fully equivalent. One-time edits are not associatively driven constraints.
- **Interaction and settings:** Previous gestures and design-rule settings have not yet been migrated. Passing smoke tests for Chinese/English languages and implemented settings does not establish equivalence for all previous settings.
- **Drawings and exchange:** Precise hidden lines, DXF, and the complete drawing output pipeline are not yet fully equivalent to the previous version. Merely listing a UI element or command does not mean the corresponding format has passed acceptance.
- **Topology and features:** Edge/face references based on coordinates or proximity matching can become invalid after large dimension changes. Complex booleans, surfaces, patterns, wraps, actual threads, and similar operations require case-by-case checks; success cannot be promised for arbitrary inputs.
- **Analysis is not certification:** Support for assembly motion, interference, statics, and manufacturing estimates is bounded by the native implementation and tests. These are not a general-purpose constraint solver or engineering certification, and precision figures from the previous implementation that have not been reverified are not carried forward.
- **Resources and distribution:** Application QML, languages, and icons are embedded. External STEP files, assembly references, and example recipes that still use source paths must be located correctly. See above for the SKYE and vehicle verification boundaries. Standalone installer packages and cross-platform releases have not yet passed acceptance.

## Project Structure and Historical Backup

```text
GenForm/
├── CMakeLists.txt             # C++20 core, desktop, MCP, tests, and examples
├── build-native.cmd          # MSVC/Ninja build entry point with overridable local paths
├── run-native.cmd            # DLL paths and desktop launch entry point
├── run-mcp.cmd               # DLL paths and MCP stdio launch entry point
├── main.cpp                  # Desktop launcher
├── genform_mcp.cpp           # Native MCP stdio entry point
├── genform/
│   ├── document.* / session.* # JSON documents, history, commands, and recomputation
│   ├── features.* / commands.json
│   ├── controller/           # QML bridging and sketch interaction
│   ├── domain/               # Geometry, materials, processes, costs, and checks
│   ├── kernel/               # OCCT geometry and display data
│   ├── assembly/             # Assemblies, motion, analysis, and BOM
│   ├── api/                  # Loopback TCP, MCP, and protocol encoding
│   └── view/                 # Software triangle-mesh viewport and drawing views
├── qml/                      # Window and interface sources compiled into Qt resources
├── examples/                 # Native entry points, recipes, and audits
├── models/                   # Example documents and external geometry resources
├── tests/                    # C++ tests and COVERAGE.md migration ledger
└── migration/                # Historical ZIP backup of previous sources and documentation
```

The original **234 Python files and the original README / ARCHITECTURE have been archived** in `migration/python-original-2026-11-02.zip`, with each group's hashes verified. All `.py` files in the active code tree were removed through patches. The ZIP's SHA-256 is:

```text
D3951AF710D9FF157299F6BF0E5F3A3F3C34D3C993DC1E297AB8DC7C3140709F
```

The ZIP is a historical backup only. It is not involved in configuration, building, testing, or running, and it does not need to be extracted to use the native program. See [ARCHITECTURE.md](ARCHITECTURE.md) for more detailed responsibilities and security boundaries.

## Troubleshooting

| Symptom | Checks and actions |
| --- | --- |
| Qt / OCCT DLL not found | Check SDK architectures and paths. Use `run-native.cmd` for the desktop and `run-mcp.cmd` for MCP; do not try to fix native linking problems by installing Python packages |
| CMake cannot find an SDK | Check `QT_ROOT`, `GENFORM_OCCT_ROOT`, and the actual header/library directories. Use a new build directory after changing the compiler/SDK |
| `qml/Main.qml` not found | Normal builds embed QML. Confirm that you are using the latest artifacts and that the resource build succeeded. During development, use `GENFORM_QML_DIR` to specify an override directory containing `Main.qml` |
| MCP cannot connect to the desktop | Confirm that the window is running, the ports match, and the port is not set to 0. Use `--headless` for independent modeling |
| Headless commands cannot take screenshots | Screenshots/camera views depend on an actual desktop viewport; use MCP mode connected to the desktop |
| Uncertain result after a timeout or cancellation | Wait and query the current document; avoid blindly retrying modifying commands. A timeout does not guarantee rollback or interruption of the calculation |
| Feature failure or unexpected volume | Check feature status, closed profiles, references, and scale. Correct/undo, recompute, and verify the solid |
