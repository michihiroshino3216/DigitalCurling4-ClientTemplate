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
# 盤面解析（拡張版）
# ============================================================

def analyze_board(state, my_team: str):
    """
    盤面から自石・相手石・ハウス内の石・相手ナンバーワン（危険石）・ガード石などを抽出
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

    # ガード石 = ハウス外の自石（防御用）
    guards = [s for s in my_stones if not is_in_house(s["x"], s["y"])]
    
    # 盤面の異常判定（全ての石が0,0 = エンド開始時）
    is_board_empty = len(stones) == 0

    return {
        "stones": stones,
        "my": my_stones,
        "opp": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "dangerous": dangerous,
        "guards": guards,
        "is_empty": is_board_empty,
    }


# ============================================================
# 改善戦略
#   1. 相手ナンバーワン（危険石）がハウス内にあればテイクアウト
#   2. 自石が少ない場合はセンタードロー
#   3. ガードショット（ハウス外防御）
# ============================================================

def choose_improved_strategy_shot(board, my_team, logger):
    dangerous = board["dangerous"]
    house_my = board["house_my"]
    house_opp = board["house_opp"]
    guards = board["guards"]
    is_empty = board["is_empty"]

    reason = ""

    # エンド開始時（盤面が空）なら、力強いセンタードロー
    if is_empty:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = "Board empty (end start), first draw shot."
    # 1. 相手ナンバーワンがハウス内にあるなら、そのテイクアウトを狙う
    elif dangerous and is_in_house(dangerous["x"], dangerous["y"]):
        kind = "takeout"
        tx, ty = dangerous["x"], dangerous["y"]
        reason = f"Dangerous stone at ({dangerous['x']:.2f}, {dangerous['y']:.2f}), attempting takeout."
    # 2. 自石がハウス内に少なく、相手石が多い場合はセンタードロー
    elif len(house_my) < len(house_opp) + 1:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = f"Fewer stones in house (my: {len(house_my)}, opp: {len(house_opp)}), attempting center draw."
    # 3. ガードショット（ハウス外に防御石を置く）
    elif len(guards) < 2:
        kind = "guard"
        # ハウス外の適当な位置（例: TEEの少し手前）
        tx, ty = 0.0, TEE_Y - 5.0
        reason = f"Building guards (current: {len(guards)}), placing guard stone."
    else:
        # デフォルト: センタードロー
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = "Default center draw."

    if kind == "takeout":
        v, angle, omega = convert_takeout(tx, ty, board)
    elif kind == "guard":
        v, angle, omega = convert_guard(tx, ty)
    else:
        v, angle, omega = convert_center_draw(tx, ty)

    logger.info(f"Strategy reason: {reason}")
    return (v, angle, omega), kind, (tx, ty)


# ============================================================
# ショット変換（改善版）
# ============================================================

def convert_center_draw(tx, ty):
    """
    センタードロー用の速度計算（摩擦と距離を考慮）
    """
    # 動作確認されたパラメータに統一
    v = 2.42
    angle = math.radians(90)  # π/2
    omega = math.pi / 2

    return v, angle, omega


def convert_takeout(tx, ty, board):
    """
    テイクアウト用のショット（盤面を考慮した調整）
    """
    # 距離に応じたvelocity調整
    d = dist(tx, ty, TEE_X, TEE_Y)
    v = 3.2 + (d / 40.0)
    angle = math.atan2(tx, ty)
    omega = 0.5  # takeout の場合は異なる角速度

    return v, angle, omega


def convert_guard(tx, ty):
    """
    ガードショット用のショット（ハウス外防御）
    """
    # ガード値は動作確認済みの値に統一
    v = 2.33
    angle = math.radians(90)  # π/2
    omega = math.pi / 2

    return v, angle, omega


# ============================================================
# main()（改善版: エラーハンドリング強化、ログ詳細化）
# ============================================================

async def main():
    # match_id の読み込み
    json_path = Path(__file__).parents[1] / "match_id.json"
    try:
        with open(json_path, "r") as f:
            match_id = json.load(f)
    except FileNotFoundError:
        print("Error: match_id.json not found.")
        return
    except json.JSONDecodeError:
        print("Error: Invalid match_id.json.")
        return

    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=MatchNameModel.team0,
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address(host="localhost", port=5000)

    # チーム設定
    try:
        with open("team_config.json", "r") as f:
            data = json.load(f)
        client_data = TeamModel(**data)
    except FileNotFoundError:
        print("Error: team_config.json not found.")
        return
    except json.JSONDecodeError:
        print("Error: Invalid team_config.json.")
        return

    # ショットエンジン用ロガー（詳細化）
    logger = logging.getLogger("ShotEngine_B_Improved")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    try:
        match_team_name = await client.send_team_info(client_data)
        my_team = match_team_name.value
        logger.info(f"=== I AM {my_team} (Improved Strategy: Takeout + Draw + Guard) ===")
        logger.info(f"Client data sent: {client_data}")

        shot_count = 0
        async for state in client.receive_state_data():
            # 盤面状態をログ
            logger.debug(f"State received: end={state.end_number}, shot={state.shot_number}, "
                        f"total_shot={state.total_shot_number}, next_team={state.next_shot_team}")
            
            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            if client.get_next_team() == my_team:
                try:
                    board = analyze_board(state, my_team)
                    
                    # 盤面分析をログ
                    logger.info(f"Board Analysis: my_stones={len(board['my'])}, opp_stones={len(board['opp'])}, "
                               f"house_my={len(board['house_my'])}, house_opp={len(board['house_opp'])}")
                    
                    if board['dangerous']:
                        logger.info(f"Dangerous stone: ({board['dangerous']['x']:.2f}, {board['dangerous']['y']:.2f})")
                    
                    (v, angle, omega), kind, target = choose_improved_strategy_shot(board, my_team, logger)

                    logger.info(
                        f"[Shot #{shot_count}] ShotKind={kind}, Target=({target[0]:.2f}, {target[1]:.2f}), "
                        f"v={v:.3f}, angle={angle:.3f}, omega={omega:.3f}"
                    )

                    await client.send_shot_info(
                        translational_velocity=v,
                        shot_angle=angle,
                        angular_velocity=omega,
                    )
                    shot_count += 1
                except Exception as shot_error:
                    logger.error(f"Error during shot calculation: {shot_error}", exc_info=True)
                    # フォールバック: シンプルドロー
                    logger.warning("Falling back to simple draw shot")
                    await client.send_shot_info(
                        translational_velocity=2.35,
                        shot_angle=0.0,
                        angular_velocity=math.pi / 2,
                    )
                    shot_count += 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)

    finally:
        client.save_log_file()


if __name__ == "__main__":
    asyncio.run(main())