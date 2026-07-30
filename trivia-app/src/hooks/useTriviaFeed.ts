import { useCallback, useEffect, useRef, useState } from 'react';
import { PREFETCH_THRESHOLD } from '../config';
import { HISTORY_LIMIT } from '../theme';
import {
  fetchManifest,
  fetchShard,
  shuffle,
  type Manifest,
  type Trivia,
} from '../data/remote';

export type FeedStatus = 'loading' | 'ready' | 'error';

type Feed = { queue: Trivia[]; pos: number };

const EMPTY: Feed = { queue: [], pos: 0 };

/**
 * 雑学はサーバー配信のみ。**端末に永続化しない**（メモリ内だけ）。
 * これは意図的で、保存してしまうとオフラインのまま起動して広告を出さずに
 * 遊べてしまうため。アプリを起動し直せば必ず通信が必要になる。
 *
 * サーバー負荷を軽くするため、1セッションの通信はマニフェスト1回 +
 * シャード数回（1シャード=既定500件）だけ。全件は取得しないしできない。
 */
export function useTriviaFeed() {
  const [status, setStatus] = useState<FeedStatus>('loading');
  const [feed, setFeed] = useState<Feed>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const manifestRef = useRef<Manifest | null>(null);
  const usedShardsRef = useRef<Set<number>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  // queue/pos を非同期処理から参照するため（setState の反映を待たない）
  const feedRef = useRef<Feed>(EMPTY);
  feedRef.current = feed;

  /** まだ引いていないシャードを優先して1つ選ぶ。全部引いたら履歴を捨てて再抽選。 */
  const pickShard = useCallback((shardCount: number) => {
    const used = usedShardsRef.current;
    if (used.size >= shardCount) used.clear();
    // 数千シャードに対して数回の再抽選で十分当たる
    for (let i = 0; i < 12; i++) {
      const candidate = Math.floor(Math.random() * shardCount);
      if (!used.has(candidate)) return candidate;
    }
    for (let i = 0; i < shardCount; i++) {
      if (!used.has(i)) return i;
    }
    return Math.floor(Math.random() * shardCount);
  }, []);

  /**
   * シャードを1つ取り込む。`append` が false なら初回ロード扱い。
   * 取り込み時に古い履歴を切り詰めて、長時間プレイでメモリが膨らむのを防ぐ。
   */
  const loadShard = useCallback(
    async (append: boolean) => {
      if (busyRef.current) return;
      busyRef.current = true;

      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      try {
        if (!append) {
          setStatus('loading');
          setError(null);
        }

        let manifest = manifestRef.current;
        // マニフェストは軽いが、毎シャードごとに取る必要はない
        if (!manifest || !append) {
          manifest = await fetchManifest(ac.signal);
          manifestRef.current = manifest;
        }

        const index = pickShard(manifest.shardCount);
        const items = await fetchShard(index, manifest.version, ac.signal);
        if (ac.signal.aborted) return;
        usedShardsRef.current.add(index);

        setFeed((prev) => {
          const fresh = shuffle(items);
          if (!append) return { queue: fresh, pos: 0 };
          // 下スワイプで戻れるよう、消費済みも直近 HISTORY_LIMIT 件までは残す。
          // 全部捨てると「前へ戻る」が成立せず、全部残すとメモリが際限なく伸びる。
          const drop = Math.max(0, prev.pos - HISTORY_LIMIT);
          return { queue: [...prev.queue.slice(drop), ...fresh], pos: prev.pos - drop };
        });
        setStatus('ready');
        setError(null);
      } catch (e) {
        if (ac.signal.aborted) return;
        // 先読み失敗は手持ちがある限り黙って見送る（体験を止めない）
        const hasStock = feedRef.current.queue.length - feedRef.current.pos > 1;
        if (append && hasStock) return;
        setStatus('error');
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        busyRef.current = false;
      }
    },
    [pickShard]
  );

  useEffect(() => {
    void loadShard(false);
    return () => abortRef.current?.abort();
  }, [loadShard]);

  const retry = useCallback(() => {
    void loadShard(false);
  }, [loadShard]);

  /** 次の雑学へ。手持ちが薄くなったら先読みする。 */
  const advance = useCallback(() => {
    const { queue, pos } = feedRef.current;
    const remaining = queue.length - pos - 1;

    if (remaining <= 0) {
      // 手持ちが尽きた（通信が細っている）。取り直すまで進めない。
      void loadShard(false);
      return;
    }

    setFeed((f) => ({ ...f, pos: f.pos + 1 }));
    if (remaining <= PREFETCH_THRESHOLD) void loadShard(true);
  }, [loadShard]);

  /** 前の雑学へ戻る。履歴の先頭に居るときは何もしない。 */
  const goBack = useCallback(() => {
    setFeed((f) => (f.pos > 0 ? { ...f, pos: f.pos - 1 } : f));
  }, []);

  const current = feed.queue[feed.pos] ?? null;
  const canGoBack = feed.pos > 0;

  return {
    status,
    error,
    current,
    advance,
    goBack,
    canGoBack,
    retry,
    // 詳細取得のキャッシュ無効化に使う
    version: manifestRef.current?.version ?? 1,
  };
}
