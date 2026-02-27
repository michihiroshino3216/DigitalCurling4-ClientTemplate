import json
import math
from pathlib import Path


def compute_takeout_fields(tx, ty):
    d = math.hypot(tx, ty)
    base_angle = math.atan2(tx, ty)
    correction = 0.045 * min(d / 40.0, 1.0)
    adjusted_angle = base_angle - correction
    v = 3.2 + (d / 40.0)
    return {
        "takeout_correction": correction,
        "takeout_adjusted_angle": adjusted_angle,
        "takeout_v": v,
    }


def main():
    src = Path(__file__).parents[1] / "grid_export_filled.json"
    dest = Path(__file__).parents[1] / "grid_export_filled_with_takeout.json"

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        if "position_x" in item and "position_y" in item:
            try:
                tx = float(item["position_x"])
                ty = float(item["position_y"])
            except Exception:
                continue
            fields = compute_takeout_fields(tx, ty)
            item.update(fields)

    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote: {dest}")


if __name__ == "__main__":
    main()
