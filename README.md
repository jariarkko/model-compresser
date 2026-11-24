# model-compresser

A small command-line tool that makes 3D models of caves smaller, so that they
are easier to share, download and view. A scanned cave is typically hundreds
of megabytes; the same cave at a size that still looks right in a viewer is
usually a tenth of that or less.

    model-compresser [options] inputfile outputfile
    model-compresser --info inputfile

It does four things, the same four one would do by hand in Blender:

1. **Welds duplicate vertices.** Scanner apps and Blender's glTF export store
   every triangle with its own three vertices; in every cave model I have
   looked at this alone cuts the vertex count by 5-6x without changing the
   geometry at all. It is also a precondition for the next step: a mesh of
   disconnected triangles cannot be simplified, only have triangles deleted.
2. **Simplifies the mesh** with quadric edge collapse -- the algorithm behind
   Blender's *Decimate* modifier (Collapse mode) -- using MeshLab's
   texture-aware variant, so that texture seams stay put.
3. **Shrinks the textures** to a given maximum size and re-encodes them as
   JPEG. The textures of a scan are often more than half of the file size and
   almost all of the viewer's GPU memory.
4. **Writes a compact binary file**, by default glTF binary (`.glb`): one mesh,
   one primitive per material, 16-bit indices where they suffice, no
   per-triangle vertex duplication.

