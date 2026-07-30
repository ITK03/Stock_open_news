import React, { memo, useEffect } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withDelay,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { BG, NEON } from '../theme';
import { FONT_BLACK } from '../fonts';

const ACCENT = NEON[0];

/**
 * 長押し保存の確認表示。「一瞬だけ出て消える」ので状態は持たず、
 * trigger の増加だけで完結させる（残り続けると常時ノイズになる）。
 */
export const SavedToast = memo(function SavedToast({
  trigger,
  label,
}: {
  trigger: number;
  label: string;
}) {
  const p = useSharedValue(0);

  useEffect(() => {
    if (trigger === 0) return;
    p.value = 0;
    p.value = withSequence(
      withTiming(1, { duration: 140, easing: Easing.out(Easing.back(2)) }),
      withDelay(620, withTiming(0, { duration: 220, easing: Easing.in(Easing.quad) }))
    );
  }, [trigger]);

  const style = useAnimatedStyle(() => ({
    opacity: p.value,
    transform: [{ scale: 0.82 + p.value * 0.18 }],
  }));

  return (
    <View pointerEvents="none" style={styles.center}>
      <Animated.View style={[styles.chip, style]}>
        <Text style={styles.text}>{label}</Text>
      </Animated.View>
    </View>
  );
});

const styles = StyleSheet.create({
  center: {
    ...StyleSheet.absoluteFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chip: {
    backgroundColor: BG,
    borderColor: ACCENT,
    borderWidth: 3,
    paddingHorizontal: 26,
    paddingVertical: 16,
  },
  text: {
    color: ACCENT,
    fontSize: 30,
    fontFamily: FONT_BLACK,
    letterSpacing: 2,
  },
});
