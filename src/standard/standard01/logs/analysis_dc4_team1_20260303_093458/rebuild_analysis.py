import csv
import math
import re
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / 'dc4_team1_20260303_093458.jsonl'
OUT_DIR = Path(__file__).parent
BUTTON = (0.0, 38.5)


def parse_log(path: Path):
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            if 'latest_state_data' not in line:
                continue

            m_end = re.search(r'end_number=(\d+)', line)
            m_shot = re.search(r'shot_number=(\d+)', line)
            m_total = re.search(r'total_shot_number=(\d+)', line)
            m_next = re.search(r"next_shot_team='?(team0|team1|None)'?", line)
            m_lastmove = re.search(r'last_move=ShotInfoSchema\(([^)]*)\)', line)
            if not (m_end and m_shot and m_total and m_next):
                continue

            end_number = int(m_end.group(1))
            shot_number = int(m_shot.group(1))
            total_shot_number = int(m_total.group(1))
            next_shot = m_next.group(1)
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
                'total': total_shot_number,
                'next_shot': next_shot,
                'last_move': last_move,
                'shot_params': shot_params,
                'coords': coords,
            })
    return entries


def non_zero_count(coords, team):
    return sum(1 for x, y in coords.get(team, []) if not (x == 0.0 and y == 0.0))


def compute_tee(coords, button=BUTTON):
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


def map_shooter(per_shot):
    by_end = {}
    for e in per_shot.values():
        by_end.setdefault(e['end'], {})[e['total']] = e

    shooter_map = {}
    for end, seq in by_end.items():
        if 0 not in seq:
            continue
        first = seq[0]['next_shot']
        if first not in ('team0', 'team1'):
            continue
        for total, e in seq.items():
            if total <= 0:
                continue
            shooter = first if (total % 2 == 1) else ('team1' if first == 'team0' else 'team0')
            shooter_map[(end, total)] = shooter
    return shooter_map


def make_svg(coords, path, title='Shot'):
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

        x_ticks = [-1.0, -0.5, 0.0, 0.5, 1.0, 1.5]
        for xv in x_ticks:
            px = mapx(xv)
            f.write(f'<line x1="{px:.1f}" y1="30" x2="{px:.1f}" y2="370" stroke="#d6d6d6" stroke-width="0.8"/>\n')
            f.write(f'<text x="{px:.1f}" y="385" font-size="10" text-anchor="middle" fill="#666">{xv:.1f}</text>\n')

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

        bx = mapx(BUTTON[0])
        by = mapy(BUTTON[1])
        f.write(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="6" fill="none" stroke="#ff9900" stroke-width="3"/>\n')
        f.write('</svg>\n')


def write_outputs(entries, outdir: Path):
    per_end = {}
    per_shot = {}
    for e in entries:
        per_end[e['end']] = e
        per_shot[(e['end'], e['total'])] = e

    shooter_map = map_shooter(per_shot)

    with open(outdir / 'per_end_final.csv', 'w', newline='', encoding='utf-8') as cf:
        w = csv.writer(cf)
        w.writerow(['end', 'team', 'stone_index', 'x', 'y', 'distance_to_button'])
        for en in sorted(per_end.keys()):
            coords = per_end[en]['coords']
            for team in ('team0', 'team1'):
                for idx, (x, y) in enumerate(coords.get(team, [])):
                    if x == 0.0 and y == 0.0:
                        continue
                    d = math.hypot(x - BUTTON[0], y - BUTTON[1])
                    w.writerow([en, team, idx, x, y, round(d, 3)])

    with open(outdir / 'tee_positions_rebuild.txt', 'w', encoding='utf-8') as tf:
        tf.write('TEE (button=(0.0,38.5)) — rebuilt\n')
        for en in sorted(per_end.keys()):
            tee = compute_tee(per_end[en]['coords'])
            if tee:
                d, team, x, y = tee
                tf.write(f'End {en}: team={team}, x={x}, y={y}, dist={round(d,3)}\n')
            else:
                tf.write(f'End {en}: no stones\n')

    with open(outdir / 'per_shot_state.csv', 'w', newline='', encoding='utf-8') as sf:
        w = csv.writer(sf)
        w.writerow([
            'end', 'total_shot_number', 'shot_number', 'shooter_team',
            'team0_stones', 'team1_stones',
            'translational_velocity', 'angular_velocity', 'shot_angle'
        ])
        for key in sorted(per_shot.keys()):
            en, total = key
            if total == 0:
                continue
            e = per_shot[key]
            sp = e['shot_params']
            w.writerow([
                en, total, e['shot'], shooter_map.get((en, total), ''),
                non_zero_count(e['coords'], 'team0'),
                non_zero_count(e['coords'], 'team1'),
                sp.get('translational_velocity'),
                sp.get('angular_velocity'),
                sp.get('shot_angle'),
            ])

    for (en, total), e in sorted(per_shot.items()):
        if total == 0:
            continue
        title = f'End {en} TotalShot {total} / Shooter={shooter_map.get((en,total), "unknown")}'
        svg_path = outdir / f'end{en}_total{total}_rebuild.svg'
        make_svg(e['coords'], svg_path, title=title)

    for en in sorted(per_end.keys()):
        make_svg(per_end[en]['coords'], outdir / f'end{en}_rebuild.svg', title=f'End {en} final (rebuild)')

    takeout_stats = {
        'team0': {'attempts': 0, 'successes': 0, 'removed_total': 0},
        'team1': {'attempts': 0, 'successes': 0, 'removed_total': 0},
    }

    by_end = {}
    for (en, total), e in per_shot.items():
        by_end.setdefault(en, {})[total] = e

    rows = []
    for en, seq in sorted(by_end.items()):
        for total in sorted(t for t in seq.keys() if t > 0):
            cur = seq[total]
            prev = seq.get(total - 1)
            if prev is None:
                continue
            shooter = shooter_map.get((en, total))
            if shooter not in ('team0', 'team1'):
                continue
            opponent = 'team1' if shooter == 'team0' else 'team0'
            before = non_zero_count(prev['coords'], opponent)
            after = non_zero_count(cur['coords'], opponent)
            removed = max(0, before - after)

            takeout_stats[shooter]['attempts'] += 1
            takeout_stats[shooter]['removed_total'] += removed
            success = 1 if removed > 0 else 0
            takeout_stats[shooter]['successes'] += success

            rows.append([
                en, total, shooter, opponent, before, after, removed, success
            ])

    with open(outdir / 'takeout_events.csv', 'w', newline='', encoding='utf-8') as tf:
        w = csv.writer(tf)
        w.writerow(['end', 'total_shot_number', 'shooter', 'opponent', 'opponent_before', 'opponent_after', 'removed', 'success'])
        w.writerows(rows)

    with open(outdir / 'takeout_summary.txt', 'w', encoding='utf-8') as sf:
        sf.write('Takeout success summary\n')
        for team in ('team0', 'team1'):
            att = takeout_stats[team]['attempts']
            suc = takeout_stats[team]['successes']
            rem = takeout_stats[team]['removed_total']
            rate = (suc / att * 100.0) if att else 0.0
            sf.write(f'{team}: successes={suc}, attempts={att}, success_rate={rate:.1f}%, removed_total={rem}\n')


def main():
    entries = parse_log(LOG_PATH)
    write_outputs(entries, OUT_DIR)
    print('Rebuild completed. Outputs in', OUT_DIR)


if __name__ == '__main__':
    main()
