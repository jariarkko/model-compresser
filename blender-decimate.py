###################################################################################################
#
#    MODEL-COMPRESSER -- the same reduction done inside Blender, without the GUI
#
#    Copyright (C) 2026 by Jari Arkko -- See LICENSE for license information.
#
###################################################################################################
#
# Usage:
#
#     blender --background --python blender-decimate.py -- input.glb output.glb [options]
#
# Options (after the "--"):
#
#     --ratio R             Fraction of the triangles to keep (default 0.25)
#     --texture-size N      Shrink textures to at most N pixels on the longer side
#                           (default 2048; 0 keeps them as they are)
#     --texture-quality Q   JPEG quality for exported textures (default 80; needs Blender 3.6+)
#     --no-weld             Do not merge duplicate vertices first
#     --no-draco            Do not use Draco mesh compression in glTF/GLB output
#
# Input: anything Blender can import (.glb/.gltf, .obj, .stl, .ply, .fbx, .usdz, ...).
# Output: .glb or .gltf (recommended), .obj, .stl or .ply, chosen by the file name.
#
# This does, with Blender's own tools, what model-compresser does with MeshLab:
#
#   1. import the model;
#   2. merge duplicate vertices (Mesh > Clean Up > Merge by Distance) -- scanner
#      exports store every triangle with its own three vertices, and the Decimate
#      modifier cannot simplify a mesh of disconnected triangles, it only deletes
#      them, so this step is essential;
#   3. add a Decimate modifier in Collapse mode with the given ratio and apply it;
#   4. shade smooth, scale down the texture images;
#   5. export, as a binary GLB with JPEG textures and Draco compression by default.
#
# NOTE: written against the Blender 3.4 - 4.x Python API, but it has not been run
# in the same environment as the rest of this repository (which has no Blender
# installation); please report problems.

import argparse
import os
import sys

import bpy
import bmesh


def parse_arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="blender-decimate.py")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--ratio", type=float, default=0.25)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--texture-quality", type=int, default=80)
    parser.add_argument("--no-weld", dest="weld", action="store_false")
    parser.add_argument("--no-draco", dest="draco", action="store_false")
    return parser.parse_args(argv)


def first_working(*calls):
    """Call the first operator that exists in this Blender version."""
    for op, kwargs in calls:
        try:
            return op(**kwargs)
        except AttributeError:      # operator not in this Blender version
            continue
    raise SystemExit("blender-decimate.py: no import/export operator for this format in this Blender")


def import_model(path):
    ext = os.path.splitext(path)[1].lower()
    path = os.path.abspath(path)
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".obj":
        first_working((bpy.ops.wm.obj_import, dict(filepath=path)),
                      (bpy.ops.import_scene.obj, dict(filepath=path)))
    elif ext == ".stl":
        first_working((bpy.ops.wm.stl_import, dict(filepath=path)),
                      (bpy.ops.import_mesh.stl, dict(filepath=path)))
    elif ext == ".ply":
        first_working((bpy.ops.wm.ply_import, dict(filepath=path)),
                      (bpy.ops.import_mesh.ply, dict(filepath=path)))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".usd", ".usda", ".usdc", ".usdz"):
        bpy.ops.wm.usd_import(filepath=path)
    else:
        raise SystemExit(f"blender-decimate.py: unsupported input format '{ext}'")


def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def weld(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return before, len(obj.data.vertices)


def decimate(obj, ratio):
    modifier = obj.modifiers.new(name="Decimate", type="DECIMATE")
    modifier.decimate_type = "COLLAPSE"
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True
    with bpy.context.temp_override(object=obj, active_object=obj, selected_objects=[obj],
                                   selected_editable_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.data.polygons.foreach_set("use_smooth", [True] * len(obj.data.polygons))
    obj.data.update()


def shrink_textures(max_size):
    for image in bpy.data.images:
        w, h = image.size
        if w == 0 or max_size <= 0 or max(w, h) <= max_size:
            continue
        scale = max_size / float(max(w, h))
        image.scale(max(1, round(w * scale)), max(1, round(h * scale)))
        print(f"blender-decimate.py: texture {image.name}: {w}x{h} -> {image.size[0]}x{image.size[1]}")


def export_model(path, args):
    ext = os.path.splitext(path)[1].lower()
    path = os.path.abspath(path)
    if ext in (".glb", ".gltf"):
        kwargs = dict(filepath=path, export_format="GLB" if ext == ".glb" else "GLTF_SEPARATE",
                      export_image_format="JPEG", export_apply=True)
        if args.draco:
            kwargs.update(export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
                          export_draco_position_quantization=14, export_draco_normal_quantization=10,
                          export_draco_texcoord_quantization=12)
        try:
            bpy.ops.export_scene.gltf(export_jpeg_quality=args.texture_quality, **kwargs)
        except TypeError:           # export_jpeg_quality arrived in Blender 3.6
            bpy.ops.export_scene.gltf(**kwargs)
    elif ext == ".obj":
        first_working((bpy.ops.wm.obj_export, dict(filepath=path, export_materials=True)),
                      (bpy.ops.export_scene.obj, dict(filepath=path)))
    elif ext == ".stl":
        first_working((bpy.ops.wm.stl_export, dict(filepath=path)),
                      (bpy.ops.export_mesh.stl, dict(filepath=path)))
    elif ext == ".ply":
        first_working((bpy.ops.wm.ply_export, dict(filepath=path)),
                      (bpy.ops.export_mesh.ply, dict(filepath=path)))
    else:
        raise SystemExit(f"blender-decimate.py: unsupported output format '{ext}'")


def main():
    args = parse_arguments()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import_model(args.input)
    objects = mesh_objects()
    if not objects:
        raise SystemExit("blender-decimate.py: no meshes found in the input")
    faces_before = sum(len(o.data.polygons) for o in objects)
    verts_before = sum(len(o.data.vertices) for o in objects)
    if args.weld:
        for obj in objects:
            weld(obj)
        print(f"blender-decimate.py: welded vertices: {verts_before:,} -> "
              f"{sum(len(o.data.vertices) for o in objects):,}")
    if args.ratio < 1.0:
        for obj in objects:
            decimate(obj, args.ratio)
    faces_after = sum(len(o.data.polygons) for o in objects)
    print(f"blender-decimate.py: triangles: {faces_before:,} -> {faces_after:,}")
    shrink_textures(args.texture_size)
    export_model(args.output, args)
    print(f"blender-decimate.py: wrote {args.output} ({os.path.getsize(args.output) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
