import asyncio
import json
import math
import logging
from pathlib import Path

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

DRAW_V = 2.39
FREEZE_V = 2.30
OMEGA = math.pi / 2


def dist(x1, y1, x2, y2):
    return math.hypot(x1 - x2, y1 - y2)


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


def choose_target(state, my_team):
    shot_index = state.shot_number + 1
    no1 = get_no1_stone(state)

    if shot_index == 1:
        return "draw", TEE_X, TEE_Y, no1

    if 2 <= shot_index <= 5:
        if no1 is None:
            return "draw", TEE_X, TEE_Y, no1
        return "freeze", no1["x"], no1["y"] - STONE_R, no1

    if 6 <= shot_index <= 15:
        if no1 is None:
            return "draw", TEE_X, TEE_Y, no1
        if no1["team"] == my_team:
            return "freeze", no1["x"], no1["y"] - STONE_R, no1
        return "deep", no1["x"], no1["y"] + (2 * STONE_R), no1

    if shot_index == 16:
        if no1 is None:
            return "draw", TEE_X, TEE_Y, no1
        if no1["team"] == my_team:
            return "freeze", no1["x"], no1["y"] - STONE_R, no1
        return "deep", no1["x"], no1["y"] + (2 * STONE_R), no1

    return "draw", TEE_X, TEE_Y, no1


def shot_to_target(kind, tx, ty):
    angle = math.atan2(tx, ty)
    if kind == "freeze":
        v = FREEZE_V
    else:
        v = DRAW_V
    return v, angle, OMEGA

async def main():
    # 最初のエンドにおいて、team0が先攻、team1が後攻です。
    # デフォルトではteam1となっており、先攻に切り替えたい場合は下記を
    # team_name=MatchNameModel.team0
    # に変更してください
    json_path = Path(__file__).parents[1] / "match_id.json"

    # match_idを読み込みます。
    with open(json_path, "r") as f:
        match_id = json.load(f)
    
    # クライアントの初期化（ログレベルはデフォルトでINFO、保存機能はデフォルトでTrue）
    client = DCClient(match_id=match_id, username=username, password=password, match_team_name=MatchNameModel.team0, auto_save_log=True, log_dir="logs")

    # ここで、接続先のサーバのアドレスとポートを指定します。
    # デフォルトではlocalhost:5000となっています。
    # こちらは接続先に応じて変更してください。
    client.set_server_address(host="localhost", port=5000)

    # チーム設定の読み込み
    with open("team_config.json", "r") as f:
        data = json.load(f)
    client_data = TeamModel(**data)

    # ログ設定(不要であれば削除してください)
    # DCClient内にもloggerがあるため、そちらを利用することも可能ですが、
    # client.logger を使用するとライブラリ側で管理しているバッファに自動的に入ります
    logger = logging.getLogger("SampleClient")
    logger.setLevel(level=logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logger.info(f"client_data.team_name: {client_data.team_name}")
    logger.debug(f"client_data: {client_data}")

    # チーム情報をサーバに送信します。
    # 相手のクライアントも同様にチーム情報を送信するまで待機します。
    # 送信後、自チームの名前を受け取ります(team0 または team1)。
    # 両チームが揃うと試合が開始され、思考時間のカウントが始まります。
    # そのため、AIの初期化などはこの前に行ってください。
    match_team_name: MatchNameModel = await client.send_team_info(client_data)
    my_team = match_team_name.value

    try:
        async for state_data in client.receive_state_data():
            
            # ゲーム終了の判定
            if (winner_team := client.get_winner_team()) is not None:
                logger.info(f"Winner: {winner_team}")
                break
            
            next_shot_team = client.get_next_team()

            # AIを実装する際の処理はこちらになります。
            if next_shot_team == my_team:
                kind, tx, ty, no1 = choose_target(state_data, my_team)
                translational_velocity, shot_angle, angular_velocity = shot_to_target(kind, tx, ty)

                if no1 is None:
                    logger.info(f"Shot {state_data.shot_number + 1}: {kind} to ({tx:.2f}, {ty:.2f}) (NO1 none)")
                else:
                    logger.info(
                        f"Shot {state_data.shot_number + 1}: {kind} to ({tx:.2f}, {ty:.2f}) "
                        f"NO1=({no1['x']:.2f}, {no1['y']:.2f}) team={no1['team']}"
                    )

                await client.send_shot_info(
                    translational_velocity=translational_velocity,
                    shot_angle=shot_angle,
                    angular_velocity=angular_velocity,
                )
                # なお、デジタルカーリング3で使用されていた、(vx, vy, rotation(cw または ccw))での送信も可能です。
                # vx = 0.0
                # vy = 2.33
                # rotation = "cw"
                # await client.send_shot_info_dc3(
                #     vx=vx,
                #     vy=vy,
                #     rotation=rotation,
                # )

    except Exception as e:
        client.logger.error(f"Unexpected error in main loop: {e}")
    
    finally:
        # 試合終了後、あるいはエラー時に溜まったログをファイルに書き出す
        # ファイル名（チーム名や時刻）の生成やディレクトリ作成はライブラリが自動で行います
        client.save_log_file()

if __name__ == "__main__":
    asyncio.run(main())