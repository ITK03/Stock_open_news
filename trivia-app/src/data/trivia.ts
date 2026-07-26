import raw from './trivia.json';

export type Trivia = {
  id: number;
  /** 導入。小さめに表示する前フリ。 */
  setup_text: string;
  /** オチ。極太・特大で表示する主役。 */
  punchline_text: string;
};

export const TRIVIA: Trivia[] = raw as Trivia[];

/**
 * セッションごとに順番を入れ替える（Fisher-Yates）。
 * 毎回同じ並びだと2周目以降の「引きの良さ」が死ぬため。
 */
export function shuffledDeck(): Trivia[] {
  const deck = [...TRIVIA];
  for (let i = deck.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return deck;
}
