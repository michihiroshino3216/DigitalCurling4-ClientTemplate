import re
import json
import csv
import sys
from math import hypot

TEE = (0.0, 40.0)

coord_re = re.compile(r"CoordinateDataSchema\(x=([0-9eE+\-.]+), y=([0-9eE+\-.]+)\)")


def parse_message(msg):
    # basic shot fields
    def r(p):
        m = re.search(p, msg)
        return m.group(1) if m else None

    end = r(r"end_number=([0-9]+)")
    shot = r(r"shot_number=([0-9]+)")
    total = r(r"total_shot_number=([0-9]+)")
    next_team = r(r"next_shot_team='([^']*)'")
    if next_team == '':
        next_team = None

    lm = re.search(r"last_move=ShotInfoSchema\(translational_velocity=([0-9eE+\-.]+), angular_velocity=([0-9eE+\-.]+), shot_angle=([0-9eE+\-.]+)\)", msg)
    if lm:
        tv = float(lm.group(1))
        av = float(lm.group(2))
        sa = float(lm.group(3))
    else:
        tv = av = sa = None

    # parse stone_coordinate block
    teams = {'team0': [], 'team1': []}
    sc_idx = msg.find("stone_coordinate=StoneCoordinateSchema(data=")
    if sc_idx != -1:
        sc = msg[sc_idx:]
        for team in ('team0', 'team1'):
            tpat = "'{}': [".format(team)
            i = sc.find(tpat)
            if i != -1:
                start = i + len(tpat)
                # find matching closing bracket for this list
                j = start
                depth = 1
                while j < len(sc) and depth > 0:
                    if sc[j] == '[':
                        depth += 1
                    elif sc[j] == ']':
                        depth -= 1
                    j += 1
                block = sc[start:j-1]
                coords = coord_re.findall(block)
                teams[team] = [(float(x), float(y)) for x, y in coords]

    return {
        'end': int(end) if end is not None else None,
        'shot': int(shot) if shot is not None else None,
        'total': int(total) if total is not None else None,
        'next_team': next_team,
        'tv': tv,
        'av': av,
        'sa': sa,
        'teams': teams,
    }


def tee_distance(pt, tee=TEE):
    return hypot(pt[0]-tee[0], pt[1]-tee[1])


def find_no1_no2(all_stones):
    # all_stones: list of (team, x, y)
    if not all_stones:
        return (None, None)
    sorted_st = sorted(all_stones, key=lambda s: tee_distance((s[1], s[2])))
    no1 = sorted_st[0]
    no2 = sorted_st[1] if len(sorted_st) > 1 else None
    return (no1, no2)


def main():
    if len(sys.argv) > 1:
        infile = sys.argv[1]
    else:
        infile = 'c:/Users/michi/DigitalCurling4-ClientTemplate/src/standard/standard02/logs/dc4_team1_20260225_144540.jsonl'

    outcsv = infile.replace('.jsonl', '_16th_correlation.csv')

    rows = []
    with open(infile, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msg = obj.get('message', '')
            parsed = parse_message(msg)
            if parsed['total'] == 15:
                # collect stones as (team, x, y)
                all_stones = []
                for t in ('team0', 'team1'):
                    for x, y in parsed['teams'].get(t, []):
                        all_stones.append((t, x, y))
                no1, no2 = find_no1_no2(all_stones)
                team0_coords = ';'.join([f"{x:.3f}:{y:.3f}" for x, y in parsed['teams'].get('team0', [])])
                team1_coords = ';'.join([f"{x:.3f}:{y:.3f}" for x, y in parsed['teams'].get('team1', [])])
                row = {
                    'timestamp': obj.get('timestamp'),
                    'end': parsed['end'],
                    'shot': parsed['shot'],
                    'total': parsed['total'],
                    'next_team': parsed['next_team'],
                    'tv': parsed['tv'],
                    'av': parsed['av'],
                    'sa': parsed['sa'],
                    'no1_team': no1[0] if no1 else '',
                    'no1_x': (f"{no1[1]:.6f}" if no1 else ''),
                    'no1_y': (f"{no1[2]:.6f}" if no1 else ''),
                    'no1_dist': (f"{tee_distance((no1[1], no1[2])):.6f}" if no1 else ''),
                    'no2_team': no2[0] if no2 else '',
                    'no2_x': (f"{no2[1]:.6f}" if no2 else ''),
                    'no2_y': (f"{no2[2]:.6f}" if no2 else ''),
                    'no2_dist': (f"{tee_distance((no2[1], no2[2])):.6f}" if no2 else ''),
                    'team0_coords': team0_coords,
                    'team1_coords': team1_coords,
                }
                rows.append(row)

    fieldnames = ['timestamp','end','shot','total','next_team','tv','av','sa',
                  'no1_team','no1_x','no1_y','no1_dist','no2_team','no2_x','no2_y','no2_dist',
                  'team0_coords','team1_coords']
    with open(outcsv, 'w', newline='', encoding='utf-8') as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f'Wrote {len(rows)} rows to {outcsv}')


if __name__ == '__main__':
    main()
