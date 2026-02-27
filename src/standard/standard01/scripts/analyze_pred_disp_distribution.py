import argparse
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List


def predict_lateral_disp(omega: float, v: float, path_len: float, alpha: float) -> float:
    if v <= 0:
        return 0.0
    return alpha * omega * path_len / max(v, 0.1)


def percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    idx = (len(sorted_values) - 1) * (p / 100.0)
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return sorted_values[low]
    frac = idx - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def summarize(values: Iterable[float]) -> Dict[str, float]:
    arr = sorted(float(x) for x in values)
    if not arr:
        return {
            "count": 0,
            "min": float("nan"),
            "p01": float("nan"),
            "p05": float("nan"),
            "p25": float("nan"),
            "p50": float("nan"),
            "p75": float("nan"),
            "p95": float("nan"),
            "p99": float("nan"),
            "max": float("nan"),
            "mean": float("nan"),
            "std": float("nan"),
        }
    mean = sum(arr) / len(arr)
    variance = sum((x - mean) ** 2 for x in arr) / len(arr)
    return {
        "count": len(arr),
        "min": arr[0],
        "p01": percentile(arr, 1),
        "p05": percentile(arr, 5),
        "p25": percentile(arr, 25),
        "p50": percentile(arr, 50),
        "p75": percentile(arr, 75),
        "p95": percentile(arr, 95),
        "p99": percentile(arr, 99),
        "max": arr[-1],
        "mean": mean,
        "std": math.sqrt(variance),
    }


def fmt_stats(label: str, stats: Dict[str, float]) -> str:
    if stats["count"] == 0:
        return f"{label}: count=0"
    return (
        f"{label}: count={int(stats['count'])}, "
        f"min={stats['min']:.6f}, p05={stats['p05']:.6f}, p50={stats['p50']:.6f}, "
        f"p95={stats['p95']:.6f}, max={stats['max']:.6f}, "
        f"mean={stats['mean']:.6f}, std={stats['std']:.6f}"
    )


def load_entries(grid_path: Path) -> List[Dict]:
    with grid_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("grid file must be a list of entries")
    return data


def collect_base_vectors(entries: List[Dict]) -> Dict[str, List[float]]:
    source_distance_values: List[float] = []
    path_lengths: List[float] = []
    omegas: List[float] = []
    speeds: List[float] = []

    missing_source_distance = 0
    invalid_entries = 0

    for entry in entries:
        src_dist = entry.get("source_distance")
        if isinstance(src_dist, (int, float)):
            path_len = float(src_dist)
            source_distance_values.append(path_len)
        else:
            missing_source_distance += 1
            path_len = 1.0

        for spin in ("ccw", "cw"):
            try:
                vx = float(entry[f"{spin}_velocity_x"])
                vy = float(entry[f"{spin}_velocity_y"])
                omega = float(entry[f"{spin}_angular_velocity"])
            except (KeyError, TypeError, ValueError):
                invalid_entries += 1
                continue
            speeds.append(math.hypot(vx, vy))
            omegas.append(omega)
            path_lengths.append(path_len)

    return {
        "source_distance_values": source_distance_values,
        "path_lengths": path_lengths,
        "omegas": omegas,
        "speeds": speeds,
        "missing_source_distance": [missing_source_distance],
        "invalid_entries": [invalid_entries],
    }


def analyze_for_alpha(omegas: List[float], speeds: List[float], path_lengths: List[float], alpha: float) -> Dict[str, Dict[str, float]]:
    pred_disp_signed: List[float] = []
    pred_disp_abs: List[float] = []
    for omega, v, path_len in zip(omegas, speeds, path_lengths):
        pred = predict_lateral_disp(omega=omega, v=v, path_len=path_len, alpha=alpha)
        pred_disp_signed.append(pred)
        pred_disp_abs.append(abs(pred))
    return {
        "pred_signed_stats": summarize(pred_disp_signed),
        "pred_abs_stats": summarize(pred_disp_abs),
    }


def main() -> None:
    default_grid = Path(__file__).resolve().parents[1] / "grid_export_filled.json"
    parser = argparse.ArgumentParser(
        description="Analyze source_distance and predicted lateral displacement distribution."
    )
    parser.add_argument(
        "--grid",
        type=Path,
        default=default_grid,
        help="Path to grid JSON (default: standard01/grid_export_filled.json)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.03,
        help="alpha used by _predict_lateral_disp (default: 0.03)",
    )
    parser.add_argument(
        "--alpha-list",
        type=str,
        default="",
        help="Comma separated alpha values for sensitivity sweep, e.g. 0.02,0.03,0.05",
    )
    args = parser.parse_args()

    entries = load_entries(args.grid)

    base = collect_base_vectors(entries)
    source_distance_values = base["source_distance_values"]
    path_lengths = base["path_lengths"]
    omegas = base["omegas"]
    speeds = base["speeds"]
    missing_source_distance = int(base["missing_source_distance"][0])
    invalid_entries = int(base["invalid_entries"][0])

    src_stats = summarize(source_distance_values)
    v_stats = summarize(speeds)
    one_alpha = analyze_for_alpha(omegas, speeds, path_lengths, args.alpha)
    pred_signed_stats = one_alpha["pred_signed_stats"]
    pred_abs_stats = one_alpha["pred_abs_stats"]

    realistic_low = pred_abs_stats["p05"]
    realistic_high = pred_abs_stats["p95"]

    print("=== Grid Predicted Lateral Displacement Analysis ===")
    print(f"grid_path: {args.grid}")
    print(f"entries: {len(entries)}")
    print(f"alpha: {args.alpha}")
    print(f"missing_source_distance: {missing_source_distance}")
    print(f"invalid_spin_records_skipped: {invalid_entries}")
    print()
    print(fmt_stats("source_distance", src_stats))
    print(fmt_stats("speed(|v|)", v_stats))
    print(fmt_stats("pred_disp_signed", pred_signed_stats))
    print(fmt_stats("pred_disp_abs", pred_abs_stats))
    print()
    print(
        "realistic pred_disp(abs) range (p05-p95): "
        f"[{realistic_low:.6f}, {realistic_high:.6f}] m"
    )

    if args.alpha_list.strip():
        raw_parts = [p.strip() for p in args.alpha_list.split(",") if p.strip()]
        alphas: List[float] = []
        for part in raw_parts:
            try:
                alphas.append(float(part))
            except ValueError as e:
                raise ValueError(f"invalid alpha in --alpha-list: {part}") from e

        print()
        print("=== Alpha Sensitivity (pred_disp_abs) ===")
        print("alpha\tp05(m)\tp50(m)\tp95(m)\tmax(m)")
        for alpha in alphas:
            result = analyze_for_alpha(omegas, speeds, path_lengths, alpha)
            abs_stats = result["pred_abs_stats"]
            print(
                f"{alpha:.6f}\t{abs_stats['p05']:.6f}\t{abs_stats['p50']:.6f}\t"
                f"{abs_stats['p95']:.6f}\t{abs_stats['max']:.6f}"
            )


if __name__ == "__main__":
    main()
