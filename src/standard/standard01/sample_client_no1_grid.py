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
# 例: 9 -> 10エンド方式の最終エンド
FINAL_END_NUMBER = 9
# 最大強度ショットの translational_velocity（既存値より大きめに設定）
MAX_TRANSLATIONAL_VELOCITY = 3.0


def dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot(x1 - x2, y1 - y2)


class GridShotSelector:
    """grid_export_filled.json から最寄りターゲットの初速度・角速度を取得するヘルパー。

    JSON 1行の例:
    {
        "position_x": -2.085,
        "position_y": 32.004,
        "cw_velocity_x": -0.255,
        "cw_velocity_y": 2.197,
        "cw_angular_velocity": -15.7079,
        "ccw_velocity_x": -0.021,
        "ccw_velocity_y": 2.212,
        "ccw_angular_velocity": 15.7079,
        "source_distance": 0.085
    }

    - position_x, position_y: 到達位置（DigitalCurling 座標系）
    - cw_*: 右回転（clockwise）ショットの初速度ベクトルと角速度
    - ccw_*: 左回転（counter-clockwise）ショットの初速度ベクトルと角速度
    """

    def __init__(self, json_path: Path) -> None:
        with open(json_path, "r") as f:
            data: List[Dict] = json.load(f)

        # そのまま保持しておき、毎回最近傍検索する（件数的に十分高速）
        self._entries: List[Dict] = data

    def _find_nearest_entry(self, tx: float, ty: float) -> Dict:
        """ターゲット座標 (tx, ty) に最も近い position_x, position_y を持つ行を返す。"""
        best = None
        best_d2 = float("inf")
        for e in self._entries:
            dx = e["position_x"] - tx
            dy = e["position_y"] - ty
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = e
        return best

    def get_shot_params(self, tx: float, ty: float) -> Tuple[float, float, float]:
        """ターゲット座標から初速度の大きさ・角度・角速度を決定する。

        戻り値:
            translational_velocity, shot_angle, angular_velocity
        """
        entry = self._find_nearest_entry(tx, ty)

        # x の正負で回転方向を自動選択（簡易ルール）
        #   x >= 0 → ccw（左回転）
        #   x <  0 → cw （右回転）
        if tx >= 0.0:
            vx = entry["ccw_velocity_x"]
            vy = entry["ccw_velocity_y"]
            omega = entry["ccw_angular_velocity"]
        else:
            vx = entry["cw_velocity_x"]
            vy = entry["cw_velocity_y"]
            omega = entry["cw_angular_velocity"]

        # DC4 クライアントのインターフェースに合わせて
        #   v: 速度の大きさ
        #   angle: atan2(vx, vy)
        v = math.hypot(vx, vy)
        angle = math.atan2(vy, vx)

        # 返り値に最近傍エントリも含める（デバッグ用）
        return v, angle, omega, entry


# モジュール読み込み時に一度だけグリッドをロード
GRID_JSON_PATH = Path(__file__).parent / "grid_export_filled.json"
_grid_selector = GridShotSelector(GRID_JSON_PATH)


