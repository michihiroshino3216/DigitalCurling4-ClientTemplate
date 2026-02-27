import json
import re
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print('usage: check_hammer_rule.py <match_jsonl>')
    sys.exit(1)

p = Path(sys.argv[1])
if not p.exists():
    print('file not found', p)
    sys.exit(1)

score_pattern = re.compile(r'score=ScoreSchema\(team0=\[([^\]]*)\], team1=\[([^\]]*)\]\)')
end_pattern = re.compile(r'end_number=(\d+)')
shot_pattern = re.compile(r'shot_number=(\d+)')
next_pattern = re.compile(r"next_shot_team='([^']*)'")

# store latest score arrays per message
start_messages = {}
with p.open('r', encoding='utf-8') as fh:
    for line in fh:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get('message','')
        if 'score=ScoreSchema' not in msg:
            continue
        end_m = end_pattern.search(msg)
        shot_m = shot_pattern.search(msg)
        next_m = next_pattern.search(msg)
        end = int(end_m.group(1)) if end_m else None
        shot = int(shot_m.group(1)) if shot_m else None
        next_shot = next_m.group(1) if next_m else None
        sc_m = score_pattern.search(msg)
        if not sc_m:
            continue
        team0_arr = [int(x.strip()) for x in sc_m.group(1).split(',') if x.strip()!='']
        team1_arr = [int(x.strip()) for x in sc_m.group(2).split(',') if x.strip()!='']
        # record the message at the start of an end (shot==0)
        if shot == 0:
            start_messages[end] = {'next_shot_team': next_shot, 'team0': team0_arr, 'team1': team1_arr, 'timestamp': obj.get('timestamp','')}

# Now for each end E, find the start message for end E+1 to read cumulative after end E
results = []
ends = sorted(start_messages.keys())
for e in ends:
    # we will evaluate scoring for end e using start of end e+1
    after = start_messages.get(e+1)
    if not after:
        continue
    team0_arr = after['team0']
    team1_arr = after['team1']
    def val_at(arr, idx):
        if idx < 0:
            return 0
        if idx < len(arr):
            return arr[idx]
        return arr[-1] if arr else 0
    cum0 = val_at(team0_arr, e)
    cum1 = val_at(team1_arr, e)
    prev0 = val_at(team0_arr, e-1)
    prev1 = val_at(team1_arr, e-1)
    scored0 = cum0 - prev0
    scored1 = cum1 - prev1
    if scored0 > scored1:
        scorer = 'team0'
    elif scored1 > scored0:
        scorer = 'team1'
    else:
        scorer = None
    next_shot = after['next_shot_team']
    ok = None
    if scorer is not None:
        ok = (next_shot == scorer)
    results.append({'end': e, 'scored0': scored0, 'scored1': scored1, 'scorer': scorer, 'next_shot_start_end_plus1': next_shot, 'rule_holds': ok})

# Print concise report
for r in results:
    if r['scorer']:
        print(f"End {r['end']}: scored team0={r['scored0']} team1={r['scored1']} -> scorer={r['scorer']} | start of end {r['end']+1} first_shot={r['next_shot_start_end_plus1']} | rule_holds={r['rule_holds']}")
    else:
        print(f"End {r['end']}: scored team0={r['scored0']} team1={r['scored1']} -> tie/blank | start of end {r['end']+1} first_shot={r['next_shot_start_end_plus1']} | rule_holds=unknown")

# Summarize overall
ok_count = sum(1 for r in results if r['rule_holds'] is True)
total_checked = sum(1 for r in results if r['rule_holds'] is not None)
print('\nSummary: rule held for {}/{} checked ends'.format(ok_count, total_checked))
