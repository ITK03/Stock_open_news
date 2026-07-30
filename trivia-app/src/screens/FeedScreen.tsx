import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { LayoutChangeEvent, StyleSheet, View } from 'react-native';
import { useNetworkState } from 'expo-network';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  Easing,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSequence,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AdBanner } from '../components/AdBanner';
import { ConnectionGate, type GateMode } from '../components/ConnectionGate';
import { InterstitialAd } from '../components/InterstitialAd';
import { MaxFlash } from '../components/MaxFlash';
import { ParticleBurst, type Burst } from '../components/ParticleBurst';
import { SavedToast } from '../components/SavedToast';
import { TriviaCard } from '../components/TriviaCard';
import { reactionCappedHaptic, reactionHaptic, saveHaptic, swipeHaptic } from '../haptics';
import { useProgress } from '../hooks/useProgress';
import { useTriviaFeed } from '../hooks/useTriviaFeed';
import { BG, INTERSTITIAL_EVERY, MAX_REACTIONS } from '../theme';

/** バナーと本文の間隔。ここを詰めると誤タップで広告を踏むので削らない。 */
const CONTENT_GAP = 24;

/** この距離ぶん上に振れたら次へ送る。velocity 判定と OR。 */
const SWIPE_DISTANCE = 80;
const SWIPE_VELOCITY = -650;

/** 同時に走らせるバーストの上限。連打で積み上がって落ちるのを防ぐ。 */
const MAX_CONCURRENT_BURSTS = 6;

