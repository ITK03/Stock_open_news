import React, { memo, useEffect, useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  Extrapolation,
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
  type SharedValue,
} from 'react-native-reanimated';
import { FG } from '../theme';
import { FONT_BLACK } from '../fonts';

/** 破壊の総時間。長いと「嫌なものを見せ続ける」ことになるので短く。 */
export const SHATTER_DURATION = 620;

type Piece = { drift: number; fall: number; spin: number; delay: number };

const rand = (min: number, max: number) => min + Math.random() * (max - min);

const Shard = memo(function Shard({
  ch,
  piece,
  size,
  t,
}: {
  ch: string;
  piece: Piece;
  size: number;
  t: SharedValue<number>;
}) {
  const style = useAnimatedStyle(() => {
    const p = interpolate(t.value, [piece.delay, 1], [0, 1], Extrapolation.CLAMP);
    return {
      transform: [
        { translateX: piece.drift * p },
        // 落下は加速させる（等速だと「崩れた」ではなく「動いた」に見える）
        { translateY: piece.fall * p * p },
        { rotate: `${piece.spin * p}deg` },
        { scale: 1 - 0.25 * p },
      ],
      opacity: interpolate(p, [0, 0.55, 1], [1, 0.85, 0], Extrapolation.CLAMP),
    };
  });

  return (
    <Animated.View style={style}>
      <Text style={[styles.shard, { fontSize: size, lineHeight: size * 1.12 }]}>{ch}</Text>
    </Animated.View>
  );
});

/**
 * BAD の破壊演出。オチを1文字ずつ砕いて落とす。
 *
 * **ネオンを一切使わない。** 色は本文と同じ無彩色のまま。
 * 報酬の通貨（ネオン）を BAD に渡すと、BAD が快感になって娯楽として連打される。
 * 爽快感は色ではなく「砕けて落ちる手触り」と Haptic で出す。
 */
export const ShatterText = memo(function ShatterText({
  text,
  fontSize,
  onDone,
}: {
  text: string;
  fontSize: number;
  onDone: () => void;
}) {
  const chars = useMemo(() => Array.from(text), [text]);
  const pieces = useMemo<Piece[]>(
    () =>
      chars.map(() => ({
        drift: rand(-70, 70),
        fall: rand(160, 340),
        spin: rand(-160, 160),
        // 左から順にごくわずかずつ遅らせると「割れ広がる」ように見える
        delay: rand(0, 0.18),
      })),
    [chars]
  );

  const t = useSharedValue(0);

  useEffect(() => {
    t.value = withTiming(1, { duration: SHATTER_DURATION, easing: Easing.linear }, (finished) => {
      if (finished) runOnJS(onDone)();
    });
  }, []);

  /**
   * 着弾の衝撃は「揺れ」で出す。
   * 背景が黒なので暗くしても沈まないし、明るくすると報酬の閃光に見えてしまう。
   * 揺れなら無彩色のまま衝撃だけを伝えられる。
   */
  const shake = useAnimatedStyle(() => {
    const decay = interpolate(t.value, [0, 0.3], [1, 0], Extrapolation.CLAMP);
    return {
      transform: [{ translateX: Math.sin(t.value * 90) * 9 * decay }],
    };
  });

  return (
    <Animated.View pointerEvents="none" style={[styles.root, shake]}>
      <View style={styles.line}>
        {chars.map((ch, i) => (
          <Shard key={i} ch={ch} piece={pieces[i]} size={fontSize} t={t} />
        ))}
      </View>
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  line: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  shard: {
    color: FG,
    fontFamily: FONT_BLACK,
    letterSpacing: -1,
  },
});
