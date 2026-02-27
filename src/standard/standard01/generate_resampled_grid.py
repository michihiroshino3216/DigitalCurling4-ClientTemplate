import json, math
from pathlib import Path
p = Path(__file__).parent / 'grid_export_filled.json'
out = Path(__file__).parent / 'grid_resampled_0.1.json'
with p.open('r', encoding='utf-8') as f:
    data = json.load(f)
# build lookup by rounded coords
lookup = {}
coords = []
for e in data:
    key = (round(float(e['position_x']),3), round(float(e['position_y']),3))
    lookup[key] = e
    coords.append(key)

xs = []
x = -2.085
while x <= 2.085 + 1e-9:
    xs.append(round(x,3))
    x += 0.1
ys = []
y = 32.004
while y <= 40.234 + 1e-9:
    ys.append(round(y,3))
    y += 0.1

out_list = []
for yy in ys:
    for xx in xs:
        key = (xx, yy)
        if key in lookup:
            e = dict(lookup[key])
            e['position_x'] = xx
            e['position_y'] = yy
            out_list.append(e)
        else:
            best = None
            bd = 1e9
            for (px,py) in coords:
                dx = px - xx
                dy = py - yy
                d2 = dx*dx+dy*dy
                if d2 < bd:
                    bd = d2; best=(px,py)
            e = dict(lookup[best])
            e['position_x'] = xx
            e['position_y'] = yy
            out_list.append(e)

with out.open('w', encoding='utf-8') as f:
    json.dump(out_list, f, ensure_ascii=False, indent=2)
print('wrote', out, 'entries', len(out_list))
