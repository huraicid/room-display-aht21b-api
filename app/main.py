"""室温・湿度を配信する FastAPI サーバー。

提供するもの:
    GET /api/climate  … AHT21B の最新の計測結果を JSON で返す
    GET /             … フロントエンドのビルド成果物（存在する場合のみ）

このファイルは相対 import（from .sensor ...）を使っているため、
パッケージとして起動する必要がある。リポジトリのルートで実行する:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .sensor import ClimateReader

# センサーの読み取りはアプリ全体で 1 つだけ持つ
reader = ClimateReader()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """サーバーの起動・終了に合わせて計測スレッドを開始・停止する。"""
    reader.start()  # 起動時: 計測開始
    yield
    reader.stop()  # 終了時: 計測停止


app = FastAPI(lifespan=lifespan)


@app.get("/api/climate")
def climate() -> dict:
    """最新の温湿度を返す。

    レスポンス例（成功時）:
        {"temp": 23.4, "humidity": 45.6, "at": "2026-11-10T21:00:00+09:00",
         "ok": true, "error": null}

    計測に失敗している場合は ok=false となり、error に理由が入る。
    temp / humidity / at は最後に成功したときの値（一度も成功していなければ null）。
    """
    return reader.latest()


# ---------------------------------------------------------------------------
# フロントエンドの静的ファイル配信
# ---------------------------------------------------------------------------
# frontend で `npm run generate` した出力（<リポジトリのルート>/frontend/.output/public）を
# ルート "/" で配信する。ディレクトリが無ければ API のみで起動する。
#
# 注意: "/" へのマウントは全パスにマッチするため、API ルートより後に登録すること。
WEB_DIR = Path(__file__).resolve().parent.parent / "frontend" / ".output" / "public"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
