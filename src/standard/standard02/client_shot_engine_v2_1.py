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

# ログから見える挙動に合わせた簡易カール係数（やや控えめ）
CURL_FACTOR = 0.03


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

    return {
        "stones": stones,
        "my": my_stones,
        "opp": opp_stones,
        "house_my": house_my,
        "house_opp": house_opp,
        "dangerous": dangerous,
    }


# ============================================================
# 簡易シミュレーション（1手先）
# ============================================================

def simulate_shot(v, angle, omega):
    """
    DC4 の完全物理は使わず、環境に合わせた簡易モデルで着地点を予測する。
    - 距離 ≒ v * 17.0（v=2.3 前後で TEE 付近）
    - 横ズレ = CURL_FACTOR * omega * travel
    """
    travel = v * 17.0
    dx = math.sin(angle) * travel
    dy = math.cos(angle) * travel

    curl = CURL_FACTOR * omega * travel
    dx += curl

    return dx, dy


# ============================================================
# 評価関数（攻撃寄り）
# ============================================================

def evaluate_board_after_shot(board, my_team, x, y):
    score = 0.0

    # 1) 自石としてハウス内に残る価値（中心に近いほど高評価）
    d_tee = dist(x, y, TEE_X, TEE_Y)
    if d_tee <= HOUSE_R:
        score += (HOUSE_R - d_tee) * 80.0  # 攻撃寄りなので重めのウェイト

    # 2) 危険石（相手の一番良い石）へのプレッシャー／除去
    dangerous = board["dangerous"]
    if dangerous:
        d_danger = dist(x, y, dangerous["x"], dangerous["y"])
        # ほぼ重なっていればテイク or フリーズ成功とみなす
        if d_danger < STONE_R * 1.2:
            score += 120.0  # 危険石除去・フリーズは最優先
        elif d_danger < STONE_R * 2.0:
            score += 60.0   # かなりプレッシャーをかけている

    # 3) ガード裏（相手石 or 自石の前に隠れる形）
    for s in board["stones"]:
        if s["y"] < y and abs(s["x"] - x) < 0.5:
            score += 25.0

    # 4) フリーズ（相手石に密着）
    for opp in board["opp"]:
        if dist(x, y, opp["x"], opp["y"]) < STONE_R * 1.3:
            score += 50.0

    # 5) 将来的な複数得点のポテンシャル（自石が多いほど加点）
    #    ここでは簡易的に「自石がハウスに多いほど」加点するイメージ
    my_house_count = len(board["house_my"])
    opp_house_count = len(board["house_opp"])
    score += (my_house_count - opp_house_count) * 10.0

    return score


# ============================================================
# ショット候補生成（攻撃寄り）
# ============================================================

def generate_candidates(board, my_team):
    cands = []

    # --- 危険石・ハウス内相手石へのテイクアウトを最優先で候補化 ---
    for opp in board["house_opp"]:
        ox, oy = opp["x"], opp["y"]
        for offset in [-0.15, 0.0, 0.15]:
            cands.append(("takeout", ox + offset, oy))

    if board["dangerous"] and board["dangerous"] not in board["house_opp"]:
        dx = board["dangerous"]["x"]
        dy = board["dangerous"]["y"]
        for offset in [-0.15, 0.0, 0.15]:
            cands.append(("takeout", dx + offset, dy))

    # --- 攻撃的ドロー（複数得点を狙う配置） ---
    draw_targets = [
        (0.0, TEE_Y),           # ボタン
        (0.4, TEE_Y - 0.3),     # 右前
        (-0.4, TEE_Y - 0.3),    # 左前
        (0.8, TEE_Y - 0.5),     # さらに右
        (-0.8, TEE_Y - 0.5),    # さらに左
    ]
    for tx, ty in draw_targets:
        cands.append(("draw", tx, ty))

    # --- フリーズ（危険石にくっつける） ---
    if board["dangerous"]:
        dx = board["dangerous"]["x"]
        dy = board["dangerous"]["y"]
        cands.append(("freeze", dx, dy))

    # --- 攻撃のためのガード（危険石 or 自石の前） ---
    guard_y = TEE_Y - 4.0
    if board["dangerous"]:
        gx = board["dangerous"]["x"]
        cands.append(("guard", gx, guard_y))
    else:
        for gx in [-0.5, 0.0, 0.5]:
            cands.append(("guard", gx, guard_y))

    return cands


# ============================================================
# 候補ショット → 速度・角度変換
# ============================================================

def convert_draw_or_freeze(tx, ty):
    # TEE まで v ≒ 2.35 前後になるようにスケーリング
    d = dist(0, 0, tx, ty)
    base_v = 2.35
    v = base_v * (d / TEE_Y)

    angle = math.atan2(tx, ty)
    # カールをしっかり使う前提でやや大きめ
    omega = math.pi / 2

    return v, angle, omega


def convert_guard(tx, ty):
    # ガードは TEE より手前なので少し弱め
    d = dist(0, 0, tx, ty)
    base_v = 2.2
    v = base_v * (d / TEE_Y)

    angle = math.atan2(tx, ty)
    omega = math.pi / 2

    return v, angle, omega


def convert_takeout(tx, ty):
    # テイクアウトはやや強め
    d = dist(0, 0, tx, ty)
    v = 3.0 + (d / 40.0)
    angle = math.atan2(tx, ty)
    # カールは控えめ（真っ直ぐ目に）
    omega = 0.3
    return v, angle, omega


# ============================================================
# 最適ショット選択（期待値最大化）
# ============================================================

def choose_best_shot(board, my_team):
    candidates = generate_candidates(board, my_team)

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
        score = evaluate_board_after_shot(board, my_team, sx, sy)

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
    logger = logging.getLogger("ShotEngine")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s, %(name)s : %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)

    try:
        match_team_name = await client.send_team_info(client_data)
        my_team = match_team_name.value
        logger.info(f"=== I AM {my_team} (Aggressive Attack AI) ===")

        async for state in client.receive_state_data():
            if client.get_winner_team() is not None:
                logger.info(f"Winner: {client.get_winner_team()}")
                break

            if client.get_next_team() == my_team:
                board = analyze_board(state, my_team)
                (v, angle, omega), kind, target = choose_best_shot(board, my_team)

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
