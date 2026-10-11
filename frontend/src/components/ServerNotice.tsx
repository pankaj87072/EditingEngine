import { useHealth } from '@/hooks/useHealth';
import { ErrorState } from './ErrorState';
import { friendlyMessage } from '@/api/client';

/** Only renders when the server is unreachable or can't render video. */
export function ServerNotice() {
  const h = useHealth();
  if (h.isError)
    return (
      <ErrorState compact title="Can't reach the server" message={friendlyMessage(h.error)} onRetry={() => void h.refetch()} retryLabel="Check again" />
    );
  if (h.data && !h.data.ffmpeg_available)
    return (
      <ErrorState compact title="The server can't render video yet" message="FFmpeg isn't installed on the server, so Reels can't be generated. Install FFmpeg and restart the server." />
    );
  return null;
}
