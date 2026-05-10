"""
Generate a tiny OpenLive2D test model on disk.

Layout produced:
    test_model/
        model.json
        head.json    + head_layers/01_face.png   02_eyes.png
        torso.json   + torso_layers/01_body.png
        left_arm.json + left_arm_layers/01_arm.png
        right_arm.json + right_arm_layers/01_arm.png
        left_leg.json  + left_leg_layers/01_leg.png
        right_leg.json + right_leg_layers/01_leg.png
        idle.json     -- motion3.json (head bob + body breathe)

Each part references `<part>.kra`; render.py's PNG-directory fallback picks up
the matching `<part>_layers/` directory automatically. So you can paint real .kra
files later without changing the JSON.

Usage:
    python scripts/make_test_model.py [output_dir]
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw


CANVAS = (512, 1024)  # whole-character art canvas


def _draw_layer(size: tuple[int, int], shapes: list[tuple]) -> Image.Image:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for kind, *rest in shapes:
        if kind == "ellipse":
            box, fill = rest
            d.ellipse(box, fill=fill)
        elif kind == "rect":
            box, fill = rest
            d.rectangle(box, fill=fill)
        elif kind == "polygon":
            pts, fill = rest
            d.polygon(pts, fill=fill)
    return img


def _save_png(img: Image.Image, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def make_motion(duration: float, fps: float, curves: list[dict]) -> dict:
    total_segments = 0
    total_points = 0
    for c in curves:
        segs = c["Segments"]
        n = len(segs)
        if n > 0:
            total_points += 1
            i = 2
            while i < n:
                total_segments += 1
                seg_type = segs[i]; i += 1
                if seg_type == 1:
                    i += 6; total_points += 3
                else:
                    i += 2; total_points += 1
    return {
        "Version": 3,
        "Meta": {
            "Duration": duration, "Fps": fps, "Loop": True,
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": total_segments,
            "TotalPointCount": total_points,
            "UserDataCount": 0, "TotalUserDataSize": 0,
        },
        "Curves": curves,
        "UserData": [],
    }


def build_layers(out: str) -> None:
    head_w, head_h = 320, 320
    skin = (255, 220, 195, 255)
    hair = (90, 60, 40, 255)
    eye = (40, 40, 40, 255)
    cheek = (255, 180, 180, 220)
    cloth = (80, 130, 200, 255)
    pants = (50, 50, 70, 255)

    # Head: face + eyes + hair
    face = _draw_layer((head_w, head_h), [
        ("ellipse", (40, 60, 280, 300), skin),
        ("ellipse", (110, 200, 150, 220), cheek),
        ("ellipse", (170, 200, 210, 220), cheek),
    ])
    eyes = _draw_layer((head_w, head_h), [
        ("ellipse", (110, 150, 145, 175), eye),
        ("ellipse", (175, 150, 210, 175), eye),
        ("polygon", [(140, 240), (180, 240), (160, 260)], (200, 80, 80, 255)),
    ])
    hair_layer = _draw_layer((head_w, head_h), [
        ("ellipse", (30, 30, 290, 180), hair),
        ("rect", (30, 100, 80, 180), hair),
        ("rect", (240, 100, 290, 180), hair),
    ])
    _save_png(face,        os.path.join(out, "head_layers", "01_face.png"))
    _save_png(eyes,        os.path.join(out, "head_layers", "02_eyes.png"))
    _save_png(hair_layer,  os.path.join(out, "head_layers", "03_hair.png"))

    # Torso
    torso_w, torso_h = 360, 380
    torso = _draw_layer((torso_w, torso_h), [
        ("polygon", [(80, 0), (280, 0), (320, 380), (40, 380)], cloth),
        ("ellipse", (160, 5, 200, 35), skin),  # neck
    ])
    _save_png(torso, os.path.join(out, "torso_layers", "01_body.png"))

    # Arms
    arm_w, arm_h = 100, 320
    larm = _draw_layer((arm_w, arm_h), [
        ("rect", (20, 0, 80, 280), cloth),
        ("ellipse", (15, 250, 85, 320), skin),
    ])
    rarm = larm.transpose(Image.FLIP_LEFT_RIGHT)
    _save_png(larm, os.path.join(out, "left_arm_layers", "01_arm.png"))
    _save_png(rarm, os.path.join(out, "right_arm_layers", "01_arm.png"))

    # Legs
    leg_w, leg_h = 120, 360
    lleg = _draw_layer((leg_w, leg_h), [
        ("rect", (25, 0, 95, 320), pants),
        ("ellipse", (15, 300, 105, 360), (30, 30, 30, 255)),
    ])
    rleg = lleg.transpose(Image.FLIP_LEFT_RIGHT)
    _save_png(lleg, os.path.join(out, "left_leg_layers", "01_leg.png"))
    _save_png(rleg, os.path.join(out, "right_leg_layers", "01_leg.png"))


def build_jsons(out: str) -> None:
    model = {
        "humanoid": {"color": "#FFCC99", "size": 1.0, "width": 1.0, "height": 2.0},
        "head": "head.json",
        "torso": "torso.json",
        "left_arm": "left_arm.json",
        "right_arm": "right_arm.json",
        "left_leg": "left_leg.json",
        "right_leg": "right_leg.json",
        "animations": {"idle": "idle.json"},
    }
    _write_json(os.path.join(out, "model.json"), model)

    parts = ["head", "torso", "left_arm", "right_arm", "left_leg", "right_leg"]
    for p in parts:
        # The .kra path doesn't have to exist -- render.py will fall back to <part>_layers/.
        _write_json(os.path.join(out, f"{p}.json"), {
            "kra_file": f"{p}.kra",
            "logo": f"{p}.png",
            "animations": {},
        })

    # Idle: head sways +/- 8 degrees in Z (ParamAngleZ), body breathes (ParamBreath 0->1->0)
    idle = make_motion(
        duration=4.0, fps=30.0,
        curves=[
            {"Target": "Parameter", "Id": "ParamAngleZ",
             "Segments": [0.0, 0.0, 0, 1.0, 8.0, 0, 2.0, 0.0, 0, 3.0, -8.0, 0, 4.0, 0.0]},
            {"Target": "Parameter", "Id": "ParamAngleX",
             "Segments": [0.0, 0.0, 0, 2.0, 5.0, 0, 4.0, 0.0]},
            {"Target": "Parameter", "Id": "ParamBreath",
             "Segments": [0.0, 0.0, 0, 2.0, 1.0, 0, 4.0, 0.0]},
            {"Target": "Parameter", "Id": "ParamBodyAngleZ",
             "Segments": [0.0, 0.0, 0, 2.0, 2.0, 0, 4.0, 0.0]},
        ],
    )
    _write_json(os.path.join(out, "idle.json"), idle)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "test_model"
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    print(f"writing test model to {out}")
    build_jsons(out)
    build_layers(out)
    print("done. try:")
    print(f"    python render.py {out} -o render.png -v")
    print(f"    python render.py {out} --output-mode sequence -o {out}/seq --duration 4 --fps 30")
    print(f"    python render.py {out} --output-mode video -o render.mp4 --duration 4 --fps 30")
    return 0


if __name__ == "__main__":
    sys.exit(main())
