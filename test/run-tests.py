#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10,<3.15"
# dependencies = [
#   "numpy>=1.26",
#   "trimesh>=4.4",
#   "pillow>=10.0",
# ]
# ///
#
###################################################################################################
#
#    MODEL-COMPRESSER -- test suite
#
#    Copyright (C) 2026 by Jari Arkko -- See LICENSE for license information.
#
###################################################################################################
#
# Builds synthetic cave-like models (a bumpy tunnel whose texture colors and
# vertex colors are analytic functions of position), runs model-compresser on
# them in various format combinations, and checks the results with an
# independent reader (trimesh): triangle counts, welding, geometry error against
# the analytic surface, and -- most importantly -- that the colors sampled from
# the compressed model's textures at each output vertex still match the colors
# that belong at that point in space. That last check catches broken UVs,
# textures assigned to the wrong material, flipped texture orientation, and
# seams that drifted apart.
#
# Usage: test/run-tests.py            (or: make test)
#
# The tool under test is ./model-compresser; set MODEL_COMPRESSER to run a
# different command (for example "python3.11 ./model-compresser").

import json
import os
import shlex
import struct
import shutil
import subprocess
import sys

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "output")
TOOL = shlex.split(os.environ.get("MODEL_COMPRESSER", "")) or [os.path.join(ROOT, "model-compresser")]

L = 30.0          # tunnel length
TEX = 1024        # texture size of the fixtures

failures = 0
checks = 0


def check(condition, text):
    global failures, checks
    checks += 1
    if not condition:
        failures += 1
        print(f"    FAIL: {text}")
    return condition


def run(*args, expect_status=0):
    cmd = TOOL + [str(a) for a in args]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if proc.returncode != expect_status:
        print("    command:", " ".join(shlex.quote(c) for c in cmd))
        print("    stdout:", proc.stdout.strip())
        print("    stderr:", proc.stderr.strip())
    check(proc.returncode == expect_status, f"exit status {proc.returncode}, expected {expect_status}")
    return proc


# ------------------------------------------------------------------------------------------------
# The synthetic tunnel
# ------------------------------------------------------------------------------------------------

def tunnel_axis_offset(s):
    return 0.3 * np.sin(0.2 * s)


def tunnel_radius(s, theta):
    return 1.5 + 0.25 * np.sin(0.7 * s) + 0.15 * np.cos(3.0 * theta + 0.3 * s)


def tunnel_params(points):
    """Inverse of the tunnel parametrization: (s, theta, radius) for points in local coordinates."""
    s = points[:, 0]
    y = points[:, 1] - tunnel_axis_offset(s)
    z = points[:, 2]
    theta = np.mod(np.arctan2(z, y), 2 * np.pi)
    return s, theta, np.sqrt(y * y + z * z)


def tunnel_uv(s, theta):
    tex = (s >= L / 2).astype(int)
    u = (s - tex * L / 2) / (L / 2)
    v = theta / (2 * np.pi)
    return tex, u, v


def texture_color(tex, u, v):
    """The analytic color of texture `tex` at (u, v), 0..255 floats."""
    u = np.clip(u, 0, 1)
    v = np.clip(v, 0, 1)
    rgb = np.empty(np.shape(u) + (3,))
    rgb[..., 0] = np.where(tex == 0, 255 * u, 40)
    rgb[..., 1] = np.where(tex == 0, 255 * v, 255 * u)
    rgb[..., 2] = np.where(tex == 0, 40, 255 * v)
    return rgb


def vertex_color(s, theta):
    return np.stack([255 * s / L, 255 * theta / (2 * np.pi), np.full_like(s, 100)], axis=-1)


def make_texture(tex):
    v, u = np.meshgrid((TEX - 0.5 - np.arange(TEX)) / TEX, (np.arange(TEX) + 0.5) / TEX, indexing="ij")
    return Image.fromarray(texture_color(tex, u, v).round().astype(np.uint8), "RGB")