def get_no1_stone(state):
    # NO1 = ハウス内でTEEに最も近い石
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
    # ハック(0,0)とNO1を結ぶ線分上にある石を探す
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
    # NO2 = NO1に次いでTEEに近い石（ハウス内）
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
    # shot_numberは0始まりのため、+1して条件に合わせる
    shot_index = state.shot_number + 1
    no1 = get_no1_stone(state)

    if shot_index == 1:
        # 各エンドの1投目はセンタードロー
        return TEE_X, TEE_Y, no1, None

    if 2 <= shot_index <= 5:
        # 2-5投目: 元のルールに戻す — NO1 があればフリーズ、なければセンタードロー
        if no1 is None:
            return TEE_X, TEE_Y, no1, None
        return no1["x"], no1["y"] - STONE_R, no1, None

    if 6 <= shot_index <= 15:
        # 6-15投目はNO1が自チームならフリーズ、相手なら奥2個分
        if no1 is None:
            return TEE_X, TEE_Y, no1, None
        # ハック- NO1 の直線上に石があればその石を狙う
        if (blocker := get_blocking_stone(state, no1)) is not None:
            return blocker["x"], blocker["y"], no1, None
        if no1["team"] == my_team:
            return no1["x"], no1["y"] - STONE_R, no1, None
        return no1["x"], no1["y"] + (2 * STONE_R), no1, None

    if shot_index == 16:
        # 16投目の特別条件
        # NO1が無い場合は「最終エンドのみTEEを狙い、最終エンドでなければ
        # 最大強度ショットを行う」ように変更
        if no1 is None:
            # 最終エンドならTEEを狙う
            if state.end_number == FINAL_END_NUMBER:
                return TEE_X, TEE_Y, no1, None
            # それ以外のエンドではTEE方向への最大強度ショット
            return TEE_X, TEE_Y, no1, 'max'
        if no1["team"] == my_team:
            # 自チームNO1なら2個分手前へフリーズ
            return no1["x"], no1["y"] - (2 * STONE_R), no1, None

        # 相手NO1の場合の挙動:
        # - NO2が自チームの石であれば、NO1と同じ座標に止まるようにショット（フリーズを狙う）
        # - NO2が自チームでない（または存在しない）場合は最大強度ショットでNO1を狙う
        #   ただし、ハック-NO1線上にガードがあるときはそのガードへ最大強度ショットを行い
        #   ガードがNO1に当たるようにする
        no2 = get_no2_stone(state, no1)
        if no2 is not None and no2.get("team") == my_team:
            # NO2が自チームなら、NO1と同じ座標を目指して止めに行く（フリーズ狙い）
            return no1["x"], no1["y"], no1, None

        # NO2が自チームでない場合は最大強度ショットでNO1を狙う（ガード優先で当てに行く）
        if (blocker := get_blocking_stone(state, no1)) is not None:
            return blocker["x"], blocker["y"], no1, 'max'

        # ガードがなければNO1へ最大強度ショット
        return no1["x"], no1["y"], no1, 'max'

    return TEE_X, TEE_Y, no1, None


def shot_to_target(tx: float, ty: float, mode: str = None) -> Tuple[float, float, float, Dict]:
    """ターゲット座標 (tx, ty) に対して、グリッドからパラメータを決定する。

    戻り値: translational_velocity, shot_angle, angular_velocity, matched_entry
    """
    # モードが 'max' の場合は最大強度ショットを返すが、ショット角度は
    # パラメータファイル（grid_export_filled.json）から取得する。
    # 速度のみ最大値に置き換える。
    if mode == 'max':
        _, angle, _, entry = _grid_selector.get_shot_params(tx, ty)
        return MAX_TRANSLATIONAL_VELOCITY, angle, 0.0, entry

    return _grid_selector.get_shot_params(tx, ty)


async def main():
    json_path = Path(__file__).parents[1] / "match_id.json"

    with open(json_path, "r") as f:
        match_id = json.load(f)

    # クライアント初期化
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

    logger = logging.getLogger("SampleClientNO1Grid")
    logger.setLevel(level=logging.DEBUG)

    # コンソールには INFO 以上を流す
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # 詳細ログはファイルへ（DEBUG レベル）
    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(logs_dir / "sample_client_no1_grid_debug.log", mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"client_data.team_name: {client_data.team_name}")
    logger.debug(f"client_data: {client_data}")

    # チーム情報送信後、自チームが確定
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

                # コンソール向けの簡潔ログ
                if no1 is None:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: target=({tx:.2f}, {ty:.2f}) (NO1 none)"
                    )
                else:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: target=({tx:.2f}, {ty:.2f}) "
                        f"NO1=({no1['x']:.2f}, {no1['y']:.2f}) team={no1['team']}"
                    )

                # 詳細はファイルにデバッグ出力
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
