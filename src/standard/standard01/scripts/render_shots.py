import json
import re
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

TEE_X = 0.0
TEE_Y = 38.405
# Stone physical radius (m). Keep units consistent with coordinates in the log.
STONE_R = 0.145
HOUSE_R = 1.829
HACK_X = 0.0
HACK_Y = 0.0


def parse_stone_coordinate(substr: str):
    """Parse the StoneCoordinateSchema(data=...) substring from the log line.
    Returns dict {'team0': [(x,y),...], 'team1': [(x,y),...]}"""
    # Extract the inner dict part starting from { and ending at the matching }
    # The substring given typically looks like: { 'team0': [CoordinateDataSchema(x=..., y=...), ...], 'team1': [...] }
    # Convert CoordinateDataSchema(x=.., y=..) into JSON-friendly form
    s = substr
    # Remove the prefix 'StoneCoordinateSchema(data=' if present
    s = re.sub(r"^StoneCoordinateSchema\(data=", "", s)
    # Trim trailing ) if exists
    if s.endswith(")"):
        s = s[:-1]

    # Replace CoordinateDataSchema(x=..., y=...) with {"x":..., "y":...}
    s = re.sub(r"CoordinateDataSchema\(x=([-0-9.eE]+), y=([-0-9.eE]+)\)", r'{"x":\1, "y":\2}', s)

    # Replace single quotes to double quotes for keys
    s = s.replace("'team0'", '"team0"').replace("'team1'", '"team1"')

    # Now s should be valid JSON-ish; fix Python-style True/False/None if any
    s = s.replace("None", "null")

    try:
        data = json.loads(s)
    except Exception:
        # As a fallback, try to extract all Coordinate occurrences and split in half (8/8)
        coords = re.findall(r"\(x=([-0-9.eE]+), y=([-0-9.eE]+)\)", substr)
        coords = [(float(x), float(y)) for x, y in coords]
        if len(coords) >= 16:
            team0 = coords[:8]
            team1 = coords[8:16]
        else:
            # split evenly
            mid = len(coords) // 2
            team0 = coords[:mid]
            team1 = coords[mid:]
        return {"team0": team0, "team1": team1}

    team0 = [(c["x"], c["y"]) for c in data.get("team0", []) if c.get("x") is not None]
    team1 = [(c["x"], c["y"]) for c in data.get("team1", []) if c.get("x") is not None]
    return {"team0": team0, "team1": team1}


