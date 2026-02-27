#!/usr/bin/env python3
"""Extract final stone coordinates per end from a JSONL match log.

Usage: python extract_end_final_positions.py <path/to/log.jsonl>
Writes per-end CSV and ASCII map files into the same directory as the log.
"""
import re
import sys
import os
import csv
from math import floor


COORD_RE = re.compile(r"CoordinateDataSchema\(x=([^,]+), y=([^\)]+)\)")
END_RE = re.compile(r"end_number=(\d+)")
STONE_BLOCK_RE = re.compile(r"stone_coordinate=StoneCoordinateSchema\(data=\{(?P<data>.*?)\}\)\sscore=", re.DOTALL)


def parse_coord_list(block):
    # find all CoordinateDataSchema(x=..., y=...)
    coords = []
    for m in COORD_RE.finditer(block):
        try:
            x = float(m.group(1))
            y = float(m.group(2))
        except Exception:
            x = 0.0
            y = 0.0
        coords.append((x, y))
    return coords


def parse_data_block(data_text):
    # data_text contains e.g. "'team0': [CoordinateDataSchema(...), ...], 'team1': [..]"
    # Extract team0 and team1 lists
    team0 = []
    team1 = []
    # find the part for 'team0': [ ... ]
    t0 = re.search(r"'team0'\s*:\s*\[(.*?)\]", data_text, re.DOTALL)
    t1 = re.search(r"'team1'\s*:\s*\[(.*?)\]", data_text, re.DOTALL)
    if t0:
        team0 = parse_coord_list(t0.group(1))
    if t1:
        team1 = parse_coord_list(t1.group(1))
    return {'team0': team0, 'team1': team1}


def write_csv_for_end(out_dir, base_name, end_num, stones):
    fname = os.path.join(out_dir, f"{base_name}.end_{end_num}_stones.csv")
    with open(fname, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['end', 'team', 'index', 'x', 'y'])
        for team in ('team0', 'team1'):
            lst = stones.get(team, [])
            for i, (x, y) in enumerate(lst):
                w.writerow([end_num, team, i, x, y])
    return fname


def write_ascii_map(out_dir, base_name, end_num, stones, cell_size=0.5, pad=2.0):
    # build grid bounding box from stones
    pts = []
    for t in ('team0', 'team1'):
        pts.extend(stones.get(t, []))
    # include T at (0, 38.405)
    TEE = (0.0, 38.405)
    pts.append(TEE)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx = min(xs) - pad
    maxx = max(xs) + pad
    miny = min(ys) - pad
    maxy = max(ys) + pad
    nx = max(3, int((maxx - minx) / cell_size) + 1)
    ny = max(3, int((maxy - miny) / cell_size) + 1)

    # initialize grid with dots
    grid = [['.' for _ in range(nx)] for _ in range(ny)]

    def cell_coords(x, y):
        ix = int(floor((x - minx) / cell_size))
        iy = int(floor((y - miny) / cell_size))
        return ix, iy

    # place stones: team0 -> 0, team1 -> 1
    for team, ch in (('team0', '0'), ('team1', '1')):
        for (x, y) in stones.get(team, []):
            ix, iy = cell_coords(x, y)
            if 0 <= ix < nx and 0 <= iy < ny:
                # y axis: higher y -> upper rows, we'll invert later
                if grid[iy][ix] == '.':
                    grid[iy][ix] = ch
                else:
                    grid[iy][ix] = '*'

    # mark TEE
    tx, ty = TEE
    ix, iy = cell_coords(tx, ty)
    if 0 <= ix < nx and 0 <= iy < ny:
        grid[iy][ix] = 'T'

    # write text with y descending
    fname = os.path.join(out_dir, f"{base_name}.end_{end_num}_map.txt")
    with open(fname, 'w', encoding='utf-8') as f:
        for row in reversed(grid):
            f.write(''.join(row) + '\n')
    return fname


def main():
    if len(sys.argv) < 2:
        print("Usage: extract_end_final_positions.py <log.jsonl>")
        sys.exit(1)
    infile = sys.argv[1]
    out_dir = os.path.dirname(infile) or '.'
    base_name = os.path.splitext(os.path.basename(infile))[0]

    last_by_end = {}

    with open(infile, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # extract end_number
            m = END_RE.search(line)
            if not m:
                continue
            end_num = int(m.group(1))
            # extract stone block
            sb = STONE_BLOCK_RE.search(line)
            if not sb:
                # maybe the line uses slightly different spacing; try a looser match
                sb2 = re.search(r"stone_coordinate=StoneCoordinateSchema\(data=\{(.*?)\}\)", line)
                if sb2:
                    data_text = sb2.group(1)
                else:
                    continue
            else:
                data_text = sb.group('data')

            stones = parse_data_block(data_text)
            # store last seen for this end
            last_by_end[end_num] = stones

    if not last_by_end:
        print("No stone_coordinate blocks found in file.")
        sys.exit(1)

    written = []
    for end in sorted(last_by_end.keys()):
        stones = last_by_end[end]
        csvf = write_csv_for_end(out_dir, base_name, end, stones)
        mapf = write_ascii_map(out_dir, base_name, end, stones)
        written.append((end, csvf, mapf))

    for end, c, m in written:
        print(f"Wrote end {end}: {c}, {m}")


if __name__ == '__main__':
    main()
