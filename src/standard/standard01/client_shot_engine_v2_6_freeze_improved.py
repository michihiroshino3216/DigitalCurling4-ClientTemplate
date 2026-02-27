import asyncio
import json
import math
import logging
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel

TEE_X = 0.0
TEE_Y = 38.405
HOUSE_R = 1.829
STONE_R = 0.145

# ユーティリティ

def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)

def is_in_house(x, y):
    return dist(x, y, TEE_X, TEE_Y) <= HOUSE_R

# 盤面解析

def analyze_board(state, my_team: str):
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

# 戦略（フリーズ精度改善）

def choose_improved_strategy_shot(board, my_team, logger):
    dangerous = board["dangerous"]
    house_my = board["house_my"]
    house_opp = board["house_opp"]
    guards = board["guards"]
    is_empty = board["is_empty"]
    reason = ""
    # フリーズ条件: 相手石がハウス内にあり、自石が少ない場合
    if house_opp and len(house_my) < len(house_opp):
        freeze_target = min(house_opp, key=lambda s: dist(s["x"], s["y"], TEE_X, TEE_Y))
        kind = "freeze"
        # 改善: 相手石の手前STONE_R+0.05だけ離す
        tx, ty = freeze_target["x"], freeze_target["y"] - (STONE_R + 0.05)
        reason = f"Freeze improved: aiming {STONE_R+0.05:.2f} in front of opp stone at ({freeze_target['x']:.2f}, {freeze_target['y']:.2f})"
    elif is_empty:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = "Board empty (end start), first draw shot."
    elif dangerous and is_in_house(dangerous["x"], dangerous["y"]):
        kind = "takeout"
        tx, ty = dangerous["x"], dangerous["y"]
        reason = f"Dangerous stone at ({dangerous['x']:.2f}, {dangerous['y']:.2f}), attempting takeout."
    elif len(house_my) < len(house_opp) + 1:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = f"Fewer stones in house (my: {len(house_my)}, opp: {len(house_opp)}), attempting center draw."
    elif len(guards) < 2:
        kind = "guard"
        tx, ty = 0.0, TEE_Y - 5.0
        reason = f"Building guards (current: {len(guards)}), placing guard stone."
    else:
        kind = "draw"
        tx, ty = TEE_X, TEE_Y
        reason = "Default center draw."
    if kind == "takeout":
        v, angle, omega = convert_takeout(tx, ty, board)
    elif kind == "guard":
        v, angle, omega = convert_guard(tx, ty)
    elif kind == "freeze":
        v, angle, omega = convert_freeze(tx, ty)
    else:
        v, angle, omega = convert_center_draw(tx, ty)
    logger.info(f"Strategy reason: {reason}")
    return (v, angle, omega), kind, (tx, ty)

# ショット変換

def convert_center_draw(tx, ty):
    v = 2.42
    angle = math.radians(90)
    omega = math.pi / 2
    return v, angle, omega

def convert_takeout(tx, ty, board):
    d = dist(tx, ty, TEE_X, TEE_Y)
    v = 3.2 + (d / 40.0)
    angle = math.atan2(tx, ty)
    omega = 0.5
    return v, angle, omega

def convert_guard(tx, ty):
    v = 2.33
    angle = math.radians(90)
    omega = math.pi / 2
    return v, angle, omega

def convert_freeze(tx, ty):
    # 改善: 速度をやや低めに（2.25）・回転もやや強め
    v = 2.25
    angle = math.radians(90)
    omega = math.pi / 1.7
    return v, angle, omega

async def main():
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
    # match_team_nameは後で取得するので一旦None
    client = DCClient(
        match_id=match_id,
        username=username,
        password=password,
        match_team_name=None,
        auto_save_log=True,
        log_dir="logs",
    )
    client.set_server_address(host="localhost", port=5000)
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
    logger = logging.getLogger("ShotEngine_B_FreezeImproved")
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)
    try:
        match_team_name = await client.send_team_info(client_data)
        if match_team_name is None:
            logger.error("Error: match_team_name is None. チーム名が取得できませんでした。サーバーや設定を確認してください。")
            return
        my_team = match_team_name.value
        logger.info(f"=== I AM {my_team} (Freeze Improved) ===")
        logger.info(f"Client data sent: {client_data}")
        shot_count = 0
        v_adjust = {"freeze": 2.25, "draw": 2.42, "guard": 2.33}
        last_shot_info = None
        last_target = None
        async for state in client.receive_state_data():
            logger.debug(f"State received: end={state.end_number}, shot={state.shot_number}, "
                        f"total_shot={state.total_shot_number}, next_team={state.next_shot_team}")
            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break
            # ショット結果によるv調整
            if last_shot_info and last_target:
                coord = state.stone_coordinate.data[my_team]
                stones = [c for c in coord if not (c.x == 0 and c.y == 0)]
                if stones:
                    last_stone = stones[-1]
                    dx = last_stone.x - last_target[0]
                    dy = last_stone.y - last_target[1]
                    dist_err = math.hypot(dx, dy)
                    logger.info(f"Last shot result: stopped at ({last_stone.x:.2f}, {last_stone.y:.2f}), target=({last_target[0]:.2f}, {last_target[1]:.2f}), error={dist_err:.3f}")
                    if dist_err > 0.15:
                        if dy < 0:
                            v_adjust[last_shot_info] += 0.03
                            logger.info(f"v調整: 手前→v+0.03 ({last_shot_info})")
                        else:
                            v_adjust[last_shot_info] -= 0.03
                            logger.info(f"v調整: 奥→v-0.03 ({last_shot_info})")
                        v_adjust[last_shot_info] = max(2.0, min(3.0, v_adjust[last_shot_info]))
            if client.get_next_team() == my_team:
                try:
                    board = analyze_board(state, my_team)
                    logger.info(f"Board Analysis: my_stones={len(board['my'])}, opp_stones={len(board['opp'])}, "
                               f"house_my={len(board['house_my'])}, house_opp={len(board['house_opp'])}")
                    if board['dangerous']:
                        logger.info(f"Dangerous stone: ({board['dangerous']['x']:.2f}, {board['dangerous']['y']:.2f})")
                    (v, angle, omega), kind, target = choose_improved_strategy_shot(board, my_team, logger)
                    if kind in v_adjust:
                        v = v_adjust[kind]
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
                    last_shot_info = kind
                    last_target = target
                except Exception as shot_error:
                    logger.error(f"Error during shot calculation: {shot_error}", exc_info=True)
                    logger.warning("Falling back to simple draw shot")
                    await client.send_shot_info(
                        translational_velocity=2.35,
                        shot_angle=0.0,
                        angular_velocity=math.pi / 2,
                    )
                    shot_count += 1
                    last_shot_info = "draw"
                    last_target = (TEE_X, TEE_Y)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        client.save_log_file()

if __name__ == "__main__":
    asyncio.run(main())
