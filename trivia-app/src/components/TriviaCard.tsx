import React, { memo, useEffect } from 'react';
import { StyleSheet, Text } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import { FG } from '../theme';
import { FONT_BLACK, FONT_BODY } from '../fonts';
import type { Trivia } from '../data/trivia';

const PUNCH_MAX = 82;
const PUNCH_MIN = 28;
const PUNCH_MAX_LINES = 3;

/**
 * 日本語は全角前提で「1文字 ≒ fontSize」として行数を見積もり、
 * PUNCH_MAX_LINES に収まる最大サイズを選ぶ。端数は adjustsFontSizeToFit に任せる。
 */
function punchFontSize(text: string, width: number) {
  if (!text.length || width <= 0) return PUNCH_MIN;
  const fit = (width * PUNCH_MAX_LINES) / text.length;
  return Math.max(PUNCH_MIN, Math.min(PUNCH_MAX, Math.floor(fit)));
}

export const TriviaCard = memo(function TriviaCard({
  item,
  width,
  kick,
}: {
  item: Trivia;
  width: number;
  /** リアクション時に親から叩かれる 0..1 のパルス。オチだけを弾ませる。 */
  kick: SharedValue<number>;
}) {
  // 切り替えは「遅延ゼロ」が要件なので、入場は最短で抜ける
  const enter = useSharedValue(0);

  useEffect(() => {
    enter.value = 0;
    enter.value = withTiming(1, { duration: 130, easing: Easing.out(Easing.cubic) });
  }, [item.id]);

  const enterStyle = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ scale: 0.94 + enter.value * 0.06 }],
  }));

  const punchStyle = useAnimatedStyle(() => ({
    transform: [{ scale: 1 + kick.value * 0.14 }],
  }));

  const size = punchFontSize(item.punchline_text, width);

  return (
    <Animated.View style={[styles.root, enterStyle]}>
      <Text style={styles.setup} numberOfLines={2}>
        {item.setup_text}
      </Text>

      <Animated.View style={punchStyle}>
        <Text
          style={[styles.punch, { fontSize: size, lineHeight: size * 1.12 }]}
          numberOfLines={PUNCH_MAX_LINES}
          adjustsFontSizeToFit
          minimumFontScale={0.5}
        >
          {item.punchline_text}
        </Text>
      </Animated.View>
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  setup: {
    color: FG,
    fontSize: 20,
    // fontFamily とウェイトを併用しない（iOS で合成ボールドが二重にかかる）
    fontFamily: FONT_BODY,
    letterSpacing: 1,
    textAlign: 'center',
    marginBottom: 18,
  },
  punch: {
    color: FG,
    fontFamily: FONT_BLACK,
    // 特大フォントは字間を詰めた方が「塊」として強く見える
    letterSpacing: -1,
    textAlign: 'center',
  },
});
