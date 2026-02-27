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
STONE_R = 0.145  # ストーン半径（当たり判定用）


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


# ============================================================
# カール補正モデル（B→C の橋渡し）
# ============================================================

class CurlModel:
    """
    中間版 curl 補正モデル。
    - 右回転（omega>0）→ 右に曲がる → 左に補正
    - 補正量は距離に応じて変化
    """

    def __init__(self):
        # 距離に対する補正係数（調整可能）
        self.base_correction = 0.045  # だいたい 0.03〜0.06 rad が妥当

    def correct_angle(self, base_angle, distance, omega):
        """
        base_angle: atan2(tx, ty)
        distance: ストーンまでの距離
        omega: 回転方向（正→右回転）
        """
        # 距離が遠いほど curl が大きくなる → 補正も増やす
        factor = min(distance / 40.0, 1.0)

        correction = self.base_correction * factor

        # 右回転（omega>0）なら右に曲がる → 左に補正（angle - correction）
        if omega > 0:
            return base_angle - correction
        else:
            return base_angle + correction


curl_model = CurlModel()


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
# ショットプリセット
# ============================================================

def shot_center_guard():
    return {"v": 2.27, "angle": math.radians(90), "omega": math.pi / 2}


def shot_draw():
    return {"v": 2.39, "angle": math.radians(90), "omega": math.pi / 2}


# ============================================================
# 精度向上版 TAKEOUT
# ============================================================

def shot_takeout(target):
    tx, ty = target["x"], target["y"]

    # 距離
    d = math.hypot(tx, ty)

    # 基本角度
    base_angle = math.atan2(tx, ty)

    # 回転方向（右回転）
    omega = 0.5

    # curl 補正
    corrected_angle = curl_model.correct_angle(base_angle, d, omega)

    # 距離に応じて速度調整
    v = 3.2 + (d / 40.0)  # 3.2〜3.5 程度

    return {"v": v, "angle": corrected_angle, "omega": omega}


# ============================================================
# 戦略（B 完成版）
# ============================================================

def choose_strategy(board, my_team, turn_number, state):
    # 先手 team0 の第1エンドだけ特別処理
    if my_team == "team0" and state.end_number == 0:
        if state.shot_number == 0:
            return "center_guard", None
        if state.shot_number == 2:
            return "draw", None

    # 相手が shot stone → テイクアウト
    if board["shot_team"] and board["shot_team"] != my_team:
        return "takeout", board["shot_stone"]

    # 序盤はガード
    if turn_number <= 4:
        return "center_guard", None

    # 自分が shot stone → ドロー
    if board["shot_team"] == my_team:
        return "draw", None

    return "draw", None


# ============================================================
# AI メイン
# ============================================================

def ai_decide_shot(state, my_team, turn_number):
    board = analyze_board(state, my_team)
    strategy, target = choose_strategy(board, my_team, turn_number, state)

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
        match_team_name=MatchNameModel.team0,  # ★ここは固定でOK
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

    # ★ 自分が team0 / team1 か確定
    match_team_name = await client.send_team_info(client_data)
    my_team = match_team_name.value
    logger.info(f"=== I AM {my_team} ===")

    turn_number = 0

    try:
        async for state in client.receive_state_data():

            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            if client.get_next_team() == my_team:
                turn_number += 1

                shot = ai_decide_shot(
                    state=state,
                    my_team=my_team,
                    turn_number=turn_number,
                )

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