def render_board(stones, no1_pos, outpath: Path, title: str, labels0=None, labels1=None,
                 xlim=(-3.0, 3.0), ylim=(30.0, 40.0), shot_params: str = None, shot_target=None,
                 target_rotate: bool = False):
    fig, ax = plt.subplots(figsize=(6, 8))
    ax.set_aspect('equal')
    # plotting coordinates (no global rotate)
    plot_TEE = (TEE_X, TEE_Y)
    plot_HACK = (HACK_X, HACK_Y)
    ax.add_patch(plt.Circle(plot_TEE, HOUSE_R, fill=False, color='gray', linewidth=1))

    # draw stones
    for i, (x, y) in enumerate(stones.get('team0', []), start=1):
        if x == 0 and y == 0:
            continue
        px, py = (x, y)
        circ = plt.Circle((px, py), STONE_R, color='red', ec='black')
        ax.add_patch(circ)
        lab = str(i) if not labels0 else labels0[i-1]
        ax.text(px, py, lab, color='white', ha='center', va='center', fontsize=8, weight='bold')

    for i, (x, y) in enumerate(stones.get('team1', []), start=1):
        if x == 0 and y == 0:
            continue
        px, py = (x, y)
        circ = plt.Circle((px, py), STONE_R, color='gold', ec='black')
        ax.add_patch(circ)
        lab = str(i) if not labels1 else labels1[i-1]
        ax.text(px, py, lab, color='black', ha='center', va='center', fontsize=8, weight='bold')

    # mark NO1 by drawing a small inner dot so it doesn't stick out
    if no1_pos is not None:
        nx, ny = no1_pos
        inner = plt.Circle((nx, ny), STONE_R * 0.45, fill=True, color='black', alpha=0.85)
        ax.add_patch(inner)

    # use requested fixed axes and keep stone scale consistent
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    ax.set_title(title)
    # show axes and labels
    ax.set_xlabel('X')
    ax.set_ylabel('Y')

    # create legend handles and place legend outside the plot (to the right)
    handles = [Patch(facecolor='red', edgecolor='black', label='team0'),
               Patch(facecolor='gold', edgecolor='black', label='team1'),
               Line2D([0], [0], marker='o', color='gold', markerfacecolor='none', markersize=10, linestyle='None', label='house/TEE'),
               Line2D([0], [0], marker='+', color='gold', markersize=12, linestyle='None', label='TEE'),
               Line2D([0], [0], marker='*', color='green', markersize=12, linestyle='None', label='NO1')]

    # adjust layout so legend outside fits; leave extra bottom margin for shot params
    ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1.0), borderaxespad=0.)
    fig.tight_layout(rect=(0, 0.12, 0.86, 1.0))
    outpath.parent.mkdir(parents=True, exist_ok=True)
    # if shot parameters provided, render them below the axes
    if shot_params:
        # place centered short parameters line under the figure
        fig.text(0.5, 0.04, shot_params, ha='center', va='bottom', fontsize=9)

    # if a shot target is provided, draw a dashed line from hack to target
    if shot_target is not None:
        try:
            tx, ty = shot_target
            # map target to plotting coordinates when requested (swap X/Y only for marker)
            ptx, pty = (tx, ty) if not target_rotate else (ty, tx)
            phx, phy = plot_HACK
            # dashed line from hack to target (draw first)
            ax.plot([phx, ptx], [phy, pty], color='blue', linestyle='--', linewidth=1.6, zorder=4)
            # draw a visible target marker: filled blue with white edge, plus a white X on top
            ax.scatter([ptx], [pty], s=600, facecolor='blue', edgecolor='white', linewidth=1.4, zorder=12)
            # outer blue ring to increase visibility
            ax.scatter([ptx], [pty], s=1000, facecolors='none', edgecolors='blue', linewidths=1.0, zorder=11)
            # white X marker on top
            ax.plot(ptx, pty, marker='x', color='white', markersize=16, zorder=13, markeredgewidth=2)
        except Exception:
            pass

    fig.savefig(outpath, dpi=150, bbox_inches='tight')
    plt.close(fig)


def find_no1(stones):
    # nearest to TEE within HOUSE_R
    best = None
    bestd = 1e9
    for team in ('team0', 'team1'):
        for x, y in stones.get(team, []):
            if x == 0 and y == 0:
                continue
            d = ((x - TEE_X)**2 + (y - TEE_Y)**2)**0.5
            if d <= 1.829 and d < bestd:
                bestd = d
                best = (x, y)
    return best


