import re
import csv
import math
from pathlib import Path

LOG_PATH = Path(__file__).parent.parent / 'dc4_team1_20260302_175415.jsonl'
OUT_DIR = Path(__file__).parent

def parse_log(path):
    entries = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if 'latest_state_data' not in line:
                continue
            # extract end_number and shot_number
            m_end = re.search(r'end_number=(\d+)', line)
            m_shot = re.search(r'shot_number=(\d+)', line)
            end_number = int(m_end.group(1)) if m_end else None
            shot_number = int(m_shot.group(1)) if m_shot else None
            # extract next_shot_team
            m_next = re.search(r"next_shot_team='?(team0|team1|None)'?", line)
            next_shot = m_next.group(1) if m_next else None
            # extract last_move block (optional)
            m_lastmove = re.search(r'last_move=ShotInfoSchema\(([^)]*)\)', line)
            last_move = m_lastmove.group(1) if m_lastmove else ''
            # extract stone coordinates
            coords = {'team0': [], 'team1': []}
            m_stone = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{(.+?)\}\)\s*score=", line, re.DOTALL)
            block = None
            if m_stone:
                block = m_stone.group(1)
            else:
                # fallback: find stone_coordinate=StoneCoordinateSchema(data={ ... }) without score
                m2 = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{(.+?)\}\)", line, re.DOTALL)
                if m2:
                    block = m2.group(1)
            if block:
                # split teams
                # find team0: [CoordinateDataSchema(x=..., y=...), ...]
                for team in ('team0', 'team1'):
                    # keys in block are quoted like 'team0': [...]
                    m_team = re.search(r"['\"]?" + team + r"['\"]?\s*:\s*\[(.*?)\](?:,|$)", block, re.DOTALL)
                    if m_team:
                        items = m_team.group(1)
                        # find all x=..., y=...
                        for m in re.finditer(r"x=([\-0-9\.eE]+),\s*y=([\-0-9\.eE]+)", items):
                            x = float(m.group(1))
                            y = float(m.group(2))
                            coords[team].append((x,y))
            entries.append({
                'end': end_number,
                'shot': shot_number,
                'next_shot': next_shot,
                'last_move': last_move,
                'coords': coords,
                'raw': line.strip()
            })
    return entries


def pick_final_snapshot_per_end(entries):
    per_end = {}
    # choose last entry for each end where next_shot is None or when end increments
    for e in entries:
        en = e['end']
        if en is None:
            continue
        # Keep latest by appearance (iterative overwrite)
        per_end[en] = e
    return per_end


def compute_tee(coords, button=(0.0,38.5)):
    # coords: dict team->list of (x,y)
    best = None
    bx, by = button
    for team in ('team0','team1'):
        for (x,y) in coords.get(team,[]):
            if x==0.0 and y==0.0:
                continue
            d = math.hypot(x-bx, y-by)
            if best is None or d < best[0]:
                best = (d, team, x, y)
    return best


def write_outputs(per_end, outdir):
    # CSV per end
    csv_path = outdir / 'per_end_final.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as cf:
        w = csv.writer(cf)
        w.writerow(['end','team','stone_index','x','y','distance_to_button'])
        for en in sorted(per_end.keys()):
            entry = per_end[en]
            coords = entry['coords']
            tee = compute_tee(coords)
            # write all stones
            for team in ('team0','team1'):
                for idx,(x,y) in enumerate(coords.get(team, [])):
                    if x==0.0 and y==0.0:
                        continue
                    d = math.hypot(x-0.0, y-38.5)
                    w.writerow([en, team, idx, x, y, round(d,3)])
    # tee positions text
    tee_path = outdir / 'tee_positions_rebuild.txt'
    with open(tee_path, 'w', encoding='utf-8') as tf:
        tf.write('TEE (button=(0.0,38.5)) — rebuilt\n')
        for en in sorted(per_end.keys()):
            entry = per_end[en]
            tee = compute_tee(entry['coords'])
            if tee:
                d,team,x,y = tee
                tf.write(f'End {en}: team={team}, x={x}, y={y}, dist={round(d,3)}\n')
            else:
                tf.write(f'End {en}: no stones\n')
    # important shots: choose the entry flagged as last snapshot for that end
    imp_path = outdir / 'important_shots_rebuild.txt'
    with open(imp_path, 'w', encoding='utf-8') as imf:
        imf.write('Important shots (end final snapshots)\n')
        for en in sorted(per_end.keys()):
            e = per_end[en]
            imf.write(f'End {en}: shot={e["shot"]}, next_shot={e["next_shot"]}\n')
            imf.write('last_move: ' + (e['last_move'] or 'None') + '\n')
            imf.write('coords:\n')
            for team in ('team0','team1'):
                imf.write(' ' + team + ':\n')
                for (x,y) in e['coords'].get(team, []):
                    imf.write(f'   {x},{y}\n')
            imf.write('\n')
    # simple SVGs
    for en in sorted(per_end.keys()):
        e = per_end[en]
        svg_path = outdir / f'end{en}_rebuild.svg'
        make_svg(e['coords'], svg_path, title=f'End {en} final (rebuild)')


def make_svg(coords, path, title='end'):
    # map x in [-1.0,1.5] -> [50,750], y in [36,40] -> [370,30]
    def mapx(x):
        return 50 + (x+1.0)/(2.5)*700
    def mapy(y):
        return 30 + (40 - y)/(4.0)*340
    with open(path,'w',encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400" viewBox="0 0 800 400">\n')
        f.write('<rect width="100%" height="100%" fill="#fff"/>\n')
        f.write(f'<text x="10" y="20" font-size="14">{title}</text>\n')
        f.write('<rect x="50" y="30" width="700" height="340" fill="#f0f8ff" stroke="#c0e0ff"/>\n')
        # stones
        for team,color in [('team0','#2b6cff'),('team1','#e63946')]:
            for (x,y) in coords.get(team,[]):
                if x==0.0 and y==0.0:
                    continue
                cx = mapx(x)
                cy = mapy(y)
                f.write(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="{color}" stroke="#000" stroke-width="0.6" />\n')
        # draw button marker
        bx = mapx(0.0); by = mapy(38.5)
        f.write(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="6" fill="none" stroke="#ff9900" stroke-width="3"/>\n')
        f.write('</svg>\n')

if __name__ == '__main__':
    entries = parse_log(LOG_PATH)
    per_end = pick_final_snapshot_per_end(entries)
    write_outputs(per_end, OUT_DIR)
    print('Rebuild completed. Outputs in', OUT_DIR)
