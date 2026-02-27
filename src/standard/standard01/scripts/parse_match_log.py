import json
import sys
from pathlib import Path

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / 'logs' / 'dc4_team1_20260225_170008.jsonl'

ends = {}
start_info = {}
last_state_for_end = {}

with log_path.open('r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            # try to extract json part after logger fields
            try:
                j = line[line.index('{'):]
                obj = json.loads(j)
            except Exception:
                continue
        # message field contains structured repr; try to parse end_number and score by searching
        msg = obj.get('message','')
        # quick parse for patterns like "end_number=1 shot_number=0"
        def find_val(s, key):
            i = s.find(key + '=')
            if i == -1:
                return None
            j = i + len(key) + 1
            # read until space or comma or )
            buf = ''
            while j < len(s) and s[j] not in [',', ' ', ')', '\\n']:
                buf += s[j]
                j += 1
            return buf
        end_num_s = find_val(msg, 'end_number')
        shot_num_s = find_val(msg, 'shot_number')
        next_shot_team = find_val(msg, "next_shot_team")
        # score arrays appear as score=ScoreSchema(team0=[...], team1=[...])
        score = None
        if 'score=ScoreSchema' in msg:
            try:
                sc_part = msg[msg.index('score=ScoreSchema')+len('score=ScoreSchema'):]
                # naive extract between 'score=ScoreSchema(' and final ')'
                if sc_part.startswith('('):
                    sc_text = sc_part[1:]
                    # attempt to find matching ) by searching last ) in the line
                    if sc_text.endswith(')'):
                        sc_text = sc_text[:-1]
                    # now find team0 and team1 arrays
                    t0_i = sc_text.find('team0=')
                    t1_i = sc_text.find('team1=')
                    if t0_i != -1 and t1_i != -1:
                        t0_txt = sc_text[t0_i+len('team0='):t1_i].strip().rstrip(',')
                        t1_txt = sc_text[t1_i+len('team1='):].strip().rstrip(')')
                        # eval arrays safely
                        team0 = eval(t0_txt)
                        team1 = eval(t1_txt)
                        score = {'team0': team0, 'team1': team1}
            except Exception:
                score = None
        # stone coordinates appear as StoneCoordinateSchema(data={'team0': [CoordinateDataSchema(x=..., y=...), ...], 'team1': [...]})
        stones = None
        if 'stone_coordinate=StoneCoordinateSchema' in msg or 'stone_coordinate=' in msg:
            try:
                # find "stone_coordinate=StoneCoordinateSchema(data=" and then extract the python-like dict
                k = 'stone_coordinate=StoneCoordinateSchema(data='
                ki = msg.find(k)
                if ki != -1:
                    sc = msg[ki+len(k):]
                    # find matching closing ) for the StoneCoordinateSchema(...)
                    if sc.endswith(')'):
                        sc = sc[:-1]
                    # replace CoordinateDataSchema(x=..., y=...) with dict
                    sc = sc.replace('CoordinateDataSchema', '')
                    sc = sc.replace('CoordinateDataSchema', '')
                    sc = sc.replace("x=", '"x":')
                    sc = sc.replace("y=", '"y":')
                    sc = sc.replace('(', '{').replace(')', '}')
                    sc = sc.replace("'", '"')
                    # crude eval
                    stones = eval(sc)
            except Exception:
                stones = None
        # now record
        try:
            end_num = int(end_num_s) if end_num_s is not None else None
        except Exception:
            end_num = None
        try:
            shot_num = int(shot_num_s) if shot_num_s is not None else None
        except Exception:
            shot_num = None
        if end_num is not None:
            # store first occurrence of start of end
            if end_num not in start_info and shot_num == 0:
                start_info[end_num] = {'first_shot_team': next_shot_team.strip("'\"") if next_shot_team else None, 'ts': obj.get('timestamp')}
            # update last observed state for this end
            if stones is not None:
                last_state_for_end[end_num] = {'stones': stones, 'score': score, 'ts': obj.get('timestamp')}
            elif score is not None:
                last_state_for_end[end_num] = {'stones': None, 'score': score, 'ts': obj.get('timestamp')}

# compile per-end summary for ends that have score info
ends_sorted = sorted(last_state_for_end.keys())
summary = []
for e in ends_sorted:
    st = last_state_for_end[e]
    score = st.get('score')
    team0_pt = None
    team1_pt = None
    if score:
        # cumulative arrays
        try:
            team0_pt = score['team0'][e-1]
            team1_pt = score['team1'][e-1]
        except Exception:
            # fallback: compute difference if previous end exists
            team0_pt = score['team0'][e-1] if e-1 < len(score['team0']) else None
            team1_pt = score['team1'][e-1] if e-1 < len(score['team1']) else None
    stones = st.get('stones')
    team0_house = []
    team1_house = []
    if stones and isinstance(stones, dict):
        for t in ('team0','team1'):
            arr = stones.get(t, [])
            for c in arr:
                # c may be dict-like with x and y
                try:
                    x = c.get('x') if isinstance(c, dict) else getattr(c, 'x', None)
                    y = c.get('y') if isinstance(c, dict) else getattr(c, 'y', None)
                except Exception:
                    x = None; y = None
                if x is None or y is None:
                    continue
                # simple house threshold: y >= 36
                if y >= 36:
                    if t == 'team0':
                        team0_house.append((round(x,3), round(y,3)))
                    else:
                        team1_house.append((round(x,3), round(y,3)))
    summary.append({'end': e, 'start_first': start_info.get(e,{}).get('first_shot_team'), 'team0': team0_pt, 'team1': team1_pt, 'team0_house': team0_house, 'team1_house': team1_house, 'ts': st.get('ts')})

# write csv
out_csv = log_path.with_suffix('.summary.csv')
with out_csv.open('w', encoding='utf-8') as f:
    f.write('end,start_first,team0_points,team1_points,team0_house_count,team1_house_count,team0_house_coords,team1_house_coords,ts\n')
    for r in summary:
        f.write(f"{r['end']},{r['start_first'] or ''},{r['team0'] or 0},{r['team1'] or 0},{len(r['team0_house'])},{len(r['team1_house'])},\"{r['team0_house']}\",\"{r['team1_house']}\",{r['ts']}\n")

# print human-readable report
print('Match summary for', log_path.name)
for r in summary:
    print(f"End {r['end']}: starter={r['start_first']}, score {r['team0']}-{r['team1']}, stones in house: team0={len(r['team0_house'])}, team1={len(r['team1_house'])} (coords shown)")
    if r['team0_house']:
        print('  team0 coords:', r['team0_house'])
    if r['team1_house']:
        print('  team1 coords:', r['team1_house'])

print('\nCSV written to', out_csv)
