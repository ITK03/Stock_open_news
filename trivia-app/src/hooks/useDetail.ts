import { useEffect, useRef, useState } from 'react';
import { fetchDetail } from '../data/remote';

export type DetailStatus = 'loading' | 'ready' | 'error';

/**
 * 詳細説明の取得。左スワイプで開いた時だけ走る。
 * 本文と同じく端末には保存しない（通信必須の方針を詳細にも適用する）。
 */
export function useDetail(id: number | string | null, version: number) {
  const [status, setStatus] = useState<DetailStatus>('loading');
  const [text, setText] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (id == null) return;

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setStatus('loading');
    setText('');

    fetchDetail(id, version, ac.signal)
      .then((d) => {
        if (ac.signal.aborted) return;
        setText(d);
        setStatus('ready');
      })
      .catch(() => {
        if (ac.signal.aborted) return;
        setStatus('error');
      });

    return () => ac.abort();
  }, [id, version]);

  return { status, text };
}
