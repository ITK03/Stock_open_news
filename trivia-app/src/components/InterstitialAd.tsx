import React, { memo, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { BG, FG } from '../theme';

/** 実SDKの「◯秒後にスキップ可」に合わせた擬似クールダウン。 */
const SKIP_AFTER_SEC = 3;

/**
 * 全画面広告プレースホルダー。
 * 表示中はフィードのジェスチャーを完全に塞ぐ（実広告と同じ挙動にするため）。
 */
export const InterstitialAd = memo(function InterstitialAd({ onClose }: { onClose: () => void }) {
  const [remaining, setRemaining] = useState(SKIP_AFTER_SEC);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const id = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(id);
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const skippable = remaining === 0;

  return (
    <View style={styles.root}>
      <Pressable
        style={styles.body}
        disabled={!skippable}
        onPress={() => onCloseRef.current()}
        accessibilityRole="button"
        accessibilityLabel={skippable ? '広告を閉じる' : `あと${remaining}秒で閉じられます`}
      >
        <Text style={styles.tag}>INTERSTITIAL AD</Text>
        <Text style={styles.size}>全画面広告プレースホルダー</Text>
        <Text style={styles.hint}>
          {skippable ? 'タップして閉じる' : `${remaining} 秒後に閉じられます`}
        </Text>
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  root: {
    ...StyleSheet.absoluteFill,
    backgroundColor: BG,
    zIndex: 100,
  },
  body: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    margin: 12,
    borderColor: FG,
    borderWidth: StyleSheet.hairlineWidth,
    borderStyle: 'dashed',
  },
  tag: {
    color: FG,
    fontSize: 20,
    fontWeight: '900',
    letterSpacing: 4,
  },
  size: {
    color: FG,
    fontSize: 13,
    marginTop: 10,
  },
  hint: {
    color: FG,
    fontSize: 15,
    fontWeight: '700',
    marginTop: 40,
  },
});
