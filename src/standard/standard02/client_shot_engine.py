import asyncio
import json
import math
import logging
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel


# ============================================================
# 基本定数
# ============================================================

TEE_Y = 38.405
HOUSE_R = 1.829
STONE_R = 0.145


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


# ============================================================
# 盤面解析
# ============================================================

def analyze_board(state, my_team):
    coord = state.stone_coordinate.data

    stones = []
    for team in ("team0", "team1"):
        for c in coord[team]:
            if c.x == 0 and c.y == 0:
                continue
            stones.append({"x": c.x, "y": c.y, "team": team})

    my_stones = [s for s in stones if s["team"] == my_team]
    opp_stones = [s for s in stones if s["team"] != my_team]

    house_my = []
    house_opp = []

    for s in stones:
        d = dist(s["x"], s["y"], 0, TEE_Y)
        if d <= HOUSE_R:
            if s["team"] == my_team:
                house_my.append(s)
            else:
                house_opp.append(s)

    shot_team = None
    shot_stone = None
    if house_my or house_opp:
        all_house = house_my + house_opp
        shot_stone = max(all_house, key=lambda s: s["y"])
        shot_team = shot_stone["team"]

    return {
        "my_stones": my_stones,
        "opp_stones": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "shot_team": shot_team,
        "shot_stone": shot_stone,
    }


# ============================================================
# ショット実装（精度重視）
# ============================================================

# ---- ガード ----

def shot_center_guard():
    return {"v": 2.27, "angle": math.radians(90), "omega": math.pi / 2}


def shot_side_guard(left=True):
    if left:
        angle = math.radians(100)
    else:
        angle = math.radians(80)
    return {"v": 2.27, "angle": angle, "omega": math.pi / 2}


# ---- ドロー ----

def shot_draw_to_button():
    return {"v": 2.39, "angle": math.radians(90), "omega": math.pi / 2}


def shot_freeze(target):
    tx, ty = target["x"], target["y"]
    angle = math.atan2(tx, ty)
    v = 2.30
    return {"v": v, "angle": angle, "omega": math.pi / 2}


# ---- テイクアウト ----

def shot_takeout(target):
    tx, ty = target["x"], target["y"]
    d = math.hypot(tx, ty)
    base_angle = math.atan2(tx, ty)

    correction = 0.045 * min(d / 40.0, 1.0)
    angle = base_angle - correction

    v = 3.2 + (d / 40.0)
    return {"v": v, "angle": angle, "omega": 0.5}


# ---- ダブルテイク（簡易版）----

def shot_double_takeout(target1, target2):
    mx = (target1["x"] + target2["x"]) / 2
    my = (target1["y"] + target2["y"]) / 2

    base_angle = math.atan2(mx, my)
    angle = base_angle - 0.03
    v = 3.8
    return {"v": v, "angle": angle, "omega": 0.5}


# ============================================================
# シンプル戦略（B戦略）
# ============================================================

def choose_strategy(board, my_team, turn_number):
    # 相手が shot stone → takeout
    if board["shot_team"] and board["shot_team"] != my_team:
        return "takeout", board["shot_stone"]

    # 序盤はガード
    if turn_number <= 2:
        return "center_guard", None

    # 中盤以降は draw
    return "draw", None


# ============================================================
# AI メイン
# ============================================================

def ai_decide_shot(state, my_team, turn_number):
    board = analyze_board(state, my_team)
    strategy, target = choose_strategy(board, my_team, turn_number)

    if strategy == "center_guard":
        return shot_center_guard()

    if strategy == "draw":
        return shot_draw_to_button()

    if strategy == "takeout":
        if target is None:
            return shot_draw_to_button()
        return shot_takeout(target)

    return shot_draw_to_button()


# ============================================================
# main()
# ============================================================

async def main():
    json_path = Path(__file__).parents[1] / "match_id.json"
    with open(json_path, "r") as f:
        match_id = json.load(f)

    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=MatchNameModel.team0,  # ← team0 で要求しても自動で team1 に振られる
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address(host="localhost", port=5000)

    with open("team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    logger = logging.getLogger("ShotEngine")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s"))
    logger.addHandler(handler)

    # ★ サーバーが team0/team1 を割り当てる → 自動認識
    match_team_name = await client.send_team_info(client_data)
    my_team = match_team_name.value
    logger.info(f"=== I AM {my_team} (Shot Engine AI) ===")

    turn_number = 0

    async for state in client.receive_state_data():
        if client.get_winner_team() is not None:
            logger.info(f"Winner: {client.get_winner_team()}")
            break

        if client.get_next_team() == my_team:
            turn_number += 1
            shot = ai_decide_shot(state, my_team, turn_number)
            logger.info(
                f"Shot #{turn_number}: v={shot['v']:.3f}, angle={shot['angle']:.3f}, omega={shot['omega']:.3f}"
            )
            await client.send_shot_info(
                translational_velocity=shot["v"],
                shot_angle=shot["angle"],
                angular_velocity=shot["omega"],
            )


if __name__ == "__main__":
    asyncio.run(main())
