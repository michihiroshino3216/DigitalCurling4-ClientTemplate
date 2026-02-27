import sys
import csv
import math

def main():
    path = sys.argv[1] if len(sys.argv) >= 2 else r'.\\standard02\\analysis_outputs\\dc4_team1_20260227_102555_team0_20260227_102734\\team0_shots.csv'
    house_y = 38.405
    house_r = 1.829
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        idx_dc_x = header.index('dc_x')
        idx_dc_y = header.index('dc_y')
        idx_in = header.index('in_house')
        for row in r:
            try:
                dc_x = float(row[idx_dc_x])
                dc_y = float(row[idx_dc_y])
                in_house = int(row[idx_in])
            except Exception:
                continue
            dist = math.hypot(dc_x - 0.0, dc_y - house_y)
            rows.append((dc_x, dc_y, in_house, dist, row))

    if not rows:
        print('no rows')
        return

    total = len(rows)
    in_count = sum(1 for r in rows if r[2]==1)
    dists = [r[3] for r in rows]
    mind = min(dists)
    maxd = max(dists)
    avg = sum(dists)/len(dists)

    print(f'total_shots: {total}')
    print(f'in_house_count: {in_count}')
    print(f'min_dist_to_house_center: {mind:.3f} m')
    print(f'mean_dist: {avg:.3f} m, max_dist: {maxd:.3f} m')
    print('\nclosest 5 shots:')
    for dc_x,dc_y,in_house,dist,row in sorted(rows, key=lambda x: x[3])[:5]:
        print(f'  dc_x={dc_x:.3f}, dc_y={dc_y:.3f}, in_house={in_house}, dist={dist:.3f}')

if __name__ == "__main__":
    main()
