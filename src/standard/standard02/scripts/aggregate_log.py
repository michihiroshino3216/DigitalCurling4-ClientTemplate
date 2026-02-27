import re
import json
import sys
import csv

def parse_line(obj):
    msg = obj.get('message','')
    ts = obj.get('timestamp')
    # only process latest_state_data lines
    if not msg.startswith('latest_state_data:'):
        return None

    # basic fields
    end_number = re.search(r'end_number=(\d+)', msg)
    shot_number = re.search(r'shot_number=(\d+)', msg)
    total_shot_number = re.search(r'total_shot_number=(\d+)', msg)
    next_shot_team = re.search(r"next_shot_team='([^']*)'", msg)

    end_number = int(end_number.group(1)) if end_number else None
    shot_number = int(shot_number.group(1)) if shot_number else None
    total_shot_number = int(total_shot_number.group(1)) if total_shot_number else None
    next_shot_team = next_shot_team.group(1) if next_shot_team else None

    # last_move
    lm = re.search(r'last_move=ShotInfoSchema\(translational_velocity=([^,]+), angular_velocity=([^,]+), shot_angle=([^\)]+)\)', msg)
    if not lm:
        return None
    v = float(lm.group(1))
    omega = float(lm.group(2))
    angle = float(lm.group(3))

    # score
    sc = re.search(r'score=ScoreSchema\(team0=\[([^\]]*)\], team1=\[([^\]]*)\]\)', msg)
    def sum_scores(s):
        if not s:
            return None
        parts = [p.strip() for p in s.split(',') if p.strip()]
        return sum(int(x) for x in parts) if parts else 0
    score0 = sum_scores(sc.group(1)) if sc else None
    score1 = sum_scores(sc.group(2)) if sc else None

    # stone coords for team1
    tc = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{.*'team1': \[(.*?)\]\}\) score=", msg)
    team1_coords = []
    if tc:
        body = tc.group(1)
        # find CoordinateDataSchema(x=..., y=...)
        for m in re.finditer(r'CoordinateDataSchema\(x=([^,]+), y=([^\)]+)\)', body):
            try:
                x = float(m.group(1))
                y = float(m.group(2))
                team1_coords.append((x,y))
            except:
                continue

    # count non-zero coordinates
    nonzero = sum(1 for (x,y) in team1_coords if not (abs(x) < 1e-6 and abs(y) < 1e-6))
    first_x = team1_coords[0][0] if team1_coords else ''
    first_y = team1_coords[0][1] if team1_coords else ''

    return {
        'timestamp': ts,
        'end_number': end_number,
        'shot_number': shot_number,
        'total_shot_number': total_shot_number,
        'next_shot_team': next_shot_team,
        'translational_velocity': v,
        'angular_velocity': omega,
        'shot_angle': angle,
        'score_team0': score0,
        'score_team1': score1,
        'team1_first_x': first_x,
        'team1_first_y': first_y,
        'team1_nonzero_count': nonzero,
    }

def main():
    if len(sys.argv) < 3:
        print('Usage: aggregate_log.py <input.jsonl> <output.csv>')
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2]

    rows = []
    with open(inp, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            parsed = parse_line(obj)
            if parsed:
                rows.append(parsed)

    if not rows:
        print('No shot entries found')
        sys.exit(0)

    fieldnames = ['timestamp','end_number','shot_number','total_shot_number','next_shot_team','translational_velocity','angular_velocity','shot_angle','score_team0','score_team1','team1_first_x','team1_first_y','team1_nonzero_count']
    with open(out, 'w', encoding='utf-8', newline='') as csvf:
        writer = csv.DictWriter(csvf, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f'Wrote {len(rows)} rows to {out}')

if __name__ == '__main__':
    main()
