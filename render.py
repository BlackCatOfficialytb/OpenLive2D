"""
OpenLive2D renderer (CLI only).

Pipeline:
  1. Load an .ol2d / .ml2d archive (or an already-extracted directory).
  2. Parse model.json -> per-part .json -> .kra layered texture + motion3.json animations.
  3. Build a Blender scene: one textured plane per .kra layer, parented per Live2D part,
     mesh-deformed and transformed by evaluating motion3 curves (Bezier / Linear /
     Stepped / Inverse Stepped) just like the original Live2D Cubism runtime.
  4. Render frames offscreen with bpy.
  5. Hand each frame to Panda3D, which displays it on a fullscreen card via an
     offscreen window. (Panda3D is the "display" host; bpy is the rasterizer.)
  6. Depending on --output-mode, write a single PNG, a numbered sequence, an
     encoded video, or no file at all.

GUI is intentionally out of scope -- client.py drives interaction. This file is CLI.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Iterable

# Panda3D -- display host only.
from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    CardMaker,
    NodePath,
    OrthographicLens,
    PNMImage,
    Texture,
    WindowProperties,
    loadPrcFileData,
)

# bpy is imported lazily inside BlenderBaker so `--help` still works without it.
bpy = None  # type: ignore[assignment]


log = logging.getLogger("openlive2d.render")


# Blender's bpy index ships cp310 / cp311 / cp313 wheels (no cp314 yet, as of 2026-05).
# Fail fast with a clear message instead of letting `pip install bpy` choke later.
SUPPORTED_PYTHON = (3, 10), (3, 13)
if not (SUPPORTED_PYTHON[0] <= sys.version_info[:2] <= SUPPORTED_PYTHON[1]):
    log.warning(
        "render.py is tested on Python %d.%d - %d.%d; you are on %d.%d. "
        "Blender does not yet ship a bpy wheel for your interpreter; "
        "install will likely fail. See https://download.blender.org/pypi/bpy/.",
        SUPPORTED_PYTHON[0][0], SUPPORTED_PYTHON[0][1],
        SUPPORTED_PYTHON[1][0], SUPPORTED_PYTHON[1][1],
        sys.version_info.major, sys.version_info.minor,
    )


# --------------------------------------------------------------------------- #
# Archive loading                                                             #
# --------------------------------------------------------------------------- #

def _load_key_iv(key_path: str) -> tuple[bytes, bytes]:
    with open(key_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    key_hex = lines[0].split(": ", 1)[1].strip()
    iv_hex = lines[1].split(": ", 1)[1].strip()
    return bytes.fromhex(key_hex), bytes.fromhex(iv_hex)


def extract_archive(archive_path: str, dest_dir: str, key_path: str | None = None) -> str:
    """Extract .ol2d (zip) or .ml2d (AES-256-CBC encrypted zip). Returns dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(archive_path)[1].lower()

    if ext == ".ol2d":
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
        return dest_dir

    if ext == ".ml2d":
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        key_path = key_path or (archive_path + ".key")
        if not os.path.exists(key_path):
            raise FileNotFoundError(f"missing key file for ml2d archive: {key_path}")
        key, iv = _load_key_iv(key_path)

        with open(archive_path, "rb") as f:
            ct = f.read()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        padded = decryptor.update(ct) + decryptor.finalize()
        zip_bytes = unpadder.update(padded) + unpadder.finalize()

        with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
            zf.extractall(dest_dir)
        return dest_dir

    raise ValueError(f"unsupported archive type: {ext}")


def resolve_model_root(path: str, work_dir: str, key_path: str | None) -> str:
    """Accept a .ol2d / .ml2d archive or a directory. Return directory containing model.json."""
    if os.path.isdir(path):
        return path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".ol2d", ".ml2d"):
        extract_archive(path, work_dir, key_path)
        return work_dir
    if ext == ".json":
        return os.path.dirname(os.path.abspath(path)) or "."
    raise ValueError(f"unsupported input: {path}")


