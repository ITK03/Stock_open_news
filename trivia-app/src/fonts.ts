import { NotoSansJP_500Medium } from '@expo-google-fonts/noto-sans-jp/500Medium';
import { NotoSansJP_900Black } from '@expo-google-fonts/noto-sans-jp/900Black';

/**
 * 日本語の「極太」は OS 任せにできない。
 * Android の日本語フォールバックには Black ウェイトが無く、fontWeight:'900' を指定しても
 * iOS ほど太くならないため、iOS/Android で見た目を揃えるにはフォントを同梱するしかない。
 *
 * ウェイトは2つだけ（各 5.4MB）。ルートから import すると9ウェイト全部
 * バンドルされてしまうので、必ずサブパスで読むこと。
 */
export const FONT_MAP = {
  NotoSansJP_500Medium,
  NotoSansJP_900Black,
};

/** 前フリ用。控えめに置きたいので Medium。 */
export const FONT_BODY = 'NotoSansJP_500Medium';

/** オチ用。極太の主役。 */
export const FONT_BLACK = 'NotoSansJP_900Black';
