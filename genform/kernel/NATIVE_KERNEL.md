# Native kernel integration

The kernel implementation uses Qt 6 Core and native OpenCascade C++; it does not load, spawn, embed or call Python. The active source tree no longer contains the original Python files. All 234 original `.py` files and the original root README/ARCHITECTURE documents are archived in `migration/python-original-2026-11-02.zip` (SHA-256 `D3951AF710D9FF157299F6BF0E5F3A3F3C34D3C993DC1E297AB8DC7C3140709F`). See `MIGRATION.md` for the repository-wide native module map, evidence and remaining behavior gaps. Removing the old sources is not proof of 1:1 feature or user-behavior parity.

## Build and link

Compile all of this directory's `.cpp` files. `native_selftest.cpp` is an empty translation unit unless `GENFORM_KERNEL_SELFTEST` is defined. Define `GENFORM_HAS_OCCT=1` only when the OCCT headers and libraries are available. Without it, the implementation needs only Qt Core, returns a successful empty document (also variables-only, fully suppressed or fully rolled-back documents), and throws an explicit SDK dependency error for active geometric features, geometry queries and export. It never returns a substitute mesh.

Verified locally with Qt 6.9.1, MSVC 2022 and OCCT 7.9.0. Required OCCT modules include `TKernel TKMath TKG2d TKG3d TKGeomBase TKBRep TKGeomAlgo TKTopAlgo TKPrim TKBO TKBool TKFillet TKOffset TKFeat TKShHealing TKMesh TKHLR TKXSBase`, the platform's STEP/STL exchange modules, and `TKV3d TKService` for exact font geometry. On OCCT 7.9 those exchange modules are `TKDESTEP TKDESTL`; older SDKs use different module names. Prefer the SDK's own CMake package library list rather than hardcoding the 7.9 names. MSVC needs `/Zc:__cplusplus` for Qt; CMake's normal Qt imported targets should supply the expected compiler configuration.

## JSON and state

- `build(features, upto, progress)` consumes the existing `.gform` feature objects: `id`, `type`, `params`, `suppressed`, optional `name`. `upto` is an exclusive count, clamped to `[0, features.size()]`.
- The exact Python output keys are preserved: `status` (singular), `sketches`, `info`, `has_body`; for solids also `verts`, `normals`, `tris`, `tri_face`, `faces`, `segments`, `segment_edge`, `edges`, `props`, `vertices`. Numeric arrays are ordinary nested JSON arrays, not base64. Mesh/edge/topology ids are zero-based and mutually aligned within a build.
- `props` preserves `volume`, `area`, `bodies`, `bbox_min`, `bbox_max`, `size`, `center_of_mass`. Face data contains `id/type/center/area/normal/feature/edges`, plus radius/origin where relevant. Edge data preserves `id/type/mid/length/dir` and circle parameters.
- States are `ok`, `suppressed`, `skipped`, `error: ...`. The first failed feature rolls back to the last successful body and later features are skipped. Errors are explicit, not replaced by zero geometry. Ownership is inherited using identity and touching compatible surfaces; patterned copies also retain their source feature.
- `preview` constructs a separate kernel and cannot replace the committed/exportable body. Its output is Python-compatible `verts/normals/tris/low/high/errors`, or `verts: null` plus errors if no solid exists.
- `query` operates on the last successful `build` state. Supported names: `model`, `status`, `preview`, `props`/`properties`, `bounds`, `edges`/`list_edges`, `faces`/`list_faces`, `vertices`, `measure`, `inspect`, `section`, `silhouette`. `measure` takes `{ "items": [{"kind":"face|edge|vertex", "id":0}, ...] }` and processes at most two entities, returning exact OCCT distances and applicable angles/center distances. `section`/`silhouette` return `{ "lines": [...] }` in the supplied plane; the frame can be `{origin,x,y}` or `[origin,x,y]`. Inspect rule-pair checks and optional proofing have been ported in `inspect.cpp`; nonempty rules are no longer categorically rejected as unported. This does not certify every rule, settings interaction or parameter combination as equivalent to the original implementation.
- `exportFile` exports the current committed body to STEP/STP, binary STL or BREP, checking writer results. Shape reads/writes use the native `file_io.hpp` / `file_io.cpp` helper for Unicode paths; Unicode file I/O regressions have passed. Unsupported formats fail explicitly.

## Feature coverage

