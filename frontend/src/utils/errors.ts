/**
 * The backend stores raw exception text in `job.error` (can include FFmpeg
 * stderr). Never show it – classify it into something understandable.
 */
export interface FriendlyFailure {
  title: string;
  body: string;
}

export function explainJobFailure(raw?: string | null): FriendlyFailure {
  const e = (raw ?? '').toLowerCase();
  if (/tts|voice|elevenlabs|gtts|audio generation|speech/.test(e))
    return {
      title: "The voiceover couldn't be created",
      body: 'The voice service did not respond. Try again, or pick a different voice in Style.',
    };
  if (/ffmpeg|composition|concat|scale|export|zoompan|codec|encoder/.test(e))
    return {
      title: "The video couldn't be rendered",
      body: 'One of your clips may be damaged or in an unusual format. Try re-exporting your clips as MP4 and generate again.',
    };
  if (/clip|scene mapping|ffprobe/.test(e))
    return {
      title: "Your clips couldn't be read",
      body: 'Check that every file is a playable video (MP4, MOV, AVI, MKV or WebM), then try again.',
    };
  if (/script|segmentation|empty/.test(e))
    return {
      title: "Your script couldn't be processed",
      body: 'Check that the script contains normal sentences, then try again.',
    };
  if (/storage|disk|permission/.test(e))
    return {
      title: 'The server could not save your files',
      body: 'This is a problem on the server side. Try again in a moment.',
    };
  return {
    title: "This Reel couldn't be finished",
    body: 'Something went wrong while editing. Try generating it again.',
  };
}
