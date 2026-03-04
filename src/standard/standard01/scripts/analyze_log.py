import re
import json
import os
import math
import argparse
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

STONE_R = 0.145
TEE_X = 0.0
TEE_Y = 38.405
HOUSE_R = 1.829

MSG_SCALAR = {
    'team0': 'team0',
    'team1': 'team1'
}

coord_pair_re = re.compile(r"CoordinateDataSchema\(x=([\-0-9\.eE]+), y=([\-0-9\.eE]+)\)")
end_shot_re = re.compile(r"end_number=(\d+).*?shot_number=(\d+).*?total_shot_number=(\d+).*?next_shot_team='(team0|team1)'")
last_move_re = re.compile(r"last_move=(ShotInfoSchema\((.*?)\))")
vel_re = re.compile(r"translational_velocity=([\-0-9\.eE]+)")


def parse_stone_data(msg: str):
    # extract substring like "stone_coordinate=StoneCoordinateSchema(data={...}) score="
    m = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=(\{.*?\})\) score=", msg)
    if not m:
        return {'team0': [], 'team1': []}
    data_str = m.group(1)
    # split team0/team1 arrays
    t0 = re.search(r"'team0': \[(.*?)\], 'team1'", data_str, re.DOTALL)
    t1 = re.search(r"'team1': \[(.*?)\]\}.*", data_str, re.DOTALL)
    def parse_list(s):
        if not s:
            return []
        return [(float(x), float(y)) for x,y in coord_pair_re.findall(s)]
    team0 = parse_list(t0.group(1)) if t0 else []
    team1 = parse_list(t1.group(1)) if t1 else []
    return {'team0': team0, 'team1': team1}


def extract_numbers(msg: str):
    m = end_shot_re.search(msg)
    if not m:
        return None
    end_number = int(m.group(1))
    shot_number = int(m.group(2))
    total_shot_number = int(m.group(3))
    next_shot_team = m.group(4)
    return end_number, shot_number, total_shot_number, next_shot_team


def extract_velocity(msg: str):
    m = vel_re.search(msg)
    if not m:
        return None
    return float(m.group(1))


def draw_board(stones, outpath, title=None):
    # stones: {'team0': [(x,y),...], 'team1': [...]} in DC coordinates
    # Fixed axis ranges requested: X axis -3.0..+3.0, Y axis 30.0..40.0
    minx, maxx = -3.0, 3.0
    miny, maxy = 30.0, 40.0

    fig, ax = plt.subplots(figsize=(8,6))
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    # ensure equal scaling on both axes so stone radius is correct visually
    ax.set_aspect('equal', adjustable='box')

    # draw house reference (TEE at (0, TEE_Y)=38.405, house radius 1.829)
    # But we just draw stones and optional house circle at y ~ 38.405
    # plot stones
    # draw stones and annotate numbers
    idx = 1
    team0_idx = 1
    team1_idx = 1
    for x,y in stones.get('team0', []):
        if x == 0 and y == 0:
            continue
        circ = Circle((x,y), STONE_R, color='red', ec='k', lw=0.5)
        ax.add_patch(circ)
        ax.text(x, y, str(team0_idx), color='white', fontsize=8, weight='bold', ha='center', va='center')
        team0_idx += 1
    for x,y in stones.get('team1', []):
        if x == 0 and y == 0:
            continue
        circ = Circle((x,y), STONE_R, color='blue', ec='k', lw=0.5)
        ax.add_patch(circ)
        ax.text(x, y, str(team1_idx), color='white', fontsize=8, weight='bold', ha='center', va='center')
        team1_idx += 1

    # draw TEE marker
    ax.plot(TEE_X, TEE_Y, marker='+', color='gold', markersize=12, markeredgewidth=2, label='TEE')
    # draw house circle for reference
    house = Circle((TEE_X, TEE_Y), HOUSE_R, fill=False, color='gold', ls='--', lw=1)
    ax.add_patch(house)

    # find NO1 (closest stone to TEE within house)
    def find_no1(stones):
        best = None
        best_d = 1e9
        for team in ('team0','team1'):
            for x,y in stones.get(team, []):
                if x == 0 and y == 0:
                    continue
                d = math.hypot(x - TEE_X, y - TEE_Y)
                if d <= HOUSE_R and d < best_d:
                    best_d = d
                    best = (x,y,team)
        return best

    no1 = find_no1(stones)
    if no1 is not None:
        nx, ny, nteam = no1
        # offset NO1 marker to sit just outside the stone so it doesn't overlap
        dx = nx - TEE_X
        dy = ny - TEE_Y
        d = math.hypot(dx, dy)
        if d == 0:
            ux, uy = 0.0, 1.0
        else:
            ux, uy = dx / d, dy / d
        offset = STONE_R + 0.03
        mx, my = nx + ux * offset, ny + uy * offset
        ax.plot(mx, my, marker='*', color='lime', markersize=10, markeredgecolor='k', label='NO1')

    # legend: create manual patches
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D
    legend_handles = [
        Patch(facecolor='red', edgecolor='k', label='team0'),
        Patch(facecolor='blue', edgecolor='k', label='team1'),
        Patch(facecolor='none', edgecolor='gold', label='house/TEE'),
        Line2D([0], [0], marker='+', color='gold', linestyle='None', markersize=8, markeredgewidth=2, label='TEE'),
        Line2D([0], [0], marker='*', color='lime', linestyle='None', markersize=10, markeredgecolor='k', label='NO1')
    ]
    ax.legend(handles=legend_handles, loc='upper right', fontsize=8)

    ax.set_xlabel('X')
    ax.set_ylabel('Y')
    if title:
        ax.set_title(title)
    plt.savefig(outpath, dpi=150, bbox_inches='tight')
    plt.close(fig)