- Sketches: rect, polygon, regular ngon, line, circle, arc, ellipse, slot, arcslot, Catmull-Rom splines, style Beziers, equation curves, points, construction geometry and exact font glyph text including path layout. Unordered/reversed connected edges form loops; nested loop parity creates holes/islands; open geometry remains display/path-only. Clockwise loops are oriented to the sketch plane.
- Frames: XY/XZ/YZ, explicit frames, reference planes (offset, angle or picked normal), global/sketch/reference/picked axes, reference points, coordinate systems, center of mass and bounding boxes.
- Makers: extrude (blind, distance2, mid/symmetric, reverse, through, vertex, planar surface/offset and up-to-body), revolve (including centerline and symmetric), sweep, loft/boundary, simple/counterbore/countersink/tapped holes, advanced stepped holes, studs, standard cap/button/flat socket screws and STEP solid import. Tapped holes, studs, screws and the standalone thread modifier generate real segmented helical thread cuts with the original phase/clearance conventions.
- Operations: add/cut/common and void/fill/pocket; fillet, chamfer, draft, opened/closed shell with optional partitions, rib, cylindrical wrap and surface split lines. Booleans split compound tools into individual arguments as Python does, use non-destructive OCCT algorithms, validate closed/oriented finite solids and conserve volume; freeform mass uses adaptive integration with a bounded thread-local cache.
- Patterns: linear, circular, mirror, curve, sketch, table, variable and fill; original tools and operations are retained for feature patterns and patterns-of-patterns.
- Curves: sketch3d, helix/spiral, xyz point spline, reference-point spline, projected sketch, UV surface curve and composite curves/selected edges.

## Remaining differences

No Python fallback exists. Assembly is implemented by the separate native `genform::assembly::Engine` in `genform/assembly/`, not by the kernel query interface. Its assembly, motion/analysis, BOM and fastener paths have real regression coverage, including the new fastener tests; assembly and fasteners must not be described as wholly unported. Manufacturing inspect rule-pair/proof checks are implemented in the kernel and have their own passing regressions. These results are not a blanket claim that every original assembly workflow or geometric branch is supported or equivalent.

STL solid reconstruction/import is not implemented. There is no independent-process watchdog or process-isolated execution, and cancellation of a running calculation is not fully migrated. There is no incremental/disk build checkpoint cache yet, so a changed feature list rebuilds from the start. The examples' method-B journal/checkpoint is a separate bounded workflow, not a general kernel checkpoint or full compatibility with original Python recovery behavior.

Complete gestures/rule-settings behavior and arbitrary inclined-plane workflows remain incomplete. UI, topology/ownership ids, material/per-feature color presentation and performance parity are not guaranteed. SKYE still needs four external STEP inputs, and full vehicle/example workflows have not all been run; deleting Python sources cannot conceal these gaps.

Sweep uses the standard exact pipe algorithm; sharp-corner or helix pipe-shell sweeps require one outer contour without holes. Loft follows the Python outer-wire behavior and does not loft nested holes. Cylindrical wrap currently rejects profiles containing nested holes/islands rather than silently dropping them. Thread construction has a 500-turn limit; patterns are bounded to 20,000 instances/candidates. Very complex self-intersecting or tolerance-sensitive geometry can fail visibly instead of using Python's specialized recovery paths. Exact topology ids can differ from Python/OCCT versions; stable references should continue using face centers/edge midpoints, not persisted numeric ids. Ownership inheritance uses identity/surface contact, not OCCT history for every algorithm, and performance on very large imported parts needs further profiling.

## Verification

Run `genform\kernel\run_native_selftest.cmd` or add `--without-occt`. The batch script accepts `QT_ROOT`, `OCCT_ROOT`, `VCVARS` environment overrides, changes no persistent environment configuration, writes only to ignored `.native-build*` subdirectories and links no Python library. It uses the locally observed SDK defaults as convenience values, not project requirements. The test main is macro-gated and does not affect the production library.

The root CMake build also provides the `genform_kernel_tests` target and `kernel_tests` CTest entry:

```bat
cmake --build build --target genform_kernel_tests --parallel 4
ctest --test-dir build -R "^kernel_tests$" --output-on-failure
```

As of 2026-11-02, all root targets have linked. The first root CTest run passed 15 of 16 tests; the old protocol diagnostic assertion was corrected and its standalone rerun passed 42/42. The final root 16-test rerun is still assigned to the parent task and must not be reported as passed in advance. Reported component runs passed migration 18/18, domain 1880 assertions, sketch 63, viewport 17, GUI 65 with `qmlwarning[]`, file I/O 423 and inspect 18, plus real assembly regressions including new fasteners. The examples' 52/52 valid-solid audit is separate evidence, not full workflow or geometry equivalence. This documentation update does not rerun those tests.

Runtime tests cover empty/missing-SDK/suppressed cases, expression evaluation and variables, extrusion/mid-plane/closed and unordered profiles, mesh topology alignment, preview isolation, holes, fillet/chamfer, linear/circular/variable/fill patterns, nested profiles, revolve, rollback/failure states, measurements, STEP/STL/BREP writing and STEP reimport, void/fill/pocket, opened/closed shell, loft, sweep, screws and real thread material removal, tapped thread removal, text, surface split, UV curves, inspect, section/silhouette, slots/ellipses, draft and cylindrical wrap. This is representative regression coverage, not evidence that every geometric branch, parameter combination or original user workflow has been tested or fully migrated.
