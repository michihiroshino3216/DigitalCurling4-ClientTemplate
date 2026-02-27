import asyncio
import json
import math
import logging
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel

# ============================================================
# 基本定数（DC4 環境に合わせた値）
# ============================================================

TEE_X = 0.0
TEE_Y = 38.405          # TEE の y 座標
HOUSE_R = 1.829         # ハウス半径
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

def analyze_board(state, my_team: str):
    """
    盤面から自石・相手石・ハウス内の石・相手ナンバーワン（危険石）を抽出
    """
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

    # 危険石 = TEE に最も近い相手石（ハウス内を優先）
    dangerous = None
    if house_opp:
        dangerous = min(house_opp, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))
    elif opp_stones:
        dangerous = min(opp_stones, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))
    
    # 盤面の異常判定（全ての石が0,0 = エンド開始時）
    is_board_empty = len(stones) == 0

    return {
        "stones": stones,
        "my": my_stones,
        "opp": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "dangerous": dangerous,
        "is_empty": is_board_empty,
    }


# ============================================================
# シンプル戦略
#   1. 相手ナンバーワン（危険石）がハウス内にあればテイクアウト
#   2. それ以外は常にセンタードロー（TEE 付近）
# ============================================================

def choose_simple_strategy_shot(board, my_team):
    dangerous = board["dangerous"]
    is_empty = board["is_empty"]

    # エンド開始時（盤面が空）なら、力強いセンタードロー
    if is_empty:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
    # 1. 相手ナンバーワンがハウス内にあるなら、そのテイクアウトを狙う
    elif dangerous and is_in_house(dangerous["x"], dangerous["y"]):
        kind = "takeout"
        tx, ty = dangerous["x"], dangerous["y"]
    else:
        # 2. それ以外は常にセンタードロー（TEE 付近）
        kind = "draw"
        tx, ty = TEE_X, TEE_Y

    if kind == "takeout":
        v, angle, omega = convert_takeout(tx, ty)
    else:
        v, angle, omega = convert_center_draw(tx, ty)

    return (v, angle, omega), kind, (tx, ty)


# ============================================================
# ショット変換
# ============================================================

def convert_center_draw(tx, ty):
    """
    センタードロー用（動作確認済みコードに統一）
    """
    v = 2.42
    angle = math.radians(90)  # π/2
    omega = math.pi / 2
    return v, angle, omega


def convert_takeout(tx, ty):
    """
    テイクアウト用（距離に応じた動的な速度）
    """
    d = dist(tx, ty, TEE_X, TEE_Y)
    v = 3.2 + (d / 40.0)
    angle = math.atan2(tx, ty)
    omega = 0.5  # takeout の場合は異なる角速度
    return v, angle, omega


# ============================================================
# main()
# ============================================================

async def main():
    # match_id の読み込み
    json_path = Path(__file__).parents[1] / "match_id.json"
    with open(json_path, "r") as f:
        match_id = json.load(f)

    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=MatchNameModel.team0,  # ★ B 用なら基本は team0 を想定
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address(host="localhost", port=5000)

    # チーム設定
    with open("team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    # ショットエンジン用ロガー
    logger = logging.getLogger("ShotEngine_B_Simple")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    try:
        match_team_name = await client.send_team_info(client_data)
        my_team = match_team_name.value  # "team0" or "team1"
        logger.info(f"=== I AM {my_team} (B Simple Strategy: Center Draw + Takeout) ===")

        async for state in client.receive_state_data():
            # 勝敗がついたら終了
            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            # 自分の番ならショットを決めて送信
            if client.get_next_team() == my_team:
                board = analyze_board(state, my_team)
                (v, angle, omega), kind, target = choose_simple_strategy_shot(board, my_team)

                logger.info(
                    f"ShotKind={kind}, Target={target}, "
                    f"v={v:.3f}, angle={angle:.3f}, omega={omega:.3f}"
                )

                await client.send_shot_info(
                    translational_velocity=v,
                    shot_angle=angle,
                    angular_velocity=omega,
                )

    except Exception as e:
        logger.error(f"Unexpected error: {e}")

    finally:
        client.save_log_file()


if __name__ == "__main__":
    asyncio.run(main())
