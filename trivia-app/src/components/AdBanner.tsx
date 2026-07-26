import React, { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { BG, FG } from '../theme';

/** 標準バナー(320x50)相当。実SDK導入時もこの高さを維持すればレイアウトは崩れない。 */
export const AD_BANNER_HEIGHT = 50;

/**
 * 広告枠プレースホルダー。実装差し替え時は中身だけを SDK のバナーに置き換える。
 * 高さを固定しているのは、読み込み前後で本文が動くのを防ぐため。
 */
export const AdBanner = memo(function AdBanner({ slot }: { slot: 'top' | 'bottom' }) {
  return (
    <View style={styles.frame}>
      <Text style={styles.label}>{`AD / ${slot} / 320×50`}</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  frame: {
    height: AD_BANNER_HEIGHT,
    backgroundColor: BG,
    borderColor: FG,
    borderWidth: StyleSheet.hairlineWidth,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    color: FG,
    fontSize: 11,
    letterSpacing: 2,
    fontWeight: '600',
  },
});