def process_log(logpath: Path, outdir: Path, target_rotate: bool = False):
    start_team_for_end = {}
    # for takeout statistics
    takeout_attempts = {"team0": 0, "team1": 0}
    takeout_success = {"team0": 0, "team1": 0}
    prev_stones = None
    with open(logpath, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            msg = rec.get('message', '')
            if 'latest_state_data:' not in msg:
                continue

            # extract end_number, total_shot_number, next_shot_team
            end_m = re.search(r'end_number=(\d+)', msg)
            total_m = re.search(r'total_shot_number=(\d+)', msg)
            next_m = re.search(r"next_shot_team='([^']*)'", msg)
            end_number = int(end_m.group(1)) if end_m else 0
            total_shot_number = int(total_m.group(1)) if total_m else 0
            next_shot_team = next_m.group(1) if next_m else None

            # track starting team for each end
            if total_shot_number == 0 and next_shot_team is not None:
                start_team_for_end[end_number] = next_shot_team

            # parse stone_coordinate
            sc_m = re.search(r'stone_coordinate=StoneCoordinateSchema\(data=(\{.*?\})\)', msg)
            stones = None
            if sc_m:
                stones = parse_stone_coordinate('StoneCoordinateSchema(data=' + sc_m.group(1) + ')')
            else:
                # fallback: try to find large substring
                sc_m2 = re.search(r'stone_coordinate=(StoneCoordinateSchema\(data=.*?\)) score=', msg)
                if sc_m2:
                    stones = parse_stone_coordinate(sc_m2.group(1))

            if stones is None:
                continue

            # only render when there is a last_move (i.e., a shot just played)
            if 'last_move=None' in msg:
                continue

            # determine shot_by using starting team for the end
            starting_team = start_team_for_end.get(end_number)
            if starting_team is None:
                # cannot determine starting team; skip
                continue
            # if total_shot_number is odd -> shot_by = starting_team
            if total_shot_number % 2 == 1:
                shot_by = starting_team
            else:
                shot_by = 'team0' if starting_team == 'team1' else 'team1'

            # extract shot params (if present) before rendering
            lm = re.search(r'last_move=ShotInfoSchema\(([^)]*)\)', msg)
            shot_params = None
            if lm:
                shot_params = lm.group(1)

            # compute NO1 and render
            no1 = find_no1(stones)
            # use 1-based shot number in filenames/labels (user expectation)
            shot_num_display = total_shot_number + 1
            fname = f"{end_number+1}_{shot_num_display}_{shot_by}.png"
            outpath = outdir / fname
            title = f"End {end_number+1} Shot {shot_num_display} by {shot_by}"
            # try to extract chosen target from the message text (client debug line "target=(x, y)")
            tgt_m = re.search(r'target=\(\s*([\-0-9.eE]+)\s*,\s*([\-0-9.eE]+)\s*\)', msg)
            shot_target = None
            if tgt_m:
                try:
                    shot_target = (float(tgt_m.group(1)), float(tgt_m.group(2)))
                except Exception:
                    shot_target = None

            render_board(stones, no1, outpath, title, xlim=(-3.0, 3.0), ylim=(30.0, 40.0), shot_params=shot_params, shot_target=shot_target, target_rotate=target_rotate)

            # write short commentary text (include shot params if present)
            comment = f"End {end_number+1} Shot {shot_num_display} by {shot_by}\n"
            if shot_params:
                comment += shot_params + '\n'
            (outdir / (fname.replace('.png', '.txt'))).write_text(comment, encoding='utf-8')

            # --- takeout detection: compare prev_stones -> stones using shot_params ---
            if shot_params and prev_stones is not None:
                # extract numeric fields
                tv_m = re.search(r'translational_velocity=([-0-9.eE]+)', shot_params)
                av_m = re.search(r'angular_velocity=([-0-9.eE]+)', shot_params)
                tv = float(tv_m.group(1)) if tv_m else 0.0
                av = float(av_m.group(1)) if av_m else 0.0
                # heuristic: high translational velocity and near-zero angular velocity => takeout
                is_takeout = (tv >= 3.9) and (abs(av) < 1e-6)
                if is_takeout:
                    takeout_attempts[shot_by] += 1
                    opponent = 'team0' if shot_by == 'team1' else 'team1'
                    def count_in_house(st):
                        c = 0
                        for x, y in st.get(opponent, []):
                            if x == 0 and y == 0:
                                continue
                            d = ((x - TEE_X)**2 + (y - TEE_Y)**2)**0.5
                            if d <= HOUSE_R:
                                c += 1
                        return c

                    before = count_in_house(prev_stones)
                    after = count_in_house(stones)
                    if after < before:
                        takeout_success[shot_by] += 1

            prev_stones = stones

    # after processing, write takeout summary
    summary = []
    total_attempts = sum(takeout_attempts.values())
    total_success = sum(takeout_success.values())
    summary.append(f"Takeout attempts: total={total_attempts}, team0={takeout_attempts['team0']}, team1={takeout_attempts['team1']}")
    summary.append(f"Takeout successes: total={total_success}, team0={takeout_success['team0']}, team1={takeout_success['team1']}")
    total_rate = (total_success / total_attempts * 100.0) if total_attempts > 0 else 0.0
    rate0 = (takeout_success['team0'] / takeout_attempts['team0'] * 100.0) if takeout_attempts['team0'] > 0 else 0.0
    rate1 = (takeout_success['team1'] / takeout_attempts['team1'] * 100.0) if takeout_attempts['team1'] > 0 else 0.0
    summary.append(f"Success rate: total={total_rate:.1f}%, team0={rate0:.1f}%, team1={rate1:.1f}%")
    (outdir / 'takeout_summary.txt').write_text('\n'.join(summary), encoding='utf-8')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('logfile', help='path to jsonl log')
    p.add_argument('--outdir', default='rendered_shots', help='output directory')
    p.add_argument('--target-rotate', action='store_true', help='Swap X/Y for the shot target marker only')
    args = p.parse_args()
    process_log(Path(args.logfile), Path(args.outdir), target_rotate=args.target_rotate)
