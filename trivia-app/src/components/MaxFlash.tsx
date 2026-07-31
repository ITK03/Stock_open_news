import React, { memo, useEffect } from 'react';
import { StyleSheet, useWindowDimensions } from 'react-native';
import Animated, {
  Easing,
  Extrapolation,
  interpolate,
  interpolateColor,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';
import { NEON } from '../theme';

const DURATION = 850;

/**
 * 5回目（MAX）専用の全画面演出。trigger が増えるたびに一度だけ走る。
 * 常時マウントしておき、非アクティブ時は opacity 0 なので描画コストはほぼゼロ。
 */
export const MaxFlash = memo(function MaxFlash({ trigger }: { trigger: number }) {
  const { width, height } = useWindowDimensions();
  const p = useSharedValue(0);

  useEffect(() => {
    if (trigger === 0) return;
    p.value = 0;
    p.value = withTiming(1, { duration: DURATION, easing: Easing.out(Easing.quad) });
  }, [trigger]);

  const wash = useAnimatedStyle(() => ({
    opacity: interpolate(p.value, [0, 0.04, 0.18, 0.5, 1], [0, 0.9, 0.45, 0.15, 0], Extrapolation.CLAMP),
    backgroundColor: interpolateColor(
      p.value,
      [0, 0.2, 0.4, 0.6, 1],
      [NEON[0], NEON[1], NEON[3], NEON[4], NEON[0]]
    ),
  }));

  // 画面より大きく広がる輪。中央から画面外へ抜けていく。
  const ringSize = Math.max(width, height);
  const ring = useAnimatedStyle(() => ({
    transform: [{ scale: interpolate(p.value, [0, 1], [0.05, 2.2], Extrapolation.CLAMP) }],
    opacity: interpolate(p.value, [0, 0.08, 0.7, 1], [0, 1, 0.3, 0], Extrapolation.CLAMP),
    borderColor: interpolateColor(p.value, [0, 0.5, 1], [NEON[0], NEON[1], NEON[2]]),
  }));

  // 内側の枠。画面が「縁から弾ける」印象を足す。
  const frame = useAnimatedStyle(() => ({
    opacity: interpolate(p.value, [0, 0.06, 0.35, 1], [0, 1, 0.4, 0], Extrapolation.CLAMP),
    borderColor: interpolateColor(p.value, [0, 0.5, 1], [NEON[2], NEON[0], NEON[1]]),
    borderWidth: interpolate(p.value, [0, 0.15, 1], [0, 18, 0], Extrapolation.CLAMP),
  }));

  return (
    <Animated.View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, wash]} />
      <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, frame]} />
      <Animated.View
        pointerEvents="none"
        style={[
          styles.ringWrap,
          {
            width: ringSize,
            height: ringSize,
            marginLeft: -ringSize / 2,
            marginTop: -ringSize / 2,
            borderRadius: ringSize / 2,
          },
          ring,
        ]}
      />
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  ringWrap: {
    position: 'absolute',
    left: '50%',
    top: '50%',
    borderWidth: 10,
  },
});
