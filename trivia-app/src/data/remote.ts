import { FETCH_RETRIES, FETCH_TIMEOUT_MS, TRIVIA_BASE_URL } from '../config';

export type Trivia = {
  id: number | string;
  /** 導入。小さめに表示する前フリ。 */
  setup_text: string;
  /** オチ。極太・特大で表示する主役。 */
  punchline_text: string;
};

export type Manifest = {
  version: number;
  shardSize: number;
  shardCount: number;
  total: number;
};

/** 配信は「通信必須」の要なので、失敗理由を区別してUIに出す。 */
export class TriviaFetchError extends Error {
  constructor(
    message: string,
    readonly kind: 'network' | 'format'
  ) {
    super(message);
    this.name = 'TriviaFetchError';
  }
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * タイムアウト付き fetch。AbortController を使うのは、電波が死んでいる時に
 * 既定の長いタイムアウトまで黙って待たされるのを防ぐため。
 */
async function fetchJson(url: string, signal?: AbortSignal): Promise<unknown> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= FETCH_RETRIES; attempt++) {
    if (attempt > 0) {
      // 指数バックオフ。混雑時に総攻撃しない
      await sleep(400 * 2 ** (attempt - 1));
      if (signal?.aborted) throw new TriviaFetchError('中断された', 'network');
    }

    const timer = new AbortController();
    const timeout = setTimeout(() => timer.abort(), FETCH_TIMEOUT_MS);
    const onOuterAbort = () => timer.abort();
    signal?.addEventListener('abort', onOuterAbort);

    try {
      const res = await fetch(url, { signal: timer.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      lastError = e;
    } finally {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', onOuterAbort);
    }
  }

  throw new TriviaFetchError(
    `取得できなかった: ${url} (${String(lastError)})`,
    'network'
  );
}

/**
 * マニフェスト取得。件数に依存せず常に数十バイトなので、毎セッション取っても軽い。
 * ここだけは短TTLで配る（シャードは不変なので恒久キャッシュ）。
 */
export async function fetchManifest(signal?: AbortSignal): Promise<Manifest> {
  // 端末やCDNの古いキャッシュを避けるため、マニフェストだけは毎回鮮度を要求する
  const raw = await fetchJson(`${TRIVIA_BASE_URL}/manifest.json?t=${Date.now()}`, signal);

  if (!raw || typeof raw !== 'object') {
    throw new TriviaFetchError('マニフェストが壊れている', 'format');
  }
  const m = raw as Record<string, unknown>;
  const version = Number(m.version);
  const shardSize = Number(m.shard_size);
  const shardCount = Number(m.shard_count);
  const total = Number(m.total);

  if (!Number.isFinite(shardCount) || shardCount < 1) {
    throw new TriviaFetchError('配信可能な雑学が無い', 'format');
  }
  return {
    version: Number.isFinite(version) ? version : 1,
    shardSize: Number.isFinite(shardSize) ? shardSize : 0,
    shardCount,
    total: Number.isFinite(total) ? total : 0,
  };
}

function toTrivia(raw: unknown): Trivia | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const id = o.i;
  const punchline = typeof o.p === 'string' ? o.p : '';
  const setup = typeof o.s === 'string' ? o.s : '';
  // オチが無い雑学は表示しても意味がないので落とす
  if (!punchline) return null;
  if (typeof id !== 'number' && typeof id !== 'string') return null;
  return { id, setup_text: setup, punchline_text: punchline };
}

/**
 * シャード1つ取得。パスは不変なので CDN のエッジでほぼ100%返り、オリジンには届かない。
 * version はクライアント側から強制的に無効化したい時だけ効かせる。
 */
export async function fetchShard(
  index: number,
  version: number,
  signal?: AbortSignal
): Promise<Trivia[]> {
  const name = String(index).padStart(6, '0');
  const raw = await fetchJson(`${TRIVIA_BASE_URL}/shards/${name}.json?v=${version}`, signal);

  if (!Array.isArray(raw)) {
    throw new TriviaFetchError('シャードが配列でない', 'format');
  }
  const items = raw.map(toTrivia).filter((x): x is Trivia => x !== null);
  if (items.length === 0) {
    throw new TriviaFetchError('シャードが空', 'format');
  }
  return items;
}

/**
 * 詳細ファイルの配置先を決めるハッシュ（FNV-1a）。
 * 100万件を1ディレクトリに置くとオブジェクト一覧や同期が破綻するので、
 * 4096個のディレクトリに分散させる。**サーバー側の生成器と同じ実装**であること。
 */
export function detailBucket(id: number | string): string {
  const s = String(id);
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    // FNV prime を 32bit で掛ける（Math.imul でオーバーフローを揃える）
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return (h % 4096).toString(16).padStart(3, '0');
}

/**
 * 詳細説明を取得する。本文シャードには同梱しない（同梱するとシャードが
 * 数倍に膨らみ「1リクエストで500件」の軽さが崩れる）。
 * 詳細を読むのは左スワイプされた一部の雑学だけなので個別取得が最も軽い。
 */
export async function fetchDetail(
  id: number | string,
  version: number,
  signal?: AbortSignal
): Promise<string> {
  const url = `${TRIVIA_BASE_URL}/details/${detailBucket(id)}/${encodeURIComponent(String(id))}.json?v=${version}`;
  const raw = await fetchJson(url, signal);

  if (!raw || typeof raw !== 'object') {
    throw new TriviaFetchError('詳細が壊れている', 'format');
  }
  const text = (raw as Record<string, unknown>).d;
  if (typeof text !== 'string' || !text) {
    throw new TriviaFetchError('詳細が空', 'format');
  }
  return text;
}

/** Fisher-Yates。シャード内の並びをそのまま出すと毎回同じ順になるため。 */
export function shuffle<T>(list: T[]): T[] {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
