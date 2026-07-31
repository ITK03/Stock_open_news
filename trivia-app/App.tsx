import { useCallback, useEffect } from 'react';
import { useFonts } from 'expo-font';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { FONT_MAP } from './src/fonts';
import { FeedScreen } from './src/screens/FeedScreen';
import { BG, MODE } from './src/theme';

// フォント読み込み中にスプラッシュを閉じさせない（黒→白→黒のちらつき防止）
void SplashScreen.preventAutoHideAsync().catch(() => {});

export default function App() {
  // 日本語フォントは1ウェイト 5.4MB あり、端末によっては読み込みに数百ms かかる
  const [fontsLoaded, fontError] = useFonts(FONT_MAP);

  // フォントが壊れていても無表示で詰まらせない（システムフォントで続行）
  const ready = fontsLoaded || fontError != null;

  useEffect(() => {
    if (ready) void SplashScreen.hideAsync().catch(() => {});
  }, [ready]);

  const onLayoutRoot = useCallback(() => {
    if (ready) void SplashScreen.hideAsync().catch(() => {});
  }, [ready]);

  return (
    // GestureHandlerRootView は最上位に1つだけ。外すと Android でジェスチャーが動かない。
    <GestureHandlerRootView style={styles.root} onLayout={onLayoutRoot}>
      <SafeAreaProvider>
        <StatusBar style={MODE === 'dark' ? 'light' : 'dark'} />
        {ready ? <FeedScreen /> : <View style={styles.root} />}
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: BG,
  },
});
