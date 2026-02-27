import re
import json
from datetime import datetime

DEBUG_LOG = "standard01/logs/sample_client_no1_grid_debug.log"
MATCH_LOG = "standard01/logs/dc4_team0_20260225_101139.jsonl"

ts_fmt_debug = "%Y-%m-%d %H:%M:%S,%f"

# parse debug log into list of entries
debug_entries = []
with open(DEBUG_LOG, encoding='utf-8') as f:
    lines = [l.rstrip('\n') for l in f]

i = 0
while i < len(lines):
    line = lines[i]
    m_info = re.search(r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*INFO - Shot (?P<shot>\d+): target=\((?P<tx>[-0-9.]+), (?P<ty>[-0-9.]+)\)(?P<rest>.*)$", line)
    if m_info:
        ts = datetime.strptime(m_info.group('ts'), ts_fmt_debug)
        shot = int(m_info.group('shot'))
        tx = float(m_info.group('tx'))
        ty = float(m_info.group('ty'))
        # next line should be DEBUG with details
        entry = {'ts': ts, 'shot': shot, 'tx': tx, 'ty': ty, 'matched_entry': None, 'v': None, 'angle': None, 'omega': None}
        if i+1 < len(lines):
            dbg = lines[i+1]
            m_dbg = re.search(r"DEBUG - Chosen shot details: .*matched_entry=(?P<me>\{.*\}) v=(?P<v>[-0-9.]+) angle=(?P<angle>[-0-9.]+) omega=(?P<omega>[-0-9.]+)$", dbg)
            if m_dbg:
                # matched_entry is a Python-like dict; convert single quotes to double for json
                me = m_dbg.group('me')
                try:
                    me_json = json.loads(me.replace("'", '"'))
                except Exception:
                    me_json = {'raw': me}
                entry['matched_entry'] = me_json
                entry['v'] = float(m_dbg.group('v'))
                entry['angle'] = float(m_dbg.group('angle'))
                entry['omega'] = float(m_dbg.group('omega'))
            i += 2
            debug_entries.append(entry)
            continue
    i += 1

# parse match log snapshots
match_snapshots = []
with open(MATCH_LOG, encoding='utf-8') as f:
    for raw in f:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        # parse ISO timestamp
        ts = None
        if 'timestamp' in obj:
            try:
                ts = datetime.fromisoformat(obj['timestamp'])
            except Exception:
                pass
        message = obj.get('message','')
        # extract stone_coordinate team0 and team1 coordinate lists
        team0 = []
        team1 = []
        m_sc = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{\\'team0\\': \[(?P<t0>.*?)\], \\'team1\\': \[(?P<t1>.*?)\]\}\)", message)
        # fallback generic pattern: find all CoordinateDataSchema(x=..., y=...)
        if m_sc:
            t0s = m_sc.group('t0')
            t1s = m_sc.group('t1')
            coords0 = re.findall(r"CoordinateDataSchema\(x=(?P<x>[-0-9.eE]+), y=(?P<y>[-0-9.eE]+)\)", t0s)
            coords1 = re.findall(r"CoordinateDataSchema\(x=(?P<x>[-0-9.eE]+), y=(?P<y>[-0-9.eE]+)\)", t1s)
        else:
            coords0 = re.findall(r"stone_coordinate=StoneCoordinateSchema\(data=.*?\\'team0\\': \[(.*?)\]", message)
            # generic all coords
            coords0 = re.findall(r"CoordinateDataSchema\(x=(?P<x>[-0-9.eE]+), y=(?P<y>[-0-9.eE]+)\)", message)
            # Not ideal; we'll split half to team1 if count==16
            if len(coords0) == 16:
                coords0_raw = coords0
                coords0 = coords0_raw[:8]
                coords1 = coords0_raw[8:]
                coords0 = [(float(x), float(y)) for x,y in coords0]
                coords1 = [(float(x), float(y)) for x,y in coords1]
            else:
                # best-effort: try to extract team1 separately
                coords1 = re.findall(r"\\'team1\\': \[(?P<t1>.*?)\]", message)
                if coords1:
                    coords1 = re.findall(r"CoordinateDataSchema\(x=(?P<x>[-0-9.eE]+), y=(?P<y>[-0-9.eE]+)\)", coords1[0])
                    coords0 = re.findall(r"\\'team0\\': \[(?P<t0>.*?)\]", message)
                    if coords0:
                        coords0 = re.findall(r"CoordinateDataSchema\(x=(?P<x>[-0-9.eE]+), y=(?P<y>[-0-9.eE]+)\)", coords0[0])
                else:
                    coords0 = []
                    coords1 = []
        # normalize
        if isinstance(coords0, list) and coords0 and isinstance(coords0[0], tuple):
            team0 = [(float(x), float(y)) for x,y in coords0]
        elif isinstance(coords0, list) and coords0 and isinstance(coords0[0], str):
            # handled above
            team0 = [(float(x), float(y)) for x,y in coords0]
        if isinstance(coords1, list) and coords1 and isinstance(coords1[0], tuple):
            team1 = [(float(x), float(y)) for x,y in coords1]
        elif isinstance(coords1, list) and coords1 and isinstance(coords1[0], str):
            team1 = [(float(x), float(y)) for x,y in coords1]

        match_snapshots.append({'ts': ts, 'message': message, 'team0': team0, 'team1': team1})

