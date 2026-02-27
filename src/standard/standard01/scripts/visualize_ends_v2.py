import json, re, sys, ast
from pathlib import Path

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / 'logs' / 'dc4_team1_20260225_170008.jsonl'
out_dir = log_path.parent
key = 'stone_coordinate=StoneCoordinateSchema(data='
end_marker = '}) score='
team_pattern = re.compile(r"'team0':\s*\[(.*?)\],\s*'team1':\s*\[(.*?)\]\}\)", re.S)
coord_pattern = re.compile(r"CoordinateDataSchema\(x=([0-9eE+\-\.]+),\s*y=([0-9eE+\-\.]+)\)")

last_for_end = {}
with log_path.open('r', encoding='utf-8') as f:
    for line in f:
        line=line.strip()
        if not line: continue
        try:
            obj = json.loads(line)
            msg = obj.get('message','')
            ts = obj.get('timestamp')
        except Exception:
            try:
                j = line[line.index('{'):]
                obj = json.loads(j)
                msg = obj.get('message','')
                ts = obj.get('timestamp')
            except Exception:
                continue
        if key not in msg:
            continue
        start = msg.find(key) + len(key)
        em = msg.find(end_marker, start)
        if em == -1:
            # try to find trailing '})' manually
            em2 = msg.find('})', start)
            if em2 == -1:
                continue
            fragment = msg[start:em2+2]
        else:
            fragment = msg[start:em+1]
        # search for team lists
        m = team_pattern.search(fragment)
        if not m:
            # fallback: try separate team captures
            t0 = re.search(r"'team0':\s*\[(.*?)\]", fragment, re.S)
            t1 = re.search(r"'team1':\s*\[(.*?)\]", fragment, re.S)
            if not (t0 and t1):
                continue
            team0_text = t0.group(1)
            team1_text = t1.group(1)
        else:
            team0_text = m.group(1)
            team1_text = m.group(2)
        team0_coords = coord_pattern.findall(team0_text)
        team1_coords = coord_pattern.findall(team1_text)
        # convert to list of dicts
        def to_list(lst):
            out = []
            for x,y in lst:
                try:
                    out.append({'x': float(x), 'y': float(y)})
                except:
                    pass
            return out
        st = {'team0': to_list(team0_coords), 'team1': to_list(team1_coords)}
        # find end_number if present
        en = 0
        er = re.search(r'end_number=([0-9]+)', msg)
        if er:
            en = int(er.group(1))
        last_for_end[en] = {'stones': st, 'ts': ts}

count = 0
for e in sorted(last_for_end.keys()):
    st = last_for_end[e]['stones']
    ts = last_for_end[e]['ts']
    if not st['team0'] and not st['team1']:
        continue
    count += 1
    csvp = out_dir / f"end_{e}_stones.csv"
    with csvp.open('w', encoding='utf-8') as cf:
        cf.write('team,x,y\n')
        for t in ('team0','team1'):
            for c in st.get(t, []):
                cf.write(f"{t},{c['x']},{c['y']}\n")
    # simple ASCII map: bucketize x (-3..3) and y (30..46) into 19x19 grid
    grid = [['.' for _ in range(19)] for _ in range(19)]
    def to_idx(x,y):
        xi = int(round((x + 3) / 6 * 18))
        yi = int(round((y - 30) / 16 * 18))
        xi = max(0, min(18, xi)); yi = max(0, min(18, yi))
        return xi, 18-yi
    for t,ch in (('team0','0'),('team1','1')):
        for c in st.get(t, []):
            xi, yi = to_idx(float(c['x']), float(c['y']))
            grid[yi][xi] = ch
    txtp = out_dir / f"end_{e}_map.txt"
    with txtp.open('w', encoding='utf-8') as tf:
        tf.write(f"End {e} (ts={ts})\n")
        for row in grid:
            tf.write(''.join(row) + '\n')

print('Wrote', count, 'end maps and CSVs to', out_dir)