export function FeedScreen() {
  const insets = useSafeAreaInsets();
  const { get, bumpReaction, markSaved } = useProgress();

  // 雑学はサーバー配信のみ。端末には残さない（オフラインで遊ばせない）
  const { status, current, advance: advanceFeed, retry } = useTriviaFeed();

  // 通信が切れたら手持ちがあっても止める。広告なしで遊ばれる隙を作らないため。
  const net = useNetworkState();
  const online = net.isInternetReachable !== false && net.isConnected !== false;

  // 現在の雑学を非同期処理から参照する（setState の反映を待たない）
  const currentRef = useRef(current);
  currentRef.current = current;

  const [bursts, setBursts] = useState<Burst[]>([]);
  const burstKeyRef = useRef(0);

  const [maxTrigger, setMaxTrigger] = useState(0);
  const [savedTrigger, setSavedTrigger] = useState(0);
  const [savedLabel, setSavedLabel] = useState('保存しました');

  const [adVisible, setAdVisible] = useState(false);
  const swipeCountRef = useRef(0);

  const [area, setArea] = useState({ width: 0, height: 0 });

  const drag = useSharedValue(0);
  const kick = useSharedValue(0);

  const onContentLayout = useCallback((e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setArea((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
  }, []);

  // 通信が戻ったら黙って取り直す（ユーザーに再試行させない）
  useEffect(() => {
    if (online && status === 'error') retry();
  }, [online, status, retry]);

  /** 上スワイプ確定。遅延ゼロで差し替え、INTERSTITIAL_EVERY 回ごとに全面広告を挟む。 */
  const advance = useCallback(() => {
    advanceFeed();
    setBursts([]);
    swipeHaptic();

    swipeCountRef.current += 1;
    if (swipeCountRef.current % INTERSTITIAL_EVERY === 0) {
      setAdVisible(true);
    }
  }, [advanceFeed]);

  const onReaction = useCallback(
    (x: number, y: number) => {
      const item = currentRef.current;
      if (!item) return;

      if (get(item.id).reactions >= MAX_REACTIONS) {
        // 上限。無音だと故障に見えるので最弱の触覚だけ返す。
        reactionCappedHaptic();
        return;
      }

      const level = bumpReaction(item.id);
      reactionHaptic(level);

      const key = burstKeyRef.current++;
      setBursts((prev) => [...prev.slice(-(MAX_CONCURRENT_BURSTS - 1)), { key, level, x, y }]);

      kick.value = withSequence(
        withTiming(1, { duration: 80, easing: Easing.out(Easing.quad) }),
        withTiming(0, { duration: 260, easing: Easing.out(Easing.quad) })
      );

      if (level === MAX_REACTIONS) setMaxTrigger((t) => t + 1);
    },
    [get, bumpReaction]
  );

  const onSave = useCallback(() => {
    const item = currentRef.current;
    if (!item) return;
    const isNew = markSaved(item.id);
    saveHaptic();
    setSavedLabel(isNew ? '保存しました' : '保存済み');
    setSavedTrigger((t) => t + 1);
  }, [markSaved]);

  const dropBurst = useCallback((key: number) => {
    setBursts((prev) => prev.filter((b) => b.key !== key));
  }, []);

  /**
   * 遊べない理由。オフラインを最優先で見るのは、手持ちの雑学が残っていても
   * 通信が無い間は遊ばせない（=広告なしで遊ばれない）ようにするため。
   */
  const gateMode: GateMode | null = !online
    ? 'offline'
    : status === 'error'
      ? 'error'
      : status === 'loading' || !current
        ? 'loading'
        : null;
  const blocked = gateMode !== null;

  const gesture = useMemo(() => {
    // 全面広告中と、通信が無い／読み込み中は操作させない
    const live = !adVisible && !blocked;

    const doubleTap = Gesture.Tap()
      .enabled(live)
      .numberOfTaps(2)
      .maxDuration(280)
      .maxDelay(220)
      .maxDistance(40)
      .onEnd((e, success) => {
        if (success) runOnJS(onReaction)(e.x, e.y);
      });

    const longPress = Gesture.LongPress()
      .enabled(live)
      .minDuration(350)
      .maxDistance(20)
      .onStart(() => {
        runOnJS(onSave)();
      });

    const pan = Gesture.Pan()
      .enabled(live)
      .activeOffsetY([-12, 12])
      .failOffsetX([-60, 60])
      .onUpdate((e) => {
        // 上は指に追従、下は戻り先が無いので抵抗をかける
        drag.value = e.translationY < 0 ? e.translationY : e.translationY * 0.22;
      })
      .onEnd((e) => {
        const committed = e.translationY < -SWIPE_DISTANCE || e.velocityY < SWIPE_VELOCITY;
        if (committed) {
          // アニメーションで送り出さない。差し替え直後の入場演出で繋ぐ方が速く見える。
          drag.value = 0;
          runOnJS(advance)();
        } else {
          drag.value = withTiming(0, { duration: 140, easing: Easing.out(Easing.cubic) });
        }
      });

    // タップ系はどちらか片方だけ、スワイプとは独立に競わせる
    return Gesture.Race(pan, Gesture.Exclusive(doubleTap, longPress));
  }, [onReaction, onSave, advance, adVisible, blocked]);

  const cardStyle = useAnimatedStyle(() => ({
    transform: [{ translateY: drag.value }],
    opacity: 1 - Math.min(Math.abs(drag.value) / 420, 0.55),
  }));

  return (
    <View style={styles.root}>
      {/* 広告とコンテンツはセーフエリア内。全面広告だけはこの外側に重ねる。 */}
      <View style={[styles.column, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        <AdBanner slot="top" />

        <View style={styles.contentArea} onLayout={onContentLayout}>
          <GestureDetector gesture={gesture}>
            {/* collapsable={false}: Android でこの View が畳まれるとタッチを拾えない */}
            <View style={styles.gestureArea} collapsable={false}>
              {current ? (
                <Animated.View style={[styles.cardLayer, cardStyle]}>
                  <TriviaCard item={current} width={area.width} kick={kick} />
                </Animated.View>
              ) : null}

              {bursts.map((burst) => (
                <ParticleBurst key={burst.key} burst={burst} onDone={dropBurst} />
              ))}

              {/* 広告枠には重ねない。演出はコンテンツ領域内で完結させる。 */}
              <MaxFlash trigger={maxTrigger} />
              <SavedToast trigger={savedTrigger} label={savedLabel} />

              {/* バナーは塞がない（広告は出し続ける）。本文だけを塞ぐ。 */}
              {gateMode ? <ConnectionGate mode={gateMode} onRetry={retry} /> : null}
            </View>
          </GestureDetector>
        </View>

        <AdBanner slot="bottom" />
      </View>

      {adVisible ? <InterstitialAd onClose={() => setAdVisible(false)} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: BG,
  },
  column: {
    flex: 1,
  },
  contentArea: {
    flex: 1,
    paddingVertical: CONTENT_GAP,
  },
  gestureArea: {
    flex: 1,
    overflow: 'hidden',
  },
  cardLayer: {
    flex: 1,
  },
});
