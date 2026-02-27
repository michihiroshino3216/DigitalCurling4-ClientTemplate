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
# ショット実装（物理強化版）
# ============================================================

# ---- ガード ----
def shot_center_guard():
    return {"v": 2.27, "angle": math.radians(90), "omega": math.pi / 2}


# ---- ドロー（ボタン）----
def shot_draw_to_button():
    return {"v": 2.39, "angle": math.radians(90), "omega": math.pi / 2}


# ---- フリーズ（相手石の前にピタッと止める）----
def shot_freeze(target):
    tx, ty = target["x"], target["y"]

    # 目標は相手石の 30cm 手前
    dy = ty - 0.30
    dx = tx

    angle = math.atan2(dx, dy)
    v = 2.33  # draw より少し弱め
    return {"v": v, "angle": angle, "omega": math.pi / 2}


# ---- テイクアウト（物理強化版）----
def shot_takeout(target):
    tx, ty = target["x"], target["y"]
    d = math.hypot(tx, ty)

    base_angle = math.atan2(tx, ty)

    # A の物理モデル：距離依存の補正
    correction = 0.045 * min(d / 40.0, 1.0)
    angle = base_angle - correction

    # 距離依存の速度
    v = 3.2 + (d / 40.0)

    return {"v": v, "angle": angle, "omega": 0.5}


# ============================================================
# B の戦略ロジック（強化版）
# ============================================================

def choose_strategy(board, my_team, turn_number):
    # ① 相手が shot stone → takeout
    if board["shot_team"] and board["shot_team"] != my_team:
        return "takeout", board["shot_stone"]

    # ② 相手の石がハウスに複数 → freeze
    if len(board["house_opp"]) >= 1:
        target = min(board["house_opp"], key=lambda s: s["y"])
        return "freeze", target

    # ③ 序盤はセンターガード
    if turn_number <= 2:
        return "center_guard", None

    # ④ それ以外はドロー
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

    if strategy == "freeze":
        return shot_freeze(target)

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
        match_team_name=MatchNameModel.team0,
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

    try:
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

    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")

    finally:
        client.save_log_file()


if __name__ == "__main__":
    asyncio.run(main())
