import json
import re
import csv
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print('usage: analyze_match.py <match_jsonl>')
    sys.exit(1)

infile = Path(sys.argv[1])
if not infile.exists():
    print('file not found:', infile)
    sys.exit(1)

outcsv = infile.with_name(infile.stem + '_shots.csv')
pattern_end = re.compile(r'end_number=(\d+)')
pattern_shot = re.compile(r'shot_number=(\d+)')
pattern_total = re.compile(r'total_shot_number=(\d+)')
pattern_next = re.compile(r"next_shot_team='([^']*)'")
pattern_last = re.compile(r'last_move=ShotInfoSchema\(([^)]*)\)')
pattern_tv = re.compile(r'translational_velocity=([\-\d\.eE]+)')
pattern_av = re.compile(r'angular_velocity=([\-\d\.eE]+)')
pattern_sa = re.compile(r'shot_angle=([\-\d\.eE]+)')

rows = []
found_16 = []
with infile.open('r', encoding='utf-8') as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get('message','')
        if 'last_move=ShotInfoSchema' not in msg:
            continue
        ts = obj.get('timestamp','')
        end_m = pattern_end.search(msg)
        shot_m = pattern_shot.search(msg)
        total_m = pattern_total.search(msg)
        next_m = pattern_next.search(msg)
        end_number = int(end_m.group(1)) if end_m else None
        shot_number = int(shot_m.group(1)) if shot_m else None
        total_shot_number = int(total_m.group(1)) if total_m else None
        next_shot_team = next_m.group(1) if next_m else ''
        last_m = pattern_last.search(msg)
        tv = av = sa = ''
        if last_m:
            inner = last_m.group(1)
            tvm = pattern_tv.search(inner)
            avm = pattern_av.search(inner)
            sam = pattern_sa.search(inner)
            tv = float(tvm.group(1)) if tvm else ''
            av = float(avm.group(1)) if avm else ''
            sa = float(sam.group(1)) if sam else ''
        rows.append({
            'timestamp': ts,
            'end_number': end_number,
            'shot_number': shot_number,
            'total_shot_number': total_shot_number,
            'next_shot_team': next_shot_team,
            'translational_velocity': tv,
            'angular_velocity': av,
            'shot_angle': sa,
        })
        if total_shot_number == 15:
            found_16.append(rows[-1])

# write CSV
with outcsv.open('w', encoding='utf-8', newline='') as ofh:
    writer = csv.DictWriter(ofh, fieldnames=['timestamp','end_number','shot_number','total_shot_number','next_shot_team','translational_velocity','angular_velocity','shot_angle'])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

print('Wrote CSV:', outcsv)

# analyze 16th shot(s)
if not found_16:
    print('No entries with total_shot_number==15 found in file.')
else:
    for entry in found_16:
        tv = entry['translational_velocity']
        av = entry['angular_velocity']
        is_max = False
        try:
            # MAX translational in client is 3.0; detect >2.9 and angular close to 0
            is_max = (tv != '' and float(tv) >= 2.9 and abs(float(av)) <= 0.1)
        except Exception:
            is_max = False
        print('16th shot entry: end', entry['end_number'], 'shot', entry['shot_number'], 'total', entry['total_shot_number'])
        print(' translational_velocity=', tv, ' angular_velocity=', av, ' -> max_mode_detected=', is_max)

print('Done')
