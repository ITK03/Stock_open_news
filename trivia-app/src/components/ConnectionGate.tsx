import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { BG, FG, NEON } from '../theme';
import { FONT_BLACK, FONT_BODY } from '../fonts';

export type GateMode = 'loading' | 'offline' | 'error';

const COPY: Record<GateMode, { title: string; body: string; action?: string }> = {
  loading: { title: '読み込み中', body: '雑学を取りに行ってる' },
  offline: {
    title: 'オフライン',
    body: '雑学はネット経由で届く。通信をオンにして',
  },
  error: {
    title: 'つながらない',
    body: '雑学を取れなかった',
    action: 'タップで再試行',
  },
};

/**
 * 通信が無い／取得できない間はフィードを完全に塞ぐ。
 * 雑学を端末に持たせない方針とセットで、「オフラインで広告を出さずに遊ぶ」を成立させない。
 */
export const ConnectionGate = memo(function ConnectionGate({
  mode,
  onRetry,
}: {
  mode: GateMode;
  onRetry: () => void;
}) {
  const copy = COPY[mode];
  const retryable = copy.action != null;

  return (
    <Pressable
      style={styles.root}
      disabled={!retryable}
      onPress={retryable ? onRetry : undefined}
      accessibilityRole={retryable ? 'button' : undefined}
      accessibilityLabel={`${copy.title}。${copy.body}`}
    >
      <Text style={styles.title}>{copy.title}</Text>
      <Text style={styles.body}>{copy.body}</Text>
      {copy.action ? <Text style={styles.action}>{copy.action}</Text> : null}
    </Pressable>
  );
});

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFill,
    backgroundColor: BG,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 28,
  },
  title: {
    color: FG,
    fontFamily: FONT_BLACK,
    fontSize: 40,
    letterSpacing: -1,
    textAlign: 'center',
  },
  body: {
    color: FG,
    fontFamily: FONT_BODY,
    fontSize: 17,
    marginTop: 14,
    textAlign: 'center',
  },
  action: {
    color: NEON[0],
    fontFamily: FONT_BLACK,
    fontSize: 18,
    marginTop: 36,
    textAlign: 'center',
  },
});
