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

TEE_X = 0.0
TEE_Y = 38.405
HOUSE_R = 1.829
STONE_R = 0.145

# ============================================================
# ユーティリティ
# ============================================================

def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)

def is_in_house(x, y):
    return dist(x, y, TEE_X, TEE_Y) <= HOUSE_R

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

    house_my = [s for s in my_stones if is_in_house(s["x"], s["y"])]
    house_opp = [s for s in opp_stones if is_in_house(s["x"], s["y"])]

    dangerous = None
    if house_opp:
        dangerous = min(house_opp, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))
    elif opp_stones:
        dangerous = min(opp_stones, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))

    guards = [s for s in my_stones if not is_in_house(s["x"], s["y"])]
    is_empty = len(stones) == 0

    return {
        "my": my_stones,
        "opp": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "dangerous": dangerous,
        "guards": guards,
        "is_empty": is_empty,
    }

# ============================================================
# ショット変換
# ============================================================

def convert_center_draw(board):
    """
    例1ベース：
      v = 2.20
      angle = ±0.045
      omega = ±2.8
    ガードの外側から巻き込む
    """

    v = 2.20
    omega = 2.8
    angle = 0.045

    guards = board["guards"]

    if guards:
        avg_x = sum(g["x"] for g in guards) / len(guards)
        sign = 1.0 if avg_x >= 0 else -1.0
        angle *= sign

        avg_dist = sum(dist(g["x"], g["y"], TEE_X, TEE_Y) for g in guards) / len(guards)
        if avg_dist < 6.0:
            v -= 0.15
            angle *= 1.2

    v = max(1.8, min(2.4, v))
    angle = max(-0.12, min(0.12, angle))

    return v, angle, omega

def convert_takeout(tx, ty):
    d = dist(tx, ty, TEE_X, TEE_Y)
    v = 3.2 + d / 40.0
    angle = math.atan2(tx, ty)
    omega = 0.5
    return v, angle, omega

def convert_guard():
    return 2.30, 0.0, math.pi / 2

# ============================================================
# 戦略選択
# ============================================================

def choose_shot(board, my_team, logger):
    if board["is_empty"]:
        logger.info("End start → center draw")
        return convert_center_draw(board), "draw"

    if board["dangerous"] and is_in_house(board["dangerous"]["x"], board["dangerous"]["y"]):
        d = board["dangerous"]
        logger.info("Dangerous stone → takeout")
        return convert_takeout(d["x"], d["y"]), "takeout"

    if len(board["house_my"]) <= len(board["house_opp"]):
        logger.info("Behind in house → center draw")
        return convert_center_draw(board), "draw"

    if len(board["guards"]) < 2:
        logger.info("Building guard")
        return convert_guard(), "guard"

    logger.info("Default → center draw")
    return convert_center_draw(board), "draw"

# ============================================================
# main
# ============================================================

async def main():
    with open("../match_id.json") as f:
        match_id = json.load(f)

    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=MatchNameModel.team0,
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address("localhost", 5000)

    with open("team_config.json") as f:
        team_data = TeamModel(**json.load(f))

    logger = logging.getLogger("DC4_AI")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler())

    my_team = (await client.send_team_info(team_data)).value
    logger.info(f"I am {my_team}")

    try:
        async for state in client.receive_state_data():
            if client.get_winner_team():
                break

            if client.get_next_team() == my_team:
                board = analyze_board(state, my_team)
                (v, angle, omega), kind = choose_shot(board, my_team, logger)

                logger.info(
                    f"Shot={kind} v={v:.2f} angle={angle:.3f} omega={omega:.2f}"
                )

                await client.send_shot_info(
                    translational_velocity=v,
                    shot_angle=angle,
                    angular_velocity=omega,
                )
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        client.save_log_file()

if __name__ == "__main__":
    asyncio.run(main())
