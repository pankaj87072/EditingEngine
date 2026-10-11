import { useId, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, Film, GripVertical, Loader2, UploadCloud, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { useDraft } from '@/lib/draft';
import { formatBytes, formatDuration } from '@/utils/format';
import { ACCEPTED_EXT, isLandscape } from '@/utils/video';
import { MAX_CLIPS } from '@/utils/script';

export function ClipUploader() {
  const { clips, addFiles, removeClip, moveClip } = useDraft();
  const inputId = useId();
  const [over, setOver] = useState(false);
  const [notes, setNotes] = useState<string[]>([]);
  const dragFrom = useRef<number | null>(null);
  const [dropAt, setDropAt] = useState<number | null>(null);

  const take = (list: FileList | null) => {
    if (!list?.length) return;
    setNotes(addFiles(Array.from(list)));
  };

  return (
    <div className="space-y-5">
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes('Files')) {
            e.preventDefault();
            setOver(true);
          }
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files);
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors',
          'focus-within:ring-2 focus-within:ring-azure',
          over ? 'border-violet bg-violet/10' : 'border-line bg-surface hover:border-mute/60',
        )}
      >
        <UploadCloud size={30} className="mb-3 text-violet" aria-hidden />
        <span className="text-base font-medium">Drop your clips here, or choose files</span>
        <span className="mt-1 text-sm text-mute">
          MP4, MOV, AVI, MKV or WebM. Up to {MAX_CLIPS} clips. Any orientation.
        </span>
        <input
          id={inputId}
          type="file"
          multiple
          accept={`video/*,${ACCEPTED_EXT.join(',')}`}
          className="sr-only"
          onChange={(e) => {
            take(e.target.files);
            e.target.value = '';
          }}
        />
      </label>

      <div aria-live="polite">
        {notes.length > 0 && (
          <ul className="space-y-1 rounded-xl border border-warn/30 bg-warn/10 p-3 text-sm text-warn">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>

      {clips.length > 0 && (
        <div>
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-base font-semibold">
              {clips.length} {clips.length === 1 ? 'clip' : 'clips'}
            </h3>
            <p className="text-xs text-mute">Clips are used in this order. Drag or use the arrows to reorder.</p>
          </div>
          <ol className="space-y-2">
            {clips.map((c, i) => (
              <li
                key={c.id}
                draggable
                onDragStart={(e) => {
                  dragFrom.current = i;
                  e.dataTransfer.effectAllowed = 'move';
                }}
                onDragOver={(e) => {
                  if (dragFrom.current != null) {
                    e.preventDefault();
                    setDropAt(i);
                  }
                }}
                onDrop={(e) => {
                  if (dragFrom.current != null) {
                    e.preventDefault();
                    moveClip(dragFrom.current, i);
                  }
                  dragFrom.current = null;
                  setDropAt(null);
                }}
                onDragEnd={() => {
                  dragFrom.current = null;
                  setDropAt(null);
                }}
                className={cn(
                  'card flex items-center gap-3 p-2.5 pr-2',
                  dropAt === i && dragFrom.current !== i && 'border-violet',
                )}
              >
                <GripVertical size={16} className="hidden shrink-0 cursor-grab text-mute sm:block" aria-hidden />
                <div className="grid h-[4.5rem] w-12 shrink-0 place-items-center overflow-hidden rounded-lg bg-raised">
                  {c.thumb ? (
                    <img src={c.thumb} alt="" className="h-full w-full object-cover" draggable={false} />
                  ) : c.state === 'reading' ? (
                    <Loader2 size={16} className="animate-spin text-mute" aria-label="Reading clip" />
                  ) : (
                    <Film size={16} className="text-mute" aria-hidden />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium" title={c.name}>
                    {c.name}
                  </p>
                  <p className="mt-0.5 text-xs text-mute">
                    {c.state === 'reading'
                      ? 'Reading…'
                      : c.state === 'unreadable'
                        ? `${formatBytes(c.size)}. Preview unavailable in this browser, it will still be uploaded.`
                        : `${formatDuration(c.duration)} long, ${formatBytes(c.size)}`}
                  </p>
                  {isLandscape(c) && (
                    <p className="mt-0.5 text-xs text-warn">Landscape clip: the sides will be cropped to fit vertical.</p>
                  )}
                </div>
                <div className="flex shrink-0 items-center">
                  <IconBtn label={`Move ${c.name} up`} disabled={i === 0} onClick={() => moveClip(i, i - 1)}>
                    <ArrowUp size={16} />
                  </IconBtn>
                  <IconBtn label={`Move ${c.name} down`} disabled={i === clips.length - 1} onClick={() => moveClip(i, i + 1)}>
                    <ArrowDown size={16} />
                  </IconBtn>
                  <IconBtn label={`Remove ${c.name}`} onClick={() => removeClip(c.id)} danger>
                    <X size={16} />
                  </IconBtn>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function IconBtn({ label, onClick, disabled, danger, children }: { label: string; onClick: () => void; disabled?: boolean; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'grid h-10 w-10 place-items-center rounded-lg text-mute transition-colors hover:bg-raised disabled:opacity-30 disabled:hover:bg-transparent',
        danger ? 'hover:text-bad' : 'hover:text-ink',
      )}
    >
      {children}
    </button>
  );
}
