import sys
import csv
import math

def analyze(path):
    house_y = 38.405
    house_r = 1.829
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        idx_fx = header.index('final_x_model')
        idx_fy = header.index('final_y_model')
        for row in r:
            try:
                fx = float(row[idx_fx])
                fy = float(row[idx_fy])
            except Exception:
                continue
            # mapping A: current script used dc_x=fx, dc_y=fy
            dc_x_a, dc_y_a = fx, fy
            dist_a = math.hypot(dc_x_a - 0.0, dc_y_a - house_y)
            # mapping B: swap axes: dc_x=fy, dc_y=fx
            dc_x_b, dc_y_b = fy, fx
            dist_b = math.hypot(dc_x_b - 0.0, dc_y_b - house_y)
            rows.append((fx,fy,dist_a,dist_b))

    if not rows:
        print('no rows')
        return
    dists_a = [r[2] for r in rows]
    dists_b = [r[3] for r in rows]
    print('mapping A (dc_x=fx, dc_y=fy): min/mean/max =', min(dists_a), sum(dists_a)/len(dists_a), max(dists_a))
    print('mapping B (dc_x=fy, dc_y=fx): min/mean/max =', min(dists_b), sum(dists_b)/len(dists_b), max(dists_b))
    print('\nclosest 5 (B):')
    for fx,fy,da,db in sorted(rows, key=lambda x: x[3])[:5]:
        print(f'  fx={fx:.3f}, fy={fy:.3f}, distB={db:.3f}')

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv)>=2 else r'.\\standard02\\analysis_outputs\\dc4_team1_20260226_130713_20260226_133412\\team0_shots.csv'
    analyze(path)