# --------------------------------------------------------------------------- #
# Live2D motion3.json curve evaluation                                        #
# --------------------------------------------------------------------------- #
# Segment type IDs (matches Cubism spec & file_handler.animation_json_generator):
#   0 = Linear        (2 floats:  time, value)
#   1 = Bezier        (6 floats:  cp1.t, cp1.v, cp2.t, cp2.v, end.t, end.v)
#   2 = Stepped       (2 floats:  end.t, end.v)            -- hold previous value
#   3 = InverseStepped(2 floats:  end.t, end.v)            -- jump to value immediately

def _bezier(p0: tuple[float, float], p1: tuple[float, float],
            p2: tuple[float, float], p3: tuple[float, float], t: float) -> float:
    u = 1.0 - t
    return (u * u * u * p0[1]
            + 3 * u * u * t * p1[1]
            + 3 * u * t * t * p2[1]
            + t * t * t * p3[1])


def _bezier_solve_t(p0: tuple[float, float], p1: tuple[float, float],
                    p2: tuple[float, float], p3: tuple[float, float], x: float) -> float:
    """Binary-search the bezier parameter t such that x(t) == x. Cubism is monotone in t."""
    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) * 0.5
        u = 1.0 - mid
        xm = (u * u * u * p0[0]
              + 3 * u * u * mid * p1[0]
              + 3 * u * mid * mid * p2[0]
              + mid * mid * mid * p3[0])
        if xm < x:
            lo = mid
        else:
            hi = mid
    return (lo + hi) * 0.5


def evaluate_curve(segments: list[float], time: float) -> float:
    """Evaluate a Cubism Curve.Segments float-array at the given time."""
    if not segments:
        return 0.0
    cur_t = segments[0]
    cur_v = segments[1]
    if time <= cur_t:
        return cur_v
    i = 2
    n = len(segments)
    while i < n:
        seg_type = int(segments[i]); i += 1
        if seg_type == 1:  # Bezier
            cp1 = (segments[i], segments[i + 1]); i += 2
            cp2 = (segments[i], segments[i + 1]); i += 2
            end = (segments[i], segments[i + 1]); i += 2
            if time <= end[0]:
                t = _bezier_solve_t((cur_t, cur_v), cp1, cp2, end, time)
                return _bezier((cur_t, cur_v), cp1, cp2, end, t)
            cur_t, cur_v = end
        elif seg_type == 0:  # Linear
            end = (segments[i], segments[i + 1]); i += 2
            if time <= end[0]:
                a = (time - cur_t) / max(end[0] - cur_t, 1e-9)
                return cur_v + (end[1] - cur_v) * a
            cur_t, cur_v = end
        elif seg_type == 2:  # Stepped (hold previous, then jump at end)
            end = (segments[i], segments[i + 1]); i += 2
            if time < end[0]:
                return cur_v
            cur_t, cur_v = end
        elif seg_type == 3:  # Inverse Stepped (jump immediately)
            end = (segments[i], segments[i + 1]); i += 2
            if time < end[0]:
                return end[1]
            cur_t, cur_v = end
        else:
            raise ValueError(f"unknown segment type {seg_type}")
    return cur_v


# --------------------------------------------------------------------------- #
# Model graph                                                                 #
# --------------------------------------------------------------------------- #

PART_KEYS = ("head", "torso", "left_arm", "right_arm", "left_leg", "right_leg", "nsfw")
# Approximate L2D-style stack order (back to front). NSFW intentionally last so it can be hidden.
PART_Z_ORDER = {
    "right_leg": -0.6,
    "left_leg":  -0.5,
    "torso":     -0.3,
    "right_arm": -0.2,
    "left_arm":  -0.1,
    "head":       0.1,
    "nsfw":       0.2,
}
# Default pivots (canvas-relative, 0..1) so transforms feel like real L2D.
PART_DEFAULT_PIVOTS = {
    "head":      (0.50, 0.78),
    "torso":     (0.50, 0.50),
    "left_arm":  (0.38, 0.55),
    "right_arm": (0.62, 0.55),
    "left_leg":  (0.45, 0.30),
    "right_leg": (0.55, 0.30),
    "nsfw":      (0.50, 0.50),
}


@dataclass
class LayerImage:
    name: str
    pil_image: object  # PIL.Image.Image
    offset_x: float = 0.0
    offset_y: float = 0.0


@dataclass
class Part:
    name: str
    layers: list[LayerImage] = field(default_factory=list)
    animations: dict[str, dict] = field(default_factory=dict)  # name -> motion3 dict
    z: float = 0.0
    pivot: tuple[float, float] = (0.5, 0.5)