def make_tunnel(ns=500, nt=96):
    s = np.linspace(0, L, ns)
    theta = np.linspace(0, 2 * np.pi, nt + 1)        # theta = 0 and 2*pi are separate rows: a UV seam
    S, TH = np.meshgrid(s, theta, indexing="ij")
    R = tunnel_radius(S, TH)
    V = np.stack([S.ravel(), (R * np.cos(TH) + tunnel_axis_offset(S)).ravel(), (R * np.sin(TH)).ravel()], 1)
    idx = np.arange(ns * (nt + 1)).reshape(ns, nt + 1)
    a, b, c, d = idx[:-1, :-1], idx[1:, :-1], idx[:-1, 1:], idx[1:, 1:]
    F = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([b, d, c], -1).reshape(-1, 3)])
    _, u, v = tunnel_uv(S.ravel(), TH.ravel())
    tex_of_face = (V[F].mean(1)[:, 0] >= L / 2).astype(int)
    parts = []
    for tex in (0, 1):
        f = F[tex_of_face == tex]
        # one vertex per triangle corner, like scanner exports do
        verts = V[f].reshape(-1, 3)
        faces = np.arange(len(verts)).reshape(-1, 3)
        sv = verts[:, 0]
        uu = (sv - tex * L / 2) / (L / 2)
        vv = v[f].reshape(-1)
        parts.append((verts, faces, np.stack([uu, vv], 1)))
    return V, F, parts


