# room-display-aht21b-api
温湿度センサー（AHT21B）を使って室温・湿度を計測してAPIで配布するサーバーアプリ

Raspberry Pi 4 に接続した AHT21B から 10 秒ごとに温度・湿度を読み取り、
最新の値を HTTP API（JSON）で返します。

## 必要なもの

- Raspberry Pi 4（Raspberry Pi OS または Ubuntu）
- AHT21B 温湿度センサー
- Python 3.9 以上

## センサーの配線

| AHT21B | Raspberry Pi 4                  |
| ------ | ------------------------------- |
| VIN    | 3.3V（物理ピン 1）              |
| GND    | GND（物理ピン 6）               |
| SDA    | GPIO2 / SDA1（物理ピン 3）      |
| SCL    | GPIO3 / SCL1（物理ピン 5）      |

## セットアップ

### 1. I2C を有効にする

OS によって手順が異なります。

#### Raspberry Pi OS の場合

```sh
sudo raspi-config
# Interface Options → I2C → Enable
```

標準のユーザーは最初から `i2c` グループに入っているため、追加の権限設定は不要です。

#### Ubuntu の場合

Ubuntu には `raspi-config` が標準で入っていません。I2C は多くの場合最初から有効になっていますが、
`/dev/i2c-1` が存在しない場合は `/boot/firmware/config.txt` に次の行があるか確認し、無ければ追記して再起動します。

```
dtparam=i2c_arm=on
```

```sh
sudo reboot
```

また、`sudo` なしで I2C を使えるように、ユーザーを `i2c` グループに追加します（追加後はログインし直してください）。

```sh
sudo usermod -aG i2c $USER
```

#### センサーの認識を確認する（共通）

センサーが認識されているか確認します（`38` が表示されれば OK）。

```sh
sudo apt install -y i2c-tools
i2cdetect -y 1
```

### 2. ソースコードを配置する

```sh
cd ~
git clone <このリポジトリの URL>
cd room-display-aht21b-api
```

ディレクトリ構成は次のとおりです。

```
room-display-aht21b-api/   ← ここで uvicorn を実行する
├── app/
│   ├── __init__.py
│   ├── main.py            … FastAPI アプリ本体
│   └── sensor.py          … AHT21B の読み取り処理
├── frontend/              ← （任意）フロントエンド
├── requirements.txt
└── README.md
```

### 3. 依存パッケージをインストールする

Ubuntu の場合は、先に venv を作るためのパッケージを入れておきます（Raspberry Pi OS では不要です）。

```sh
sudo apt install -y python3-venv
```

```sh
cd ~/room-display-aht21b-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 実行方法

リポジトリのルート（`app/` がある階層）で実行します。

```sh
cd ~/room-display-aht21b-api
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` … 同じネットワーク内の他の端末からもアクセスできるようにします
- `--port 8000` … 待ち受けるポート番号

起動したら、別の端末から次のように動作を確認できます。

```sh
curl http://<Raspberry Pi の IP アドレス>:8000/api/climate
```

ブラウザで `http://<Raspberry Pi の IP アドレス>:8000/docs` を開くと、FastAPI が自動生成する API ドキュメントも見られます。

## 自動起動（systemd）

Raspberry Pi の起動時にサーバーが自動で立ち上がるようにする手順です（Raspberry Pi OS / Ubuntu 共通）。
「セットアップ」の手順を `~/room-display-aht21b-api` で済ませていることを前提とします。

### 1. サービスを登録する

[deploy/room-display-aht21b-api.service](deploy/room-display-aht21b-api.service) の `YOUR_USER` を自分のユーザー名に置き換えて、`/etc/systemd/system/` に配置します。

```sh
cd ~/room-display-aht21b-api
sed "s/YOUR_USER/$USER/g" deploy/room-display-aht21b-api.service | sudo tee /etc/systemd/system/room-display-aht21b-api.service
```

リポジトリを別の場所に置いた場合は、配置後のファイルの `WorkingDirectory` と `ExecStart` のパスを書き換えてください。

### 2. 有効化して起動する

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now room-display-aht21b-api
```

`enable` で起動時に自動で立ち上がるようになり、`--now` で今すぐ起動します。

### よく使うコマンド

```sh
systemctl status room-display-aht21b-api              # 状態を確認する
journalctl -u room-display-aht21b-api -f              # ログを見る
sudo systemctl restart room-display-aht21b-api        # 再起動する（コードを更新したとき）
sudo systemctl disable --now room-display-aht21b-api  # 停止して自動起動を解除する
```

## API

### `GET /api/climate`

最新の温度・湿度を返します。

レスポンス例（成功時）:

```json
{
  "temp": 23.4,
  "humidity": 45.6,
  "at": "2026-11-10T21:00:00+09:00",
  "ok": true,
  "error": null
}
```

| フィールド | 型               | 説明                                                         |
| ---------- | ---------------- | ------------------------------------------------------------ |
| `temp`     | number \| null   | 温度 [℃]（小数第 1 位まで）                                  |
| `humidity` | number \| null   | 湿度 [%]（小数第 1 位まで）                                  |
| `at`       | string \| null   | 最後に計測に成功した日時（ISO 8601、タイムゾーン付き）       |
| `ok`       | boolean          | 直近の計測が成功したかどうか                                 |
| `error`    | string \| null   | 直近の計測が失敗した場合のエラー内容                         |

計測に失敗した場合は `ok` が `false` になり、`error` に理由が入ります。
このとき `temp` / `humidity` / `at` には最後に成功したときの値が残ります
（起動直後でまだ一度も計測していない場合は `null` で、`error` は `"not read yet"` です）。

## フロントエンドの配信（任意）

リポジトリのルート（`app/` と同じ階層）に `frontend/` を置き、そこで `npm run generate` を実行すると、
出力された `frontend/.output/public` を `/` で配信します。
このディレクトリが無い場合は API だけが動きます。

## 設定

[app/sensor.py](app/sensor.py) の先頭の定数で変更できます。

| 定数           | 既定値 | 説明                    |
| -------------- | ------ | ----------------------- |
| `ADDR`         | `0x38` | センサーの I2C アドレス |
| `BUS_NUM`      | `1`    | I2C バス番号            |
| `INTERVAL_SEC` | `10`   | 計測間隔（秒）          |

## ライセンス

[MIT License](LICENSE)
