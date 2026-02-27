import asyncio
import json
import math
import logging
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel

formatter = logging.Formatter(
    "%(asctime)s, %(name)s : %(levelname)s - %(message)s"
)

TEE_X = 0.0
TEE_Y = 38.405
HOUSE_R = 1.829
STONE_R = 0.145
HACK_X = 0.0
HACK_Y = 0.0

DRAW_V = 2.39
FREEZE_V = 2.30
HIT_V = 3.60
HIT_STAY_V = 3.00
OMEGA = math.pi / 2
HIT_OMEGA = 0.5


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


def get_no1_stone(state):
    # NO1 = ハウス内でTEEに最も近い石
    coord = state.stone_coordinate.data

    in_house = []
    for team in ("team0", "team1"):
        for c in coord[team]:
            if c.x == 0 and c.y == 0:
                continue
            if dist(c.x, c.y, TEE_X, TEE_Y) <= HOUSE_R:
                in_house.append({"x": c.x, "y": c.y, "team": team})

    if not in_house:
        return None

    return min(in_house, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))


def get_blocking_stone(state, no1):
    # ハック(0,0)とNO1を結ぶ線分上にある石を探す
    if no1 is None:
        return None

    coord = state.stone_coordinate.data
    target_x, target_y = no1["x"], no1["y"]
    line_dx = target_x - HACK_X
    line_dy = target_y - HACK_Y
    line_len_sq = (line_dx * line_dx) + (line_dy * line_dy)
    if line_len_sq == 0:
        return None

    blockers = []
    for team in ("team0", "team1"):
        for c in coord[team]:
            if c.x == 0 and c.y == 0:
                continue
            if c.x == target_x and c.y == target_y and team == no1["team"]:
                continue

            t = ((c.x - HACK_X) * line_dx + (c.y - HACK_Y) * line_dy) / line_len_sq
            if t <= 0 or t >= 1:
                continue

            proj_x = HACK_X + t * line_dx
            proj_y = HACK_Y + t * line_dy
            if dist(c.x, c.y, proj_x, proj_y) <= (2 * STONE_R):
                blockers.append({"x": c.x, "y": c.y, "team": team, "t": t})

    if not blockers:
        return None

    return min(blockers, key=lambda s: s["t"])


def get_no2_stone(state, no1):
    # NO2 = NO1に次いでTEEに近い石（ハウス内）
    if no1 is None:
        return None

    coord = state.stone_coordinate.data
    in_house = []
    for team in ("team0", "team1"):
        for c in coord[team]:
            if c.x == 0 and c.y == 0:
                continue
            if dist(c.x, c.y, TEE_X, TEE_Y) <= HOUSE_R:
                in_house.append({"x": c.x, "y": c.y, "team": team})

    if len(in_house) < 2:
        return None

    sorted_stones = sorted(in_house, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))
    if sorted_stones[0]["x"] == no1["x"] and sorted_stones[0]["y"] == no1["y"]:
        return sorted_stones[1]

    return sorted_stones[0]


def choose_target(state, my_team):
    # shot_numberは0始まりのため、+1して条件に合わせる
    shot_index = state.shot_number + 1
    no1 = get_no1_stone(state)

    if shot_index == 1:
        # 各エンドの1投目はセンタードロー
        return "draw", TEE_X, TEE_Y, no1

    if 2 <= shot_index <= 5:
        # 2-5投目はNO1があればフリーズ、なければセンター
        if no1 is None:
            return "draw", TEE_X, TEE_Y, no1
        return "freeze", no1["x"], no1["y"] - STONE_R, no1

    if 6 <= shot_index <= 15:
        # 6-15投目はNO1が自チームならフリーズ、相手なら奥2個分
        if no1 is None:
            return "draw", TEE_X, TEE_Y, no1
        # ハック- NO1 の直線上に石があれば最高速でヒット
        if (blocker := get_blocking_stone(state, no1)) is not None:
            return "hit", blocker["x"], blocker["y"], no1
        if no1["team"] == my_team:
            return "freeze", no1["x"], no1["y"] - STONE_R, no1
        return "deep", no1["x"], no1["y"] + (2 * STONE_R), no1

    if shot_index == 16:
        # 16投目の特別条件
        if no1 is None:
            # NO1なしなら全力投球で0点狙い
            return "power", TEE_X, TEE_Y, no1
        if no1["team"] == my_team:
            # 自チームNO1なら2個分手前へフリーズ
            return "freeze", no1["x"], no1["y"] - (2 * STONE_R), no1
        # 相手NO1ならブロッカーを優先してヒット
        if (blocker := get_blocking_stone(state, no1)) is not None:
            return "hit", blocker["x"], blocker["y"], no1
        # NO2があるならNO1へヒット&ステイ狙い
        if get_no2_stone(state, no1) is not None:
            return "hit_stay", no1["x"], no1["y"], no1
        # NO2がないなら全力でNO1へヒット
        return "power_hit", no1["x"], no1["y"], no1

    return "draw", TEE_X, TEE_Y, no1


def shot_to_target(kind, tx, ty):
    # 目標座標に向けた簡易パラメータ（角度のみターゲット依存）
    angle = math.atan2(tx, ty)
    if kind == "freeze":
        v = FREEZE_V
        omega = OMEGA
    elif kind == "hit":
        v = HIT_V
        omega = HIT_OMEGA
    elif kind == "hit_stay":
        v = HIT_STAY_V
        omega = HIT_OMEGA
    elif kind in ("power", "power_hit"):
        v = HIT_V
        omega = HIT_OMEGA
    else:
        v = DRAW_V
        omega = OMEGA
    return v, angle, omega


async def main():
    json_path = Path(__file__).parents[1] / "match_id.json"

    with open(json_path, "r") as f:
        match_id = json.load(f)

    # クライアント初期化
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

    logger = logging.getLogger("SampleClientNO1")
    logger.setLevel(level=logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.info(f"client_data.team_name: {client_data.team_name}")
    logger.debug(f"client_data: {client_data}")

    # チーム情報送信後、自チームが確定
    match_team_name: MatchNameModel = await client.send_team_info(client_data)
    my_team = match_team_name.value
    # 自分のチームをコンソールに表示（team0 または team1）
    logger.info(f"Assigned team: {my_team}")

    try:
        async for state_data in client.receive_state_data():
            if (winner_team := client.get_winner_team()) is not None:
                logger.info(f"Winner: {winner_team}")
                break

            next_shot_team = client.get_next_team()

            if next_shot_team == my_team:
                kind, tx, ty, no1 = choose_target(state_data, my_team)
                translational_velocity, shot_angle, angular_velocity = shot_to_target(kind, tx, ty)

                if no1 is None:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: {kind} to ({tx:.2f}, {ty:.2f}) (NO1 none)"
                    )
                else:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: {kind} to ({tx:.2f}, {ty:.2f}) "
                        f"NO1=({no1['x']:.2f}, {no1['y']:.2f}) team={no1['team']}"
                    )

                await client.send_shot_info(
                    translational_velocity=translational_velocity,
                    shot_angle=shot_angle,
                    angular_velocity=angular_velocity,
                )

    except Exception as e:
        client.logger.error(f"Unexpected error in main loop: {e}")

    finally:
        client.save_log_file()


if __name__ == "__main__":
    asyncio.run(main())