def analyze(logpath: Path, outdir: Path, max_vel_threshold=3.9):
    outdir.mkdir(parents=True, exist_ok=True)
    lines = []
    with open(logpath, 'r', encoding='utf-8') as f:
        for ln in f:
            if not ln.strip():
                continue
            try:
                j = json.loads(ln)
            except Exception:
                continue
            msg = j.get('message','')
            if 'latest_state_data' in msg and 'stone_coordinate' in msg:
                lines.append(msg)

    # iterate and capture pre/post pairs when last_move present
    pre_state = None
    shot_index = 0
    takeout_attempts = 0
    takeout_success = 0
    shot_summaries = []
    for msg in lines:
        nums = extract_numbers(msg)
        if not nums:
            continue
        end_number, shot_number, total_shot_number, next_shot_team = nums
        vel = extract_velocity(msg)
        stones = parse_stone_data(msg)
        # detect shot event: if vel is not None -> a shot just happened and this is post-shot state
        if vel is not None:
            # shooter is opposite of next_shot_team
            shooter = 'team0' if next_shot_team == 'team1' else 'team1'
            opponent = 'team1' if shooter == 'team0' else 'team0'
            post = stones
            pre = pre_state if pre_state is not None else {'team0': [], 'team1': []}

            # save board image for post-shot
            # filename format: End_内の投目_チーム (例: 01_03_team0.png)
            fname = f"{end_number:02d}_{shot_number+1:02d}_{shooter}.png"
            outimg = outdir / fname
            title = f"End {end_number} Shot {shot_number+1} shooter={shooter} vel={vel:.3f}"
            draw_board(post, outimg, title=title)

            # takeout heuristic: high velocity attempt and opponent lost a stone (non-zero coords)
            pre_op_count = sum(1 for (x,y) in pre.get(opponent, []) if not (x==0 and y==0))
            post_op_count = sum(1 for (x,y) in post.get(opponent, []) if not (x==0 and y==0))
            attempted = vel >= max_vel_threshold
            success = attempted and (post_op_count < pre_op_count)
            if attempted:
                takeout_attempts += 1
                if success:
                    takeout_success += 1

            shot_summaries.append({
                'end': end_number,
                'shot_number': shot_number+1,
                'shooter': shooter,
                'velocity': vel,
                'attempted_takeout': attempted,
                'takeout_success': success,
                'pre_op_count': pre_op_count,
                'post_op_count': post_op_count,
                'image': str(outimg)
            })
        # update pre_state to current stones for next iteration
        pre_state = stones

    # write summary
    summary_path = outdir / 'summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump({
            'log': str(logpath),
            'total_shots': len(shot_summaries),
            'takeout_attempts': takeout_attempts,
            'takeout_success': takeout_success,
            'takeout_success_rate': (takeout_success / takeout_attempts) if takeout_attempts>0 else None,
            'shots': shot_summaries
        }, f, indent=2)
    print('Analysis complete. Outputs in', outdir)
    print('Takeout attempts:', takeout_attempts, 'success:', takeout_success,
          'rate:', (takeout_success / takeout_attempts) if takeout_attempts>0 else 'N/A')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('log', help='path to jsonl log')
    p.add_argument('--out', help='output dir', default=None)
    args = p.parse_args()
    logp = Path(args.log)
    out = Path(args.out) if args.out else logp.parent / (logp.stem + '_analysis')
    analyze(logp, out)