Input formats: `.glb`, `.gltf`, `.obj` (with `.mtl` and textures), `.ply`,
`.stl`, and other formats [trimesh](https://trimesh.org) can read. Polycam's
`.ply` point clouds are handled too (they are subsampled rather than
decimated). Output formats: `.glb` (recommended), `.obj`, `.ply`, `.stl`;
for point clouds `.ply` or `.glb`.

Options:

    --ratio R              Keep this fraction of the triangles (or points), 0 < R <= 1.
                           Default 0.25. Use 1 for a lossless weld-and-repack only.
    --faces N              Target number of triangles (or points); overrides --ratio.
    --texture-size N       Shrink textures so that their longer side is at most N
                           pixels. Default 2048; 0 keeps the original size.
    --texture-quality Q    JPEG quality for the textures, 1-100. Default 80.
    --min-part-size N      Remove disconnected fragments with fewer than N triangles.
                           Default 0 (keep everything).
    --weld-distance D      Also merge vertices closer than D model units (usually
                           meters) to each other. Default 0 (exact duplicates only).
    --no-weld              Do not merge duplicate vertices (not recommended).
    --no-normals           Do not store vertex normals (smaller files, flat shading).
    --info                 Print information about the input file and exit.
    --force                Overwrite the output file without asking for confirmation.
    --quiet                Print only warnings and errors.
    --verbose              Print timing and per-texture details.
    --help                 Print usage information.
    --version              Print version information.

If `outputfile` already exists, model-compresser warns and asks for
confirmation before overwriting it (unless `--force` is given).

## Example

    model-compresser Kommelin-luola-3D-GLB.glb Kommelin-luola-3D-small.glb

prints, for an 81 MB scan of a small cave in Mikkeli, Finland:

    model-compresser: reading Kommelin-luola-3D-GLB.glb (81.0 MB)
    model-compresser: input: 15 parts, 271,240 triangles, 813,719 vertices, 15 textures (13 x 4096x4096, 1 x 4096x3520, 1 x 4096x704) taking 52.2 MB
    model-compresser: welded vertices: 813,719 -> 137,279
    model-compresser: simplified: 271,240 -> 67,810 triangles (25.0%), 137,279 -> 35,564 vertices
    model-compresser: textures: 15 images, longest side 4096 -> 2048 px, JPEG quality 80, 52.2 MB -> 11.0 MB
    model-compresser: wrote Kommelin-luola-3D-small.glb: 13.2 MB (16.3% of the input), 3.6 s in total

The same model with `--ratio 0.1 --texture-size 1024` comes out at 4.2 MB
(5% of the original) and still reads fine as a cave.

With the default settings, on an Apple Silicon laptop, some larger models:

| Model | Input | Output | Time | Peak memory |
|---|---|---|---|---|
| Schneefleckhöhle (Austria), GLB, 3.0M triangles, 51 textures up to 8192x8192 | 522 MB | 52 MB (10%) | 30 s | 3.8 GB |
| Gjógur (Iceland), STL, 9.9M triangles, no textures | 496 MB | 56 MB GLB (11%) | 103 s | 7.7 GB |
| Lummelunda (Sweden), GLB, 2.1M triangles, plain grey material | 231 MB | 13 MB (6%) | 19 s | 1.9 GB |
| Eispalast (Austria), PLY point cloud, 4.7M points with colors | 126 MB | 17 MB (14%) | 10 s | 2.0 GB |
| Kommelin (Finland), GLB, 271k triangles, 15 textures (above) | 81 MB | 13 MB (16%) | 4 s | 0.7 GB |

Textured models end up at around 10-15% of the original because the textures
(now the bulk of the file) are only shrunk 4x in area; the geometry itself
shrinks 20-30x.

## Choosing the settings

- `--ratio` (or `--faces`) controls the geometry. Scans are heavily
  oversampled, so 0.25 is visually almost indistinguishable from the original
  at any normal viewing distance, and 0.1 is still good. For web and phone
  viewers, aim at a few hundred thousand triangles in total with `--faces`.
- `--texture-size` controls memory use in the viewer more than anything
  else: a 4096x4096 texture takes 64 MB of GPU memory when decoded (plus a
  third for mipmaps), so fifteen of them need a gigabyte, which is what makes
  phones and browsers give up. At 2048 that is 16 MB each, at 1024 4 MB.
  Textures are never upscaled.
- `--texture-quality 80` is a good compromise for photographic cave walls;
  going below about 70 starts to show.
- `--min-part-size 100` or so removes the floating specks that scanners
  leave behind; look at the model first, small real features (stalactite
  tips, loose rocks) can be separate pieces too.
- `--ratio 1 --texture-size 0 --texture-quality 95` is a nearly lossless
  repack: welding plus the binary format alone typically halves a Blender
  GLB export.

## Installing and running

The program is a single Python script, `model-compresser`, with its
dependencies (numpy, [pymeshlab](https://pymeshlab.readthedocs.io),
trimesh, pillow) declared inline. The easiest way to run it is with
[uv](https://docs.astral.sh/uv/), which installs the dependencies in its
cache the first time, into an environment of its own:

    brew install uv            # or: curl -LsSf https://astral.sh/uv/install.sh | sh
    make                       # optional: installs the dependencies ahead of time
    ./model-compresser --help

Copy or symlink `model-compresser` somewhere on your `PATH` if you like;
it finds its environment through uv regardless of where it is run from.

Without uv, create a virtual environment with Python 3.10-3.14 (pymeshlab
has no wheels for newer Pythons yet), install `requirements.txt` into it,
and run the script with that Python:

    python3.11 -m venv ~/.model-compresser
    ~/.model-compresser/bin/pip install -r requirements.txt
    ~/.model-compresser/bin/python model-compresser input.glb output.glb

Peak memory use is about 8 times the size of the input file for GLB input
(see the table above); STL input needs about twice that, because all of its
unshared vertices go through MeshLab before they are welded. The largest
scans therefore want a machine with 16 GB.

    make          # installs the dependencies and checks the program starts
    make test     # runs the test suite (test/run-tests.py)
    make clean    # removes test output
    make wc       # line/word/byte counts of the source

## Doing the same in Blender

The tool exists because the same job in Blender is a dozen clicks per model
and easy to get subtly wrong; but Blender does it fine. In Blender 3.x or 4.x:

1. **Import:** File > Import > glTF 2.0 (`.glb`), or Wavefront (`.obj`),
   STL, Stanford PLY. Turn on *Overlays > Statistics* in the 3D viewport to
   see vertex and triangle counts while you work.
2. **Weld first.** Hover the 3D viewport, press `A` to select everything,
   `Tab` into Edit Mode, `A` again, then *Mesh > Clean Up > Merge by
   Distance* (called *Remove Doubles* before 2.8); the status bar reports
   how many vertices were removed -- for a scanner export, two thirds of
   them. `Tab` back to Object Mode. Without this step, the Decimate modifier
   on a mesh of disconnected triangles does not simplify anything, it just
   deletes triangles and leaves holes. (The glTF importer has a *Merge
   Vertices* option, but it cannot merge vertices whose normals differ, which
   is most of them in a scan, so do this anyway.)
3. **Decimate.** With a mesh object selected, go to the Properties editor,
   *Modifier Properties* (the wrench), *Add Modifier > Generate > Decimate*.
   Leave the mode at *Collapse*, set *Ratio* to e.g. 0.25 and watch the
   *Face Count* readout at the bottom of the panel; tick *Triangulate* if you
   want only triangles. Apply it from the small dropdown arrow in the
   modifier header (*Apply*, or `Ctrl+A` with the mouse over the modifier).
   Scans usually consist of several objects: select them all, make one
   active, add the modifier to the active one, then *Object > Link/Transfer
   Data (`Ctrl+L`) > Copy Modifiers*, and finally *Object > Apply > Visual
   Geometry to Mesh* (or *Object > Convert > Mesh*), which applies the
   modifiers of every selected object at once. The equivalent one-shot
   operator is, in Edit Mode, *Mesh > Clean Up > Decimate Geometry* with the
   ratio in the operator panel.
   The other Decimate modes, *Un-Subdivide* and *Planar*, and the *Remesh*
   modifier are not for scans: they either need a regular grid, flatten
   detail, or destroy the texture mapping.
4. **Textures.** In the UV Editor or Image Editor, pick each image from the
   image dropdown and use *Image > Resize* (e.g. 2048 x 2048). Blender's
   exporter re-encodes images but does not resize them.
5. **Export:** File > Export > glTF 2.0. *Format: glTF Binary (.glb)*;
   under *Data > Mesh* keep *Apply Modifiers*; under *Material > Images*
   choose *JPEG Format (.jpg)* (and *Image Quality* 80, in 3.6 and later);
   and under *Data > Compression* tick the Draco compression (level 6,
   position 14 bits, normals 10, texture coordinates 12 are the defaults and
   fine). Draco shrinks the geometry another 3-5x but the viewer must
   support it -- three.js, Babylon.js, Sketchfab, `<model-viewer>`, Blender
   itself and most modern viewers do; if yours does not, untick it.

`blender-decimate.py` in this repository does those steps unattended:

    blender --background --python blender-decimate.py -- input.glb output.glb --ratio 0.25 --texture-size 2048

(options go after the `--`: `--ratio`, `--texture-size`, `--texture-quality`,
`--no-weld`, `--no-draco`). It was written against the Blender 3.4-4.x API
but could not be tested while writing this, as the machine this was
developed on has no Blender installed; treat it as a starting point.

[MeshLab](https://www.meshlab.net) can do the same by hand as well, with the
very filters model-compresser calls: *Filters > Cleaning and Repairing >
Remove Duplicate Vertices*, then *Filters > Remeshing, Simplification and
Reconstruction > Simplification: Quadric Edge Collapse Decimation (with
texture)*, then export.

## Going further

model-compresser deliberately writes plain glTF that every viewer can read.
If your recipients' viewer supports it, Draco or meshopt compression of the
geometry brings another sizable reduction; the free
[glTF-Transform](https://gltf-transform.dev) command line does it in one step
on model-compresser's output:

    npm install -g @gltf-transform/cli
    gltf-transform draco small.glb smaller.glb                 # Draco geometry compression
    gltf-transform optimize small.glb smaller.glb --compress draco --texture-compress webp

After decimation the textures are most of the file, so the gain on the whole
file is moderate (WebP textures help more than Draco does, but need a viewer
with `EXT_texture_webp` support).

## How it works

The script reads the model with trimesh, bakes the scene transforms, and
collects one part per material. The geometry then goes to MeshLab (through
pymeshlab) as a binary PLY that carries the texture coordinates per triangle
corner and a texture index per triangle -- MeshLab's own convention -- so
that a model with many textures is simplified as one mesh with all of its
seams known. In MeshLab it welds duplicate vertices, removes degenerate and
duplicate triangles (and, if asked, small fragments), and runs quadric edge
collapse decimation, the texture-aware version when the model has textures.
Back in Python it recomputes smooth vertex normals, splits the vertices again
only where texture coordinates actually differ, shrinks and re-encodes the
textures with Pillow, and writes the output file with its own writers (GLB,
OBJ, PLY, STL), so that what ends up in the file is exactly what is intended.

Point clouds skip the mesh steps: they are subsampled with MeshLab's
Poisson-disk sampling, which keeps the points evenly spaced and their colors
intact, and written as float32 PLY (Polycam's doubles are not meaningful at
scanner accuracy).

## Known limitations

- Only the base color texture of each material is kept. Normal, roughness or
  occlusion maps, additional UV sets, animations, skeletons, cameras and
  lights are dropped. Cave scans do not have them.
- The scene is flattened: node transforms are baked in and the output has
  one mesh with one primitive per material; object names are not preserved.
- Textures are shrunk but not repacked, so unused atlas space is kept, and a
  texture that only a handful of surviving triangles still use is exported in
  full.
- Per-face colors are averaged into vertex colors. PLY and STL output cannot
  carry textures; PLY output gets the texture colors baked into vertex
  colors instead, STL loses them.
- USDZ (and FBX) cannot be read; export those from Blender or Reality
  Converter as GLB first. Neither can GLB input that is already
  Draco-compressed (`KHR_draco_mesh_compression`); re-export it without
  compression, or decode it with `gltf-transform` first.
- Point-cloud subsampling hits the requested count only approximately
  (within a couple of percent).
- Decimation does not fill the holes that scans have; it only tries not to
  shrink away from their edges.
- glTF stores coordinates as 32-bit floats. Models in local coordinates (as
  scanners produce them) are unaffected; a model positioned in a national
  grid with coordinates in the millions would lose millimeters.

## Testing

`make test` runs `test/run-tests.py`, which builds synthetic cave-like
models -- a bumpy tunnel whose texture colors and vertex colors are analytic
functions of position, stored the way scanners store them (three vertices
per triangle, two texture atlases, a seam around the tunnel, a node
transform) -- and runs the tool on them in the supported format
combinations: GLB and OBJ with textures, PLY with vertex colors, STL, a
plain-colored GLB, and a colored point cloud. The results are read back with
trimesh (an independent implementation) and checked for triangle counts,
welding, deviation from the analytic surface, GLB structural validity, and,
most importantly, that the color sampled from the compressed model's texture
at each output vertex still matches the color that belongs at that point in
space; that last check catches broken UVs, textures attached to the wrong
material, flipped images and seams that have drifted apart.
