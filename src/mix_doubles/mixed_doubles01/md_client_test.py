import asyncio
import json
import numpy as np
import logging
import random
from pathlib import Path

from load_secrets import username, password
from dc4client.dc_client import DCClient
from dc4client.send_data import TeamModel, MatchNameModel, PositionedStonesModel

formatter = logging.Formatter(
    "%(asctime)s, %(name)s : %(levelname)s - %(message)s"
)

# -------------------------
# 先攻1投目選択ロジック（関数）
# -------------------------
def select_first_shot_position(score_diff, has_opponent_in_house, has_center_guard):
    """
    score_diff: 先攻側視点の得点差（負: Down, 0: Tie, 正: Up）
    has_opponent_in_house: 相手石がハウス内にいるか（bool）
    has_center_guard: センターガードが存在するか（bool）
    戻り値: "Zone6" / "Zone7" / "Freeze"
    """
    # 元重み（パーセンテージ）
    if score_diff < 0:
        mapping = {"strong":"Zone6", "medium":"Freeze", "weak":"Zone7"}
        weights = {"strong":55, "medium":30, "weak":15}
    elif score_diff == 0:
        mapping = {"strong":"Zone7", "medium":"Freeze", "weak":"Zone6"}
        weights = {"strong":50, "medium":35, "weak":15}
    else:
        mapping = {"strong":"Freeze", "medium":"Zone7", "weak":"Zone6"}
        weights = {"strong":45, "medium":40, "weak":15}

    # 弱除外判定（相手がハウス内 OR センターガードが無い）
    weak_excluded = has_opponent_in_house or (not has_center_guard)
    if weak_excluded:
        weights["weak"] = 0

    total = weights["strong"] + weights["medium"] + weights["weak"]
    if total <= 0:
        # フェイルセーフ：守備寄りを返す
        return "Freeze"

    probs = {k: v / total for k, v in weights.items()}

    # 抽選（揺らぎを残す）
    r = random.random()
    cum = 0.0
    for label in ("strong", "medium", "weak"):
        cum += probs[label]
        if r < cum:
            return mapping[label]

    return mapping["strong"]

# -------------------------
# 位置 -> ショットパラメータ マッピング
# （ここは実機でチューニングしてください）
# -------------------------
def shot_params_for_position(position_label):
    """
    position_label: "Zone6" / "Zone7" / "Freeze"
    戻り値: dict {translational_velocity, shot_angle, angular_velocity}
    ※ shot_angle はラジアン（0 = 正面方向）。実装環境に合わせて調整してください。
    """
    if position_label == "Zone6":
        return {"translational_velocity": 2.3, "shot_angle": 0.0, "angular_velocity": 0.0}
    if position_label == "Zone7":
        return {"translational_velocity": 2.0, "shot_angle": 0.0, "angular_velocity": 0.0}
    if position_label == "Freeze":
        # Freeze は速度を落として回転を付ける想定（微調整必須）
        return {"translational_velocity": 1.6, "shot_angle": 0.0, "angular_velocity": np.pi / 8}
    # デフォルト（安全）
    return {"translational_velocity": 1.8, "shot_angle": 0.0, "angular_velocity": 0.0}

