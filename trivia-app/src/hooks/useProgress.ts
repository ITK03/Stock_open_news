import { useCallback, useEffect, useReducer, useRef } from 'react';
import { AppState } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { MAX_REACTIONS } from '../theme';

export type Entry = {
  /** タップ回数（0〜MAX_REACTIONS） */
  reactions: number;
  /** 長押しで BAD 評価を付けたか */
  bad: boolean;
  /** 詳細画面でブックマークしたか */
  bookmarked: boolean;
};

export type ProgressMap = Record<string, Entry>;

// v2: saved(お気に入り) を bad(ネガティブ評価) + bookmarked に分離した
const STORAGE_KEY = 'trivia:progress:v2';
const WRITE_DEBOUNCE_MS = 500;

const EMPTY: Entry = { reactions: 0, bad: false, bookmarked: false };

function sanitize(raw: unknown): ProgressMap {
  if (!raw || typeof raw !== 'object') return {};
  const out: ProgressMap = {};
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!value || typeof value !== 'object') continue;
    const v = value as Partial<Entry>;
    const reactions = typeof v.reactions === 'number' && Number.isFinite(v.reactions) ? v.reactions : 0;
    out[id] = {
      reactions: Math.min(Math.max(Math.trunc(reactions), 0), MAX_REACTIONS),
      bad: v.bad === true,
      bookmarked: v.bookmarked === true,
    };
  }
  return out;
}

/**
 * 進捗はローカルのみ。ref を正にしているのは、タップ直後に
 * 「今何回目か」を同期で知らないと演出強度が1タップ遅れるため。
 */
export function useProgress() {
  const mapRef = useRef<ProgressMap>({});
  const readyRef = useRef(false);
  const dirtyRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [, rerender] = useReducer((c: number) => c + 1, 0);

  const flush = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!readyRef.current) {
      // 読み込み前に書くと既存データを潰す。ロード完了後に書き直させる。
      dirtyRef.current = true;
      return;
    }
    dirtyRef.current = false;
    // 失敗しても体験は続行させる（保存はあくまでおまけ）
    AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(mapRef.current)).catch(() => {});
  }, []);

  const schedule = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(flush, WRITE_DEBOUNCE_MS);
  }, [flush]);

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => (raw ? sanitize(JSON.parse(raw)) : {}))
      .catch(() => ({} as ProgressMap))
      .then((loaded) => {
        if (!alive) return;
        // 読み込み中に付いたリアクションを消さないよう、既存を優先してマージ
        mapRef.current = { ...loaded, ...mapRef.current };
        readyRef.current = true;
        // ロード待ちの間に捨てた書き込みを取り戻す
        if (dirtyRef.current) flush();
        rerender();
      });
    return () => {
      alive = false;
    };
  }, [flush]);

  // バックグラウンド遷移でデバウンス待ちを取りこぼさない
  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') flush();
    });
    return () => {
      sub.remove();
      flush();
    };
  }, [flush]);

  const get = useCallback((id: number | string): Entry => mapRef.current[String(id)] ?? EMPTY, []);

  /** リアクションを1つ加算し、加算後の回数を返す。上限に達していたら据え置きで返す。 */
  const bumpReaction = useCallback(
    (id: number | string): number => {
      const key = String(id);
      const current = mapRef.current[key] ?? EMPTY;
      if (current.reactions >= MAX_REACTIONS) return current.reactions;
      const next = { ...current, reactions: current.reactions + 1 };
      mapRef.current = { ...mapRef.current, [key]: next };
      schedule();
      rerender();
      return next.reactions;
    },
    [schedule]
  );

  /**
   * BAD を付ける。**トグルにしてある**のは、全ジェスチャーが即実行で誤爆が避けられず、
   * 誤った BAD がコンテンツに恒久的な烙印を残すため。戻り値は適用後の状態。
   */
  const toggleBad = useCallback(
    (id: number | string): boolean => {
      const key = String(id);
      const current = mapRef.current[key] ?? EMPTY;
      const next = !current.bad;
      mapRef.current = { ...mapRef.current, [key]: { ...current, bad: next } };
      schedule();
      rerender();
      return next;
    },
    [schedule]
  );

  /** ブックマークを切り替える。戻り値は適用後の状態。 */
  const toggleBookmark = useCallback(
    (id: number | string): boolean => {
      const key = String(id);
      const current = mapRef.current[key] ?? EMPTY;
      const next = !current.bookmarked;
      mapRef.current = { ...mapRef.current, [key]: { ...current, bookmarked: next } };
      schedule();
      rerender();
      return next;
    },
    [schedule]
  );

  return { get, bumpReaction, toggleBad, toggleBookmark };
}