@dataclass
class Model:
    root_dir: str
    humanoid: dict
    parts: dict[str, Part] = field(default_factory=dict)
    animations: dict[str, dict] = field(default_factory=dict)  # global anims
    # canvas size in Blender world units (1 unit ~= 1m)
    canvas_w: float = 2.0
    canvas_h: float = 4.0


def _load_motion(json_path: str) -> dict | None:
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_png_dir_layers(dir_path: str) -> list[LayerImage]:
    """Fallback: read every PNG in a directory as one layer, sorted by filename.

    Filename convention: `01_back.png`, `02_torso.png`, ... -- numeric prefix sets
    z-order within the part. This sidesteps .kra entirely for testing or for users
    who'd rather paint layers in any tool.
    """
    try:
        from PIL import Image
    except ImportError:
        log.warning("Pillow not installed; cannot read %s", dir_path)
        return []
    out: list[LayerImage] = []
    for name in sorted(os.listdir(dir_path)):
        if not name.lower().endswith(".png"):
            continue
        path = os.path.join(dir_path, name)
        try:
            img = Image.open(path).convert("RGBA").copy()
        except Exception as e:  # noqa: BLE001
            log.warning("skip %s: %s", path, e)
            continue
        out.append(LayerImage(name=os.path.splitext(name)[0], pil_image=img))
    return out


def _load_kra_layers(kra_path: str) -> list[LayerImage]:
    """Open a .kra file and return one LayerImage per visible layer (back -> front).

    If `kra_path` ends in `/` or names a directory of PNGs, falls back to the
    PNG-per-layer convention (handy for tests and for the kritapy-doesn't-import-on-3.13 case).
    """
    # Directory fallback -- explicit "layers/<part>/" dir or a `.kra` that's actually a dir.
    if os.path.isdir(kra_path):
        return _load_png_dir_layers(kra_path)

    if not os.path.exists(kra_path):
        # Look for a sibling layers dir: `head.kra` -> `head_layers/` next to it.
        alt = os.path.splitext(kra_path)[0] + "_layers"
        if os.path.isdir(alt):
            return _load_png_dir_layers(alt)
        log.warning("missing kra: %s", kra_path)
        return []

    try:
        from kritapy import Krita  # type: ignore
    except Exception as e:  # ImportError or kritapy's own dataclass errors on 3.13
        log.warning("kritapy unusable (%s); cannot read %s", e.__class__.__name__, kra_path)
        return []
    try:
        kra = Krita(kra_path)
    except Exception as e:
        log.warning("failed to open %s: %s", kra_path, e)
        return []

    layers: list[LayerImage] = []
    raw = getattr(kra, "layers", None) or []
    for layer in raw:
        try:
            img = layer.get_image()
        except Exception as e:  # noqa: BLE001
            log.debug("skip layer %r: %s", layer, e)
            continue
        if img is None:
            continue
        name = getattr(layer, "name", "layer")
        layers.append(LayerImage(name=name, pil_image=img))
    return layers


def load_model(root_dir: str) -> Model:
    model_json_path = os.path.join(root_dir, "model.json")
    with open(model_json_path, "r", encoding="utf-8") as f:
        mdef = json.load(f)
    humanoid = mdef.get("humanoid", {})
    width = float(humanoid.get("width", 1.0)) * float(humanoid.get("size", 1.0))
    height = float(humanoid.get("height", 2.0)) * float(humanoid.get("size", 1.0))
    model = Model(root_dir=root_dir, humanoid=humanoid,
                  canvas_w=width * 2.0, canvas_h=height * 2.0)

    for key in PART_KEYS:
        part_json_rel = mdef.get(key)
        if not part_json_rel:
            continue
        part_json_path = os.path.join(root_dir, part_json_rel)
        if not os.path.exists(part_json_path):
            log.info("skip part %s (no %s)", key, part_json_rel)
            continue
        with open(part_json_path, "r", encoding="utf-8") as f:
            pdef = json.load(f)

        kra_rel = pdef.get("kra_file", f"{key}.kra")
        layers = _load_kra_layers(os.path.join(root_dir, kra_rel))

        anims: dict[str, dict] = {}
        for anim_name, anim_rel in (pdef.get("animations") or {}).items():
            data = _load_motion(os.path.join(root_dir, anim_rel))
            if data is not None:
                anims[anim_name] = data

        model.parts[key] = Part(
            name=key,
            layers=layers,
            animations=anims,
            z=PART_Z_ORDER.get(key, 0.0),
            pivot=PART_DEFAULT_PIVOTS.get(key, (0.5, 0.5)),
        )

    for anim_name, anim_rel in (mdef.get("animations") or {}).items():
        data = _load_motion(os.path.join(root_dir, anim_rel))
        if data is not None:
            model.animations[anim_name] = data

    return model


