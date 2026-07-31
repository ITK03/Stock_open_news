import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  LayoutChangeEvent,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  Share,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Gesture, GestureDetector, ScrollView } from 'react-native-gesture-handler';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Animated, { runOnJS, useSharedValue } from 'react-native-reanimated';

import { AdBanner } from '../components/AdBanner';
import { bookmarkHaptic } from '../haptics';
import { useDetail } from '../hooks/useDetail';
import type { Entry } from '../hooks/useProgress';
import type { Trivia } from '../data/remote';
import { BG, FG, NEON } from '../theme';
import { FONT_BLACK, FONT_BODY } from '../fonts';

const SWIPE_DISTANCE = 80;
const SWIPE_VELOCITY = 650;

/** スクロール端と判定する余裕。ぴったり0を要求すると端に着けない端末がある。 */
const EDGE_SLOP = 4;

/**
 * 詳細画面。**ここはボタンレスの例外**で、ブックマークと共有だけボタンを置く。
 * フィード画面の「完全ボタンレス」はあくまでフィードに限る。
 *
 * スクロール端に達している時だけ、スワイプが雑学の移動に変わる（オーバースクロール）。
 */
export function DetailScreen({
  item,
  entry,
  version,
  onClose,
  onReaction,
  onBad,
  onBookmark,
  onNext,
  onPrev,
}: {
  item: Trivia;
  entry: Entry;
  version: number;
  onClose: () => void;
  onReaction: (x: number, y: number) => void;
  onBad: () => void;
  onBookmark: () => void;
  onNext: () => void;
  onPrev: () => void;
}) {
  const insets = useSafeAreaInsets();
  const { status, text } = useDetail(item.id, version);
  const scrollRef = useRef(null);

  // ジェスチャー側（UIスレッド）から読むので shared value で持つ
  const atTop = useSharedValue(true);
  const atBottom = useSharedValue(false);

  const [bookmarked, setBookmarked] = useState(entry.bookmarked);

  const handleBookmark = useCallback(() => {
    bookmarkHaptic();
    onBookmark();
    setBookmarked((b) => !b);
  }, [onBookmark]);

  const handleShare = useCallback(() => {
    // 共有は唯一の獲得チャネルなので、オチを本文に必ず含める
    void Share.share({
      message: `${item.setup_text}\n${item.punchline_text}`,
    }).catch(() => {});
  }, [item]);

  // スクロール位置と寸法。端に居るかの判定に使う
  const offsetY = useRef(0);
  const layoutH = useRef(0);
  const contentH = useRef(0);

  const recompute = useCallback(() => {
    atTop.value = offsetY.current <= EDGE_SLOP;
    // 本文が画面に収まりきる場合は contentH <= layoutH なので、
    // スクロールしなくても「下端に居る」と判定される（両方向とも即移動になる）
    atBottom.value = offsetY.current + layoutH.current >= contentH.current - EDGE_SLOP;
  }, []);

  const onScroll = useCallback(
    (e: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, layoutMeasurement, contentSize } = e.nativeEvent;
      offsetY.current = contentOffset.y;
      layoutH.current = layoutMeasurement.height;
      contentH.current = contentSize.height;
      recompute();
    },
    [recompute]
  );

  const onContentSizeChange = useCallback(
    (_w: number, h: number) => {
      contentH.current = h;
      recompute();
    },
    [recompute]
  );

  const onScrollLayout = useCallback(
    (e: LayoutChangeEvent) => {
      layoutH.current = e.nativeEvent.layout.height;
      recompute();
    },
    [recompute]
  );

  const gesture = useMemo(() => {
    const pan = Gesture.Pan()
      .minDistance(12)
      .simultaneousWithExternalGesture(scrollRef)
      .onEnd((e) => {
        const vertical = Math.abs(e.translationY) >= Math.abs(e.translationX);

        if (!vertical) {
          // 右スワイプで閉じる
          if (e.translationX > SWIPE_DISTANCE || e.velocityX > SWIPE_VELOCITY) {
            runOnJS(onClose)();
          }
          return;
        }

        // 端に着いている時だけ雑学の移動に変わる
        const up = e.translationY < -SWIPE_DISTANCE || e.velocityY < -SWIPE_VELOCITY;
        const down = e.translationY > SWIPE_DISTANCE || e.velocityY > SWIPE_VELOCITY;
        if (up && atBottom.value) runOnJS(onNext)();
        else if (down && atTop.value) runOnJS(onPrev)();
      });

    const tap = Gesture.Tap()
      .maxDuration(300)
      .maxDistance(20)
      .onEnd((e, success) => {
        if (success) runOnJS(onReaction)(e.x, e.y);
      });

    const longPress = Gesture.LongPress()
      .minDuration(350)
      .maxDistance(20)
      .onStart(() => {
        runOnJS(onBad)();
      });

    return Gesture.Race(pan, Gesture.Exclusive(tap, longPress));
  }, [onClose, onNext, onPrev, onReaction, onBad]);

  return (
    <View style={styles.root}>
      <View style={[styles.column, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
        <AdBanner slot="top" />

        <GestureDetector gesture={gesture}>
          <Animated.View style={styles.body} collapsable={false}>
            <ScrollView
              ref={scrollRef}
              onScroll={onScroll}
              scrollEventThrottle={16}
              onContentSizeChange={onContentSizeChange}
              onLayout={onScrollLayout}
              contentContainerStyle={styles.content}
            >
              <Text style={styles.setup}>{item.setup_text}</Text>
              <Text style={styles.punch}>{item.punchline_text}</Text>

              {status === 'loading' ? (
                <Text style={styles.note}>読み込み中</Text>
              ) : status === 'error' ? (
                <Text style={styles.note}>詳細を取れなかった</Text>
              ) : (
                <Text style={styles.detail}>{text}</Text>
              )}
            </ScrollView>

            {/* ボタンレスの例外はこの2つだけ */}
            <View style={styles.actions}>
              <Pressable
                onPress={handleBookmark}
                accessibilityRole="button"
                accessibilityLabel={bookmarked ? 'ブックマークを外す' : 'ブックマークする'}
                style={styles.action}
              >
                <Text style={[styles.actionText, bookmarked && styles.actionOn]}>
                  {bookmarked ? '保存済み' : '保存'}
                </Text>
              </Pressable>
              <Pressable
                onPress={handleShare}
                accessibilityRole="button"
                accessibilityLabel="共有する"
                style={styles.action}
              >
                <Text style={styles.actionText}>共有</Text>
              </Pressable>
            </View>
          </Animated.View>
        </GestureDetector>

        <AdBanner slot="bottom" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFill,
    backgroundColor: BG,
    zIndex: 50,
  },
  column: { flex: 1 },
  body: { flex: 1 },
  content: {
    paddingHorizontal: 20,
    paddingVertical: 28,
  },
  setup: {
    color: FG,
    fontFamily: FONT_BODY,
    fontSize: 17,
    letterSpacing: 1,
    marginBottom: 10,
  },
  punch: {
    color: FG,
    fontFamily: FONT_BLACK,
    fontSize: 34,
    lineHeight: 40,
    letterSpacing: -1,
    marginBottom: 26,
  },
  detail: {
    color: FG,
    fontFamily: FONT_BODY,
    fontSize: 17,
    lineHeight: 30,
  },
  note: {
    color: FG,
    fontFamily: FONT_BODY,
    fontSize: 15,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 12,
    paddingBottom: 10,
  },
  action: {
    borderColor: FG,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 22,
    paddingVertical: 10,
  },
  actionText: {
    color: FG,
    fontFamily: FONT_BODY,
    fontSize: 15,
    letterSpacing: 1,
  },
  actionOn: {
    color: NEON[0],
  },
});
