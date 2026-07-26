import { StatusBar } from 'expo-status-bar';
import { StyleSheet } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { FeedScreen } from './src/screens/FeedScreen';
import { BG, MODE } from './src/theme';

export default function App() {
  return (
    // GestureHandlerRootView は最上位に1つだけ。外すと Android でジェスチャーが動かない。
    <GestureHandlerRootView style={styles.root}>
      <SafeAreaProvider>
        <StatusBar style={MODE === 'dark' ? 'light' : 'dark'} />
        <FeedScreen />
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
