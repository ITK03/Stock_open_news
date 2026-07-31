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
import { ShatterText } from '../components/ShatterText';
import { TriviaCard, punchFontSize, type EnterFrom } from '../components/TriviaCard';
import { DetailScreen } from './DetailScreen';
import { badHaptic, reactionCappedHaptic, reactionHaptic, swipeHaptic } from '../haptics';
import { useProgress } from '../hooks/useProgress';
import { useTriviaFeed } from '../hooks/useTriviaFeed';
import {
  ADVANCE_DELAY_MS,
  BG,
  INPUT_LOCK_MS,
  INTERSTITIAL_EVERY,
  MAX_REACTIONS,
  isMaxReaction,
  reactionLevel,
} from '../theme';

/** バナーと本文の間隔。ここを詰めると誤タップで広告を踏むので削らない。 */
const CONTENT_GAP = 24;

/** スワイプ確定のしきい値。距離か速度のどちらかを満たせば成立。 */
const SWIPE_DISTANCE = 80;
const SWIPE_VELOCITY = 650;

/** 同時に走らせるバーストの上限。連打で積み上がって落ちるのを防ぐ。 */
const MAX_CONCURRENT_BURSTS = 6;

export function FeedScreen() {
  const insets = useSafeAreaInsets();
  const { get, bumpReaction, toggleBad, toggleBookmark } = useProgress();

  // 雑学はサーバー配信のみ。端末には残さない（オフラインで遊ばせない）
  const { status, current, advance: advanceFeed, goBack, canGoBack, retry, version } =
    useTriviaFeed();

  // 通信が切れたら手持ちがあっても止める。広告なしで遊ばれる隙を作らないため。
  const net = useNetworkState();
  const online = net.isInternetReachable !== false && net.isConnected !== false;

  const currentRef = useRef(current);
  currentRef.current = current;

  const [bursts, setBursts] = useState<Burst[]>([]);
  const burstKeyRef = useRef(0);

  const [maxTrigger, setMaxTrigger] = useState(0);
  const [enterFrom, setEnterFrom] = useState<EnterFrom>('none');

  /** BAD で破壊中の雑学。破壊しきるまでカードの代わりに破片を出す。 */
  const [shattering, setShattering] = useState<string | null>(null);

  const [detailOpen, setDetailOpen] = useState(false);
  const [adVisible, setAdVisible] = useState(false);
  const advanceCountRef = useRef(0);

  const [area, setArea] = useState({ width: 0, height: 0 });

  const drag = useSharedValue({ x: 0, y: 0 });
  const kick = useSharedValue(0);

  /**
   * 評価系（タップ・長押し）を受け付けない期限。
   * 自動送り直後に連打の余りが次の雑学へ流れ込むのを防ぐ。
   * **スワイプはここで止めない**（止めると壊れて見える）。
   */
  const lockUntilRef = useRef(0);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const later = useCallback((fn: () => void, ms: number) => {
    const id = setTimeout(fn, ms);
    timersRef.current.push(id);
  }, []);

  useEffect(
    () => () => {
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
    },
    []
  );

  const onContentLayout = useCallback((e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    setArea((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
  }, []);

  // 通信が戻ったら黙って取り直す（ユーザーに再試行させない）
  useEffect(() => {
    if (online && status === 'error') retry();
  }, [online, status, retry]);

  /** 次の雑学へ。広告の頻度は「前に進んだ回数」で数える（消費量＝広告露出のため）。 */
  const goNext = useCallback(() => {
    advanceFeed();
    setEnterFrom('next');
    setBursts([]);
    setShattering(null);

    advanceCountRef.current += 1;
    if (advanceCountRef.current % INTERSTITIAL_EVERY === 0) setAdVisible(true);
  }, [advanceFeed]);

  const goPrev = useCallback(() => {
    if (!canGoBack) return;
    goBack();
    setEnterFrom('prev');
    setBursts([]);
    setShattering(null);
    swipeHaptic();
  }, [goBack, canGoBack]);

  const onSwipeNext = useCallback(() => {
    swipeHaptic();
    goNext();
  }, [goNext]);

  const onReaction = useCallback(
    (x: number, y: number) => {
      if (Date.now() < lockUntilRef.current) return;
      const item = currentRef.current;
      if (!item || shattering) return;

      if (get(item.id).reactions >= MAX_REACTIONS) {
        // 上限。無音だと故障に見えるので最弱の触覚だけ返す。
        reactionCappedHaptic();
        return;
      }

      const count = bumpReaction(item.id);
      const level = reactionLevel(count);
      reactionHaptic(level);

      const key = burstKeyRef.current++;
      setBursts((prev) => [...prev.slice(-(MAX_CONCURRENT_BURSTS - 1)), { key, level, x, y }]);

      kick.value = withSequence(
        withTiming(1, { duration: 80, easing: Easing.out(Easing.quad) }),
        withTiming(0, { duration: 260, easing: Easing.out(Easing.quad) })
      );

      // 5回目で天井。以降は毎回 MAX 演出を撃って「増えない3回」を作らない。
      if (isMaxReaction(count)) setMaxTrigger((t) => t + 1);

      if (count >= MAX_REACTIONS) {
        // 即送りすると一番大きい快感を自分で潰すので、演出を見せる間を取ってから送る
        lockUntilRef.current = Date.now() + ADVANCE_DELAY_MS + INPUT_LOCK_MS;
        later(goNext, ADVANCE_DELAY_MS);
      }
    },
    [get, bumpReaction, goNext, later, shattering]
  );

  /** BAD。破壊しきってから次へ送る。取り消し（2回目の長押し）は破壊しない。 */
  const onBad = useCallback(() => {
    if (Date.now() < lockUntilRef.current) return;
    const item = currentRef.current;
    if (!item || shattering) return;

    const nowBad = toggleBad(item.id);
    if (!nowBad) {
      // 誤爆の取り消し。壊した演出は出さず、軽い手応えだけ返す。
      reactionCappedHaptic();
      return;
    }

    badHaptic();
    setShattering(item.punchline_text);
    lockUntilRef.current = Date.now() + INPUT_LOCK_MS;
  }, [toggleBad, shattering]);

  /** 破壊が終わったら即座に次へ。嫌だと言われたものを見せ続けない。 */
  const onShatterDone = useCallback(() => {
    lockUntilRef.current = Date.now() + INPUT_LOCK_MS;
    goNext();
  }, [goNext]);

  const dropBurst = useCallback((key: number) => {
    setBursts((prev) => prev.filter((b) => b.key !== key));
  }, []);

  const gateMode: GateMode | null = !online
    ? 'offline'
    : status === 'error'
      ? 'error'
      : status === 'loading' || !current
        ? 'loading'
        : null;
  const blocked = gateMode !== null;

  const gesture = useMemo(() => {
    const live = !adVisible && !blocked && !detailOpen;

    // 単一タップ。ダブルタップにすると2回目を待つ遅延が必ず入る。
    // maxDuration を長押しの minDuration(350) より短くして、判定が重なる帯を作らない。
    const tap = Gesture.Tap()
      .enabled(live)
      .maxDuration(300)
      .maxDistance(20)
      .onEnd((e, success) => {
        if (success) runOnJS(onReaction)(e.x, e.y);
      });

    const longPress = Gesture.LongPress()
      .enabled(live)
      .minDuration(350)
      .maxDistance(20)
      .onStart(() => {
        runOnJS(onBad)();
      });

    const pan = Gesture.Pan()
      .enabled(live)
      .minDistance(12)
      .onUpdate((e) => {
        // 縦横どちらの操作かは、その時点で優勢な軸で決める
        if (Math.abs(e.translationY) >= Math.abs(e.translationX)) {
          drag.value = { x: 0, y: e.translationY };
        } else {
          // 右方向には行き先が無いので抵抗をかける
          drag.value = { x: e.translationX < 0 ? e.translationX : e.translationX * 0.2, y: 0 };
        }
      })
      .onEnd((e) => {
        const vertical = Math.abs(e.translationY) >= Math.abs(e.translationX);
        drag.value = { x: 0, y: 0 };

        if (vertical) {
          if (e.translationY < -SWIPE_DISTANCE || e.velocityY < -SWIPE_VELOCITY) {
            runOnJS(onSwipeNext)();
          } else if (e.translationY > SWIPE_DISTANCE || e.velocityY > SWIPE_VELOCITY) {
            runOnJS(goPrev)();
          }
        } else if (e.translationX < -SWIPE_DISTANCE || e.velocityX < -SWIPE_VELOCITY) {
          runOnJS(setDetailOpen)(true);
        }
      });

    // タップ系はどちらか片方だけ。スワイプとは独立に競わせる。
    return Gesture.Race(pan, Gesture.Exclusive(tap, longPress));
  }, [onReaction, onBad, onSwipeNext, goPrev, adVisible, blocked, detailOpen]);

  const cardStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: drag.value.x }, { translateY: drag.value.y }],
    opacity: 1 - Math.min((Math.abs(drag.value.x) + Math.abs(drag.value.y)) / 420, 0.55),
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
              {current && !shattering ? (
                <Animated.View style={[styles.cardLayer, cardStyle]}>
                  <TriviaCard item={current} width={area.width} kick={kick} from={enterFrom} />
                </Animated.View>
              ) : null}

              {shattering ? (
                <ShatterText
                  text={shattering}
                  fontSize={punchFontSize(shattering, area.width)}
                  onDone={onShatterDone}
                />
              ) : null}

              {bursts.map((burst) => (
                <ParticleBurst key={burst.key} burst={burst} onDone={dropBurst} />
              ))}

              {/* 広告枠には重ねない。演出はコンテンツ領域内で完結させる。 */}
              <MaxFlash trigger={maxTrigger} />

              {gateMode ? <ConnectionGate mode={gateMode} onRetry={retry} /> : null}
            </View>
          </GestureDetector>
        </View>

        <AdBanner slot="bottom" />
      </View>

      {detailOpen && current ? (
        <DetailScreen
          item={current}
          entry={get(current.id)}
          version={version}
          onClose={() => setDetailOpen(false)}
          onReaction={onReaction}
          onBad={onBad}
          onBookmark={() => toggleBookmark(current.id)}
          onNext={() => {
            setDetailOpen(false);
            onSwipeNext();
          }}
          onPrev={() => {
            setDetailOpen(false);
            goPrev();
          }}
        />
      ) : null}

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
