/**
 * Client-side script analysis. Mirrors the backend ScriptSegmentationAgent
 * (sentence split, 2.5 words/sec, 3–15 s scenes) so numbers shown here match
 * what the server will do.
 */
const WORDS_PER_SECOND = 2.5;
const MIN_SCENE = 3;
const MAX_SCENE = 15;
const MAX_SCENE_WORDS = Math.floor(MAX_SCENE * WORDS_PER_SECOND);

export const MIN_WORDS = 8;
export const MAX_CLIPS = 10;

/** "[Excited, energetic]" style directions steer the voice; they are not spoken or captioned. */
const DIRECTION_RE = /\[[^\]]*[A-Za-z][^\]]*\]/g;
export const countDirections = (t: string) => (t.match(DIRECTION_RE) ?? []).length;
export const stripDirections = (t: string) => t.replace(DIRECTION_RE, ' ').replace(/[“”"]/g, '').replace(/\s+/g, ' ').trim();

const wordCount = (t: string) => t.trim().split(/\s+/).filter(Boolean).length;
const est = (n: number) => n / WORDS_PER_SECOND;

export function splitSentences(text: string): string[] {
  return text.trim().split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
}

/** Same grouping rules as ScriptSegmentationAgent._group_sentences. */
export function estimateSceneCount(script: string): number {
  let groups = 0;
  let buf = 0;
  for (const s of splitSentences(script)) {
    buf += wordCount(s);
    const e = est(buf);
    if (e < MIN_SCENE) continue;
    if (e <= MAX_SCENE) {
      groups += 1;
      buf = 0;
    } else {
      const chunks = Math.ceil(buf / MAX_SCENE_WORDS);
      groups += chunks - 1;
      buf -= (chunks - 1) * MAX_SCENE_WORDS;
    }
  }
  if (buf > 0 && groups === 0) groups = 1;
  return groups;
}

const CTA_RE =
  /\b(follow|subscribe|comment|share|save this|link in (my )?bio|click|tap|visit|sign up|join|download|order|shop|try|get yours|learn more|check (it )?out|dm me|book|call us|available)\b/i;

export interface ScriptInsights {
  chars: number;
  words: number;
  seconds: number;
  scenes: number;
  hook: string;
  hookWords: number;
  hookTip: string | null;
  cta: string | null;
  ready: boolean;
  directions: number;
}

export function analyzeScript(script: string): ScriptInsights {
  const text = stripDirections(script);
  const wc = wordCount(text);
  const sentences = splitSentences(text);
  const hook = sentences[0] ?? '';
  const hookWords = wordCount(hook);
  const closing = sentences.slice(-2).join(' ');

  let hookTip: string | null = null;
  if (hook) {
    if (hookWords > 18) hookTip = 'Your opening line is long. Shorter first lines tend to hold attention better.';
    else if (hookWords < 4) hookTip = 'Your opening line is very short. A few more words of context can help.';
  }

  return {
    chars: script.length,
    words: wc,
    seconds: est(wc),
    scenes: estimateSceneCount(text),
    hook,
    hookWords,
    hookTip,
    cta: sentences.length > 1 && CTA_RE.test(closing) ? sentences[sentences.length - 1] : null,
    ready: wc >= MIN_WORDS,
    directions: countDirections(script),
  };
}

export function titleFromScript(script: string): string {
  const clean = stripDirections(script);
  const first = splitSentences(clean)[0] ?? clean;
  const t = first.replace(/\s+/g, ' ');
  return t.length > 56 ? `${t.slice(0, 54).trimEnd()}…` : t || 'Untitled Reel';
}
