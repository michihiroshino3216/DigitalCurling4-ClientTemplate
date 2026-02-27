import json, re, sys, ast
from pathlib import Path

log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / 'logs' / 'dc4_team1_20260225_170008.jsonl'
out_dir = log_path.parent

def extract_stone_dict(msg: str):
    key = 'stone_coordinate=StoneCoordinateSchema(data='
    i = msg.find(key)
    if i == -1:
        return None
    start = i + len(key)
    # try to find end by looking for the sequence '}) score=' which follows the stone dict in logs
    end_marker = '}) score='
    em = msg.find(end_marker, start)
    if em == -1:
        # fallback: try to find the next closing ')' after a matching brace
        depth = 0
        end = None
        for idx in range(start, len(msg)):
            ch = msg[idx]
            if ch in '{([':
                depth += 1
            elif ch in '}])':
                depth -= 1
                if depth <= 0:
                    end = idx
                    break
        if end is None:
            return None
        fragment = msg[start:end+1]
    else:
        # take substring up to the closing '}' before ' score='
        fragment = msg[start:em+1]

    # Replace CoordinateDataSchema occurrences into JSON-like dicts using manual parser
    out = ''
    i = 0
    while True:
        idx = fragment.find('CoordinateDataSchema(', i)
        if idx == -1:
            out += fragment[i:]
            break
        out += fragment[i:idx]
        j = idx + len('CoordinateDataSchema(')
        depth = 1
        k = j
        while k < len(fragment) and depth > 0:
            if fragment[k] == '(':
                depth += 1
            elif fragment[k] == ')':
                depth -= 1
            k += 1
        inner = fragment[j:k-1]
        # inner looks like 'x=2.05, y=38.88' or similar
        parts = inner.split(',')
        x_val = y_val = None
        for part in parts:
            part = part.strip()
            if part.startswith('x='):
                x_val = part[2:]
            elif part.startswith('y='):
                y_val = part[2:]
        if x_val is None or y_val is None:
            out += fragment[idx:k]
        else:
            out += '{"x":' + x_val + ', "y":' + y_val + '}'
        i = k

    # Normalize team keys and single quotes
    out = out.replace("'team0'", '"team0"').replace("'team1'", '"team1"')
    out = out.replace("'", '"')
    try:
        return ast.literal_eval(out)
    except Exception:
        return None

end_re = re.compile(r"end_number=([0-9]+)")

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
                msg = line; ts = None
        m = end_re.search(msg)
        if not m:
            continue
        end_num = int(m.group(1))
        st = extract_stone_dict(msg)
        if st:
            last_for_end[end_num] = {'stones': st, 'ts': ts}

# write per-end CSV and simple text map
for e in sorted(last_for_end.keys()):
    st = last_for_end[e]['stones']
    ts = last_for_end[e]['ts']
    csvp = out_dir / f"end_{e}_stones.csv"
    with csvp.open('w', encoding='utf-8') as cf:
        cf.write('team,x,y\n')
        for t in ('team0','team1'):
            for c in st.get(t, []):
                if isinstance(c, dict) and 'x' in c and 'y' in c:
                    cf.write(f"{t},{c['x']},{c['y']}\n")
    # simple ASCII map: bucketize x (-3..3) and y (30..40) into 9x9 grid
    grid = [['.' for _ in range(19)] for _ in range(19)]
    def to_idx(x,y):
        # rink center x ~0, y ~38; map x:-3..3 -> 0..18, y:30..46 -> 0..18
        xi = int(round((x + 3) / 6 * 18))
        yi = int(round((y - 30) / 16 * 18))
        xi = max(0, min(18, xi)); yi = max(0, min(18, yi))
        return xi, 18-yi
    for t,ch in (('team0','0'),('team1','1')):
        for c in st.get(t, []):
            if isinstance(c, dict) and 'x' in c and 'y' in c:
                xi, yi = to_idx(float(c['x']), float(c['y']))
                grid[yi][xi] = ch
    txtp = out_dir / f"end_{e}_map.txt"
    with txtp.open('w', encoding='utf-8') as tf:
        tf.write(f"End {e} (ts={ts})\n")
        for row in grid:
            tf.write(''.join(row) + '\n')

print('Wrote', len(last_for_end), 'end maps and CSVs to', out_dir)
