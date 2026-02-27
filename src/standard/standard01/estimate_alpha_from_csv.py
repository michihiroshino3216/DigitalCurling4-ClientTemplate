import csv
import math
from pathlib import Path
import statistics

import numpy as np

CSV_PATH = Path(r"c:/Users/michi/DigitalCurling4-ClientTemplate/src/standard/standard02/analysis_outputs/dc4_team1_20260226_150129_20260226_150442/team0_shots.csv")

xs = []
ys = []

with CSV_PATH.open('r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        try:
            v = float(row['tv'])
            omega = float(row['av'])
            sa = float(row['sa_rad'])
            est_dist = float(row['est_distance'])
            final_x_model = float(row['final_x_model'])
            final_y_model = float(row['final_y_model'])
            dc_x = float(row['dc_x'])
            dc_y = float(row['dc_y'])
        except Exception:
            continue
        # delta between actual and model
        dx = dc_x - final_x_model
        dy = dc_y - final_y_model
        # shot direction unit vector: (sin, cos) because angle=atan2(vx,vy)
        ux = math.sin(sa)
        uy = math.cos(sa)
        # left perpendicular vector (points to left side)
        lx = -uy
        ly = ux
        lateral = dx * lx + dy * ly
        # predictor: omega * path_len / v
        if v == 0:
            continue
        predictor = omega * est_dist / v
        xs.append(predictor)
        ys.append(lateral)

if not xs:
    print('no valid rows')
    raise SystemExit(1)

# robust simple regression: remove NaNs and infs
xs = np.array(xs, dtype=float)
ys = np.array(ys, dtype=float)
mask = np.isfinite(xs) & np.isfinite(ys)
xs = xs[mask]
ys = ys[mask]

# linear fit y = alpha * x + b
A = np.vstack([xs, np.ones_like(xs)]).T
alpha, intercept = np.linalg.lstsq(A, ys, rcond=None)[0]

# compute R^2
yhat = alpha * xs + intercept
ss_res = ((ys - yhat) ** 2).sum()
ss_tot = ((ys - ys.mean()) ** 2).sum()
r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0.0

print('rows:', len(xs))
print('estimated alpha (slope):', alpha)
print('intercept:', intercept)
print('R^2:', r2)
print('median lateral error (m):', statistics.median(ys))
print('median predictor:', statistics.median(xs))

# show some sample pairs
print('\nsample (predictor, lateral):')
for a, b in list(zip(xs, ys))[:10]:
    print(f'{a:.4f}, {b:.4f}')
