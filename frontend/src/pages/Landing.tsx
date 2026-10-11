import { Link } from 'react-router-dom';
import { AudioLines, Captions, Clapperboard, Crop, FileText, Layers, Upload, Wand2 } from 'lucide-react';
import { buttonClasses } from '@/components/Button';

const HERO_SCENES = [
  { line: 'You scroll past hundreds of videos a day.', w: 'w-[34%]', color: 'bg-violet' },
  { line: 'Here is how to make yours worth a pause.', w: 'w-[38%]', color: 'bg-azure' },
  { line: 'Follow for the full breakdown.', w: 'w-[28%]', color: 'bg-ok' },
];

function HeroMock() {
  return (
    <div className="relative mx-auto w-full max-w-md" aria-hidden>
      <div className="grid grid-cols-[1fr_9.5rem] items-end gap-4 sm:grid-cols-[1fr_11rem]">
        <div className="card space-y-3 p-4">
          <p className="text-xs font-medium text-mute">Script</p>
          {HERO_SCENES.map((s) => (
            <p key={s.line} className="flex gap-2.5 text-sm leading-snug">
              <span className={`mt-0.5 w-1 shrink-0 rounded-full ${s.color}`} />
              {s.line}
            </p>
          ))}
        </div>
        <div className="relative aspect-[9/16] overflow-hidden rounded-[1.5rem] border border-line bg-gradient-to-b from-[#2b2457] via-[#1a2a5e] to-[#0e1a3a] shadow-[0_30px_70px_-25px_rgb(var(--violet)/.55)]">
          <div className="absolute inset-x-0 top-0 h-1/2 bg-[radial-gradient(circle_at_30%_20%,rgb(var(--violet)/.55),transparent_60%)]" />
          <div className="absolute inset-x-0 bottom-[22%] px-3 text-center font-display text-[15px] font-bold leading-tight text-white [text-shadow:0_0_3px_#000,0_1px_5px_#000]">
            Here is how to make yours worth a pause.
          </div>
          <div className="absolute inset-x-3 bottom-3 h-1 rounded-full bg-white/25">
            <div className="h-full w-[52%] rounded-full bg-white" />
          </div>
        </div>
      </div>

      {/* The cut strip: each block is a scene, in the colour of its script line */}
      <div className="mt-4 rounded-2xl border border-line bg-surface p-3">
        <div className="flex h-12 gap-1">
          {HERO_SCENES.map((s) => (
            <div key={s.line} className={`${s.w} overflow-hidden rounded-lg ${s.color}/25 border border-white/5`}>
              <div className={`h-full w-full ${s.color} opacity-30 [background-image:repeating-linear-gradient(90deg,transparent_0_14px,rgb(0_0_0/.25)_14px_15px)]`} />
            </div>
          ))}
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-mute">
          <span>Your clips, cut to the script</span>
          <span>1080 × 1920</span>
        </div>
      </div>
    </div>
  );
}

const STEPS = [
  { icon: FileText, title: 'Paste your script', body: 'Write or paste what the video should say. We split it into scenes sized for short-form.' },
  { icon: Upload, title: 'Add your clips', body: 'Drop in up to 10 raw clips in any orientation. Reorder them to control the sequence.' },
  { icon: Wand2, title: 'Generate the Reel', body: 'Voiceover, captions, transitions and the final vertical export are made for you.' },
];

const FEATURES = [
  { icon: Layers, title: 'Scenes built from your script', body: 'Your script is split into a hook, body and call to action, then cut at natural phrase boundaries so the pacing follows what is being said.', span: 'md:col-span-2' },
  { icon: Clapperboard, title: 'Footage analysed, not guessed', body: 'Each clip is measured for sharpness, motion, cuts and where the subject is. The best part of the best clip lands on each shot, and the same footage is not repeated.', span: '' },
  { icon: AudioLines, title: 'Voiceover included', body: 'Pick a standard or more natural voice. Captions are timed to it.', span: '' },
  { icon: Captions, title: 'Readable captions', body: 'Choose a caption style and position that keeps text clear of the platform buttons.', span: '' },
  { icon: Crop, title: 'Vertical by default', body: 'Landscape and square footage is cropped toward the subject to fill a 9:16 frame with no black bars.', span: 'md:col-span-2' },
];

const FAQ = [
  { q: 'Does AutoVideoGen generate video footage?', a: 'No. Every frame in your Reel comes from the clips you upload. Nothing is generated or replaced with AI imagery.' },
  { q: 'What do I need to start?', a: 'A script and at least one video clip. Clips can be MP4, MOV, AVI, MKV or WebM, up to 10 per Reel.' },
  { q: 'What does the finished video look like?', a: 'A 1080×1920 vertical H.264 MP4 with AAC audio, the format Instagram Reels, TikTok and YouTube Shorts accept.' },
  { q: 'How long does it take?', a: 'It depends on your script length and clip size. The progress screen shows exactly which step is running, and you can leave and come back.' },
  { q: 'Are my clips kept on the server?', a: 'Uploaded clips are removed once the Reel finishes. The finished video stays until you delete it from your dashboard.' },
  { q: 'Will it make my video go viral?', a: 'No tool can promise that. AutoVideoGen formats your video for short-form platforms; how it performs depends on your content.' },
];

