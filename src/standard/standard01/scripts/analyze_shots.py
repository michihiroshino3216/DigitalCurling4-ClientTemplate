import json, re, sys, ast
from pathlib import Path

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / 'logs' / 'dc4_team1_20260225_170008.jsonl'
out_csv = log_path.with_name(log_path.stem + '.shots.csv')

shot_re = re.compile(r"last_move=ShotInfoSchema\(([^)]*)\)")
score_re = re.compile(r"score=ScoreSchema\(team0=\[([^\]]*)\], team1=\[([^\]]*)\]\)")

def extract_stone_dict(msg: str):
    key = 'stone_coordinate=StoneCoordinateSchema(data='
    i = msg.find(key)
    if i == -1:
        return None
    j = i + len(key)
    # find matching closing paren for the StoneCoordinateSchema(...)
    depth = 0
    start = j
    for idx in range(j, len(msg)):
        ch = msg[idx]
        if ch in '({[':
            depth += 1
        elif ch in ')}]':
            depth -= 1
            if depth < 0:
                end = idx
                fragment = msg[start:end]
                # replace CoordinateDataSchema(x=..., y=...) with JSON-like dict
                frag = re.sub(r"CoordinateDataSchema\\(x=([0-9\\.\\-eE+]+), y=([0-9\\.\\-eE+]+)\\)", r'{"x":\1, "y":\2}', fragment)
                frag = frag.replace("'", '"')
                try:
                    return ast.literal_eval(frag)
                except Exception:
                    return None
    return None

shots = []
prev_scores = None

with log_path.open('r', encoding='utf-8') as f:
    for line in f:
        line=line.strip()
        if not line: continue
        try:
            obj = json.loads(line)
        except Exception:
            try:
                j = line[line.index('{'):]
                obj = json.loads(j)
            except Exception:
                # fallback: operate on raw text
                obj = {'message': line, 'timestamp': None}
        msg = obj.get('message','')
        ts = obj.get('timestamp')
        m = shot_re.search(msg)
        if not m:
            continue
        parts = m.group(1)
        tv = av = sa = None
        tv_m = re.search(r"translational_velocity=([0-9\\.\\-eE+]+)", parts)
        av_m = re.search(r"angular_velocity=([0-9\\.\\-eE+]+)", parts)
        sa_m = re.search(r"shot_angle=([0-9\\.\\-eE+]+)", parts)
        if tv_m: tv = float(tv_m.group(1))
        if av_m: av = float(av_m.group(1))
        if sa_m: sa = float(sa_m.group(1))
        # determine shooter: shooter = team not equal to next_shot_team
        next_team_m = re.search(r"next_shot_team=\'? (team[01])\'?", msg)
        # fallback without space
        if not next_team_m:
            next_team_m = re.search(r"next_shot_team=\'?(team[01])\'?", msg)
        next_team = next_team_m.group(1) if next_team_m else None
        if next_team == 'team0':
            shooter = 'team1'
        elif next_team == 'team1':
            shooter = 'team0'
        else:
            shooter = 'unknown'
        # parse score cumulative if present
        scm = score_re.search(msg)
        team0_score = team1_score = None
        if scm:
            try:
                arr0 = [int(x.strip()) for x in scm.group(1).split(',') if x.strip()!='']
                arr1 = [int(x.strip()) for x in scm.group(2).split(',') if x.strip()!='']
                team0_score = arr0[-1] if arr0 else 0
                team1_score = arr1[-1] if arr1 else 0
            except Exception:
                pass
        # parse stone coordinates dict if present (improved)
        stones = {'team0': [], 'team1': []}
        st_dict = extract_stone_dict(msg)
        if st_dict:
            for t in ('team0','team1'):
                arr = st_dict.get(t, [])
                for c in arr:
                    if isinstance(c, dict) and 'x' in c and 'y' in c:
                        try:
                            stones[t].append((float(c['x']), float(c['y'])))
                        except Exception:
                            continue
        # count stones in house (y>=36)
        team0_house = sum(1 for x,y in stones['team0'] if y>=36)
        team1_house = sum(1 for x,y in stones['team1'] if y>=36)
        shots.append({'ts': ts, 'shooter': shooter, 'tv': tv, 'av': av, 'sa': sa, 'team0_house': team0_house, 'team1_house': team1_house, 'team0_score': team0_score, 'team1_score': team1_score, 'msg': msg})

# write CSV
with out_csv.open('w', encoding='utf-8') as f:
    f.write('idx,ts,shooter,tv,av,sa,team0_house,team1_house,team0_score,team1_score\n')
    for i,s in enumerate(shots):
        f.write(f"{i},{s['ts'] or ''},{s['shooter']},{s['tv']},{s['av']},{s['sa']},{s['team0_house']},{s['team1_house']},{s['team0_score'] or ''},{s['team1_score'] or ''}\n")

# summarize team1
team1_shots = [s for s in shots if s['shooter']=='team1']
if not team1_shots:
    print('No shots by team1 found in log')
    sys.exit(0)

import statistics
avg_tv = statistics.mean(s['tv'] for s in team1_shots)
avg_av = statistics.mean(s['av'] for s in team1_shots)
avg_sa = statistics.mean(s['sa'] for s in team1_shots)
house_counts = sum(s['team1_house'] for s in team1_shots)
print('Team1 shots:', len(team1_shots))
print('Avg translational_velocity:', round(avg_tv,3))
print('Avg angular_velocity:', round(avg_av,3))
print('Avg shot_angle:', round(avg_sa,3))
print('Total team1 stones in house after their shots:', house_counts)
print('Detailed CSV written to', out_csv)