def transform_matrix():
    angle = np.radians(30)
    T = np.eye(4)
    T[:3, :3] = [[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
    T[:3, 3] = [10.0, 5.0, 2.0]
    return T


def to_local(points, T):
    inv = np.linalg.inv(T)
    return (points @ inv[:3, :3].T) + inv[:3, 3]


def surface_error(local_points):
    s, theta, r = tunnel_params(local_points)
    inside = (s > 0.5) & (s < L - 0.5)
    return np.abs(r - tunnel_radius(s, theta))[inside]


def color_error(local_points, sampled):
    """Compare sampled colors with the analytic ones, away from seams."""
    s, theta, _ = tunnel_params(local_points)
    tex, u, v = tunnel_uv(s, theta)
    keep = (np.abs(s - L / 2) > 0.3) & (s > 0.3) & (s < L - 0.3) & (v > 0.03) & (v < 0.97)
    expected = texture_color(tex, u, v)
    return np.abs(sampled[keep] - expected[keep]).mean(axis=1)


def sample_texture(image, uv):
    arr = np.asarray(image.convert("RGB")).astype(np.float64)
    h, w = arr.shape[:2]
    x = np.clip((np.mod(uv[:, 0], 1.0) * w).astype(int), 0, w - 1)
    y = np.clip(((1.0 - np.mod(uv[:, 1], 1.0)) * h).astype(int), 0, h - 1)
    return arr[y, x]


def glb_contents(path):
    with open(path, "rb") as f:
        magic, version, length = struct.unpack("<4sII", f.read(12))
        check(magic == b"glTF" and version == 2 and length == os.path.getsize(path), "bad GLB header")
        jlen, jtype = struct.unpack("<II", f.read(8))
        js = json.loads(f.read(jlen))
        blen, btype = struct.unpack("<II", f.read(8))
        blob = f.read(blen)
    check(jtype == 0x4E4F534A and btype == 0x004E4942 and jlen % 4 == 0 and blen % 4 == 0, "bad GLB chunks")
    check(js["asset"]["version"] == "2.0" and js["buffers"][0]["byteLength"] == blen, "bad glTF asset/buffer")
    for acc in js["accessors"]:
        view = js["bufferViews"][acc["bufferView"]]
        check((view.get("byteOffset", 0) + acc.get("byteOffset", 0)) % 4 == 0, "accessor not 4-byte aligned")
        check(view["byteOffset"] + view["byteLength"] <= blen, "buffer view outside the buffer")
    return js, blob


def glb_attribute(js, blob, prim, name):
    acc = js["accessors"][prim["attributes"][name]]
    view = js["bufferViews"][acc["bufferView"]]
    dtype = {5126: "<f4", 5121: "u1", 5123: "<u2", 5125: "<u4"}[acc["componentType"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    offset = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return np.frombuffer(blob, dtype, count=acc["count"] * width, offset=offset).reshape(acc["count"], width)


def glb_primitives(js):
    return [p for m in js["meshes"] for p in m["primitives"]]


def load_parts(path):
    if not check(os.path.exists(path), f"output file {os.path.basename(path)} was not written"):
        return []
    scene = trimesh.load(path, force="scene", process=False)
    return [g for g in scene.dump(concatenate=False) if isinstance(g, trimesh.Trimesh)]


def textured_checks(path, T, expect_textures, max_tex, expect_faces):
    if not check(os.path.exists(path), f"output file {os.path.basename(path)} was not written"):
        return []
    parts = load_parts(path)
    nfaces = sum(len(p.faces) for p in parts)
    nverts = sum(len(p.vertices) for p in parts)
    check(abs(nfaces - expect_faces) <= 0.1 * expect_faces,
          f"{nfaces} triangles, expected about {expect_faces}")
    check(nverts < 0.8 * nfaces, f"{nverts} vertices for {nfaces} triangles: vertices were not welded")
    images = []
    errors, color_errors = [], []
    for p in parts:
        local = to_local(np.asarray(p.vertices, float), T)
        errors.append(surface_error(local))
        mat = getattr(p.visual, "material", None)
        img = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
        if check(img is not None and p.visual.uv is not None, f"part {p.metadata.get('name')} lost its texture"):
            images.append(img)
            check(max(img.size) <= max_tex, f"texture is {img.size}, expected at most {max_tex}")
            color_errors.append(color_error(local, sample_texture(img, np.asarray(p.visual.uv))))
            n = p.vertex_normals if "vertex_normals" in p._cache else None
    check(len(images) == expect_textures, f"{len(images)} textured parts, expected {expect_textures}")
    if not parts:
        return parts
    err = np.concatenate(errors)
    check(err.mean() < 0.01 and err.max() < 0.15,
          f"surface error mean {err.mean():.4f} max {err.max():.3f} (tunnel radius 1.5)")
    if color_errors:
        ce = np.concatenate(color_errors)
        check(ce.mean() < 12 and np.percentile(ce, 95) < 40,
              f"texture color error mean {ce.mean():.1f} p95 {np.percentile(ce, 95):.1f} (of 255)")
    return parts


# ------------------------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------------------------

def write_textured_glb(path, parts, T):
    scene = trimesh.Scene()
    for i, (verts, faces, uv) in enumerate(parts):
        material = trimesh.visual.material.PBRMaterial(name=f"Material_{i}", baseColorTexture=make_texture(i),
                                                      metallicFactor=0.0)
        mesh = trimesh.Trimesh(verts, faces, visual=trimesh.visual.TextureVisuals(uv=uv, material=material),
                               process=False)
        scene.add_geometry(mesh, node_name=f"Mesh_{i}", geom_name=f"Mesh_{i}", transform=T)
    scene.export(path)


def write_textured_obj(path, parts):
    stem = os.path.splitext(os.path.basename(path))[0]
    with open(os.path.join(os.path.dirname(path), stem + ".mtl"), "w") as f:
        for i in range(len(parts)):
            make_texture(i).save(os.path.join(os.path.dirname(path), f"{stem}_{i}.png"))
            f.write(f"newmtl mat{i}\nKd 1 1 1\nmap_Kd {stem}_{i}.png\n")
    with open(path, "w") as f:
        f.write(f"mtllib {stem}.mtl\n")
        offset = 0
        for i, (verts, faces, uv) in enumerate(parts):
            for v in verts:
                f.write(f"v {v[0]:.5f} {v[1]:.5f} {v[2]:.5f}\n")
            for t in uv:
                f.write(f"vt {t[0]:.6f} {t[1]:.6f}\n")
            f.write(f"usemtl mat{i}\n")
            for face in faces + 1 + offset:
                f.write(f"f {face[0]}/{face[0]} {face[1]}/{face[1]} {face[2]}/{face[2]}\n")
            offset += len(verts)


# ------------------------------------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------------------------------------

def test_textured_glb_to_glb():
    print("--- textured GLB (two textures, unshared vertices, node transform) -> GLB ---")
    V, F, parts = make_tunnel()
    T = transform_matrix()
    src = os.path.join(OUT, "tunnel.glb")
    dst = os.path.join(OUT, "tunnel-small.glb")
    write_textured_glb(src, parts, T)
    proc = run("--ratio", 0.25, "--texture-size", 512, "--verbose", src, dst)
    check("welded vertices" in proc.stdout, "no welding reported")
    textured_checks(dst, T, expect_textures=2, max_tex=512, expect_faces=len(F) * 0.25)
    check(os.path.getsize(dst) < 0.3 * os.path.getsize(src),
          f"output is {os.path.getsize(dst)} bytes, input {os.path.getsize(src)}")
    js, blob = glb_contents(dst)
    prims = glb_primitives(js)
    check(all(p.get("mode", 4) == 4 and "indices" in p for p in prims), "primitives are not indexed triangles")
    check(all("NORMAL" in p["attributes"] and "TEXCOORD_0" in p["attributes"] for p in prims), "normals or UVs missing")
    check(all(m["pbrMetallicRoughness"].get("metallicFactor") == 0 for m in js["materials"]), "material not non-metallic")
    check(all(i["mimeType"] == "image/jpeg" for i in js["images"]), "textures not stored as JPEG")
    for p in prims:
        n = glb_attribute(js, blob, p, "NORMAL").astype(float)
        check(np.allclose(np.linalg.norm(n, axis=1), 1, atol=1e-3), "normals not unit length")
    plain = os.path.join(OUT, "tunnel-small-nonormals.glb")
    run("--ratio", 0.25, "--texture-size", 512, "--no-normals", src, plain)
    js2, _ = glb_contents(plain)
    check(all("NORMAL" not in p["attributes"] for p in glb_primitives(js2)), "--no-normals still wrote normals")
    check(os.path.getsize(plain) < os.path.getsize(dst), "--no-normals output not smaller")
    return src, T, len(F)


def test_glb_to_obj(src, T, nfaces):
    print("--- textured GLB -> OBJ (+ MTL + JPEG textures) ---")
    dst = os.path.join(OUT, "tunnel-small.obj")
    run("--faces", 20000, "--texture-size", 256, "--force", src, dst)
    check(os.path.exists(os.path.join(OUT, "tunnel-small.mtl")), "MTL file missing")
    check(os.path.exists(os.path.join(OUT, "tunnel-small_texture_0.jpg")), "texture file missing")
    textured_checks(dst, T, expect_textures=2, max_tex=256, expect_faces=20000)


def test_obj_to_glb():
    print("--- textured OBJ (PNG textures) -> GLB ---")
    V, F, parts = make_tunnel(ns=300, nt=64)
    src = os.path.join(OUT, "tunnel-obj.obj")
    dst = os.path.join(OUT, "tunnel-obj-small.glb")
    write_textured_obj(src, parts)
    run("--ratio", 0.5, "--texture-size", 512, src, dst)
    textured_checks(dst, np.eye(4), expect_textures=2, max_tex=512, expect_faces=len(F) * 0.5)


def test_weld_only(src, T, nfaces):
    print("--- --ratio 1: lossless weld and repack ---")
    dst = os.path.join(OUT, "tunnel-welded.glb")
    run("--ratio", 1, "--texture-size", 0, "--texture-quality", 95, src, dst)
    parts = load_parts(dst)
    out_faces = sum(len(p.faces) for p in parts)
    out_verts = sum(len(p.vertices) for p in parts)
    check(out_faces == nfaces, f"{out_faces} triangles, expected exactly {nfaces}")
    check(out_verts < 0.6 * out_faces, f"{out_verts} vertices for {out_faces} triangles after welding")
    sizes = [max(getattr(p.visual.material, "baseColorTexture").size) for p in parts]
    check(all(s == TEX for s in sizes), f"texture sizes {sizes}, expected {TEX} (unchanged)")


def test_vertex_colors():
    print("--- vertex-colored PLY mesh -> PLY and GLB ---")
    V, F, _ = make_tunnel(ns=300, nt=64)
    s, theta, _ = tunnel_params(V)
    colors = np.concatenate([vertex_color(s, theta).round().astype(np.uint8),
                             np.full((len(V), 1), 255, np.uint8)], axis=1)
    src = os.path.join(OUT, "tunnel-colors.ply")
    trimesh.Trimesh(V, F, vertex_colors=colors, process=False).export(src)
    for ext in ("ply", "glb"):
        dst = os.path.join(OUT, f"tunnel-colors-small.{ext}")
        run("--ratio", 0.2, src, dst)
        parts = load_parts(dst)
        nfaces = sum(len(p.faces) for p in parts)
        check(abs(nfaces - 0.2 * len(F)) < 0.02 * len(F), f"{ext}: {nfaces} triangles, expected {0.2 * len(F):.0f}")
        if ext == "glb":
            # trimesh ignores COLOR_0 when a material is present, so read the file directly
            js, blob = glb_contents(dst)
            prim = glb_primitives(js)[0]
            if check("COLOR_0" in prim["attributes"], "glb: vertex colors lost"):
                positions = glb_attribute(js, blob, prim, "POSITION").astype(float)
                sampled = glb_attribute(js, blob, prim, "COLOR_0").astype(float)[:, :3]
                check(js["materials"][prim["material"]]["pbrMetallicRoughness"]["metallicFactor"] == 0,
                      "glb: vertex-colored material should be non-metallic")
        else:
            p = parts[0]
            if not check(p.visual.kind == "vertex", f"{ext}: vertex colors lost"):
                continue
            positions = np.asarray(p.vertices, float)
            sampled = np.asarray(p.visual.vertex_colors[:, :3], float)
        s, theta, _ = tunnel_params(positions)
        keep = (theta > 0.2) & (theta < 2 * np.pi - 0.2)
        err = np.abs(sampled - vertex_color(s, theta))[keep].mean()
        check(err < 6, f"{ext}: vertex color error {err:.1f} (of 255)")


def test_stl():
    print("--- STL -> GLB and STL ---")
    V, F, _ = make_tunnel(ns=300, nt=64)
    src = os.path.join(OUT, "tunnel.stl")
    trimesh.Trimesh(V, F, process=False).export(src)
    dst = os.path.join(OUT, "tunnel-small.glb")
    run("--faces", 5000, "--force", src, dst)
    parts = load_parts(dst)
    check(abs(sum(len(p.faces) for p in parts) - 5000) < 500, "triangle count off target")
    err = surface_error(np.asarray(parts[0].vertices, float))
    check(err.mean() < 0.02, f"surface error mean {err.mean():.4f}")
    dst = os.path.join(OUT, "tunnel-small.stl")
    run("--faces", 5000, src, dst)
    m = trimesh.load(dst, force="mesh")
    check(abs(len(m.faces) - 5000) < 500, f"STL has {len(m.faces)} triangles")
    check(os.path.getsize(dst) < 0.2 * os.path.getsize(src), "STL output not much smaller")


def test_color_only_material():
    print("--- GLB with a plain colored material (no textures) ---")
    V, F, _ = make_tunnel(ns=200, nt=48)
    material = trimesh.visual.material.PBRMaterial(name="Material Grey", baseColorFactor=[155, 155, 155, 255],
                                                  metallicFactor=0.0, roughnessFactor=0.5, doubleSided=True)
    mesh = trimesh.Trimesh(V[F].reshape(-1, 3), np.arange(F.size).reshape(-1, 3),
                           visual=trimesh.visual.TextureVisuals(material=material), process=False)
    src = os.path.join(OUT, "tunnel-grey.glb")
    dst = os.path.join(OUT, "tunnel-grey-small.glb")
    mesh.export(src)
    run("--ratio", 0.3, src, dst)
    parts = load_parts(dst)
    check(len(parts) == 1, f"{len(parts)} parts, expected 1")
    mat = parts[0].visual.material
    factor = np.asarray(mat.baseColorFactor, float)
    if factor.max() <= 1.0:
        factor = factor * 255
    check(np.allclose(factor[:3], 155, atol=2), f"material color {factor} lost")
    check(bool(mat.doubleSided), "doubleSided flag lost")
    check(len(parts[0].vertices) < 0.7 * len(parts[0].faces), "vertices not welded")


def test_point_cloud():
    print("--- colored point cloud PLY -> PLY ---")
    V, F, _ = make_tunnel(ns=400, nt=96)
    s, theta, _ = tunnel_params(V)
    colors = np.concatenate([vertex_color(s, theta).round().astype(np.uint8),
                             np.full((len(V), 1), 255, np.uint8)], axis=1)
    src = os.path.join(OUT, "points.ply")
    dst = os.path.join(OUT, "points-small.ply")
    trimesh.PointCloud(V, colors=colors).export(src)
    run("--faces", 5000, src, dst)
    cloud = trimesh.load(dst)
    check(isinstance(cloud, trimesh.PointCloud), f"output is {type(cloud).__name__}, expected a point cloud")
    n = len(cloud.vertices)
    check(4250 <= n <= 5750, f"{n} points, expected 5000 within 15%")
    check(len(cloud.colors) == n, "point colors lost")
    s, theta, _ = tunnel_params(np.asarray(cloud.vertices, float))
    keep = (theta > 0.2) & (theta < 2 * np.pi - 0.2)
    err = np.abs(np.asarray(cloud.colors[:, :3], float) - vertex_color(s, theta))[keep].mean()
    check(err < 3, f"point color error {err:.1f}")
    dst = os.path.join(OUT, "points-small.glb")
    run("--faces", 5000, src, dst)
    js, blob = glb_contents(dst)
    prims = glb_primitives(js)
    check(len(prims) == 1 and prims[0].get("mode") == 0 and "indices" not in prims[0], "point cloud GLB is not a points primitive")
    check("COLOR_0" in prims[0]["attributes"], "point cloud GLB lost its colors")
    n = len(glb_attribute(js, blob, prims[0], "POSITION"))
    check(4250 <= n <= 5750, f"point cloud GLB has {n} points, expected 5000 within 15%")


def test_cli(src):
    print("--- command line behaviour ---")
    proc = run("--info", src)
    check("triangles" in proc.stdout and "textures" in proc.stdout, "--info output lacks statistics")
    dst = os.path.join(OUT, "tunnel-small.glb")
    proc = run("--ratio", 0.5, src, dst, expect_status=1)        # exists, no --force, stdin not a tty
    check("already exists" in proc.stderr, "no overwrite warning")
    run("--ratio", 0.5, "--force", src, dst)
    run("--ratio", 0, src, dst, expect_status=1)
    run(src, os.path.join(OUT, "tunnel.xyz"), expect_status=1)
    run("--version")
    proc = run("--help")
    check(proc.stdout.startswith("Make a 3D model"), "--help output")


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(OUT)
    src, T, nfaces = test_textured_glb_to_glb()
    test_glb_to_obj(src, T, nfaces)
    test_obj_to_glb()
    test_weld_only(src, T, nfaces)
    test_vertex_colors()
    test_stl()
    test_color_only_material()
    test_point_cloud()
    test_cli(src)
    print(f"{checks - failures} of {checks} checks passed" + (f", {failures} FAILED" if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
