import * as Haptics from 'expo-haptics';

/**
 * 触覚は「撃ちっぱなし」で扱う。シミュレータや Web では reject するので必ず飲む。
 * await すると演出が1フレーム遅れるので、呼び出し側も await しない。
 */
const fire = (p: Promise<void>) => {
  void p.catch(() => {});
};

const impact = (style: Haptics.ImpactFeedbackStyle) => fire(Haptics.impactAsync(style));

/** 弱→強に単調増加する5段のはしご。ImpactFeedbackStyle は iOS/Android 両対応。 */
const LADDER: Haptics.ImpactFeedbackStyle[] = [
  Haptics.ImpactFeedbackStyle.Light,
  Haptics.ImpactFeedbackStyle.Medium,
  Haptics.ImpactFeedbackStyle.Rigid,
  Haptics.ImpactFeedbackStyle.Heavy,
  Haptics.ImpactFeedbackStyle.Heavy,
];

/**
 * リアクション n 回目の振動。level は 1..5。
 * 4回目以降は単発では強さの上限に当たるので、連打して「重さ」を作る。
 */
export function reactionHaptic(level: number) {
  const i = Math.min(Math.max(level, 1), LADDER.length) - 1;
  impact(LADDER[i]);

  if (i >= 3) {
    setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Heavy), 60);
  }
  if (i === LADDER.length - 1) {
    // MAX: 連打 + 成功パターンで「弾けた」感を出す
    setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Heavy), 120);
    setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Heavy), 180);
    setTimeout(() => fire(Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success)), 240);
  }
}

/** これ以上リアクションできない時。無反応だと壊れて見えるので最弱で返す。 */
export function reactionCappedHaptic() {
  impact(Haptics.ImpactFeedbackStyle.Soft);
}

/**
 * BAD（長押し）。**達成パターンを使わない。**
 * 重い一撃で叩き割り、崩落の微振動を尾に引く。
 * ここで Success を鳴らすと BAD が快感になり、娯楽として連打される。
 */
export function badHaptic() {
  impact(Haptics.ImpactFeedbackStyle.Heavy);
  setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Rigid), 70);
  // 崩れ落ちる尾。だんだん弱くして「壊れて散った」感を作る
  setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Medium), 150);
  setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Light), 240);
  setTimeout(() => impact(Haptics.ImpactFeedbackStyle.Soft), 330);
}

/** ブックマーク（詳細画面）。控えめな確定の手応え。 */
export function bookmarkHaptic() {
  impact(Haptics.ImpactFeedbackStyle.Medium);
}

/** 次の雑学へ。切り替えの手応えだけ欲しいので軽く。 */
export function swipeHaptic() {
  fire(Haptics.selectionAsync());
}
