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
# ショットプリセット（簡易）
# ============================================================

def shot_draw():
    return {"v": 2.39, "angle": math.radians(90), "omega": math.pi / 2}


def shot_guard():
    return {"v": 2.27, "angle": math.radians(90), "omega": math.pi / 2}


def shot_takeout(target):
    tx, ty = target["x"], target["y"]
    d = math.hypot(tx, ty)
    base_angle = math.atan2(tx, ty)

    correction = 0.04 * min(d / 40.0, 1.0)
    angle = base_angle - correction
    v = 3.2 + (d / 40.0)

    return {"v": v, "angle": angle, "omega": 0.5}


# ============================================================
# 状況コンテキスト
# ============================================================

def build_context(state, my_team):
    score = state.score
    my_score = sum(score.team0) if my_team == "team0" else sum(score.team1)
    opp_score = sum(score.team1) if my_team == "team0" else sum(score.team0)

    has_hammer = ((state.end_number % 2 == 0 and my_team == "team1") or
                  (state.end_number % 2 == 1 and my_team == "team0"))

    return {
        "end": state.end_number,
        "shot": state.shot_number,
        "my_score": my_score,
        "opp_score": opp_score,
        "score_diff": my_score - opp_score,
        "has_hammer": has_hammer,
        "state": state,
    }


# ============================================================
# リアルタイム戦略AI（安全版）
# ============================================================

def choose_strategy_rt(board, ctx, my_team):
    score_diff = ctx["score_diff"]
    end = ctx["end"]

    def safe_takeout():
        if board["shot_stone"] is None:
            return "draw", None
        return "takeout", board["shot_stone"]

    # ① 8エンド終了時点で3点以上リード → 守り切る
    if end >= 8 and score_diff >= 3:
        return safe_takeout()

    # ② 8エンド終了時点で2点差以内リード → 1点ずつ確実に
    if end >= 8 and 0 <= score_diff <= 2:
        return safe_takeout()

    # ③ 8エンド終了時点でビハインド → 大量得点狙い
    if end >= 8 and score_diff < 0:
        if ctx["shot"] <= 2:
            return "guard", None
        if board["shot_team"] == my_team:
            return "draw", None
        return safe_takeout()

    # 通常エンド（B 戦略ベース）
    if board["shot_team"] and board["shot_team"] != my_team:
        return safe_takeout()

    if ctx["shot"] <= 2:
        return "guard", None

    return "draw", None


# ============================================================
# AI メイン（安全版）
# ============================================================

def ai_decide_shot(state, my_team, turn_number):
    board = analyze_board(state, my_team)
    ctx = build_context(state, my_team)
    strategy, target = choose_strategy_rt(board, ctx, my_team)

    if strategy == "draw":
        return shot_draw()

    if strategy == "guard":
        return shot_guard()

    if strategy == "takeout":
        if target is None:
            return shot_draw()
        return shot_takeout(target)

    return shot_draw()


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

    logger = logging.getLogger("RTStrategy")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s"))
    logger.addHandler(handler)

    match_team_name = await client.send_team_info(client_data)
    my_team = match_team_name.value
    logger.info(f"=== I AM {my_team} (RT Strategy AI) ===")

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
