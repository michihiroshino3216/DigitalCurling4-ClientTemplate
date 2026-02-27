import asyncio
import json
import math
import logging
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel


# ============================================================
# DigitalCurling3 座標系
# ============================================================

TEE_Y = 38.405
HOUSE_R = 1.829


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


# ============================================================
# 盤面解析
# ============================================================

def analyze_board(state, my_team_name: str):
    coord = state.stone_coordinate.data  # {'team0': [...], 'team1': [...]}

    stones = []
    for team in ("team0", "team1"):
        for c in coord[team]:
            if c.x == 0.0 and c.y == 0.0:
                continue
            stones.append({"x": c.x, "y": c.y, "team": team})

    my_stones = [s for s in stones if s["team"] == my_team_name]
    opp_stones = [s for s in stones if s["team"] != my_team_name]

    house_my = [s for s in my_stones if dist(s["x"], s["y"], 0, TEE_Y) <= HOUSE_R]
    house_opp = [s for s in opp_stones if dist(s["x"], s["y"], 0, TEE_Y) <= HOUSE_R]

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
# ショットプリセット
# ============================================================

def shot_center_guard():
    return {"v": 2.27, "angle": math.radians(90), "omega": math.pi / 2}


def shot_draw():
    return {"v": 2.39, "angle": math.radians(90), "omega": math.pi / 2}


def shot_takeout(target):
    angle = math.atan2(target["x"], target["y"])
    return {"v": 3.40, "angle": angle, "omega": 0.5}


# ============================================================
# 戦略
# ============================================================

def choose_strategy(board, my_team_name: str, turn_number: int, state):
    # 先手 team0 の第1エンドだけ特別ルール
    if my_team_name == "team0" and state.end_number == 0:
        if state.shot_number == 0:
            return "center_guard", None
        if state.shot_number == 2:
            return "draw", None

    # 通常ロジック
    if board["shot_team"] and board["shot_team"] != my_team_name:
        return "takeout", board["shot_stone"]

    if turn_number <= 4:
        return "center_guard", None

    return "draw", None


# ============================================================
# AI メイン
# ============================================================

def ai_decide_shot(state, my_team_name, turn_number):
    board = analyze_board(state, my_team_name)
    strategy, target = choose_strategy(board, my_team_name, turn_number, state)

    if strategy == "center_guard":
        return shot_center_guard()
    if strategy == "draw":
        return shot_draw()
    if strategy == "takeout":
        return shot_takeout(target)

    return shot_draw()


# ============================================================
# DigitalCurling4 main()
# ============================================================

formatter = logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")


async def main():
    json_path = Path(__file__).parents[1] / "match_id.json"
    with open(json_path, "r") as f:
        match_id = json.load(f)

    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=MatchNameModel.team0,
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address(host="localhost", port=5000)

    with open("team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    logger = logging.getLogger("SampleClient")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # ★ ここで team0 / team1 が確定する
    match_team_name: MatchNameModel = await client.send_team_info(client_data)
    my_team_name = match_team_name.value  # 'team0' or 'team1'
    logger.info(f"=== I am {my_team_name} ===")

    turn_number = 0

    try:
        async for state in client.receive_state_data():

            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            next_team = client.get_next_team()

            if next_team == my_team_name:
                turn_number += 1

                shot = ai_decide_shot(
                    state=state,
                    my_team_name=my_team_name,
                    turn_number=turn_number,
                )

                await client.send_shot_info(
                    translational_velocity=shot["v"],
                    shot_angle=shot["angle"],
                    angular_velocity=shot["omega"],
                )

    except Exception as e:
        client.logger.error(f"Unexpected error in main loop: {e}")

    finally:
        client.save_log_file()


if __name__ == "__main__":
    asyncio.run(main())