# helper to find snapshot index by time
def find_snapshot_after(t):
    for s in match_snapshots:
        if s['ts'] and s['ts'] >= t:
            return s
    return None

def find_snapshot_before(t):
    prev = None
    for s in match_snapshots:
        if s['ts'] and s['ts'] < t:
            prev = s
        if s['ts'] and s['ts'] >= t:
            break
    return prev

# correlate
results = []
for e in debug_entries:
    ts = e['ts']
    after = find_snapshot_after(ts)
    before = find_snapshot_before(ts)
    outcome = 'unknown'
    note = ''
    if after:
        t0_after = after['team0']
        t1_after = after['team1']
        # placed if any t0 coords non-zero
        placed = any(not (abs(x) < 1e-6 and abs(y) < 1e-6) for x,y in t0_after)
        if placed:
            outcome = '残存(Placed)'
        else:
            outcome = 'アウト/消滅(Out)'
        # detect hit: compare before and after team1 counts/positions
        if before:
            t1_before = before['team1']
            if t1_before and t1_after:
                # if any position moved >0.5m
                moved = False
                removed = False
                for bx,by in t1_before:
                    # find closest after
                    dists = [((ax-bx)**2 + (ay-by)**2)**0.5 for ax,ay in t1_after]
                    if not dists:
                        removed = True
                    else:
                        if min(dists) > 0.5:
                            moved = True
                if removed:
                    note = '相手石が消滅(Hit-removed)'
                elif moved:
                    note = '相手石が移動(Hit-moved)'
        results.append({'shot': e['shot'], 'ts': ts.isoformat(), 'tx': e['tx'], 'ty': e['ty'], 'matched_entry': e['matched_entry'], 'v': e['v'], 'angle': e['angle'], 'omega': e['omega'], 'outcome': outcome, 'note': note})
    else:
        results.append({'shot': e['shot'], 'ts': ts.isoformat(), 'tx': e['tx'], 'ty': e['ty'], 'matched_entry': e['matched_entry'], 'v': e['v'], 'angle': e['angle'], 'omega': e['omega'], 'outcome': 'no-snapshot', 'note': ''})

# print summary
print('Shot, Timestamp, Target(x,y), MatchedPos(x,y), v, angle, omega, Outcome, Note')
for r in results:
    me = r['matched_entry']
    pos = ''
    if isinstance(me, dict) and 'position_x' in me and 'position_y' in me:
        pos = f"({me['position_x']},{me['position_y']})"
    elif isinstance(me, dict) and 'raw' in me:
        pos = me['raw'][:30]
    print(f"{r['shot']}, {r['ts']}, ({r['tx']:.2f},{r['ty']:.2f}), {pos}, {r['v']:.4f}, {r['angle']:.4f}, {r['omega']:.4f}, {r['outcome']}, {r['note']}")

# write CSV
import csv
with open('standard01/logs/correlated_shots.csv','w',newline='',encoding='utf-8') as cf:
    w = csv.writer(cf)
    w.writerow(['shot','timestamp','tx','ty','matched_x','matched_y','v','angle','omega','outcome','note'])
    for r in results:
        me = r['matched_entry'] if isinstance(r['matched_entry'], dict) else {}
        w.writerow([r['shot'], r['ts'], r['tx'], r['ty'], me.get('position_x',''), me.get('position_y',''), r['v'], r['angle'], r['omega'], r['outcome'], r['note']])
print('\nWrote standard01/logs/correlated_shots.csv')
