import os
import csv
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import sys


def load_hits(csv_path):
    hits = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for i,row in enumerate(r):
            if row.get('class','') == 'hit' or row.get('class','') == 'hit\n':
                traj_file = row.get('trajectory_file')
                hits.append((i, row, traj_file))
    return hits


def read_traj(traj_path):
    xs=[]
    ys=[]
    with open(traj_path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            try:
                x=float(row[0]); y=float(row[1])
            except Exception:
                continue
            xs.append(x); ys.append(y)
    return xs, ys


def to_dc(xs, ys):
    # model: x forward, y lateral -> DC: dc_x = y, dc_y = x
    return [y for y in ys], [x for x in xs]


def plot_individual(xs, ys, outpath, house_y=38.405, house_r=1.829):
    dc_x, dc_y = to_dc(xs, ys)
    plt.figure(figsize=(6,8))
    plt.plot(dc_x, dc_y, '-o', markersize=2)
    # draw house
    circle = plt.Circle((0.0, house_y), house_r, color='r', fill=False, linewidth=1)
    plt.gca().add_patch(circle)
    plt.xlabel('DC X (m)')
    plt.ylabel('DC Y (m)')
    plt.title(os.path.basename(outpath))
    plt.grid(True)
    plt.axis('equal')
    plt.savefig(outpath)
    plt.close()


def plot_overlay(all_trajs, outpath, house_y=38.405, house_r=1.829):
    plt.figure(figsize=(6,8))
    for xs,ys,label in all_trajs:
        dc_x, dc_y = to_dc(xs, ys)
        plt.plot(dc_x, dc_y, alpha=0.7)
    circle = plt.Circle((0.0, house_y), house_r, color='r', fill=False, linewidth=1)
    plt.gca().add_patch(circle)
    plt.xlabel('DC X (m)')
    plt.ylabel('DC Y (m)')
    plt.title('Overlay: hit shots')
    plt.grid(True)
    plt.axis('equal')
    plt.savefig(outpath)
    plt.close()


def main():
    csv_path = sys.argv[1] if len(sys.argv) >= 2 else r'.\\standard02\\analysis_outputs\\dc4_team1_20260227_102555_team0_20260227_102734\\team0_shots.csv'
    outdir = os.path.abspath(os.path.join(os.path.dirname(csv_path), 'hit_plots'))
    os.makedirs(outdir, exist_ok=True)
    hits = load_hits(csv_path)
    if not hits:
        print('No hit shots found in', csv_path)
        return
    all_trajs = []
    for idx, row, traj_file in hits:
        traj_path = os.path.join(os.path.dirname(csv_path), traj_file)
        if not os.path.exists(traj_path):
            traj_path = os.path.join(os.path.dirname(os.path.dirname(csv_path)), traj_file)
        xs, ys = read_traj(traj_path)
        all_trajs.append((xs, ys, f'hit_{idx:03d}'))
        outpng = os.path.join(outdir, f'hit_{idx:03d}.png')
        plot_individual(xs, ys, outpng)
    overlay_png = os.path.join(outdir, 'hit_overlay.png')
    plot_overlay([(t[0], t[1], t[2]) for t in all_trajs], overlay_png)
    print('Saved', len(all_trajs), 'hit plots to', outdir)


if __name__ == '__main__':
    main()