# --------------------------------------------------------------------------- #
# Cubism parameter -> transform mapping                                       #
# --------------------------------------------------------------------------- #
# motion3.json curves carry Target=("Parameter"|"PartOpacity"|"Model") and an Id.
# For the Parameter targets we ship a small built-in mapper that approximates the
# stock Cubism parameters. Anything we don't recognise falls through harmlessly.

PARAM_RANGES = {
    # id          : (default, min, max)
    "ParamAngleX":      (0.0, -30.0, 30.0),
    "ParamAngleY":      (0.0, -30.0, 30.0),
    "ParamAngleZ":      (0.0, -30.0, 30.0),
    "ParamBodyAngleX":  (0.0, -10.0, 10.0),
    "ParamBodyAngleY":  (0.0, -10.0, 10.0),
    "ParamBodyAngleZ":  (0.0, -10.0, 10.0),
    "ParamEyeLOpen":    (1.0, 0.0, 1.0),
    "ParamEyeROpen":    (1.0, 0.0, 1.0),
    "ParamMouthOpenY":  (0.0, 0.0, 1.0),
    "ParamBreath":      (0.0, 0.0, 1.0),
}


@dataclass
class Pose:
    """Per-part transform & deformation for a single frame."""
    tx: float = 0.0
    ty: float = 0.0
    rot: float = 0.0
    scale: float = 1.0
    opacity: float = 1.0
    # mesh deformation amounts (radians-ish; consumed by Blender shape keys)
    bend_x: float = 0.0
    bend_y: float = 0.0


def evaluate_motion(model: Model, motion: dict | None, time: float) -> dict[str, Pose]:
    """Evaluate a motion3.json dict at time `t` into per-part poses. Always returns a
    pose for every model part (defaulting to identity)."""
    poses: dict[str, Pose] = {name: Pose() for name in model.parts}
    if motion is None:
        return poses

    meta = motion.get("Meta", {})
    duration = float(meta.get("Duration", 0.0)) or 1.0
    if meta.get("Loop", False):
        time = time % duration
    else:
        time = max(0.0, min(time, duration))

    # Resolve all curves first so cross-part params (like ParamAngleX) can drive
    # multiple parts.
    params: dict[str, float] = {}
    part_opacity: dict[str, float] = {}
    for curve in motion.get("Curves", []):
        target = curve.get("Target")
        cid = curve.get("Id", "")
        segs = curve.get("Segments", [])
        v = evaluate_curve(segs, time)
        if target == "Parameter":
            params[cid] = v
        elif target == "PartOpacity":
            part_opacity[cid] = v

    # Map standard Cubism parameters onto our part transforms.
    head = poses.get("head")
    if head is not None:
        if "ParamAngleZ" in params:
            head.rot = math.radians(params["ParamAngleZ"])
        if "ParamAngleX" in params:
            head.tx += math.radians(params["ParamAngleX"]) * 0.05
            head.bend_y = math.radians(params["ParamAngleX"]) * 0.5
        if "ParamAngleY" in params:
            head.ty += math.radians(params["ParamAngleY"]) * 0.05
            head.bend_x = math.radians(params["ParamAngleY"]) * 0.5

    torso = poses.get("torso")
    if torso is not None:
        if "ParamBodyAngleZ" in params:
            torso.rot = math.radians(params["ParamBodyAngleZ"])
        if "ParamBodyAngleX" in params:
            torso.bend_y = math.radians(params["ParamBodyAngleX"]) * 0.3
        if "ParamBodyAngleY" in params:
            torso.bend_x = math.radians(params["ParamBodyAngleY"]) * 0.3
        if "ParamBreath" in params:
            torso.scale = 1.0 + 0.015 * params["ParamBreath"]

    for pid, op in part_opacity.items():
        # PartOpacity ids are user-defined; match exact part name first, then suffix.
        key = pid.lower()
        for part_name in poses:
            if key == part_name or key.endswith(part_name):
                poses[part_name].opacity = op
                break

    return poses


