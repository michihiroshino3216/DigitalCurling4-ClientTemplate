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

# ログ分析に基づくカール係数調整（精度向上）
CURL_FACTOR = 0.06


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

    # shot stone（最もTEEに近い石）
    shot_stone = None
    if house_my or house_opp:
        all_house = house_my + house_opp
        shot_stone = max(all_house, key=lambda s: s["y"])

    return {
        "stones": stones,
        "my": my_stones,
        "opp": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "dangerous": dangerous,
        "shot_stone": shot_stone,
    }


# ============================================================
# 簡易シミュレーション（1手先、ログに基づく調整）
# ============================================================

def simulate_shot(v, angle, omega):
    """
    DC4 の完全物理は使わず、環境に合わせた簡易モデルで着地点を予測する。
    - 距離 ≒ v * 17.0（v=2.3 前後で TEE 付近）
    - 横ズレ = CURL_FACTOR * omega * travel
    - 角度補正: omegaが大きいほど角度がずれる
    """
    travel = v * 17.0
    dx = math.sin(angle) * travel
    dy = math.cos(angle) * travel

    curl = CURL_FACTOR * omega * travel
    dx += curl

    # 角度補正（ログからomegaが影響）
    angle_correction = omega * 0.1
    dx += math.sin(angle + angle_correction) * travel * 0.05

    return dx, dy


# ============================================================
# 評価関数（攻撃・防御バランス、テイクアウト優先）
# ============================================================

def evaluate_board_after_shot(board, my_team, x, y, turn_number):
    score = 0.0

    # 1) 自石としてハウス内に残る価値（中心に近いほど高評価）
    d_tee = dist(x, y, TEE_X, TEE_Y)
    if d_tee <= HOUSE_R:
        score += (HOUSE_R - d_tee) * 80.0

    # 2) 危険石（相手の一番良い石）へのプレッシャー／除去（テイクアウト優先）
    dangerous = board["dangerous"]
    if dangerous:
        d_danger = dist(x, y, dangerous["x"], dangerous["y"])
        if d_danger < STONE_R * 1.2:
            score += 150.0  # 危険石除去をさらに高評価
        elif d_danger < STONE_R * 2.0:
            score += 80.0

    # 3) ガード裏（相手石 or 自石の前に隠れる形）
    for s in board["stones"]:
        if s["y"] < y and abs(s["x"] - x) < 0.5:
            score += 25.0

    # 4) フリーズ（相手石に密着）
    for opp in board["opp"]:
        if dist(x, y, opp["x"], opp["y"]) < STONE_R * 1.3:
            score += 50.0

    # 5) 防御要素: shot stoneを防ぐ（相手のshot stoneに近い場合加点）
    shot_stone = board["shot_stone"]
    if shot_stone and shot_stone["team"] != my_team:
        d_shot = dist(x, y, shot_stone["x"], shot_stone["y"])
        if d_shot < STONE_R * 2.0:
            score += 100.0  # 防御重視

    # 6) 将来的な複数得点のポテンシャル
    my_house_count = len(board["house_my"])
    opp_house_count = len(board["house_opp"])
    score += (my_house_count - opp_house_count) * 10.0

    # 7) ターン依存調整: 終盤は攻撃性向上（テイクアウトを奨励）
    if turn_number >= 7:
        if d_tee > HOUSE_R:
            score -= 30.0  # ハウス外ペナルティ軽減
        if dangerous and d_danger < STONE_R * 2.0:
            score += 50.0  # 終盤テイクアウトボーナス

    return score


# ============================================================
# ショット候補生成（ターン依存、テイクアウト強制）
# ============================================================

def generate_candidates(board, my_team, turn_number):
    cands = []

    # 危険石がある場合、テイクアウトを強制的に追加
    if board["dangerous"]:
        dx = board["dangerous"]["x"]
        dy = board["dangerous"]["y"]
        for offset in [-0.1, 0.0, 0.1]:
            cands.append(("takeout", dx + offset, dy))

    # ターン依存戦略
    if turn_number <= 2:
        # 序盤: ガード優先
        guard_y = TEE_Y - 4.0
        for gx in [-0.5, 0.0, 0.5]:
            cands.append(("guard", gx, guard_y))
    elif 3 <= turn_number <= 6:
        # 中盤: ドロー優先
        draw_targets = [
            (0.0, TEE_Y),
            (0.4, TEE_Y - 0.3),
            (-0.4, TEE_Y - 0.3),
        ]
        for tx, ty in draw_targets:
            cands.append(("draw", tx, ty))
    else:
        # 終盤: テイクアウト or ドロー（攻撃性向上）
        if board["dangerous"]:
            # すでに追加済み
            pass
        else:
            draw_targets = [(0.0, TEE_Y)]
            for tx, ty in draw_targets:
                cands.append(("draw", tx, ty))

    # フリーズ（危険石にくっつける）
    if board["dangerous"]:
        dx = board["dangerous"]["x"]
        dy = board["dangerous"]["y"]
        cands.append(("freeze", dx, dy))

    return cands


# ============================================================
# 候補ショット → 速度・角度変換
# ============================================================

def convert_draw_or_freeze(tx, ty):
    d = dist(0, 0, tx, ty)
    base_v = 2.35
    v = base_v * (d / TEE_Y)

    angle = math.atan2(tx, ty)
    omega = math.pi / 2

    return v, angle, omega


def convert_guard(tx, ty):
    d = dist(0, 0, tx, ty)
    base_v = 2.2
    v = base_v * (d / TEE_Y)

    angle = math.atan2(tx, ty)
    omega = math.pi / 2

    return v, angle, omega


def convert_takeout(tx, ty):
    d = dist(0, 0, tx, ty)
    v = 3.0 + (d / 40.0)
    angle = math.atan2(tx, ty)
    omega = 0.3
    return v, angle, omega


# ============================================================
# 最適ショット選択（期待値最大化）
# ============================================================

def choose_best_shot(board, my_team, turn_number):
    candidates = generate_candidates(board, my_team, turn_number)

    best_score = -1e9
    best_shot = None
    best_kind = None
    best_target = None

    for kind, tx, ty in candidates:
        if kind == "takeout":
            v, angle, omega = convert_takeout(tx, ty)
        elif kind == "guard":
            v, angle, omega = convert_guard(tx, ty)
        else:  # draw / freeze
            v, angle, omega = convert_draw_or_freeze(tx, ty)

        # 簡易シミュレーション
        sx, sy = simulate_shot(v, angle, omega)

        # 評価
        score = evaluate_board_after_shot(board, my_team, sx, sy, turn_number)

        if score > best_score:
            best_score = score
            best_shot = (v, angle, omega)
            best_kind = kind
            best_target = (tx, ty)

    return best_shot, best_kind, best_target


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
        match_team_name=MatchNameModel.team0,  # 必要に応じて team0 / team1 を切り替え
        auto_save_log=True,
        log_dir="logs",
    )

    client.set_server_address(host="localhost", port=5000)

    with open("team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    # あなた専用のショットエンジン用ロガー
    logger = logging.getLogger("ShotEngineV3")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    try:
        match_team_name = await client.send_team_info(client_data)
        my_team = match_team_name.value
        logger.info(f"=== I AM {my_team} (Aggressive Takeout AI) ===")

        turn_number = 0

        async for state in client.receive_state_data():
            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            if client.get_next_team() == my_team:
                turn_number += 1
                board = analyze_board(state, my_team)
                (v, angle, omega), kind, target = choose_best_shot(board, my_team, turn_number)

                logger.info(
                    f"Turn {turn_number}: ShotKind={kind}, Target={target}, "
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