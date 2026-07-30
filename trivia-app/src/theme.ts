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

export const MAX_REACTIONS = 5;

/** ダブルタップ n 回目の演出強度。1〜5 で単調増加させる。 */
export const REACTION_LEVELS = [
  { particles: 10, spread: 90, size: 10, duration: 480, ring: 0.45 },
  { particles: 18, spread: 150, size: 12, duration: 540, ring: 0.65 },
  { particles: 28, spread: 220, size: 14, duration: 620, ring: 0.85 },
  { particles: 40, spread: 300, size: 16, duration: 700, ring: 1.05 },
  { particles: 64, spread: 460, size: 20, duration: 900, ring: 1.6 },
] as const;

/**
 * 上スワイプ何回ごとにインタースティシャルを挟むか。
 * 15回だと体感30〜75秒ごとに全画面広告が出て離脱するため 30 に緩めている。
 */
export const INTERSTITIAL_EVERY = 30;
