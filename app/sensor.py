"""AHT21B 温湿度センサーの読み取りモジュール。

Raspberry Pi の I2C バスに接続された AHT21B から温度・湿度を定期的に読み取り、
最新の値をスレッドセーフに保持する。

使い方:
    reader = ClimateReader()
    reader.start()          # バックグラウンドで計測開始
    reader.latest()         # 最新の計測結果を dict で取得
    reader.stop()           # 計測停止
"""

import threading
import time
from datetime import datetime

from smbus2 import SMBus, i2c_msg

# ---------------------------------------------------------------------------
# 設定値
# ---------------------------------------------------------------------------

# AHT21B の I2C アドレス（固定値）
ADDR = 0x38

# 使用する I2C バス番号（Raspberry Pi 4 の GPIO2/3 は /dev/i2c-1）
BUS_NUM = 1

# 計測間隔（秒）
INTERVAL_SEC = 10

# ---------------------------------------------------------------------------
# AHT21B のプロトコル定数（データシート準拠）
# ---------------------------------------------------------------------------

# 計測開始コマンド: 0xAC に続けてパラメータ 0x33, 0x00 を送る
CMD_TRIGGER_MEASUREMENT = [0xAC, 0x33, 0x00]

# 計測完了までの待ち時間（秒）。データシート上は 80ms 以上
MEASUREMENT_WAIT_SEC = 0.1

# 読み出すバイト数: ステータス(1) + 湿度/温度データ(5) + CRC(1)
READ_LENGTH = 7

# ステータスバイトの Bit7。1 のときはまだ計測中（busy）
STATUS_BUSY_BIT = 0x80

# 生データは 20bit（= 2^20 段階）で表現される
RAW_FULL_SCALE = 2**20


def _read_once(bus: SMBus) -> tuple[float, float]:
    """センサーから 1 回だけ計測し、(温度[C-deg], 湿度[%]) を返す。

    Raises:
        RuntimeError: センサーが計測中（busy）で値を読めなかった場合。
        OSError: I2C 通信に失敗した場合。
    """
    # 計測開始コマンドを送信
    bus.i2c_rdwr(i2c_msg.write(ADDR, CMD_TRIGGER_MEASUREMENT))

    # 計測が終わるまで待機
    time.sleep(MEASUREMENT_WAIT_SEC)

    # 計測結果（7 バイト）を読み出す
    msg = i2c_msg.read(ADDR, READ_LENGTH)
    bus.i2c_rdwr(msg)
    d = list(msg)

    # ステータスを確認。まだ計測中なら今回は失敗扱い
    if d[0] & STATUS_BUSY_BIT:
        raise RuntimeError("sensor busy")

    # 湿度と温度の生データ（各 20bit）を取り出す
    #
    #    バイト配置（d[1]〜d[5] の 40bit）:
    #      d[1]     d[2]     d[3]          d[4]     d[5]
    #      HHHHHHHH HHHHHHHH HHHH TTTT     TTTTTTTT TTTTTTTT
    #      └──── 湿度 20bit ────┘└──────── 温度 20bit ───────┘
    #
    #    d[3] は上位 4bit が湿度、下位 4bit が温度にまたがっている
    raw_h = (d[1] << 12) | (d[2] << 4) | (d[3] >> 4)
    raw_t = ((d[3] & 0x0F) << 16) | (d[4] << 8) | d[5]

    # 生データを物理量に変換（データシートの換算式）
    #    温度[C-deg] = raw / 2^20 * 200 - 50
    #    湿度[%]  = raw / 2^20 * 100
    temp = raw_t / RAW_FULL_SCALE * 200 - 50
    humidity = raw_h / RAW_FULL_SCALE * 100
    return temp, humidity


class ClimateReader:
    """バックグラウンドスレッドで定期的に温湿度を計測し、最新値を保持するクラス。

    最新値は以下の形式の dict で保持する:
        {
            "temp": float | None,      # 温度[C-deg]（小数第 1 位で丸め）
            "humidity": float | None,  # 湿度[%]（小数第 1 位で丸め）
            "at": str | None,          # 最後に計測に成功した日時（ISO 8601, タイムゾーン付き）
            "ok": bool,                # 直近の計測が成功したか
            "error": str | None,       # 直近の計測が失敗した場合のエラー内容
        }

    計測に失敗した場合でも、temp / humidity / at は前回成功時の値を残し、
    ok と error だけを更新する（表示側で「最後に取れた値」を出し続けられるように）。
    """

    def __init__(self, interval: float = INTERVAL_SEC):
        self._interval = interval

        # _latest は計測スレッドと API スレッドの両方から触るのでロックで保護する
        self._lock = threading.Lock()
        self._latest = {
            "temp": None,
            "humidity": None,
            "at": None,
            "ok": False,
            "error": "not read yet",
        }

        # stop() で立てるフラグ。_run ループの終了と待機の中断に使う
        self._stop = threading.Event()

        # daemon=True: メインプロセス終了時にこのスレッドも一緒に終了させる
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """計測スレッドを開始する。"""
        self._thread.start()

    def stop(self) -> None:
        """計測スレッドに停止を指示する（待機中でもすぐ抜ける）。"""
        self._stop.set()

    def latest(self) -> dict:
        """最新の計測結果のコピーを返す。"""
        with self._lock:
            # 呼び出し側で書き換えられても影響しないようコピーを返す
            return dict(self._latest)

    def _run(self) -> None:
        """計測ループ本体。stop() が呼ばれるまで interval 秒ごとに計測する。"""
        while not self._stop.is_set():
            try:
                # 計測のたびにバスを開き直す（通信エラー後も確実に復帰させるため）
                with SMBus(BUS_NUM) as bus:
                    t, h = _read_once(bus)
                snap = {
                    "temp": round(t, 1),
                    "humidity": round(h, 1),
                    "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "ok": True,
                    "error": None,
                }
            except Exception as e:
                # 失敗時は前回の値を残したまま、ok / error だけ差し替える
                with self._lock:
                    snap = {**self._latest, "ok": False, "error": str(e)}

            with self._lock:
                self._latest = snap

            # interval 秒待つ。stop() が呼ばれたら待機を中断してすぐループを抜ける
            self._stop.wait(self._interval)
