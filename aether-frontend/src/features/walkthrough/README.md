# Cinematic walkthrough feature

The photo → film client. Talks to the RE Walkthrough Pro engine over HTTP;
everything else in this app talks to the Aether engine instead.

Route: `/cinematic`. Engine origin: `NEXT_PUBLIC_WALKTHROUGH_API_URL`
(default `http://localhost:4000`). If the engine is not running the route
renders a clear "engine not running" state.

```
features/walkthrough/
├── api/walkthrough-api.ts        the only module here that fetches
├── types/walkthrough.ts          the engine contract, hand-written
├── hooks/                        session, polling with backoff, staged uploads
├── utils/walkthrough-helpers.ts  room labels, stage copy, error copy
└── components/                   uploader, progress, player, summary, approval, revision
```

Things that look wrong until you know why: actions take an explicit id (a
create → upload → generate chain runs in a closure captured before state
updated); `<video>` is keyed on `videoVersion` because the engine rewrites the
master in place; uploads use XMLHttpRequest for real progress; one
`sessionStorage` key holds the in-flight walkthrough id so a refresh does not
orphan a paid render.