# --------------------------------------------------------------------------- #
# Blender baker                                                               #
# --------------------------------------------------------------------------- #

class BlenderBaker:
    """Builds a Blender scene from a Model and renders one frame at a time."""

    def __init__(self, model: Model, width: int, height: int, samples: int = 16):
        global bpy
        if bpy is None:
            try:
                import bpy as _bpy  # type: ignore
            except ImportError as e:  # pragma: no cover
                raise SystemExit(
                    "bpy (Blender as a Python module) is required.\n"
                    "Install with: pip install bpy   (Python 3.11 wheels exist; "
                    "see https://pypi.org/project/bpy/ for version matrix.)"
                ) from e
            bpy = _bpy

        self.model = model
        self.width = width
        self.height = height
        self.samples = samples
        self._tmpdir = tempfile.mkdtemp(prefix="ol2d_bake_")
        self._part_objs: dict[str, dict] = {}  # part_name -> {empty, planes:[(obj, layer)]}
        self._build_scene()

    # ---- scene construction ------------------------------------------------

    def _reset_scene(self) -> None:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {
            e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
        } else "BLENDER_EEVEE"
        scene.render.resolution_x = self.width
        scene.render.resolution_y = self.height
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = True
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGBA"
        try:
            scene.eevee.taa_render_samples = self.samples
        except AttributeError:
            pass

        # Orthographic camera looking down -Z, so layer Z directly stacks toward the camera.
        cam_data = bpy.data.cameras.new("L2DCam")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = max(self.model.canvas_w, self.model.canvas_h)
        cam = bpy.data.objects.new("L2DCam", cam_data)
        bpy.context.collection.objects.link(cam)
        cam.location = (0.0, 0.0, 5.0)
        cam.rotation_euler = (0.0, 0.0, 0.0)
        scene.camera = cam

    def _save_layer_to_disk(self, part_name: str, idx: int, layer: LayerImage) -> str:
        path = os.path.join(self._tmpdir, f"{part_name}_{idx:02d}_{layer.name}.png")
        try:
            layer.pil_image.save(path)
        except Exception as e:  # noqa: BLE001
            log.warning("failed to save layer %s/%s: %s", part_name, layer.name, e)
            return ""
        return path

    def _make_layer_plane(self, part_name: str, layer_idx: int, layer: LayerImage,
                          part_z: float, part_pivot: tuple[float, float]) -> object | None:
        img_path = self._save_layer_to_disk(part_name, layer_idx, layer)
        if not img_path:
            return None
        img = bpy.data.images.load(img_path)
        w_px, h_px = img.size
        if w_px == 0 or h_px == 0:
            return None
        # Fit the layer inside the canvas keeping its pixel aspect ratio.
        canvas_w = self.model.canvas_w
        canvas_h = self.model.canvas_h
        scale = min(canvas_w / w_px, canvas_h / h_px)
        plane_w = w_px * scale
        plane_h = h_px * scale

        # Build a subdivided plane so shape-key deformations (head turn, torso lean)
        # produce a smooth curve instead of a hard shear.
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.0, 0.0))
        plane = bpy.context.active_object
        plane.name = f"{part_name}_{layer_idx}_{layer.name}"
        plane.scale = (plane_w, plane_h, 1.0)
        # Apply scale so subdivisions are even.
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        # Subdivide for deformation fidelity.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.subdivide(number_cuts=8)
        bpy.ops.object.mode_set(mode="OBJECT")

        # UV-unwrap from the plane's natural projection -- primitive_plane_add already
        # gives a clean 0..1 UV that matches the texture.
        # Material: emission shader so we don't need to light the scene.
        mat = bpy.data.materials.new(f"mat_{plane.name}")
        mat.use_nodes = True
        mat.blend_method = "BLEND"
        nt = mat.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        emit = nt.nodes.new("ShaderNodeEmission")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        transp = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(tex.outputs["Color"], emit.inputs["Color"])
        nt.links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
        nt.links.new(transp.outputs["BSDF"], mix.inputs[1])
        nt.links.new(emit.outputs["Emission"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
        plane.data.materials.append(mat)

        # Shape keys for non-rigid head/body bend.
        plane.shape_key_add(name="Basis")
        sk_x = plane.shape_key_add(name="BendX")
        sk_y = plane.shape_key_add(name="BendY")
        verts = plane.data.vertices
        # BendX bends around vertical axis -> shifts X by ~ y*0.3
        for i, v in enumerate(verts):
            sk_x.data[i].co = v.co + ((v.co.y) * 0.3, 0.0, 0.0)
            sk_y.data[i].co = v.co + (0.0, (v.co.x) * 0.3, 0.0)
        sk_x.value = 0.0
        sk_y.value = 0.0

        # Position: layer Z = part_z + small per-layer offset so layers within a part
        # stack in their kra order without z-fighting.
        layer_z = part_z + layer_idx * 0.001

        # Pivot: shift mesh so the part's pivot in canvas space sits at origin.
        # We do this by translating the plane in mesh-local space.
        pivot_off_x = (part_pivot[0] - 0.5) * canvas_w
        pivot_off_y = (part_pivot[1] - 0.5) * canvas_h
        plane.location = (-pivot_off_x, -pivot_off_y, layer_z)

        return plane

    def _build_scene(self) -> None:
        self._reset_scene()
        for part_name, part in self.model.parts.items():
            empty = bpy.data.objects.new(f"part_{part_name}", None)
            empty.empty_display_type = "PLAIN_AXES"
            empty.empty_display_size = 0.1
            bpy.context.collection.objects.link(empty)
            # Position the empty at the part's pivot point in canvas space.
            empty.location = (
                (part.pivot[0] - 0.5) * self.model.canvas_w,
                (part.pivot[1] - 0.5) * self.model.canvas_h,
                part.z,
            )
            planes: list[tuple[object, LayerImage]] = []
            for idx, layer in enumerate(part.layers):
                plane = self._make_layer_plane(part_name, idx, layer, part.z, part.pivot)
                if plane is None:
                    continue
                plane.parent = empty
                planes.append((plane, layer))
            self._part_objs[part_name] = {"empty": empty, "planes": planes}

    # ---- per-frame application + render -----------------------------------

    def apply_poses(self, poses: dict[str, Pose]) -> None:
        for part_name, entry in self._part_objs.items():
            pose = poses.get(part_name, Pose())
            empty = entry["empty"]
            base = self.model.parts[part_name]
            empty.location = (
                (base.pivot[0] - 0.5) * self.model.canvas_w + pose.tx,
                (base.pivot[1] - 0.5) * self.model.canvas_h + pose.ty,
                base.z,
            )
            empty.rotation_euler = (0.0, 0.0, pose.rot)
            empty.scale = (pose.scale, pose.scale, 1.0)
            for plane, _layer in entry["planes"]:
                kb = plane.data.shape_keys
                if kb is not None:
                    if "BendX" in kb.key_blocks:
                        kb.key_blocks["BendX"].value = pose.bend_x
                    if "BendY" in kb.key_blocks:
                        kb.key_blocks["BendY"].value = pose.bend_y
                # Per-part opacity via material output multiplier.
                for slot in plane.material_slots:
                    mat = slot.material
                    if mat and mat.node_tree:
                        emit = mat.node_tree.nodes.get("Emission")
                        if emit is not None:
                            emit.inputs["Strength"].default_value = pose.opacity

    def render_frame(self, out_path: str) -> str:
        bpy.context.scene.render.filepath = out_path
        bpy.ops.render.render(write_still=True)
        return out_path

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Panda3D display (offscreen) -- shows the baked frame on a fullscreen card   #
# --------------------------------------------------------------------------- #

class PandaDisplay(ShowBase):
    def __init__(self, width: int, height: int, headless: bool = True):
        loadPrcFileData("", f"win-size {width} {height}")
        loadPrcFileData("", "window-type offscreen" if headless else "window-type onscreen")
        loadPrcFileData("", "audio-library-name null")
        loadPrcFileData("", "framebuffer-multisample 1")
        loadPrcFileData("", "multisamples 4")
        loadPrcFileData("", "show-frame-rate-meter false")
        super().__init__()

        # Offscreen buffers are GraphicsBuffer, which doesn't accept WindowProperties.
        if hasattr(self.win, "requestProperties"):
            props = WindowProperties()
            props.setSize(width, height)
            props.setTitle("OpenLive2D render")
            self.win.requestProperties(props)
        self.setBackgroundColor(0, 0, 0, 0)

        # Orthographic 2D camera that fills [-1, 1] in both axes -- a fullscreen card sits on it.
        self.disableMouse()
        lens = OrthographicLens()
        lens.setFilmSize(2.0, 2.0)
        lens.setNearFar(-100, 100)
        self.cam.node().setLens(lens)
        self.cam.setPos(0, -10, 0)
        self.cam.lookAt(0, 0, 0)

        cm = CardMaker("frame")
        cm.setFrame(-1, 1, -1, 1)
        self._card: NodePath = self.render.attachNewNode(cm.generate())
        self._card.setTransparency(True)
        self._tex = Texture("frame")
        self._card.setTexture(self._tex)

    def show_png(self, png_path: str) -> None:
        # Convert host path to Panda's expected forward-slash form to silence warnings.
        png_path = png_path.replace("\\", "/")
        img = PNMImage()
        if img.read(png_path):
            self._tex.load(img)
            self.graphicsEngine.renderFrame()
            return
        # Panda's PNG reader is not available in this build; round-trip via Pillow.
        try:
            from PIL import Image
        except ImportError:
            log.warning("panda3d failed to read %s and Pillow is not available", png_path)
            return
        with Image.open(png_path) as pim:
            pim = pim.convert("RGBA")
            w, h = pim.size
            img2 = PNMImage(w, h, 4)
            data = pim.tobytes()
            i = 0
            for y in range(h):
                for x in range(w):
                    img2.setXel(x, y, data[i] / 255.0, data[i+1] / 255.0, data[i+2] / 255.0)
                    img2.setAlpha(x, y, data[i+3] / 255.0)
                    i += 4
        self._tex.load(img2)
        self.graphicsEngine.renderFrame()

    def screenshot_png(self, out_path: str) -> None:
        # Render twice so the back buffer is fully populated, then pull pixels.
        self.graphicsEngine.renderFrame()
        self.graphicsEngine.renderFrame()
        tex = self.win.getScreenshot()
        if tex is None:
            log.warning("panda3d screenshot returned no texture")
            return
        # Try Panda's writer first; some builds ship without libpng glue, fall back to Pillow.
        if tex.write(out_path):
            return
        img = PNMImage()
        if not tex.store(img):
            log.warning("panda3d failed to store texture into PNMImage")
            return
        if img.write(out_path):
            return
        try:
            from PIL import Image
        except ImportError:
            log.warning("Pillow not available; cannot write %s", out_path)
            return
        w, h = img.getReadXSize(), img.getReadYSize()
        has_alpha = img.hasAlpha()
        mode = "RGBA" if has_alpha else "RGB"
        pixels = bytearray(w * h * (4 if has_alpha else 3))
        idx = 0
        for y in range(h):
            for x in range(w):
                r = int(img.getRedVal(x, y))
                g = int(img.getGreenVal(x, y))
                b = int(img.getBlueVal(x, y))
                pixels[idx] = r; pixels[idx+1] = g; pixels[idx+2] = b
                idx += 3
                if has_alpha:
                    pixels[idx] = int(img.getAlphaVal(x, y))
                    idx += 1
        Image.frombytes(mode, (w, h), bytes(pixels)).save(out_path)


# --------------------------------------------------------------------------- #
# Output writers                                                              #
# --------------------------------------------------------------------------- #

def encode_video(frame_dir: str, pattern: str, fps: float, out_path: str) -> None:
    if not shutil.which("ffmpeg"):
        raise SystemExit(
            "video output requested but ffmpeg is not on PATH; "
            "install ffmpeg or pick --output-mode sequence"
        )
    cmd = [
        "ffmpeg", "-y",
        "-framerate", f"{fps}",
        "-i", os.path.join(frame_dir, pattern),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        out_path,
    ]
    subprocess.run(cmd, check=True)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="render.py",
        description="OpenLive2D CLI renderer (Blender bakes, Panda3D displays).",
    )
    p.add_argument("input", help="Path to a .ol2d / .ml2d archive, or a directory containing model.json")
    p.add_argument("--key", help="Path to .key file (for .ml2d archives). Defaults to <archive>.key")
    p.add_argument("--width", type=int, default=1024, help="Output width in pixels (default 1024)")
    p.add_argument("--height", type=int, default=1024, help="Output height in pixels (default 1024)")
    p.add_argument("--fps", type=float, default=30.0, help="Frames per second for sequence/video output")
    p.add_argument("--time", type=float, default=0.0, help="Time in seconds for single-frame output")
    p.add_argument("--duration", type=float, default=None,
                   help="Override duration (seconds) for sequence/video. Defaults to the animation's own Duration.")
    p.add_argument("--animation", default="idle",
                   help="Which animation key to play (default: idle). Looked up in part anims, then global.")
    p.add_argument("--samples", type=int, default=16, help="EEVEE render samples (default 16)")
    p.add_argument("--output-mode", choices=("png", "sequence", "video", "none"), default="png",
                   help="png: single frame; sequence: numbered PNGs; video: encoded mp4; none: render but write nothing")
    p.add_argument("--output", "-o", default=None,
                   help="Output path. PNG: file path. sequence: directory. video: file path (e.g. out.mp4).")
    p.add_argument("--show-window", action="store_true",
                   help="Open the Panda3D window onscreen instead of running offscreen.")
    p.add_argument("-v", "--verbose", action="count", default=0, help="-v info, -vv debug")
    return p.parse_args(argv)


def _select_motion(model: Model, name: str) -> dict | None:
    for part in model.parts.values():
        if name in part.animations:
            return part.animations[name]
    return model.animations.get(name)


def _frame_count(motion: dict | None, fps: float, override: float | None) -> int:
    if override is not None:
        return max(1, int(round(override * fps)))
    if motion is None:
        return 1
    duration = float(motion.get("Meta", {}).get("Duration", 0.0))
    return max(1, int(round(duration * fps)))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2 else logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    work_dir = tempfile.mkdtemp(prefix="ol2d_extract_")
    try:
        root = resolve_model_root(args.input, work_dir, args.key)
        model = load_model(root)
        log.info("loaded model: parts=%s anims=%s", list(model.parts), list(model.animations))

        motion = _select_motion(model, args.animation)
        if motion is None:
            log.info("animation %r not found; rendering static pose", args.animation)

        baker = BlenderBaker(model, args.width, args.height, samples=args.samples)
        display = PandaDisplay(args.width, args.height, headless=not args.show_window)

        try:
            if args.output_mode == "png":
                out = args.output or "render.png"
                poses = evaluate_motion(model, motion, args.time)
                baker.apply_poses(poses)
                baker.render_frame(out)
                display.show_png(out)
                log.info("wrote %s", out)

            elif args.output_mode in ("sequence", "video", "none"):
                frames = _frame_count(motion, args.fps, args.duration)
                if args.output_mode == "sequence":
                    seq_dir = args.output or "render_seq"
                    os.makedirs(seq_dir, exist_ok=True)
                elif args.output_mode == "video":
                    seq_dir = tempfile.mkdtemp(prefix="ol2d_video_")
                else:
                    seq_dir = tempfile.mkdtemp(prefix="ol2d_none_")

                try:
                    for i in range(frames):
                        t = i / args.fps
                        poses = evaluate_motion(model, motion, t)
                        baker.apply_poses(poses)
                        frame_path = os.path.join(seq_dir, f"frame_{i:05d}.png")
                        baker.render_frame(frame_path)
                        display.show_png(frame_path)

                    if args.output_mode == "video":
                        out = args.output or "render.mp4"
                        encode_video(seq_dir, "frame_%05d.png", args.fps, out)
                        log.info("wrote %s", out)
                    elif args.output_mode == "sequence":
                        log.info("wrote %d frames to %s", frames, seq_dir)
                finally:
                    if args.output_mode in ("video", "none"):
                        shutil.rmtree(seq_dir, ignore_errors=True)
        finally:
            baker.cleanup()
            try:
                display.destroy()
            except Exception:  # noqa: BLE001
                pass
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
