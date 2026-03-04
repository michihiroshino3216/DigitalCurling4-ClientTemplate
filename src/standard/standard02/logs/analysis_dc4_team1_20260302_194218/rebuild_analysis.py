import csv
import math
import re
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / 'dc4_team1_20260302_194218.jsonl'
OUT_DIR = Path(__file__).parent


def parse_log(path: Path):
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            if 'latest_state_data' not in line:
                continue

            m_end = re.search(r'end_number=(\d+)', line)
            m_shot = re.search(r'shot_number=(\d+)', line)
            if not m_end or not m_shot:
                continue

            end_number = int(m_end.group(1))
            shot_number = int(m_shot.group(1))

            m_next = re.search(r"next_shot_team='?(team0|team1|None)'?", line)
            next_shot = m_next.group(1) if m_next else None

            m_lastmove = re.search(r'last_move=ShotInfoSchema\(([^)]*)\)', line)
            last_move = m_lastmove.group(1) if m_lastmove else ''

            shot_params = {
                'translational_velocity': None,
                'angular_velocity': None,
                'shot_angle': None,
            }
            if last_move:
                m_tv = re.search(r'translational_velocity=([\-0-9\.eE]+)', last_move)
                m_av = re.search(r'angular_velocity=([\-0-9\.eE]+)', last_move)
                m_sa = re.search(r'shot_angle=([\-0-9\.eE]+)', last_move)
                if m_tv:
                    shot_params['translational_velocity'] = float(m_tv.group(1))
                if m_av:
                    shot_params['angular_velocity'] = float(m_av.group(1))
                if m_sa:
                    shot_params['shot_angle'] = float(m_sa.group(1))

            coords = {'team0': [], 'team1': []}
            m_stone = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{(.+?)\}\)\s*score=", line, re.DOTALL)
            block = m_stone.group(1) if m_stone else None
            if block is None:
                m_fallback = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{(.+?)\}\)", line, re.DOTALL)
                if m_fallback:
                    block = m_fallback.group(1)

            if block:
                for team in ('team0', 'team1'):
                    m_team = re.search(r"['\"]?" + team + r"['\"]?\s*:\s*\[(.*?)\](?:,|$)", block, re.DOTALL)
                    if not m_team:
                        continue
                    items = m_team.group(1)
                    for m in re.finditer(r"x=([\-0-9\.eE]+),\s*y=([\-0-9\.eE]+)", items):
                        x = float(m.group(1))
                        y = float(m.group(2))
                        coords[team].append((x, y))

            entries.append({
                'line_no': line_no,
                'end': end_number,
                'shot': shot_number,
                'next_shot': next_shot,
                'last_move': last_move,
                'shot_params': shot_params,
                'coords': coords,
            })
    return entries


def pick_final_snapshot_per_end(entries):
    per_end = {}
    for e in entries:
        per_end[e['end']] = e
    return per_end


def pick_final_snapshot_per_shot(entries):
    per_shot = {}
    for e in entries:
        per_shot[(e['end'], e['shot'])] = e
    return per_shot


def compute_tee(coords, button=(0.0, 38.5)):
    best = None
    bx, by = button
    for team in ('team0', 'team1'):
        for (x, y) in coords.get(team, []):
            if x == 0.0 and y == 0.0:
                continue
            d = math.hypot(x - bx, y - by)
            if best is None or d < best[0]:
                best = (d, team, x, y)
    return best


