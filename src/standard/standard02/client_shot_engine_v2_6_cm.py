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
    極端カーブ維持 + ハウス到達狙い（安全化版）

    方針:
    - 基本は極端さを保ちつつ盤外リスクを抑える
    - 基本 v=2.50, omega=3.20, angle=0
    - ガードが近い場合は微角度で回避しつつ軽く速度上げ
    """

    # 調整: 前進力を更に強めつつ極端カーブ感を維持
    v = 2.68  # ハウス到達を優先して速度を高める
    omega = 3.80  # カーブ強度を上げる（ガード時はさらに増強）
    angle = 0.0

    guards = board["guards"]

    if guards:
        avg_x = sum(g["x"] for g in guards) / len(guards)
        sign = 1.0 if avg_x >= 0 else -1.0
        # 基本はほぼセンター、近いガードには回避を強める
        angle = 0.003 * sign

        avg_dist = sum(dist(g["x"], g["y"], TEE_X, TEE_Y) for g in guards) / len(guards)
        if avg_dist < 3.5:
            # 近いガードには角度を付け、速度を増やして貫通力を確保
            angle = 0.006 * sign
            v = min(2.78, v + 0.06)
            # ガード回避のためカーブを更に強める（上限あり）
            omega = min(4.20, omega + 0.40)

    # もし自チームの石がまだ盤上に無ければ到達を優先して更に速度を増す
    if len(board.get("my", [])) == 0:
        v = min(2.82, v + 0.08)

    # 角度が決まっている場合、角速度の符号は角度の逆符号にする
    # （初期方向を少し外側に狙い、回転で内側に戻すため）
    if angle > 0:
        omega = -abs(omega)
    elif angle < 0:
        omega = abs(omega)

    # 安全域でクリップ（極端さは維持しつつ上限を与える）
    v = max(2.60, min(2.82, v))
    angle = max(-0.02, min(0.02, angle))
    # omega は符号が入ったままクリップする（絶対値は上限を超えない）
    if omega >= 0:
        omega = max(3.60, min(4.40, omega))
    else:
        omega = -max(3.60, min(4.40, abs(omega)))

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
        match_team_name=MatchNameModel.team1,
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
