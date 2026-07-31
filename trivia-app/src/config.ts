/**
 * 雑学の配信元。ビルド時に EXPO_PUBLIC_TRIVIA_BASE_URL で差し替える。
 * ローカル検証なら `python3 -m src.trivia.build && cd dist && python3 -m http.server 8080` して
 * 実機から届くLAN内アドレス（例 http://192.168.0.5:8080/trivia）を指す。
 */
export const TRIVIA_BASE_URL = (
  process.env.EXPO_PUBLIC_TRIVIA_BASE_URL ?? 'http://localhost:8080/trivia'
).replace(/\/+$/, '');

/** 1リクエストのタイムアウト。長く待たせるより早く「通信が必要」を出す。 */
export const FETCH_TIMEOUT_MS = 8000;

/** 取得失敗時の再試行回数（指数バックオフ）。 */
export const FETCH_RETRIES = 2;

/** 手持ちがこの件数を切ったら次のシャードを先読みする。 */
export const PREFETCH_THRESHOLD = 40;