export default function Landing() {
  return (
    <>
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-[34rem] bg-[radial-gradient(60%_60%_at_70%_0%,rgb(var(--violet)/.18),transparent_70%)]" />
        <div className="relative mx-auto grid max-w-6xl items-center gap-14 px-4 pb-8 pt-14 sm:px-8 lg:grid-cols-[1.1fr_1fr] lg:pt-24">
          <div>
            <h1 className="text-[2.6rem] font-bold leading-[1.05] sm:text-6xl">Turn your clips into Reels automatically.</h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-mute">
              Upload your script and raw clips. AI creates an editing plan and automatically turns them into a polished vertical short-form video.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link to="/app/new" className={buttonClasses('primary', 'lg')}>Create a Reel</Link>
              <a href="#how" className={buttonClasses('secondary', 'lg')}>See how it works</a>
            </div>
            <p className="mt-5 text-sm text-mute">Exports 1080×1920 MP4. Optimized for short-form content.</p>
          </div>
          <HeroMock />
        </div>
      </section>

      <section id="how" className="mx-auto max-w-6xl scroll-mt-20 px-4 pt-24 sm:px-8">
        <h2 className="max-w-lg text-3xl font-bold sm:text-4xl">Three steps from raw footage to finished Reel</h2>
        <ol className="mt-10 grid gap-4 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="card p-6">
              <div className="flex items-center gap-3">
                <span className="brand-gradient grid h-8 w-8 place-items-center rounded-full text-sm font-bold text-white">{i + 1}</span>
                <s.icon size={20} className="text-mute" aria-hidden />
              </div>
              <h3 className="mt-5 text-lg font-semibold">{s.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-mute">{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 pt-24 sm:px-8">
        <h2 className="max-w-xl text-3xl font-bold sm:text-4xl">Editing decisions made for you, footage left untouched</h2>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className={`card p-6 ${f.span}`}>
              <f.icon size={22} className="text-violet" aria-hidden />
              <h3 className="mt-4 text-lg font-semibold">{f.title}</h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-mute">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pt-24 sm:px-8">
        <div className="card grid gap-10 p-6 sm:p-10 lg:grid-cols-2">
          <div>
            <h2 className="text-3xl font-bold">How the edit is made</h2>
            <p className="mt-4 leading-relaxed text-mute">
              AutoVideoGen never creates footage. It analyses your clips, reads your script, scores every part of every clip against every shot, and picks the best fit. Pacing, camera movement and transitions follow the editing style you choose. An optional AI step can refine those decisions, but the edit works fully without it. The video is then rendered with standard video tools, so the result is consistent.
            </p>
          </div>
          <dl className="grid gap-5 text-sm sm:grid-cols-2">
            <div>
              <dt className="font-semibold">Decided automatically</dt>
              <dd className="mt-2 space-y-1.5 leading-relaxed text-mute">
                <p>Cut points and shot length</p>
                <p>Which part of which clip covers each line</p>
                <p>Crop, movement, speed and highlighted words</p>
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Always from you</dt>
              <dd className="mt-2 space-y-1.5 leading-relaxed text-mute">
                <p>The script and its message</p>
                <p>Every frame of footage</p>
                <p>The voice, captions and transition style</p>
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pt-24 sm:px-8">
        <h2 className="text-3xl font-bold sm:text-4xl">Supported formats</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          <div className="card p-6">
            <h3 className="font-semibold">What you upload</h3>
            <p className="mt-2 text-sm leading-relaxed text-mute">MP4, MOV, AVI, MKV or WebM clips. Up to 10 per Reel, any orientation.</p>
          </div>
          <div className="card p-6">
            <h3 className="font-semibold">What you get</h3>
            <p className="mt-2 text-sm leading-relaxed text-mute">1080×1920 (9:16) H.264 MP4 with AAC audio at 30 fps. Works with Instagram Reels, TikTok and YouTube Shorts.</p>
          </div>
        </div>
      </section>

      <section id="faq" className="mx-auto max-w-3xl scroll-mt-20 px-4 pt-24 sm:px-8">
        <h2 className="text-3xl font-bold sm:text-4xl">Questions</h2>
        <div className="mt-8 divide-y divide-line rounded-2xl border border-line bg-surface">
          {FAQ.map((f) => (
            <details key={f.q} className="group px-5 py-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium [&::-webkit-details-marker]:hidden">
                {f.q}
                <span className="text-mute transition-transform group-open:rotate-45" aria-hidden>+</span>
              </summary>
              <p className="mt-3 text-sm leading-relaxed text-mute">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pt-24 sm:px-8">
        <div className="brand-gradient rounded-3xl px-6 py-14 text-center text-white sm:px-10">
          <h2 className="mx-auto max-w-xl text-3xl font-bold sm:text-4xl">Your next Reel is a script and a few clips away.</h2>
          <Link to="/app/new" className={buttonClasses('secondary', 'lg', 'mt-8 border-white/30 bg-black/30 text-white hover:bg-black/40')}>
            Create a Reel
          </Link>
        </div>
      </section>
    </>
  );
}
