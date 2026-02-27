import asyncio
import json
import math
import logging
from pathlib import Path
from typing import List, Dict, Tuple

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
# 最終エンド番号（0始まり）。環境に応じて変更してください。
FINAL_END_NUMBER = 9
# 最大強度ショットの translational_velocity（既存値より大きめに設定）
MAX_TRANSLATIONAL_VELOCITY = 3.0


def dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


class GridShotSelector:
    """グリッドはデバッグ用に保持しつつ、ショットパラメータは
    client_shot_engine_v2_6_freeze.py の変換関数に従って計算する実装。
    """

    def __init__(self, json_path: Path) -> None:
        try:
            with open(json_path, "r") as f:
                data: List[Dict] = json.load(f)
        except Exception:
            data = []

        self._entries: List[Dict] = data

    def _find_nearest_entry(self, tx: float, ty: float) -> Dict:
        best = None
        best_d2 = float("inf")
        for e in self._entries:
            dx = e.get("position_x", 0.0) - tx
            dy = e.get("position_y", 0.0) - ty
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = e
        return best

    # 以下は client_shot_engine_v2_6_freeze.py 由来の変換関数
    def _convert_center_draw(self, tx: float, ty: float) -> Tuple[float, float, float]:
        v = 2.42
        angle = math.radians(90)
        omega = math.pi / 2
        return v, angle, omega

    def _convert_takeout(self, tx: float, ty: float) -> Tuple[float, float, float]:
        d = dist(tx, ty, TEE_X, TEE_Y)
        v = 3.2 + (d / 40.0)
        angle = math.atan2(tx, ty)
        omega = 0.5
        return v, angle, omega

    def _convert_guard(self, tx: float, ty: float) -> Tuple[float, float, float]:
        v = 2.33
        angle = math.radians(90)
        omega = math.pi / 2
        return v, angle, omega

    def _convert_freeze(self, tx: float, ty: float) -> Tuple[float, float, float]:
        v = 2.30
        angle = math.radians(90)
        omega = math.pi / 1.8
        return v, angle, omega

    def get_shot_params(self, tx: float, ty: float) -> Tuple[float, float, float, Dict]:
        """ターゲット座標から v, angle, omega を返す。

        単純ルール:
        - TEE を狙う場合は center draw
        - ターゲットがハウス内なら takeout（ハウス内の石を狙う想定）
        - ターゲットがハウス外で TEE より手前側なら guard
        - それ以外は freeze
        """
        entry = self._find_nearest_entry(tx, ty)

        # TEE を明示的に狙う場合
        if math.isclose(tx, TEE_X, abs_tol=1e-6) and math.isclose(ty, TEE_Y, abs_tol=1e-6):
            v, angle, omega = self._convert_center_draw(tx, ty)
            return v, angle, omega, entry

        # ハウス内へ到達する座標なら takeout を想定
        if dist(tx, ty, TEE_X, TEE_Y) <= HOUSE_R:
            v, angle, omega = self._convert_takeout(tx, ty)
            return v, angle, omega, entry

        # ハウス外で TEE に向かって手前側（y が小さい）ならガード
        if ty < TEE_Y - 1.0:
            v, angle, omega = self._convert_guard(tx, ty)
            return v, angle, omega, entry

        # デフォルトはフリーズ
        v, angle, omega = self._convert_freeze(tx, ty)
        return v, angle, omega, entry


# モジュール読み込み時に一度だけグリッドをロード
GRID_JSON_PATH = Path(__file__).parent / "grid_export_filled.json"
_grid_selector = GridShotSelector(GRID_JSON_PATH)


def get_no1_stone(state):
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
    shot_index = state.shot_number + 1
    no1 = get_no1_stone(state)

    if shot_index == 1:
        return TEE_X, TEE_Y, no1, None

    if 2 <= shot_index <= 5:
        if no1 is None:
            return TEE_X, TEE_Y, no1, None
        return no1["x"], no1["y"] - STONE_R, no1, None

    if 6 <= shot_index <= 15:
        if no1 is None:
            return TEE_X, TEE_Y, no1, None
        if (blocker := get_blocking_stone(state, no1)) is not None:
            return blocker["x"], blocker["y"], no1, None
        if no1["team"] == my_team:
            return no1["x"], no1["y"] - STONE_R, no1, None
        return no1["x"], no1["y"] + (2 * STONE_R), no1, None

    if shot_index == 16:
        if no1 is None:
            if state.end_number == FINAL_END_NUMBER:
                return TEE_X, TEE_Y, no1, None
            return TEE_X, TEE_Y, no1, 'max'
        if no1["team"] == my_team:
            return no1["x"], no1["y"] - (2 * STONE_R), no1, None

        no2 = get_no2_stone(state, no1)
        if no2 is not None and no2.get("team") == my_team:
            return no1["x"], no1["y"], no1, None

        if (blocker := get_blocking_stone(state, no1)) is not None:
            return blocker["x"], blocker["y"], no1, 'max'

        return no1["x"], no1["y"], no1, 'max'

    return TEE_X, TEE_Y, no1, None


def shot_to_target(tx: float, ty: float, mode: str = None) -> Tuple[float, float, float, Dict]:
    """ターゲット座標 (tx, ty) に対して、freeze エンジン由来のパラメータを決定する。"""
    # mode == 'max' の場合は速度のみ最大化、角度は TEE 方向へ
    if mode == 'max':
        # 近傍エントリはデバッグ用に取得
        entry = _grid_selector._find_nearest_entry(tx, ty)
        angle = math.atan2(tx, ty)
        return MAX_TRANSLATIONAL_VELOCITY, angle, 0.0, entry

    return _grid_selector.get_shot_params(tx, ty)


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

    logger = logging.getLogger("SampleClientNO1GridFreeze")
    logger.setLevel(level=logging.DEBUG)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(logs_dir / "sample_client_no1_grid_freeze_debug.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"client_data.team_name: {client_data.team_name}")
    logger.debug(f"client_data: {client_data}")

    match_team_name: MatchNameModel = await client.send_team_info(client_data)
    my_team = match_team_name.value
    logger.info(f"Assigned team: {my_team}")

    try:
        async for state_data in client.receive_state_data():
            if (winner_team := client.get_winner_team()) is not None:
                logger.info(f"Winner: {winner_team}")
                break

            next_shot_team = client.get_next_team()

            if next_shot_team == my_team:
                tx, ty, no1, mode = choose_target(state_data, my_team)
                translational_velocity, shot_angle, angular_velocity, matched_entry = shot_to_target(tx, ty, mode)

                if no1 is None:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: target=({tx:.2f}, {ty:.2f}) (NO1 none)"
                    )
                else:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: target=({tx:.2f}, {ty:.2f}) "
                        f"NO1=({no1['x']:.2f}, {no1['y']:.2f}) team={no1['team']}"
                    )

                logger.debug(
                    "Chosen shot details: tx=%s ty=%s no1=%s matched_entry=%s v=%.4f angle=%.4f omega=%.4f",
                    tx,
                    ty,
                    no1,
                    matched_entry,
                    translational_velocity,
                    shot_angle,
                    angular_velocity,
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