# -------------------------
# state_data から判定するヘルパー（環境に合わせて編集）
# -------------------------
def infer_game_state_from_state_data(state_data, match_team_name):
    """
    state_data の構造は環境依存なので、ここで安全に抽出する。
    返り値: (score_diff:int, has_opponent_in_house:bool, has_center_guard:bool)
    """
    # フェイルセーフ初期値
    score_diff = 0
    has_opponent_in_house = False
    has_center_guard = False

    # --- score_diff の推定 ---
    # 可能なフィールドを順に試す（実際の state_data に合わせて追加）
    try:
        # 例: state_data.score_diff がある場合
        score_diff = int(state_data.score_diff)
    except Exception:
        try:
            # 例: state_data.scores が dict で {team0: x, team1: y}
            scores = getattr(state_data, "scores", None)
            if scores:
                # 先攻が match_team_name の場合の差を計算（先攻視点）
                # 実際の構造に合わせて修正してください
                my_score = scores.get(match_team_name, 0) if isinstance(scores, dict) else 0
                # opponent name 推定
                # ここは実装環境に合わせて正しく取得してください
                opponent_score = 0
                score_diff = my_score - opponent_score
        except Exception:
            score_diff = 0

    # --- has_opponent_in_house / has_center_guard の推定 ---
    # state_data に stones や positioned_stones 情報がある場合に解析する
    # ここでは一般的なフィールド名を試し、見つからなければ False を返す
    try:
        stones = getattr(state_data, "stones", None) or getattr(state_data, "stone_list", None)
        if stones:
            # stones の各要素に {team, x, y, in_house(bool)} のような情報がある想定
            for s in stones:
                team = getattr(s, "team", None) or s.get("team") if isinstance(s, dict) else None
                in_house = getattr(s, "in_house", None)
                if in_house is None:
                    # 距離で判定できるならここで判定（例: distance_to_t <= threshold）
                    pass
                if team is not None and team != match_team_name:
                    # 相手石がハウス内フラグが立っていれば True
                    if in_house:
                        has_opponent_in_house = True
                        break
    except Exception:
        has_opponent_in_house = False

    try:
        # センターガードの有無は mix_doubles_settings や positioned_stones 情報から推定できる場合がある
        mds = getattr(state_data, "mix_doubles_settings", None)
        if mds:
            # 例: mds.positioned_stones_type が "center_guard" など
            pst = getattr(mds, "positioned_stones_type", None) or getattr(mds, "positioned_stones", None)
            if pst is not None:
                has_center_guard = ("center_guard" in str(pst).lower()) or ("center" in str(pst).lower() and "guard" in str(pst).lower())
    except Exception:
        has_center_guard = False

    return score_diff, has_opponent_in_house, has_center_guard

# -------------------------
# メイン（あなたの既存コードに統合）
# -------------------------
async def main():
    # 最初のエンドにおいて、team0が先攻、team1が後攻です。
    json_path = Path(__file__).parents[1] / "match_id.json"

    with open(json_path, "r") as f:
        match_id = json.load(f)

    client = DCClient(match_id=match_id, username=username, password=password, match_team_name=MatchNameModel.team0, auto_save_log=True, log_dir="logs")
    client.set_server_address(host="localhost", port=5000)

    with open("md_team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    logger = logging.getLogger("SampleMDClient")
    logger.setLevel(level=logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.info(f"client_data.team_name: {client_data.team_name}")
    logger.debug(f"client_data: {client_data}")

    match_team_name: MatchNameModel = await client.send_team_info(client_data)

    # 乱数シードはテスト時のみ固定
    # random.seed(42)

    async for state_data in client.receive_state_data():
        if (winner_team := client.get_winner_team()) is not None:
            logger.info(f"Winner: {winner_team}")
            break

        next_shot_team = client.get_next_team()

        # 最初の置き石設定（既存処理）
        if state_data.next_shot_team is None and state_data.mix_doubles_settings is not None and state_data.last_move is None:
            if state_data.mix_doubles_settings.end_setup_team == match_team_name:
                logger.info("You select the positioned stones.")
                positioned_stones = PositionedStonesModel.pp_left
                await client.send_positioned_stones_info(positioned_stones)

        # 自チームのショット番なら思考して送信
        if next_shot_team == match_team_name:
            # 思考時間（任意）
            await asyncio.sleep(2)

            # --- ゲーム状態を推定 ---
            score_diff, has_opponent_in_house, has_center_guard = infer_game_state_from_state_data(state_data, match_team_name)
            logger.info(f"score_diff={score_diff}, opponent_in_house={has_opponent_in_house}, center_guard={has_center_guard}")

            # --- 先攻1投目ロジック（位置選択） ---
            # ※ ここでは「先攻1投目」かどうかの判定は省略しています。必要なら state_data.last_move 等で判定してください。
            position_label = select_first_shot_position(score_diff, has_opponent_in_house, has_center_guard)
            logger.info(f"Selected position: {position_label}")

            # --- 位置をショットパラメータに変換 ---
            params = shot_params_for_position(position_label)
            translational_velocity = params["translational_velocity"]
            shot_angle = params["shot_angle"]
            angular_velocity = params["angular_velocity"]

            # --- 送信 ---
            await client.send_shot_info(
                translational_velocity=translational_velocity,
                shot_angle=shot_angle,
                angular_velocity=angular_velocity,
            )

if __name__ == "__main__":
    asyncio.run(main())