def make_svg(coords, path, title='end'):
    x_min, x_max = -1.0, 1.5
    y_min, y_max = 36.0, 40.0

    def mapx(x):
        return 50 + (x - x_min) / (x_max - x_min) * 700

    def mapy(y):
        return 30 + (y_max - y) / (y_max - y_min) * 340

    with open(path, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400">\n')
        f.write('<rect width="100%" height="100%" fill="#fff"/>\n')
        f.write(f'<text x="10" y="20" font-size="14">{title}</text>\n')
        f.write('<rect x="50" y="30" width="700" height="340" fill="#f0f8ff" stroke="#c0e0ff"/>\n')

        # coordinate grid + axis labels
        # x ticks: -1.0 .. 1.5 step 0.5
        x_ticks = [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5]
        for xv in x_ticks:
            px = mapx(xv)
            f.write(f'<line x1="{px:.1f}" y1="30" x2="{px:.1f}" y2="370" stroke="#d6d6d6" stroke-width="0.8"/>\n')
            f.write(f'<text x="{px:.1f}" y="385" font-size="10" text-anchor="middle" fill="#666">{xv:.1f}</text>\n')

        # y ticks: 36.0 .. 40.0 step 0.5
        y_ticks = [36.0, 36.5, 37.0, 37.5, 38.0, 38.5, 39.0, 39.5, 40.0]
        for yv in y_ticks:
            py = mapy(yv)
            f.write(f'<line x1="50" y1="{py:.1f}" x2="750" y2="{py:.1f}" stroke="#d6d6d6" stroke-width="0.8"/>\n')
            f.write(f'<text x="44" y="{py + 3:.1f}" font-size="10" text-anchor="end" fill="#666">{yv:.1f}</text>\n')

        f.write('<text x="400" y="398" font-size="11" text-anchor="middle" fill="#555">x</text>\n')
        f.write('<text x="14" y="200" font-size="11" text-anchor="middle" fill="#555" transform="rotate(-90 14 200)">y</text>\n')

        for team, color in [('team0', '#2b6cff'), ('team1', '#e63946')]:
            for (x, y) in coords.get(team, []):
                if x == 0.0 and y == 0.0:
                    continue
                cx = mapx(x)
                cy = mapy(y)
                f.write(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="{color}" stroke="#000" stroke-width="0.6" />\n')

        bx = mapx(0.0)
        by = mapy(38.5)
        f.write(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="6" fill="none" stroke="#ff9900" stroke-width="3"/>\n')
        f.write('</svg>\n')


def write_outputs(per_end, per_shot, outdir: Path):
    csv_path = outdir / 'per_end_final.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
        w = csv.writer(cf)
        w.writerow(['end', 'team', 'stone_index', 'x', 'y', 'distance_to_button'])
        for en in sorted(per_end.keys()):
            entry = per_end[en]
            coords = entry['coords']
            for team in ('team0', 'team1'):
                for idx, (x, y) in enumerate(coords.get(team, [])):
                    if x == 0.0 and y == 0.0:
                        continue
                    d = math.hypot(x - 0.0, y - 38.5)
                    w.writerow([en, team, idx, x, y, round(d, 3)])

    tee_path = outdir / 'tee_positions_rebuild.txt'
    with open(tee_path, 'w', encoding='utf-8') as tf:
        tf.write('TEE (button=(0.0,38.5)) — rebuilt\n')
        for en in sorted(per_end.keys()):
            tee = compute_tee(per_end[en]['coords'])
            if tee:
                d, team, x, y = tee
                tf.write(f'End {en}: team={team}, x={x}, y={y}, dist={round(d, 3)}\n')
            else:
                tf.write(f'End {en}: no stones\n')

    shots_csv = outdir / 'per_end_shots.csv'
    with open(shots_csv, 'w', newline='', encoding='utf-8') as scf:
        w = csv.writer(scf)
        w.writerow(['end', 'shot', 'next_shot', 'translational_velocity', 'angular_velocity', 'shot_angle'])
        for en in sorted(per_end.keys()):
            e = per_end[en]
            sp = e.get('shot_params', {})
            w.writerow([
                en,
                e.get('shot'),
                e.get('next_shot'),
                sp.get('translational_velocity'),
                sp.get('angular_velocity'),
                sp.get('shot_angle'),
            ])

    # End final SVGs (existing style)
    for en in sorted(per_end.keys()):
        e = per_end[en]
        make_svg(e['coords'], outdir / f'end{en}_rebuild.svg', title=f'End {en} final (rebuild)')

    # NEW: shot-by-shot SVGs
    for (en, shot) in sorted(per_shot.keys()):
        e = per_shot[(en, shot)]
        make_svg(
            e['coords'],
            outdir / f'end{en}_shot{shot}_rebuild.svg',
            title=f'End {en} Shot {shot} (rebuild)'
        )


def main():
    entries = parse_log(LOG_PATH)
    per_end = pick_final_snapshot_per_end(entries)
    per_shot = pick_final_snapshot_per_shot(entries)
    write_outputs(per_end, per_shot, OUT_DIR)
    print('Rebuild completed. Outputs in', OUT_DIR)


if __name__ == '__main__':
    main()
