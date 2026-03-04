import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import matplotlib.pyplot as plt

ROOT = Path(__file__).parents[1]


STONE_R = 0.145
HOUSE_R = 1.829


def parse_line(line: str) -> Dict:
    j = json.loads(line)
    msg: str = j.get("message", "")

    def find_num(key: str) -> Optional[float]:
        m = re.search(fr"{key}=([\d\.-]+)", msg)
        return float(m.group(1)) if m else None

    def find_int(key: str) -> Optional[int]:
        m = re.search(fr"{key}=([0-9]+)", msg)
        return int(m.group(1)) if m else None

    transl = find_num("translational_velocity")
    angular = find_num("angular_velocity")
    shot_angle = find_num("shot_angle")
    end_number = find_int("end_number")
    shot_number = find_int("shot_number")
    total_shot_number = find_int("total_shot_number")
    next_shot_team = None
    m = re.search(r"next_shot_team=(?:'|\")?(team0|team1)(?:'|\")?", msg)
    if m:
        next_shot_team = m.group(1)

    # parse coordinates by team: capture text between "data={" and "}) score=" (if score exists)
    coords = {"team0": [], "team1": []}
    data_m = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=(\{.*?\})\) score=", msg)
    data_text = None
    if data_m:
        data_text = data_m.group(1)
    else:
        # fallback: try to capture up to end
        m2 = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=(\{.*\})\)\"", msg)
        if m2:
            data_text = m2.group(1)

    if data_text is None:
        # try looser capture of CoordinateDataSchema occurrences
        all_coords = re.findall(r"CoordinateDataSchema\(x=([\-0-9\.]+), y=([\-0-9\.]+)\)", msg)
        # assume first 8 are team0 then team1
        if all_coords:
            for i, (x, y) in enumerate(all_coords):
                if i < 8:
                    coords["team0"].append((float(x), float(y)))
                else:
                    coords["team1"].append((float(x), float(y)))
    else:
        # extract CoordinateDataSchema pairs within each team's bracket
        for team in ("team0", "team1"):
            tm = re.search(fr"'{team}': \[(.*?)\]", data_text, re.S)
            if tm:
                block = tm.group(1)
                pairs = re.findall(r"CoordinateDataSchema\(x=([\-0-9\.]+), y=([\-0-9\.]+)\)", block)
                coords[team] = [(float(x), float(y)) for x, y in pairs]

    return {
        "timestamp": j.get("timestamp"),
        "end_number": end_number,
        "shot_number": shot_number,
        "total_shot_number": total_shot_number,
        "next_shot_team": next_shot_team,
        "translational_velocity": transl,
        "angular_velocity": angular,
        "shot_angle": shot_angle,
        "coords": coords,
        "raw_message": msg,
    }


def find_no1(coords: Dict[str, List[Tuple[float, float]]]) -> Optional[Dict]:
    # nearest to TEE (0, 38.405) within HOUSE_R
    TEE_X, TEE_Y = 0.0, 38.405
    best = None
    best_d2 = float("inf")
    for team in ("team0", "team1"):
        for (x, y) in coords.get(team, []):
            if x == 0 and y == 0:
                continue
            d2 = (x - TEE_X) ** 2 + (y - TEE_Y) ** 2
            if d2 <= HOUSE_R ** 2 and d2 < best_d2:
                best_d2 = d2
                best = {"x": x, "y": y, "team": team}
    return best


def draw_board(coords: Dict[str, List[Tuple[float, float]]], path: Path, title: str):
    fig, ax = plt.subplots(figsize=(6, 8))
    ax.set_xlim(-3.0, 3.0)
    ax.set_ylim(30.0, 40.0)
    ax.set_aspect('equal')
    ax.set_title(title)

    for (x, y) in coords.get("team0", []):
        if x == 0 and y == 0:
            continue
        c = plt.Circle((x, y), STONE_R, color="#1f77b4", ec="k")
        ax.add_patch(c)
    for (x, y) in coords.get("team1", []):
        if x == 0 and y == 0:
            continue
        c = plt.Circle((x, y), STONE_R, color="#ff7f0e", ec="k")
        ax.add_patch(c)

    # draw house circle (approx)
    house = plt.Circle((0.0, 38.405), HOUSE_R, color='gray', fill=False, linestyle='--')
    ax.add_patch(house)

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    plt.savefig(path, bbox_inches='tight')
    plt.close(fig)


def analyze_log(log_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    last_snapshot = None
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = parse_line(line)
            except Exception:
                continue

            # if this line contains a shot (translational_velocity present), treat as after-shot
            if parsed.get('translational_velocity') is not None:
                after = parsed['coords']
                before = last_snapshot['coords'] if last_snapshot else parsed['coords']
                shot = {
                    'timestamp': parsed['timestamp'],
                    'end_number': parsed['end_number'],
                    'shot_number': parsed['shot_number'],
                    'total_shot_number': parsed['total_shot_number'],
                    'next_shot_team': parsed['next_shot_team'],
                    'translational_velocity': parsed['translational_velocity'],
                    'angular_velocity': parsed['angular_velocity'],
                    'before': before,
                    'after': after,
                }
                shots.append(shot)
            last_snapshot = parsed

    # classify takeout attempts and success
    attempts = 0
    successes = 0
    results = []
    for s in shots:
        v = s['translational_velocity'] or 0.0
        w = s['angular_velocity'] or 0.0
        is_takeout = v >= 3.5 and abs(w) <= 1.0
        no1_before = find_no1(s['before'])
        no1_after = find_no1(s['after'])
        success = False
        if is_takeout:
            attempts += 1
            if no1_before is not None:
                # find same-position stone in after; if it's gone or moved far, count success
                tx, ty, team = no1_before['x'], no1_before['y'], no1_before['team']
                found = False
                for (x, y) in s['after'].get(team, []):
                    if abs(x - tx) < 0.2 and abs(y - ty) < 0.2:
                        found = True
                        break
                if not found:
                    success = True
                    successes += 1

        # draw before/after boards
        name = f"end{int(s['end_number'] or 0):02d}_shot{int(s['shot_number'] or 0):02d}_tot{int(s['total_shot_number'] or 0):03d}"
        draw_board(s['before'], out_dir / f"{name}_before.png", f"Before {name}")
        draw_board(s['after'], out_dir / f"{name}_after.png", f"After {name}")

        results.append({
            'name': name,
            'timestamp': s['timestamp'],
            'translational_velocity': v,
            'angular_velocity': w,
            'is_takeout_attempt': bool(is_takeout),
            'takeout_success': bool(success),
        })

    summary = {
        'log': str(log_path),
        'shots_analyzed': len(shots),
        'takeout_attempts': attempts,
        'takeout_successes': successes,
        'takeout_success_rate': (successes / attempts * 100.0) if attempts else None,
        'per_shot': results,
    }

    with open(out_dir / 'summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument('logfile', nargs='+', help='path to jsonl log(s)')
    p.add_argument('--out', help='output directory', default='analysis_outputs')
    args = p.parse_args()

    out_base = Path(args.out)
    for lp in args.logfile:
        lp = Path(lp)
        out_dir = out_base / lp.stem
        analyze_log(lp, out_dir)


if __name__ == '__main__':
    main()
