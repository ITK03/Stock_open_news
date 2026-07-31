import React, { memo, useEffect, useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
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
import { NEON, REACTION_LEVELS } from '../theme';

type Spec = {
  angle: number;
  dist: number;
  color: string;
  size: number;
  long: boolean;
  spin: number;
  delay: number;
};

export type Burst = {
  /** 同じ座標で連打されても別インスタンスとして扱うためのキー */
  key: number;
  level: number;
  x: number;
  y: number;
};

const rand = (min: number, max: number) => min + Math.random() * (max - min);

const levelConfig = (level: number) =>
  REACTION_LEVELS[Math.min(Math.max(level, 1), REACTION_LEVELS.length) - 1];

function buildSpecs(level: number): Spec[] {
  const cfg = levelConfig(level);
  const specs: Spec[] = [];
  for (let i = 0; i < cfg.particles; i++) {
    // 均等割り + ゆらぎ。完全ランダムだと粒が偏って「弾けた」感が出ない。
    const base = (i / cfg.particles) * Math.PI * 2;
    specs.push({
      angle: base + rand(-0.25, 0.25),
      dist: cfg.spread * rand(0.45, 1),
      color: NEON[Math.floor(Math.random() * NEON.length)],
      size: cfg.size * rand(0.5, 1.15),
      long: Math.random() < 0.25,
      spin: rand(-540, 540),
      delay: rand(0, 0.12),
    });
  }
  return specs;
}

const Particle = memo(function Particle({
  spec,
  t,
  x,
  y,
}: {
  spec: Spec;
  t: SharedValue<number>;
  x: number;
  y: number;
}) {
  const w = spec.long ? spec.size * 0.35 : spec.size;
  const h = spec.long ? spec.size * 2.2 : spec.size;

  const style = useAnimatedStyle(() => {
    // delay 分を差し引いて 0..1 に伸ばし直す
    const p = interpolate(t.value, [spec.delay, 1], [0, 1], Extrapolation.CLAMP);
    const out = 1 - Math.pow(1 - p, 3); // ease-out: 初速が速く、末端で失速
    const gravity = Math.pow(p, 2) * spec.dist * 0.45;

    return {
      transform: [
        { translateX: Math.cos(spec.angle) * spec.dist * out },
        { translateY: Math.sin(spec.angle) * spec.dist * out + gravity },
        { scale: interpolate(p, [0, 0.15, 0.7, 1], [0, 1.15, 0.9, 0], Extrapolation.CLAMP) },
        { rotate: `${spec.spin * out}deg` },
      ],
      opacity: interpolate(p, [0, 0.08, 0.65, 1], [0, 1, 1, 0], Extrapolation.CLAMP),
    };
  });

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        {
          position: 'absolute',
          left: x - w / 2,
          top: y - h / 2,
          width: w,
          height: h,
          borderRadius: spec.long ? spec.size * 0.2 : spec.size / 2,
          backgroundColor: spec.color,
        },
        style,
      ]}
    />
  );
});

const Shockwave = memo(function Shockwave({
  t,
  level,
  color,
  x,
  y,
}: {
  t: SharedValue<number>;
  level: number;
  color: string;
  x: number;
  y: number;
}) {
  const cfg = levelConfig(level);
  const size = 120;

  const style = useAnimatedStyle(() => ({
    transform: [
      { scale: interpolate(t.value, [0, 1], [0.2, 1 + cfg.ring * 2.4], Extrapolation.CLAMP) },
    ],
    opacity: interpolate(t.value, [0, 0.1, 0.75, 1], [0, 0.9, 0.25, 0], Extrapolation.CLAMP),
  }));

  return (
    <Animated.View
      pointerEvents="none"
      style={[
        {
          position: 'absolute',
          left: x - size / 2,
          top: y - size / 2,
          width: size,
          height: size,
          borderRadius: size / 2,
          borderWidth: 3 + level,
          borderColor: color,
        },
        style,
      ]}
    />
  );
});

/**
 * 1回のダブルタップ = 1インスタンス。演出が終わったら onDone で自分を消してもらう。
 * マウント時に一度だけ進行度を回し、以降は UI スレッドだけで完結する。
 * 粒は画面全体レイヤーに絶対配置する（0x0 の親に置くと Android で切られる）。
 */
export const ParticleBurst = memo(function ParticleBurst({
  burst,
  onDone,
}: {
  burst: Burst;
  onDone: (key: number) => void;
}) {
  const specs = useMemo(() => buildSpecs(burst.level), [burst.level]);
  const ringColor = useMemo(() => NEON[Math.floor(Math.random() * NEON.length)], []);
  const t = useSharedValue(0);

  useEffect(() => {
    const key = burst.key;
    const { duration } = levelConfig(burst.level);
    t.value = withTiming(1, { duration, easing: Easing.linear }, (finished) => {
      if (finished) runOnJS(onDone)(key);
    });
  }, []);

  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      <Shockwave t={t} level={burst.level} color={ringColor} x={burst.x} y={burst.y} />
      {specs.map((spec, i) => (
        <Particle key={i} spec={spec} t={t} x={burst.x} y={burst.y} />
      ))}
    </View>
  );
});
