/**
 * 配色は「無彩色2色 + アクション時のネオン」だけ。
 * グレーや中間色を足すとコンセプト（通常時ノイズゼロ）が崩れるので増やさない。
 */
export const MODE: 'dark' | 'light' = 'dark';

export const BG = MODE === 'dark' ? '#000000' : '#FFFFFF';
export const FG = MODE === 'dark' ? '#FFFFFF' : '#000000';

/** アクション時のみ登場するネオン。順番に意味はなく、ランダム抽選用のプール。 */
export const NEON = [
  '#00F0FF', // cyan
  '#FF00E5', // magenta
  '#B4FF00', // lime
  '#FFE800', // yellow
  '#7B2DFF', // violet
  '#FF3B00', // orange-red
] as const;

/** 1件あたりのリアクション上限。到達すると自動で次へ送る。 */
export const MAX_REACTIONS = 8;

/**
 * タップ n 回目の演出強度。段階は5つしかない。
 * 上限は8回なので 6〜8回目は増幅の余地が無く、MAX 演出を毎回撃って埋める
 * （8段階へ薄く伸ばすと1回ごとの差が感じられなくなる）。
 */
export const REACTION_LEVELS = [
  { particles: 10, spread: 90, size: 10, duration: 480, ring: 0.45 },
  { particles: 18, spread: 150, size: 12, duration: 540, ring: 0.65 },
  { particles: 28, spread: 220, size: 14, duration: 620, ring: 0.85 },
  { particles: 40, spread: 300, size: 16, duration: 700, ring: 1.05 },
  { particles: 64, spread: 460, size: 20, duration: 900, ring: 1.6 },
] as const;

/** リアクション回数(1〜8) → 演出段階(1〜5)。5に達したら以降は据え置き。 */
export function reactionLevel(count: number): number {
  return Math.min(Math.max(count, 1), REACTION_LEVELS.length);
}

/** 全画面演出を撃つか。5回目で天井に達し、以降は毎回爆発させる。 */
export function isMaxReaction(count: number): boolean {
  return count >= REACTION_LEVELS.length;
}

/**
 * 上限到達から次へ送るまでの待ち。
 * 即送りすると一番大きい快感を自分で潰すので、演出を見せる間を取る。
 */
export const ADVANCE_DELAY_MS = 300;

/**
 * 自動送り直後に評価系（タップ・長押し）を受け付けない時間。
 * 連打の余りが次の雑学に流れ込むのを防ぐ。**スワイプは止めない**（止めると壊れて見える）。
 */
export const INPUT_LOCK_MS = 300;

/** 下スワイプで戻れる件数。無制限に持つと長時間プレイでメモリが膨らむ。 */
export const HISTORY_LIMIT = 50;

/**
 * 上スワイプ何回ごとにインタースティシャルを挟むか。
 * 15回だと体感30〜75秒ごとに全画面広告が出て離脱するため 30 に緩めている。
 */
export const INTERSTITIAL_EVERY = 30;
