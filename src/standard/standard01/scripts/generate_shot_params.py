import json
import math
from pathlib import Path

TEE_X = 0.0
TEE_Y = 38.405


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


def convert_center_draw(tx, ty):
    v = 2.42
    angle = math.radians(90)
    omega = math.pi / 2
    return v, angle, omega


def convert_takeout(tx, ty, board=None):
    d = dist(tx, ty, TEE_X, TEE_Y)
    v = 3.2 + (d / 40.0)
    angle = math.atan2(tx, ty)
    omega = 0.5
    return v, angle, omega


def convert_guard(tx, ty):
    v = 2.33
    angle = math.radians(90)
    omega = math.pi / 2
    return v, angle, omega


def convert_freeze(tx, ty):
    v = 2.30
    angle = math.radians(90)
    omega = math.pi / 1.8
    return v, angle, omega


def main():
    src = Path(__file__).parents[1] / "grid_export_filled.json"
    dest = Path(__file__).parents[1] / "grid_export_filled_with_shots.json"

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        if not isinstance(item, dict):
            continue
        if "position_x" not in item or "position_y" not in item:
            continue
        try:
            tx = float(item["position_x"])
            ty = float(item["position_y"])
        except Exception:
            continue

        v_cd, a_cd, w_cd = convert_center_draw(tx, ty)
        v_to, a_to, w_to = convert_takeout(tx, ty)
        v_gd, a_gd, w_gd = convert_guard(tx, ty)
        v_fr, a_fr, w_fr = convert_freeze(tx, ty)

        item.update({
            "center_draw_v": v_cd,
            "center_draw_angle": a_cd,
            "center_draw_omega": w_cd,
            "takeout_v": v_to,
            "takeout_angle": a_to,
            "takeout_omega": w_to,
            "guard_v": v_gd,
            "guard_angle": a_gd,
            "guard_omega": w_gd,
            "freeze_v": v_fr,
            "freeze_angle": a_fr,
            "freeze_omega": w_fr,
        })

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote: {dest}")


if __name__ == "__main__":
    main()
