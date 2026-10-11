import { useCallback, useEffect, useRef, useState } from 'react';
import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from 'lucide-react';
import { formatDuration } from '@/utils/format';

interface Props {
  src: string;
  onError?: () => void;
  onDuration?: (sec: number) => void;
}

type FsVideo = HTMLVideoElement & { webkitEnterFullscreen?: () => void };

/** Vertical 9:16 player with custom, keyboard-accessible controls. Streams from the server. */
export function VideoPreview({ src, onError, onDuration }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const vid = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const [vol, setVol] = useState(1);
  const [muted, setMuted] = useState(false);
  const [fs, setFs] = useState(false);

  useEffect(() => {
    const on = () => setFs(document.fullscreenElement === box.current);
    document.addEventListener('fullscreenchange', on);
    return () => document.removeEventListener('fullscreenchange', on);
  }, []);

  const toggle = useCallback(() => {
    const v = vid.current;
    if (!v) return;
    if (v.paused) void v.play().catch(() => undefined);
    else v.pause();
  }, []);

  const toggleFs = () => {
    const el = box.current;
    const v = vid.current as FsVideo | null;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (el?.requestFullscreen) void el.requestFullscreen();
    else v?.webkitEnterFullscreen?.(); // iOS Safari
  };

  return (
    <div
      ref={box}
      className="group relative mx-auto aspect-[9/16] w-full max-w-[22rem] overflow-hidden rounded-[1.75rem] border border-line bg-black shadow-[0_30px_80px_-30px_rgb(var(--violet)/.45)] lg:max-h-[78vh] lg:max-w-none"
    >
      <video
        ref={vid}
        src={src}
        playsInline
        preload="metadata"
        className="h-full w-full cursor-pointer object-contain"
        onClick={toggle}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          setDur(e.currentTarget.duration);
          onDuration?.(e.currentTarget.duration);
        }}
        onVolumeChange={(e) => {
          setVol(e.currentTarget.volume);
          setMuted(e.currentTarget.muted);
        }}
        onError={onError}
        aria-label="Reel preview"
      />

      {!playing && (
        <button
          type="button"
          onClick={toggle}
          aria-label="Play"
          className="absolute inset-0 m-auto grid h-16 w-16 place-items-center rounded-full bg-black/55 text-white backdrop-blur transition hover:scale-105"
        >
          <Play size={28} className="translate-x-0.5" fill="currentColor" />
        </button>
      )}

      <div className="absolute inset-x-0 bottom-0 space-y-2 bg-gradient-to-t from-black/85 via-black/40 to-transparent px-3 pb-3 pt-10">
        <input
          type="range"
          aria-label="Seek"
          min={0}
          max={dur || 0}
          step={0.05}
          value={time}
          onChange={(e) => {
            const t = Number(e.target.value);
            if (vid.current) vid.current.currentTime = t;
            setTime(t);
          }}
          className="h-1.5 w-full cursor-pointer"
        />
        <div className="flex items-center gap-1.5 text-white">
          <button type="button" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'} className="grid h-10 w-10 place-items-center rounded-lg hover:bg-white/15">
            {playing ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
          </button>
          <span className="min-w-[5.5rem] text-xs tabular-nums text-white/80">
            {formatDuration(time)} / {formatDuration(dur)}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => {
              if (vid.current) vid.current.muted = !vid.current.muted;
            }}
            aria-label={muted || vol === 0 ? 'Unmute' : 'Mute'}
            className="grid h-10 w-10 place-items-center rounded-lg hover:bg-white/15"
          >
            {muted || vol === 0 ? <VolumeX size={18} /> : <Volume2 size={18} />}
          </button>
          <input
            type="range"
            aria-label="Volume"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : vol}
            onChange={(e) => {
              if (!vid.current) return;
              vid.current.volume = Number(e.target.value);
              vid.current.muted = false;
            }}
            className="hidden h-1.5 w-16 cursor-pointer sm:block"
          />
          <button type="button" onClick={toggleFs} aria-label={fs ? 'Exit full screen' : 'Full screen'} className="grid h-10 w-10 place-items-center rounded-lg hover:bg-white/15">
            {fs ? <Minimize size={18} /> : <Maximize size={18} />}
          </button>
        </div>
      </div>
    </div>
  );
}
