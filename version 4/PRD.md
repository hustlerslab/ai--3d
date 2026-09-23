# Allure Interiors V4 — Product Requirements Document

*Version 1.0 · 2026-09-21 · the product contract that `plan.md`, `design.md` and `TRD.md` implement*

**Status labels used throughout:**
`[CURRENT]` works today, verified in the running product · `[PARTIAL]` partly built, or built but not wired · `[V4 REQUIRED]` must ship in V4 · `[FUTURE]` beyond V4 · `[UNKNOWN]` not determined.

**Priority:** `P0` launch-blocking · `P1` core V4 · `P2` important, not blocking · `P3` future.

---

## 1. Executive Summary

Allure helps a homeowner move from *"I have an idea for my home"* to *"I can see it, understand it, check it, change it, and take it to a professional."*

The product takes photographs of a real room and a description in ordinary language, works out what the room is and what the person wants, decides what furniture and finishes should exist, shows them a visual direction, turns the approved pieces into 3D models, works out where everything physically goes, assembles and renders the space, **independently checks that the render actually matches the design it solved**, and hands the person a 3D space they can walk through, question, and revise.

**What makes this different from an AI image generator:** the picture is not the product. The product is a **spatially valid 3D space** whose every object can be traced back to a decision the person approved, and whose correctness has been checked by something other than the system that produced it.

### What exists today `[CURRENT]`

A working nine-step journey: create project → upload and describe → generate moodboard (free, two-phase) → review and refine → plan 3D space → generate 3D space (paid) → view 3D experience → save/share → connect with designer. A human gate where the client approves each piece **before any money is spent**. A deterministic spatial solver that decides where furniture goes. Blender assembly and rendering. An interactive browser scene.

### What V4 adds

| Gap today | V4 requirement |
|---|---|
| A rendered object cannot be traced back to the photo that caused it | Complete, queryable provenance (§28) |
| Nothing checks that the render matches the solved design | Independent verification (§23) |
| Failures surface as raw errors or stall | Bounded automatic repair, then human review (§31, §32) |
| No accounts — anyone reaching the app can spend the owner's money | Authentication, project ownership, spend limits (§43) |
| A silently degraded render has shipped since the beginning | Render quality asserted, not assumed (§21) |
| Designer connection is a non-functional UI mock | Either make it real or label it clearly (§34) |
| The user cannot revise a design without starting over | Editing and versioning (§26–§28) |

### The V4 product promise

> **See the space before you commit to the build.**

Not *"perfect visualization."* Not *"100% accurate."* Not *"construction-ready."* The promise is **reduced uncertainty with visible limits**.

---

## 2. Product Vision

Allure is an **AI-native residential design and execution platform**.

```
HUMAN INTENT
   ↓
UNDERSTAND THE SPACE
   ↓
UNDERSTAND THE DESIGN INTENT
   ↓
IDENTIFY WHAT SHOULD EXIST
   ↓
SHOW WHAT IT LOOKS LIKE
   ↓
CONVERT IT INTO 3D
   ↓
SOLVE WHERE EVERYTHING GOES
   ↓
PRODUCE A PHOTOREALISTIC 3D SPACE
   ↓
VERIFY IT
   ↓
LET THE HUMAN REVIEW AND REFINE IT
   ↓
CONNECT THE DESIGN TO PROFESSIONALS
   ↓
EVENTUALLY CONNECT TO EXECUTION
```

**Philosophy: "From *What if?* to *Let's build.*"**

### What Allure is not

| Not this | Because |
|---|---|
| An AI image generator | An image has no scale, no collision guarantee, no per-object identity, and cannot be quoted or built |
| A moodboard tool | The moodboard is an intermediate step for human approval, not the deliverable |
| A 3D rendering tool | Rendering is the last step, not the product |
| A furniture recommendation engine | Recommendations without spatial validation are guesses about whether things fit |
| A designer marketplace | The marketplace consumes validated design data; it is not the core loop |

**V4 is the combination:** design intelligence **+** spatial intelligence **+** 3D visualization **+** independent verification **+** human review **+** (eventually) professional matchmaking.

The final artifact is a **traceable, spatially valid, photorealistic 3D representation of a residential interior.**

---

## 3. Product Problem

> Residential interior design is difficult because people must make expensive, hard-to-reverse decisions **before** they can reliably see how those decisions work together in their actual space.

### What the person struggles with

| Struggle | What goes wrong today | What Allure changes |
|---|---|---|
| Translating an idea into spatial decisions | "Warm and modern" does not tell you what to buy | Structured design intent from ordinary language (§15) |
| Understanding scale | A sofa that looked right online arrives too big | Metric dimensions carried end to end (§20) |
| Visualizing combinations | Pinterest boards do not combine into one room | One composed room from the approved pieces (§18) |
| Knowing whether furniture fits | Measured by hand, badly, once | Deterministic fit and clearance checking (§20) |
| Understanding circulation | Discovered after delivery | Walkway clearance solved, not eyeballed (§20) |
| Comparing alternatives | Each alternative costs another visit or another purchase | Design versions preserved and comparable (§27–§28) |
| Communicating intent to a professional | "Something like this, but warmer" | A structured design artifact with a bill of elements (§33) |
| **Trusting the visualization** | AI renders look convincing and may be wrong | **Independent verification, with limits stated** (§23) |
| Moving from inspiration to executable design | A gap nothing bridges | Validated design → designer handoff (§34) |

### The core promise, bounded

**"See the space before you commit to the build."**

Explicitly **not** promised: that the design is buildable as drawn, that costs are accurate, that a professional is unnecessary, or that the render is photographically identical to what would be built. §46 makes these boundaries part of the product, not a disclaimer.

---

## 4. Target Users

### Primary V4 user — the homeowner / residential client

The person who owns or rents the space and is deciding what to do with it.

They may bring: room photographs · a floor plan · approximate dimensions · furniture they already own and want to keep · style references and inspiration images · a written description · a budget · material and colour preferences · functional requirements ("we need seating for six").

**They may bring none of that except photos and a sentence.** `[V4 REQUIRED]` The product must work when the person cannot describe design professionally. That is the point.

### Secondary users — explicitly **not** equal V4 scope

| User | V4 scope | Where they appear |
|---|---|---|
| **Interior designers** | `[PARTIAL]` — a connection step exists in the UI but is a non-functional mock (§10.4) | §34 |
| Architects | `[FUTURE]` | §34 |
| Builders / contractors | `[FUTURE]` | §35 |
| Fabricators | `[FUTURE]` | §35 |
| Execution partners | `[FUTURE]` | §35 |
| **Allure internal operations** | `[V4 REQUIRED]` — someone must work the human-review queue | §32 |

**The boundary:** V4's primary experience ends at a **validated design the homeowner accepts**. Everything after that is marketplace extension. The product must be complete and valuable without it.

---

## 5. User Personas

### P1 — Priya, the first-time renovator *(primary)*

Bought a flat, has a living room she dislikes, no design vocabulary. Has phone photos and a Pinterest board. Afraid of spending money on furniture that will not fit or will not go together.

**Needs:** to see her room with new furniture in it, at the right size, before she buys.
**Fails if:** the product demands measurements she does not have, or shows her a beautiful picture she cannot trust.
**Success:** she sees her own room, recognises it, and can tell a designer "this, but the rug in green."

### P2 — Rahul, the keeper *(primary)*

Redoing the living room but keeping an expensive TV unit and a sofa he likes.

**Needs:** existing pieces preserved and designed *around*, not replaced.
**Fails if:** the system silently generates a new TV unit or ignores what he owns.
**Success:** the final scene contains his actual pieces, and he can prove it (§28).

### P3 — Meera, the precise one *(primary)*

Has a floor plan from the builder and exact dimensions. Wants to know whether a six-seater dining table fits with chairs pulled out.

**Needs:** metric truth and clearance she can rely on.
**Fails if:** the product treats her measurements as a suggestion, or cannot say *why* something does not fit.
**Success:** a definite answer with the constraint named.
*Note `[PARTIAL]`: floor-plan intake is accepted but not yet read (§14.4). This persona is not fully served until it is.*

### P4 — Sana, the designer *(secondary, `[FUTURE]`)*

Receives Allure projects as leads.

**Needs:** structured intent, an element list and dimensions — not a mood image.
**Fails if:** the handoff is a render with no data behind it.

### P5 — Arun, Allure operations *(secondary, `[V4 REQUIRED]`)*

Works the human-review queue when the system escalates.

**Needs:** the issue, the evidence, what was already attempted, and clear actions.
**Fails if:** escalations arrive without context, or everything escalates (§32.3).

---

## 6. Jobs To Be Done

| # | Job | Priority | Status |
|---|---|---|---|
| J1 | *When I have an idea for my room, help me see it in my actual space so I can judge it before spending.* | **P0** | `[PARTIAL]` — works; verification and trust missing |
| J2 | *When I don't know design language, understand what I mean anyway.* | **P0** | `[CURRENT]` |
| J3 | *When I already own pieces I like, design around them instead of replacing them.* | **P0** | `[PARTIAL]` |
| J4 | *When I'm unsure whether things fit, tell me definitively.* | **P0** | `[CURRENT]` solver; `[V4 REQUIRED]` to explain it |
| J5 | *When the system guesses, tell me it guessed.* | **P0** | `[V4 REQUIRED]` |
| J6 | *When I want to change one thing, don't make me start over.* | **P1** | `[V4 REQUIRED]` |
| J7 | *When I like a version, let me keep it while I try another.* | **P1** | `[V4 REQUIRED]` |
| J8 | *When I'm ready for a professional, give them something better than a picture.* | **P1** | `[PARTIAL]` |
| J9 | *When something goes wrong, tell me plainly and don't lose my work.* | **P0** | `[V4 REQUIRED]` |
| J10 | *When I want to explore the space, let me move through it.* | **P1** | `[CURRENT]` |

---

## 7. Product Principles

Ten principles. Every requirement in §36 traces to at least one.

### 1. User intent first
The person's intent is the starting point and the thing the system is accountable to. The product never substitutes its own taste for a stated preference.

### 2. Space before decoration
The room and its constraints are established before styling. A beautiful arrangement that does not fit is a failure, not a trade-off.

### 3. Element-first
The system understands the room as **individual elements and their instances**, not as pixels. "Three matching bar stools" is three things that are one kind of thing.

### 4. Identity persistence
An element stays identifiable from the moment it is proposed to the moment it appears in the final render. `[V4 REQUIRED]` — the chain breaks today (§10.3).

### 5. Spatial truth
Final placement is decided by deterministic geometry. Nothing that guesses gets to place furniture.

### 6. Evidence over guessing
Where the system is uncertain, it preserves the uncertainty. It does not manufacture a confident answer to fill a gap.

### 7. Verification before trust
**A beautiful render is not automatically a correct render.** The system that checks is not the system that generated.

### 8. Human control
Review, correct, reject, refine — always available. The system recommends; it does not trap.

### 9. Transparent uncertainty
Meaningful uncertainty is shown. Not every internal confidence score — the ones that change what the person should do.

### 10. Buildability
The output moves toward something a professional can actually discuss and eventually build. Not a picture: a described space.

---

## 8. Product Scope

### MUST HAVE — V4 does not ship without these

| # | Capability | Section |
|---|---|---|
| M1 | Create a residential project with a name, type and description | §13 |
| M2 | Upload room photographs and describe intent in ordinary language | §14 |
| M3 | Structured design understanding, distinguishing **stated facts from inferences** | §15 |
| M4 | Element identification with instance counts | §16–§17 |
| M5 | **Human approval gate before any money is spent** | §17.4 |
| M6 | Element images and a composed moodboard | §18 |
| M7 | 3D assets generated or reused, **one per distinct kind** | §19 |
| M8 | Spatially valid scene — fits, no improper overlap, walkways and doors respected | §20 |
| M9 | Photorealistic render **derived from the validated scene** | §21 |
| M10 | **Independent verification of the render against the scene** | §23 |
| M11 | Bounded automatic repair, then human review | §31–§32 |
| M12 | User review with approve / edit / regenerate / reject | §29 |
| M13 | Interactive 3D viewer | §22 |
| M14 | **Complete provenance** — every object traceable to its source | §28 |
| M15 | Accounts, project ownership, **spend protection** | §43 |
| M16 | Understandable failure messages; **no silent work loss** | §30 |
| M17 | Design versions preserved | §28 |
| M18 | Privacy: consent, retention, deletion | §42 |

### SHOULD HAVE — important, not launch-blocking

S1 natural-language editing ("move the sofa closer to the TV") · S2 floor-plan reading · S3 side-by-side version comparison · S4 material/finish swaps in the viewer · S5 alternate camera views on demand · S6 project duplication · S7 export of the design artifact · S8 richer uncertainty explanations.

### FUTURE — explicitly post-V4

F1 functional designer matchmaking · F2 builder/contractor matching · F3 fabricator matching · F4 bill of quantities · F5 cost estimation · F6 multi-room whole-home projects · F7 commercial and hospitality verticals · F8 learning from accepted designs · F9 AR/on-site preview · F10 procurement links.

**Scope discipline:** anything not in MUST HAVE may be cut without blocking release. Anything in MUST HAVE that slips moves the release, not the bar.

---

## 9. Non-Goals

V4 explicitly does **not** attempt:

| Non-goal | Why | What we say instead |
|---|---|---|
| Fully autonomous architecture | Architectural design requires licensed judgement | "A design direction to take to a professional" |
| Guaranteed construction execution | Allure does not build | "Connects you to people who do" `[FUTURE]` |
| Guaranteed cost estimates | Prices vary by market, supplier and time | Cost is `[FUTURE]`, and will be a range with stated assumptions |
| Building-code compliance in every jurisdiction | Codes are local and change | Clearance uses published general standards, not certified compliance (§46) |
| Automatic structural engineering | Loads, spans and structure need an engineer | Out of scope entirely |
| Replacing professional designers | The product's own end state is *handing off to one* | "Makes the conversation with your designer better" |
| Replacing contractors | Same | Same |
| **Perfect physical measurement from photographs** | Measurement from casual phone photos has real error | Dimensions are estimates unless the person supplies them, and are **labelled as such** (§25) |
| Guaranteeing the render matches reality | Materials, light and manufacture vary | The render faithfully matches **the validated scene** — a different and checkable claim (§21.3) |

**These are product positions, not disclaimers.** They shape what the UI says and what the product refuses to assert.

---

## 10. Current Product Baseline

Read from the running product and the codebase, not from documentation.

### 10.1 The journey that works today `[CURRENT]`

The Studio ships a nine-step flow with cost badges:

| # | Step | UI title | Badge | Status |
|---|---|---|---|---|
| 1 | `project` | "Tell us about your space" | — | `[CURRENT]` |
| 2 | `describe` | "Upload photos and describe your vision" | — | `[CURRENT]` |
| 3 | `moodboard` | "Generate Moodboard" — two-phase | **free** | `[CURRENT]` |
| 4 | `refine` | "Review and refine" | — | `[CURRENT]` |
| 5 | `planspace` | "Plan your 3D space" | — | `[CURRENT]` |
| 6 | `generate3d` | "Generate your 3D space" | **paid** | `[CURRENT]` |
| 7 | `experience` | "View 3D Experience" | — | `[CURRENT]` |
| 8 | `share` | "Save / Share" | — | `[CURRENT]` |
| 9 | `designer` | "Bring a designer into it" | **free** | **`[PARTIAL]` — non-functional mock** |

**Product strengths already shipped, worth protecting:**

- **The two-phase moodboard is genuinely good product design.** Before any room is painted, Allure decides what goes in it and pictures each piece on its own; the person approves the pieces, and *then* the room is painted from them. The UI says so plainly: *"Before any room is painted, Allure decides what goes in it from your photos and your brief, and pictures each piece on its own."*
- **Cost is communicated before it is incurred.** Steps are badged free or paid, and the free step says *"regenerate as often as you like."* Few AI products are this honest about where the money goes.
- **Room sizes are optional and the product says so:** *"Room sizes are optional — the AI estimates what you leave blank."* That is principle 9 already in the copy.
- **A human approves each piece before spend.** The approval gate is real, and it gates generation.

### 10.2 What the engine does today `[CURRENT]`

Reads the brief and the photographs · decides the pieces · pictures each piece on its own · paints a room from them · reads that room back into a list of real objects · lets a human confirm each one · generates 3D meshes for confirmed pieces · **shares one mesh across identical pieces** · lays them out with a deterministic solver enforcing fit, collision and clearance · assembles in Blender · renders · serves an interactive scene and a shareable link.

### 10.3 Verified product gaps

| # | Gap | Product consequence | Status |
|---|---|---|---|
| G1 | **No accounts.** Anyone who can reach the app can open any project and trigger paid generation | Cannot be exposed publicly at all | **`[V4 REQUIRED]`** P0 |
| G2 | **Nothing verifies the render against the scene** | The product cannot honour principle 7 | **`[V4 REQUIRED]`** P0 |
| G3 | **A rendered object cannot be traced to the photo that caused it** | Rahul cannot prove his TV unit survived; a designer handoff is just a picture | **`[V4 REQUIRED]`** P1 |
| G4 | **Render quality has been silently degraded since the beginning** — a colour-management setting is rejected by the renderer and the failure is discarded | Every render to date is duller than intended, and nobody was told | **`[V4 REQUIRED]`** P0 |
| G5 | **Re-reading a moodboard can orphan already-purchased 3D models** | The person can pay twice for the same piece | **`[V4 REQUIRED]`** P1 |
| G6 | **Floor-plan upload is accepted and never read** | Meera believes her floor plan was used. It was not | **`[V4 REQUIRED]`** P1 |
| G7 | ~~One route returns an error page (`/cinematic`)~~ **WITHDRAWN (C1)** — the route is an optional integration that states plainly when its engine is absent; verified in-browser | Not a gap | **`[NOT REQUIRED]`** — no V4 work |
| G8 | **No editing or versioning** | Any change means starting over; an accepted design can be lost | **`[V4 REQUIRED]`** P1 |
| G9 | **No bounded repair or human review** | A failure stalls or surfaces raw | **`[V4 REQUIRED]`** P0 |
| G10 | **The element count shown may be recomputed in the browser** rather than read from the engine | Two numbers that can disagree | **`[V4 REQUIRED]`** P2 |

### 10.4 The designer step, stated honestly

`[PARTIAL]` Step 9 renders three designer cards from **hardcoded sample data**. "Connect" sets a value in browser memory and shows *"Request sent."* **No request is sent.** Nothing is stored. Reloading the page clears it.

**This is a prototype of an intended feature presented as a working one.** V4 must either make it real or label it as a preview (§34.2). Shipping it as-is to real users would be a trust failure of exactly the kind principle 9 exists to prevent.

---

## 11. V4 Product Experience

### 11.1 One product, not a committee of robots

Internally V4 runs several models and engines — a design model, computer vision, a mesh generator, a deterministic spatial solver, Blender, and three internal supervision systems. **The person sees none of that.**

| The person must never see | They see instead |
|---|---|
| "Orchestrator agent invoked spatial repair" | "We found an issue and are correcting the layout." |
| "Validator returned REVIEW_REQUIRED" | "We'd like you to take a look at one thing." |
| "Constraint C-104 failed" | "One chair is too close to the doorway." |
| "Meshy task 429 NoMoreConcurrentTasks" | "Your 3D models are queued — this will take a few more minutes." |
| `element_id = cel_ab12cd34ef` | "3 matching bar stools" |

**Rule:** internal identifiers stay available for support and traceability, and never appear in the primary interface.

### 11.2 The user-facing pipeline

Nine plain-language stages replacing internal job names:

```
UNDERSTANDING YOUR SPACE
        ↓
UNDERSTANDING YOUR STYLE
        ↓
BUILDING YOUR DESIGN
        ↓
CREATING YOUR ELEMENTS
        ↓
BUILDING THE 3D SPACE
        ↓
SOLVING THE LAYOUT
        ↓
RENDERING YOUR SPACE
        ↓
VERIFYING THE DESIGN
        ↓
READY FOR REVIEW
```

`[V4 REQUIRED]` Each stage must show: what is happening in one line · roughly how long it usually takes · whether it costs money · whether the person can leave and come back.

**"Verifying the design" is a visible stage, deliberately.** It is a product differentiator, and it teaches the person that the render was checked.

### 11.3 Progress that does not lie

| Requirement | Why | Status |
|---|---|---|
| Never show a progress bar that cannot complete | Stalls destroy trust faster than failures | `[V4 REQUIRED]` |
| Show the current stage and what it is doing | "Loading" tells the person nothing | `[PARTIAL]` — job events exist |
| Show repair attempts as they happen ("Adjusting the layout — attempt 1 of 2") | A bounded loop the person cannot see looks identical to a hung one | `[V4 REQUIRED]` |
| Allow leaving and returning without losing work | Some stages take minutes | `[CURRENT]` — checkpoints exist |
| Distinguish "working" from "waiting for you" | Different actions required | `[V4 REQUIRED]` |

---

## 12. End-to-End User Journey

| Step | What happens | Person sees | Status |
|---|---|---|---|
| 1 | Create project | Name, room type, short description | `[CURRENT]` |
| 2 | Describe the room | Free-text vision box | `[CURRENT]` |
| 3 | Upload room photographs | Drag-drop, thumbnails, removable | `[CURRENT]` |
| 4 | Upload floor plan / dimensions | Optional fields; "the AI estimates what you leave blank" | **`[PARTIAL]`** — dimensions used; floor plan accepted but not read |
| 5 | Upload style / reference images | Same uploader | `[CURRENT]` |
| 6 | Define existing elements to keep | "Keep the TV unit" | **`[PARTIAL]`** — expressible in text; not a first-class control |
| 7 | Define constraints and preferences | Budget, materials, colours, function | **`[PARTIAL]`** — free text only |
| 8 | System understands the room | "Understanding your space" | `[CURRENT]` |
| 9 | Structured design understanding | Rooms, style, palette — **editable** | `[CURRENT]` |
| 10 | System identifies elements | Element list | `[CURRENT]` |
| 11 | System identifies instances | "3 matching bar stools" | `[CURRENT]` |
| 12 | Canonical element representations | One picture per distinct piece | `[CURRENT]` |
| 13 | Visual composition / moodboard | The painted room | `[CURRENT]` |
| 14 | **Human approves each piece** | Build / Skip per piece | `[CURRENT]` |
| 15 | Elements → 3D assets | "Building the approved pieces in 3D" | `[CURRENT]` |
| 16 | Spatial placement solved | "Solving the layout" | `[CURRENT]` |
| 17 | 3D scene assembled | "Assembling the space in Blender" | `[CURRENT]` |
| 18 | Photorealistic render | The render | **`[PARTIAL]`** — silently degraded (G4) |
| 19 | **Independent validation** | "Verifying the design" | **`[V4 REQUIRED]`** |
| 20 | Repair and re-validate if needed | "Correcting the layout — attempt 1 of 2" | **`[V4 REQUIRED]`** |
| 21 | User reviews | Review screen | **`[PARTIAL]`** — viewer exists; review surface does not |
| 22 | User accepts / edits / rejects | Explicit actions | **`[V4 REQUIRED]`** |
| 23 | Validated design → structured artifact | Design package | **`[V4 REQUIRED]`** |
| 24 | Designer matchmaking | Connect | **`[PARTIAL]`** mock → `[FUTURE]` real |
| 25 | Builder / execution matchmaking | — | `[FUTURE]` |

**Steps 19, 20, 22 and 23 are the V4 product.** Everything before them substantially works. What is missing is the part that makes the output **trustworthy and usable**, rather than merely impressive.

---

## 13. Project Creation

### 13.1 What the person must provide

| Field | Required | Why | Status |
|---|---|---|---|
| Project name | **Yes** | Identification and return | `[CURRENT]` |
| Room / project type | **Yes** | Drives element vocabulary and defaults | `[CURRENT]` |
| Short description | **Yes** | The seed of design intent | `[CURRENT]` |

### 13.2 What is optional

Room photographs · floor plan · dimensions · existing furniture to keep · style references · budget · material preferences · colour preferences · functional constraints.

**A project with only name, type and a sentence must still produce something useful.** `[V4 REQUIRED]` The output will carry more inference and therefore more visible uncertainty (§25) — but the person is not blocked.

### 13.3 Facts vs inference — a first-class distinction

`[V4 REQUIRED]` Every piece of project information is one of:

| Kind | Meaning | Shown as |
|---|---|---|
| **Stated** | The person typed or uploaded it | Plain, no marker |
| **Measured** | Derived deterministically from something stated | Plain, with a source on request |
| **Inferred** | The system decided it | **Visibly marked**, editable |
| **Unresolved** | The system could not decide | **Visibly marked**, asks or defers |

The product already does this for dimensions — *"the AI estimates what you leave blank"* — and V4 extends it to every inferred field. **A person must never discover, late, that a number they assumed was theirs was actually invented.**

---

## 14. Input Experience

### 14.1 Text — the brief

| | |
|---|---|
| **Purpose** | Capture intent in the person's own words |
| **Required** | Yes (short description at creation) |
| **Format** | Free text, no length minimum |
| **Validation** | None on content — the product must not demand design vocabulary |
| **Feedback** | The structured reading is shown back for confirmation (§15) |
| **Failure** | If the brief cannot be parsed into anything structured, the product says so and asks a specific question rather than inventing intent |
| **Privacy** | Treated as personal data (§42) |
| **Status** | `[CURRENT]` |

### 14.2 Room photographs

| | |
|---|---|
| **Purpose** | Understand the actual room, its architecture and what is already in it |
| **Required** | Strongly recommended; not strictly required |
| **Format** | Common image formats; per-file size limit; count limit |
| **Validation** | Type, size and count checked at upload; **filename discarded** |
| **Feedback** | Thumbnails, removable individually |
| **Failure** | Per-file rejection with the reason; other files unaffected |
| **Privacy** | **Photographs of the inside of a home. Highest sensitivity in the product** (§42) |
| **Status** | `[CURRENT]` |

`[V4 REQUIRED]` Every uploaded image is re-encoded on ingest before any model sees it. This is a safety measure against instructions hidden inside image data, and it is invisible to the person.

### 14.3 Dimensions

| | |
|---|---|
| **Purpose** | Ground the design in metric truth |
| **Required** | Optional |
| **Format** | Width / length / height per room |
| **Validation** | Plausibility bounds; implausible values queried, not silently corrected |
| **Feedback** | **Stated dimensions are never overwritten by inference** |
| **Failure** | Missing values are estimated and **marked estimated** |
| **Status** | `[CURRENT]` |

**PR-ROOM-002 depends on this:** a person who supplies dimensions has bought certainty, and the product must not spend it.

### 14.4 Floor plan `[PARTIAL]` → `[V4 REQUIRED]`

| | |
|---|---|
| **Purpose** | Room shape, openings, and relationships a photo cannot show |
| **Required** | Optional |
| **Current reality** | **Accepted at upload and never read.** The person reasonably believes it informed the design |
| **V4 requirement** | Either extract room geometry from it, **or** decline it at upload with a plain message |
| **Failure** | An unreadable plan is reported, not silently ignored |
| **Status** | **`[PARTIAL]` — the most misleading gap in the current product** |

### 14.5 Style and reference images

| | |
|---|---|
| **Purpose** | Communicate taste without vocabulary |
| **Required** | Optional |
| **Feedback** | Each reference is read individually and its influence is attributable (§28) |
| **Failure** | A reference that cannot be read is shown as unread **with the reason**, never dropped |
| **Status** | `[CURRENT]` |

### 14.6 Existing elements to keep `[PARTIAL]` → `[V4 REQUIRED]`

Today: expressible in the brief ("keep the TV unit") and the system can honour it.
V4: a **first-class control** — mark a piece in a photo as *keep*, and the system must not generate a replacement and must design around it.

**This is Rahul's entire job to be done (J3).** Leaving it to free text means it works when the phrasing is clear and fails silently when it is not.

### 14.7 Constraints and preferences `[PARTIAL]`

Budget, materials, colours, functional requirements ("seating for six", "no glass, we have toddlers"). Today: free text. V4 `[V4 REQUIRED]`: structured capture for the ones that change decisions — at minimum **functional requirements** and **hard exclusions**, because a violated exclusion is a trust failure, not a preference miss.

---

## 15. Design Intent

### 15.1 What the product must understand

Given:

> *"I want a warm modern living room for my family. Keep the TV unit. I want comfortable seating and don't want the room to feel crowded."*

The product must extract:

| Extracted | Value | Kind |
|---|---|---|
| Room | Living room | **Stated** |
| Style | Warm modern | **Stated** |
| Existing element | TV unit — **keep** | **Stated** |
| Functional intent | Family use | **Stated** |
| Seating requirement | Comfortable seating, quantity unstated | **Stated (partial)** |
| Density preference | Low — avoid crowding | **Stated** |
| Palette | Warm neutrals + wood | **Inferred** |
| Seating count | e.g. 4 | **Inferred** |
| Circulation priority | Elevated, from "crowded" | **Inferred** |

### 15.2 The rule that matters

**The product must not silently invent important facts.**

"Warm modern" → a specific palette is a reasonable inference and must be **marked as inferred and editable**. "Don't want it to feel crowded" → a specific clearance target is an inference and must be visible.

`[V4 REQUIRED]` The structured reading is shown back to the person before it drives spend, with inferences distinguishable at a glance.

### 15.3 When to ask

Ask only when the ambiguity **materially changes the output** and the system cannot resolve it safely. §25.3 sets the rule.

| Situation | Ask? |
|---|---|
| "Seating for the family" — 3 or 6 people changes the furniture | **Yes** |
| Exact shade of warm neutral | No — infer, mark, let them change it |
| "Keep the TV unit" but two units are visible | **Yes** — which one |
| Whether the rug is wool or jute | No — infer and mark |
| Room dimensions absent and the photos are ambiguous | **Yes** — or proceed with a clearly-marked estimate |

---

## 16. Element Intelligence

### 16.1 What an element is, in product terms

A **thing that should exist in the room**: a sofa, a rug, a wall finish, a light. Not a pixel region, not a mesh — a *design decision*.

Every element is one of:

| Origin | Meaning | Product behaviour |
|---|---|---|
| **From the person's photos** | Something they already own | Preserve; do not regenerate (§14.6) |
| **From the brief** | Something they asked for | Must appear |
| **From a reference** | Something a reference image implied | Attributable to that reference |
| **Proposed by the system** | Something the design needs | **Marked as a proposal**, rejectable |

### 16.2 Elements vs instances

| Concept | Product meaning | Example |
|---|---|---|
| **Element** | A *kind* of thing | "Bar stool, black, 45 cm" |
| **Instance** | One *occurrence* | Stool #1, #2, #3 |
| **Shared 3D model** | One model, several placements | One stool model, three chairs at the counter |

**This is why "3 matching bar stools" costs one generation, not three.** `[CURRENT]`

### 16.3 Element states, all visible

| State | Meaning | Person sees |
|---|---|---|
| **Detected** | The system found it | In the list, awaiting decision |
| **Validated** | Checked and coherent | Ready to build |
| **Rejected** | The person said no, or a check failed | Excluded, with the reason |
| **Unresolved** | Insufficient evidence | **Flagged**, asks or defers |

`[V4 REQUIRED]` **Uncertainty is not hidden.** An element the system is unsure about appears as unsure. The existing check vocabulary already supports this; the interface must use it.

---

## 17. Element Inventory

### 17.1 What the person sees

```
YOUR ROOM WILL CONTAIN

  Sofa                      1
  Lounge chair              2 matching      1 model shared
  Bar stool                 3 matching      1 model shared
  Coffee table              1
  Side table                2
  Floor lamp                1
  Rug                       1
  TV unit                   1   ← yours, kept
  Television                1

  9 kinds · 12 pieces · 8 models to build
```

### 17.2 Requirements

| Requirement | Why | Status |
|---|---|---|
| Show kinds, instance counts and shared models | The person must understand what they are approving | `[CURRENT]` |
| Say "3 matching bar stools", never `element_id` | Internal identity is not the person's concern | `[CURRENT]` |
| Mark the person's own pieces as *kept* | Rahul's job to be done | **`[V4 REQUIRED]`** |
| Show detected / validated / rejected / unresolved | Principle 9 | **`[V4 REQUIRED]`** |
| Show which reference or photo caused each element | Principle 6, and the basis of trust | **`[V4 REQUIRED]`** |
| **Counts come from the engine, never recomputed in the browser** | Two numbers that disagree is worse than one | **`[V4 REQUIRED]`** (G10) |
| Explain any shortfall | "We found 3 stools but could only use 1" must be explainable | `[PARTIAL]` — engine records it; UI must surface it |

### 17.3 Identity, made human

Internal identity stays internal. The interface speaks in human terms:

| Internal | Shown |
|---|---|
| `element_id: cel_ab12cd34ef` | "Bar stool — black, 45 cm" |
| `instance_count: 3` | "3 matching" |
| `canonical_asset_id` shared | "1 model shared across 3" |
| `approved: true` | Build toggle on |

**Internal ids remain retrievable** — for support, for provenance, and for the designer handoff (§28).

### 17.4 The approval gate — the most important control in the product

`[CURRENT]` and must be protected.

- Each piece can be **Built** or **Skipped**.
- **No money is spent on a piece that is not approved.**
- The step is free and repeatable: *"regenerate as often as you like."*
- The person can change their mind before generation starts.

`[V4 REQUIRED]` additions: show the cost implication of the current selection before they proceed, and never let a default silently approve something.

---

## 18. Moodboard

### 18.1 Purpose, stated precisely

The moodboard is **a visual composition that communicates design direction**. It is the thing the person reacts to emotionally, and it is how they decide whether Allure understood them.

**It is not the authoritative 3D scene.**

### 18.2 The distinction the product must make

| Moodboard | 3D scene |
|---|---|
| Visual direction | **Spatial truth** |
| Shows style, palette, materials, mood | Shows where things actually are |
| Positions are compositional | Positions are metric and validated |
| Generated | **Solved** |
| Free, regenerate freely | Costs money and time |

`[V4 REQUIRED]` The product must never imply *"these exact pixels are the final geometry."* Where a piece sits in the moodboard is **an intention**, not a measurement.

**This matters commercially:** a person who believes the moodboard is the plan will be confused when the 3D scene differs — and it will differ, because the solver obeys the room and the moodboard does not.

### 18.3 Requirements

| Requirement | Status |
|---|---|
| Moodboard is generated **from the approved pieces**, not independently | `[CURRENT]` |
| Free and repeatable | `[CURRENT]` |
| Clearly framed as direction, not plan | **`[V4 REQUIRED]`** |
| Person can regenerate without losing element approvals | `[CURRENT]` |
| Per-room for multi-room projects | `[CURRENT]` |

---

## 19. 3D Asset Experience

### 19.1 What the person experiences

> "Your furniture is being turned into the 3D scene."

They do not need to know about meshes, polygon budgets, remeshing or texture resolution.

### 19.2 What they must understand

| Must understand | Why |
|---|---|
| This step costs money | It does, and they should decide knowingly `[CURRENT]` |
| Identical pieces share one model | It explains why 3 stools cost one generation `[V4 REQUIRED]` |
| Generated models are **approximations** of the pictured piece | Principle 9 and §45 `[V4 REQUIRED]` |
| Their own kept pieces are not regenerated | J3 `[V4 REQUIRED]` |
| A piece that fails to build is **visibly a stand-in** | Silent substitution is a trust failure `[V4 REQUIRED]` |

### 19.3 The stand-in rule

`[V4 REQUIRED]` When a 3D model cannot be produced for an approved piece, the scene may use a placeholder — **and the placeholder must be visibly labelled** in the inventory and in the viewer.

The historical failure this prevents: a cap silently truncated generation and five pieces appeared as catalog stand-ins with nothing on screen saying why. **The person saw a finished room that was not the room they approved.**

### 19.4 Asset reuse — a product promise

| Promise | Status |
|---|---|
| Identical pieces cost one generation | `[CURRENT]` |
| Reuse is visible in the inventory ("1 model shared across 3") | `[V4 REQUIRED]` |
| Re-running a step never re-charges for a piece already built | **`[V4 REQUIRED]`** (G5) |
| Models built for one person's project are never offered to another | `[CURRENT]` — and is a privacy requirement (§42) |

---

## 20. Spatial Design

### 20.1 What the product guarantees

`[CURRENT]` The deterministic solver ensures, within the scene it produces:

| Guarantee | Plain-language meaning |
|---|---|
| Furniture fits inside the room | Nothing sticks through a wall |
| No improper overlap | Things do not occupy the same space |
| Walkways remain usable | You can move through the room |
| Doors and windows respected | A door can open; a window is not blocked by a wardrobe |
| Scale is coherent | A sofa is sofa-sized relative to the room |
| Orientation is reasonable | Chairs face into the room, not the wall |
| Room boundaries respected | The plan matches the room's shape |

### 20.2 What the person never has to understand

Constraint solving, collision geometry, clearance inflation, coordinate frames, candidate ranking. **Zero of it surfaces.**

### 20.3 What they do see when it matters

When a constraint cannot be satisfied, the person gets a plain statement and a choice:

> **"The three-seater sofa and the armchair won't both fit along the window wall with a clear walkway. We placed the sofa there and moved the armchair opposite."**
>
> `Keep this` · `Try a smaller sofa` · `Show me alternatives`

`[V4 REQUIRED]` Never *"Constraint C-104 failed"*, and never a silent drop. A piece that could not be placed is **reported by name** with the reason.

### 20.4 Clearance, stated honestly

`[CURRENT]` The product uses published general clearance standards for walkways and door swing.

`[V4 REQUIRED]` The product must **not** claim these constitute building-code compliance for the person's jurisdiction (§46). The honest claim: *"Laid out using standard residential clearances."*

---

## 21. Photorealistic 3D

### 21.1 The hard requirement

**The person ultimately receives a photorealistic 3D representation of their interior.** Not a stylised illustration, not a diagram.

The output must communicate: room architecture · furniture · materials · colours · lighting · spatial relationships · **scale** · atmosphere.

### 21.2 Derived from the validated scene — not generated alongside it

`[CURRENT]` and non-negotiable. The render is produced **from** the solved, committed 3D scene. It is not an image generated to look like the design; it is a photograph of the design.

This is why the render can be verified at all (§23), and it is the product's central technical claim.

### 21.3 How success is defined

| Not this | This |
|---|---|
| "The render looks nice" | **"The render faithfully represents the validated scene"** |
| Subjective beauty | Every expected object present, correctly sized, correctly oriented, visible where it should be |
| "Photorealistic" as marketing | Physically-based materials, plausible lighting, correct scale — each checkable |

### 21.4 The quality defect V4 must fix

`[PARTIAL]` **Every render the product has ever produced has been quieter than intended.** A contrast setting is rejected by the renderer and the failure is silently discarded, so it has never applied. Indirect lighting also runs in a lower-fidelity mode.

**Product consequence:** the product has been under-delivering on its central visual promise since the beginning, and nothing told anyone. `[V4 REQUIRED]` — settings must be applied *and verified applied*, and a failure to apply them must be loud.

### 21.5 Requirements

| Requirement | Status |
|---|---|
| Render derived from the validated scene | `[CURRENT]` |
| Physically-based materials from the design, not defaults | `[PARTIAL]` |
| Correct physical scale | `[CURRENT]` |
| Colour treatment applied **and asserted** | **`[V4 REQUIRED]`** |
| Realistic indirect lighting | **`[V4 REQUIRED]`** |
| Correct object orientation | `[PARTIAL]` |
| Multiple viewpoints | `[CURRENT]` |
| Render never presented as a photograph of a built room | **`[V4 REQUIRED]`** (§45) |

---

## 22. 3D Viewer

### 22.1 Scope

| Capability | Scope | Status |
|---|---|---|
| Orbit, pan, zoom | **MUST** | `[CURRENT]` |
| Walk through the room | **MUST** | `[CURRENT]` |
| Preset camera views | **MUST** | `[CURRENT]` |
| Select an object | **MUST** | `[PARTIAL]` |
| **See what a selected object is** (name, dimensions, material, kept-or-new) | **MUST** | **`[V4 REQUIRED]`** |
| **See where a selected object came from** (which photo or reference) | **MUST** | **`[V4 REQUIRED]`** |
| Shareable link | **MUST** | `[CURRENT]` |
| Loads on a phone | **SHOULD** | `[PARTIAL]` |
| Swap a material or finish live | **SHOULD** | `[FUTURE]` |
| Compare two versions side by side | **SHOULD** | `[FUTURE]` |
| Measure a distance | **FUTURE** | `[FUTURE]` |
| VR / AR | **FUTURE** | `[FUTURE]` |

### 22.2 The viewer's product job

**The viewer is where trust is won or lost.** A render can be dismissed as "an AI picture." A space the person can move through, where clicking a chair says *"Lounge chair · 0.78 × 0.80 × 0.75 m · from your inspiration photo 3 · 1 of 2 matching"* — that is a different product.

`[V4 REQUIRED]` Object selection showing identity, dimensions and origin is **the single highest-leverage V4 UI addition**.

### 22.3 What the viewer must never do

It renders the solved scene. It never re-arranges, re-scales or re-positions anything. What the person sees in the viewer is what the engine decided (§51.10, §51.11).

---

## 23. Validation

### 23.1 The product claim

> **"Your design has been checked."**

Allure verifies that the render actually corresponds to the design that was solved — a claim almost no visual AI product makes, and the reason the output can be trusted more than a generated image.

### 23.2 What the person sees

**When everything passes:**

> ✓ **Design verified** — every piece you approved is present, correctly sized and placed, with clear walkways.
> *See what we checked* ›

**When something needs attention:**

> ⚠ **One thing to look at** — the floor lamp is partly hidden behind the armchair in the main view.
> `Adjust the layout` · `Leave it` · `Show me`

**Never:**
> `VALIDATION_FAILURE: visibility check failed for obj_4f2a — occluded in 3/4 viewpoints`

### 23.3 What is checked

Expressed in product terms:

| Check | Person-facing phrasing |
|---|---|
| Every approved piece is in the scene | "Everything you approved is here" |
| Counts match | "3 stools — all 3 are here" |
| Pieces are visible, not buried | "Nothing is hidden inside another object" |
| Nothing floats | "Everything sits on the floor or its surface" |
| Nothing intersects badly | "Nothing overlaps" |
| Room architecture preserved | "Your room's shape, doors and windows are intact" |
| Walkways clear | "You can move through the room" |
| Sizes correct | "Everything is the size it should be" |
| Orientation sensible | "Seating faces the right way" |
| Materials and colours match the design | "It looks like the design you approved" |

### 23.4 Honesty requirement

`[V4 REQUIRED]` **A check that could not run is not a pass.** If verification cannot complete, the person is told the design is *unverified*, not that it is *verified*.

This is the product's most important honesty rule. A false "verified" is worse than no verification at all, because it converts uncertainty into misplaced confidence — exactly the harm the product exists to reduce.

---

## 24. Watcher / Validator / Orchestrator UX

### 24.1 They are invisible

Three internal supervision systems run across the pipeline. **They have no user-facing identity, no names, no personalities, and no separate UI.**

| Internal system | Internal job | What the person experiences |
|---|---|---|
| **Watcher** | Monitors the process | Accurate progress; problems noticed early |
| **Validator** | Checks the result | "Your design has been checked" |
| **Orchestrator** | Manages recovery | "We found an issue and are correcting it" |

### 24.2 Language mapping

| Internal event | Person-facing message |
|---|---|
| Watcher detects a stage produced no output | "This step didn't complete — retrying." |
| Validator returns FAIL on a collision | "Two pieces overlap — adjusting the layout." |
| Orchestrator issues a repair directive | "Correcting the layout — attempt 1 of 2." |
| Repair exhausted | "We couldn't resolve this automatically. Here's what we found." |
| Validator returns REVIEW_REQUIRED | "We'd like you to take a look at one thing." |
| Asset generation failed | "One piece couldn't be built in 3D — using a stand-in for now." |

### 24.3 The anti-requirement

`[V4 REQUIRED]` The product must **never** present these as distinct AI agents, name them in the UI, show them disagreeing, or expose their reasoning as dialogue. A person watching robots argue loses confidence in all of them.

**One product. One voice.**

---

## 25. Uncertainty

### 25.1 Levels

| Level | Meaning | Product behaviour |
|---|---|---|
| **High confidence** | Stated by the person, or measured | Use silently |
| **Medium confidence** | Inferred from strong evidence | Use, **mark as inferred**, editable |
| **Low confidence** | Inferred from weak evidence | Use, **mark prominently**, invite correction |
| **Unresolved** | Cannot decide | **Ask**, or defer and mark clearly |

### 25.2 Where uncertainty must surface

| Surface | What it shows | Status |
|---|---|---|
| Room understanding | Which dimensions were estimated | `[CURRENT]` in copy; `[V4 REQUIRED]` per-field |
| Design intent | Which attributes were inferred | **`[V4 REQUIRED]`** |
| Element inventory | Which elements are unresolved | **`[V4 REQUIRED]`** |
| 3D models | That models are approximations | **`[V4 REQUIRED]`** |
| Validation | What could not be checked | **`[V4 REQUIRED]`** |
| Final design | The overall confidence picture | **`[V4 REQUIRED]`** |

### 25.3 The rule for asking

`[V4 REQUIRED]` Ask only when **all** hold:

1. The ambiguity **materially changes the output**, and
2. The system **cannot resolve it safely**, and
3. A person can **realistically answer** it.

| Situation | Ask? | Why |
|---|---|---|
| Two TV units visible, one is to be kept | **Yes** | Wrong choice ruins the result; trivially answerable |
| Seating for 3 vs 6 | **Yes** | Changes the furniture entirely |
| Exact wood tone | No | Infer, mark, let them change it |
| Whether a rug is wool or jute | No | Barely affects the outcome |
| Room dimensions absent, photos ambiguous | **Yes, or proceed with a marked estimate** | Affects everything downstream |
| Which of 40 internal confidences fell below 0.7 | **Never** | Not the person's problem |

**Over-asking is a failure mode, not caution.** A product that asks about everything has offloaded its job onto the user.

### 25.4 What the product must never do

| Never | Why |
|---|---|
| Present an inference as a stated fact | Principle 6; destroys trust when discovered |
| Hide that a dimension was estimated | The person may be making a purchase on it |
| Say "verified" when verification did not run | §23.4 |
| Show a confidence number without meaning | "0.73" tells a homeowner nothing |
| Ask a question the person cannot answer | "Is this oak or walnut veneer?" from a phone photo |

---

## 26. Editing

### 26.1 What the person should be able to say

| Request | Change type | Scope | Status |
|---|---|---|---|
| "Move the sofa closer to the TV" | Spatial, one object | **Local** | `[FUTURE]` (S1) |
| "Make the chairs lighter" | Material/colour, one kind | **Local** | `[FUTURE]` (S1) |
| "Replace the coffee table" | Element swap | **Local** | `[FUTURE]` (S1) |
| "Keep everything but change the rug" | Element swap | **Local** | `[FUTURE]` (S1) |
| "Add two more stools" | Instance count | **Local** | `[FUTURE]` (S1) |
| "Make the whole room warmer" | Style | **Global** | `[FUTURE]` |
| "Actually make it a study" | Room purpose | **Global** | `[FUTURE]` |

### 26.2 Local vs global — the defining rule

| | Local change | Global change |
|---|---|---|
| **Affects** | One element, instance or attribute | The design direction |
| **Preserves** | All other elements' identity, all other placements, all assets | Element identity where possible |
| **Re-runs** | Placement for affected objects; re-render | Design understanding onward |
| **Costs** | No new 3D generation unless a new kind is introduced | May generate new models |
| **Time** | Minutes | Similar to the original run |

**PR-EDIT-002 `[V4 REQUIRED]`:** a local change must **not** regenerate the entire scene, must **not** re-charge for unchanged pieces, and must **not** silently move objects the person did not ask to move.

### 26.3 What editing must preserve

| Preserved | Why |
|---|---|
| Element identity of untouched pieces | Principle 4; and re-generating them costs money |
| Spatial validity | An edit that creates a collision must be resolved or refused with a reason |
| Kept existing furniture | An edit must never quietly remove the person's own pieces |
| Prior accepted versions | §28 |
| Provenance | The chain must survive the edit |

### 26.4 V4 minimum

`[V4 REQUIRED]` Natural-language editing is `[FUTURE]`. **What V4 must ship** is the ability to go back, change element approvals or room dimensions, and re-run — **without losing the accepted version and without paying twice** for pieces already built.

That is the minimum viable form of J6, and it is achievable within V4 scope.

---

## 27. Design Iteration

### 27.1 The iteration loop

```
DESIGN V1 ──accept──▶ kept forever
    │
    └─ experiment ──▶ DESIGN V2 ──▶ compare ──▶ accept / discard
                                        │
                                        └──▶ DESIGN V3 …
```

### 27.2 Requirements

| Requirement | Priority | Status |
|---|---|---|
| A project holds multiple design versions | **P1** | **`[V4 REQUIRED]`** |
| An accepted version is never lost to a later experiment | **P0** | **`[V4 REQUIRED]`** |
| The person can revert to any earlier version | **P1** | **`[V4 REQUIRED]`** |
| The person can duplicate a version and branch | **P2** | `[FUTURE]` (S6) |
| Side-by-side comparison | **P2** | `[FUTURE]` (S3) |
| Each version shows what changed | **P2** | `[FUTURE]` |

### 27.3 The rule that protects the person

**PR-VERSION-001 · P0:** *No experiment may destroy an accepted design.*

The person tries a variation and dislikes it. They must be able to return to the design they accepted, **exactly as it was** — render, scene, inventory and all.

Losing an accepted design to an experiment is the kind of failure that ends a customer relationship.

---

## 28. Versioning & Provenance

### 28.1 The version model

| Level | What it is | Person sees |
|---|---|---|
| **Project** | The room being designed | "My living room" |
| **Design version** | A complete design the person can accept | "Design 1", "Design 2" |
| **Scene version** | The solved 3D layout behind a design | Not shown directly |
| **Asset version** | A 3D model's revision | Not shown directly |
| **Render version** | A specific image of a scene | Shown as "views" |

Only **project** and **design version** are user-facing concepts. The rest exist so the product can recover, explain and compare.

### 28.2 Provenance — the trust backbone

`[V4 REQUIRED]` For **every object in the final render**, the product must be able to answer:

> **"Why is this here, and where did it come from?"**

```
This chair
  ← is 1 of 2 matching lounge chairs
  ← built from the piece Allure pictured
  ← which came from your inspiration photo #3
  ← and your brief: "comfortable seating"
```

### 28.3 Why this is a product requirement, not an engineering nicety

| It enables | Without it |
|---|---|
| Rahul proving his TV unit survived | He has to squint at a render |
| A designer handoff worth more than a picture | The designer starts from scratch |
| The person understanding a surprising choice | It looks arbitrary and they lose confidence |
| Support diagnosing a complaint | Guesswork |
| A future bill of materials | Impossible |

`[V4 REQUIRED]` **Today the chain breaks** — a rendered object cannot be traced back to the element that caused it (G3). Closing it is the difference between a picture and a design.

---

## 29. User Review

### 29.1 The review surface

`[V4 REQUIRED]` A dedicated screen where the person judges the design. Today the viewer exists; the review surface does not.

**They must be able to inspect:**

| Item | Purpose |
|---|---|
| The final render(s) | The emotional judgement |
| The interactive 3D scene | The spatial judgement |
| The element inventory | "Is everything I approved here?" |
| **Important assumptions** | "What did you guess?" |
| Validation status | "Was this checked?" |
| Any detected issues | "What's wrong with it?" |
| Design attributes | Style, palette, materials |

### 29.2 Actions

| Action | Effect |
|---|---|
| **Approve** | Design becomes accepted and preserved (§27.3); handoff unlocked |
| **Edit** | Enter the editing flow (§26) |
| **Regenerate** | Re-run from a chosen point, preserving approvals and built models |
| **Reject** | Mark rejected with an optional reason; preserved, not deleted |

`[V4 REQUIRED]` All four always available. **Reject must never delete work** — a rejected design is evidence, and the person may change their mind.

### 29.3 Assumptions panel

`[V4 REQUIRED]` A plain summary of what the system decided on its own:

> **What we assumed**
> · Room height 2.8 m — you didn't specify
> · Wall finish: warm white — inferred from "warm modern"
> · 4 seats — inferred from "family"
> · Rug material: wool — inferred from your reference
> *Any of these can be changed.*

**This panel is where principle 9 becomes a real product surface** rather than a stated value.

---

## 30. Failure Handling

### 30.1 Principles

| Principle | Meaning |
|---|---|
| **No silent loss** | Work already done survives any failure |
| **Understandable** | Plain language, no codes |
| **Actionable** | Always a next step |
| **Honest** | Never claim success on partial completion |
| **Bounded** | Never an endless progress bar (§31) |

### 30.2 Behaviour by failure type

| Failure | Person sees | Next step | Work preserved |
|---|---|---|---|
| **Upload rejected** | "That file is too large (max 25 MB)." | Try another file | Yes — other uploads unaffected |
| **Brief unreadable** | "We couldn't make sense of the description — could you add a little more?" | Edit and retry | Yes |
| **Design model unavailable** | "Our design engine is busy — we'll keep trying." | Wait or retry | Yes |
| **A piece can't be pictured** | "We couldn't picture the side table — you can retry it or skip it." | Retry / skip | Yes — other pieces unaffected |
| **3D model generation fails** | "One piece couldn't be built in 3D — we've used a stand-in, clearly marked." | Retry / accept / skip | Yes |
| **3D generation times out** | "Your 3D models are taking longer than usual — still working." | Wait; leave and return | Yes |
| **Layout can't be solved** | "The armchair won't fit with a clear walkway. Here are the options." | Choose | Yes |
| **Scene assembly fails** | "We hit a problem assembling the room — retrying." | Automatic, then manual | Yes |
| **Render fails** | "The render didn't complete — retrying." | Automatic, then manual | Yes — scene preserved |
| **Verification fails** | "We couldn't fully check this design." **Not** "verified" | Review | Yes |
| **Network / session lost** | "Connection lost — your project is saved." | Reload | Yes |
| **Job times out** | "This step took longer than expected and was stopped." | Retry from where it stopped | Yes — checkpointed |

### 30.3 The absolute rule

**PR-FAILURE-001 · P0:** *No failure may lose a person's uploads, approvals, accepted designs or purchased 3D models.*

Everything is checkpointed and resumable `[CURRENT]`. V4 must preserve this while adding the new stages.

---

## 31. Automatic Repair

### 31.1 What may be repaired automatically

| Problem | Automatic action |
|---|---|
| Two objects overlap | Re-solve the layout |
| A walkway is blocked | Re-solve |
| A piece is hidden behind another | Re-solve placement |
| 3D generation timed out | Retry (never re-charging) |
| Render failed | Retry the render |
| Assembly failed | Retry the build |
| A 3D model is obviously wrong for its type | Regenerate it |

### 31.2 What may **not** be repaired automatically

| Problem | Why not | What happens |
|---|---|---|
| Design intent is ambiguous | Guessing is the failure being prevented | **Ask** |
| Which piece to keep is unclear | Wrong answer ruins the result | **Ask** |
| The room genuinely cannot hold the furniture | Not a bug — a real constraint | **Present the trade-off** |
| The system's own data model can't express something | A product defect | **Escalate internally** |
| Repair already ran twice | §31.3 | **Human review** |

### 31.3 The bound

**PR-REPAIR-001 · P0:** **Maximum 2 automatic repair attempts.** Then human review or explicit failure.

| Requirement | Why |
|---|---|
| The count is visible: "attempt 1 of 2" | A bounded loop the person cannot see looks identical to a hung one |
| The bound is enforced by the system, not by the component asking for repair | A component that wants another try cannot grant itself one |
| **The person is never stuck in an infinite progress state** | The single most damaging failure mode in a long-running product |

### 31.4 What the person sees

```
Attempt 1  "We found an issue with the layout and are correcting it. (1 of 2)"
Attempt 2  "Still adjusting — one more attempt. (2 of 2)"
Exhausted  "We couldn't resolve this automatically.
            The armchair and sofa won't both fit along the window wall
            with a clear walkway."
            [ Use a smaller armchair ] [ Move it opposite ] [ Let me decide ]
```

Never *"repair_round exceeded"*. Never a spinner that never resolves.

---

## 32. Human Review

### 32.1 When it triggers

| Trigger | Example |
|---|---|
| Repair exhausted | The layout cannot be resolved in 2 attempts |
| Ambiguity that materially affects output | Which TV unit to keep |
| Verification could not complete | The check itself failed |
| Low confidence on something important | The room type itself is unclear |
| A conflict between checks | Two checks disagree |
| Spend limit reached | Generation would exceed the cap |
| An internal defect class | The system cannot express the right answer |

### 32.2 Two audiences

| Audience | Sees | Purpose |
|---|---|---|
| **The homeowner** | A plain choice with clear options | Resolve *their* ambiguity |
| **Allure operations (P5)** | The issue, evidence, attempts, recommendation, internal ids | Resolve *system* problems without bothering the customer |

`[V4 REQUIRED]` The product must route correctly. A rendering defect is **not** the homeowner's problem and must never be shown to them as a question.

### 32.3 The anti-requirement

**PR-HUMAN-002 · P1:** *Escalation rate must be measured, and an escalation rate approaching 100% is a product failure, not thoroughness.*

A review queue that fires on everything trains reviewers to approve without looking — which is worse than no review, because it manufactures the appearance of oversight.

### 32.4 What a review item contains

Issue · affected pieces (by human name) · evidence (render, view, comparison) · what was already attempted · a recommendation · explicit actions.

`[V4 REQUIRED]` Every human decision — especially an override — records **who, why, and what resulted** (§43).

---

## 33. Product Outputs

### 33.1 Primary V4 outputs

| # | Output | Status |
|---|---|---|
| 1 | **Photorealistic interior render** | `[PARTIAL]` — quality defect (G4) |
| 2 | **Validated 3D scene** | `[PARTIAL]` — solved `[CURRENT]`, verified `[V4 REQUIRED]` |
| 3 | **Interactive 3D representation** | `[CURRENT]` |
| 4 | **Structured design representation** | **`[V4 REQUIRED]`** |
| 5 | **Element inventory** | `[CURRENT]` |
| 6 | **Asset mapping** (which model is which piece) | `[PARTIAL]` |
| 7 | **Design provenance** | **`[V4 REQUIRED]`** |

### 33.2 Secondary / future outputs

| # | Output | Status |
|---|---|---|
| 8 | Designer-ready design package | `[FUTURE]` |
| 9 | Designer matchmaking | `[PARTIAL]` mock → `[FUTURE]` |
| 10 | Builder matchmaking | `[FUTURE]` |
| 11 | Execution package | `[FUTURE]` |

### 33.3 The structured design representation `[V4 REQUIRED]`

The artifact that makes Allure more than a renderer:

```
DESIGN SPECIFICATION
  Project · rooms with dimensions (stated or estimated, marked)
  Design intent · style, palette, materials, functional requirements
  Elements · each kind, its instances, dimensions, material, colour
  Existing pieces · what the person kept
  3D assets · which model represents which piece
  Layout · where everything sits, and the clearances honoured
  Provenance · what caused each decision
  Validation · what was checked, what passed, what could not be checked
```

**This is what a designer, and eventually a builder, actually needs.** A render is the cover; this is the document.

---

## 34. Designer Matchmaking

### 34.1 Position in the product

```
VALIDATED DESIGN  ──▶  DESIGNER MATCHMAKING
     (core)                 (extension)
```

**The marketplace is an extension, not the core loop.** V4's product must be complete and valuable if no designer is ever contacted. Matchmaking sits **outside the rendering path** and can never block or delay a design.

### 34.2 The honesty problem V4 must fix

`[PARTIAL]` The current step shows three designers from hardcoded data; "Connect" stores a value in browser memory and displays *"Request sent."* **Nothing is sent or stored.**

**PR-DESIGNER-001 · P0 — one of two paths, no third option:**

| Option A — make it real | Option B — label it |
|---|---|
| Connection requests are stored and delivered | The step is clearly marked a preview |
| The person can see request status | The button does not say "Request sent" when nothing was |
| Designers are real and consented | Sample profiles are labelled as examples |

**Shipping the mock as though it works is a trust failure of exactly the kind principle 9 exists to prevent** — and it is the one place in the current product where the interface asserts something untrue.

### 34.3 What matching may use `[FUTURE]`

Project type · style direction · location · budget range · scope · complexity · specific design requirements.

### 34.4 What the product must never promise

| Never | Instead |
|---|---|
| "You will be matched with a designer" | "We'll share your project with designers who work in this style" |
| "A designer will take this project" | "Connecting is free; designers respond at their discretion" |
| Guaranteed allocation, timing or price | Nothing about outcome |

**PR-DESIGNER-002 · P0:** *Marketplace recommendations must not imply guaranteed work, for either party.*

---

## 35. Execution Marketplace

`[FUTURE]` — no V4 scope beyond keeping the door open.

```
VALIDATED DESIGN ──▶ EXECUTION REQUIREMENTS ──▶ BUILDER / CONTRACTOR / FABRICATOR
```

### 35.1 What V4 does to enable it

Produces the **structured design representation** (§33.3) with dimensions, elements, counts, materials and provenance. That is the raw material an execution package would need.

### 35.2 What V4 explicitly does not claim

| Not claimed | Why |
|---|---|
| A construction-ready bill of quantities | Quantities need construction detailing V4 does not do |
| Accurate cost estimates | Prices are local, volatile and supplier-specific |
| Buildable drawings | Requires professional documentation |
| Structural feasibility | Requires an engineer |
| Compliance with local codes | Codes are jurisdictional |

**PR-EXECUTION-001 · P0:** *V4 must not describe its output as construction-ready, and the interface must not imply it.*

The honest framing: **"A validated design you can take to professionals"** — not *"a design ready to build."*

---

## 36. Product Requirements

Format: **PR-ID · Category · Requirement · User Value · Priority · Acceptance Criteria · Dependencies · Current Status.**

### 36.1 PR-INPUT

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-INPUT-001** | The person MUST be able to create a project with only a name, room type and short description. | Nobody is blocked for lacking measurements or design vocabulary. | P0 | A project created with those three fields alone reaches a rendered design. | — | `[CURRENT]` |
| **PR-INPUT-002** | The person MUST be able to upload room photographs, with per-file validation and individual removal. | Photos are the main evidence about the real room. | P0 | A rejected file names its reason; other files are unaffected; any file can be removed before submission. | — | `[CURRENT]` |
| **PR-INPUT-003** | Room dimensions MUST be optional, and the product MUST state that missing values are estimated. | Sets expectations before, not after. | P0 | The dimensions UI carries that statement; estimated values are marked in every later surface. | PR-UNCERTAINTY-001 | `[CURRENT]` copy; `[V4 REQUIRED]` per-field marking |
| **PR-INPUT-004** | A floor plan MUST either be read and used, or declined at upload with a plain message. | Accepting and ignoring an input misleads the person. | P1 | Uploading a floor plan produces either extracted room geometry or a message explaining it is unsupported. | — | **`[PARTIAL]`** (G6) |
| **PR-INPUT-005** | The person MUST be able to mark existing furniture to keep, as a first-class control rather than free text. | J3 — the difference between a redesign and a replacement. | P1 | A marked piece appears in the final scene and no replacement is generated for it. | PR-ELEMENT-004 | **`[PARTIAL]`** |
| **PR-INPUT-006** | Hard exclusions ("no glass") MUST be capturable as structured constraints. | A violated exclusion is a trust failure, not a missed preference. | P1 | An excluded material appears in no proposed element. | PR-INTENT-002 | **`[PARTIAL]`** |
| **PR-INPUT-007** | Uploaded images MUST be re-encoded before any model processes them. | Protects against instructions hidden in image data. | P0 | An image carrying embedded instructions changes no pipeline decision. | — | **`[V4 REQUIRED]`** |
| **PR-INPUT-008** | No upload may be silently dropped. | The person believes everything they gave was used. | P0 | With N references supplied, N results or N explained failures exist. | — | `[CURRENT]` |

### 36.2 PR-INTENT

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-INTENT-001** | The product MUST convert ordinary language into structured design intent covering room, style, existing elements, functional intent and density preference. | J2 — no design vocabulary required. | P0 | The §15.1 example brief yields all listed fields correctly classified. | — | `[CURRENT]` |
| **PR-INTENT-002** | Every intent attribute MUST be labelled **stated** or **inferred**. | Principle 6; prevents a guess being mistaken for a decision. | P0 | Each attribute in the intent summary carries its kind; inferred ones are editable. | PR-UNCERTAINTY-002 | **`[V4 REQUIRED]`** |
| **PR-INTENT-003** | The structured reading MUST be shown back for confirmation **before** any spend. | Catches misunderstanding while correcting it is free. | P0 | The person can edit rooms, style and elements before the paid step. | — | `[CURRENT]` |
| **PR-INTENT-004** | The product MUST NOT invent a material fact not supported by input. | Principle 6. | P0 | No element, room or constraint appears without a traceable source or an "inferred" label. | PR-PROVENANCE-001 | **`[V4 REQUIRED]`** |
| **PR-INTENT-005** | A stated preference MUST NOT be silently overridden. | Principle 1. | P0 | If a stated preference cannot be honoured, the person is told, with the reason. | — | **`[V4 REQUIRED]`** |

### 36.3 PR-ROOM

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-ROOM-001** | Every room MUST have dimensions, either stated or estimated, and estimated ones MUST be marked. | Scale is the foundation of every later judgement. | P0 | Every room carries dimensions and an `estimated` flag surfaced in the UI. | PR-INPUT-003 | `[CURRENT]` data; `[V4 REQUIRED]` UI |
| **PR-ROOM-002** | Stated dimensions MUST NOT be overwritten by inference. | A person who measured has bought certainty. | P0 | A stated dimension is byte-identical in the final scene. | — | `[CURRENT]` |
| **PR-ROOM-003** | The person MUST be able to correct room dimensions before the paid step. | Cheap correction beats expensive rework. | P0 | Step 4 allows dimension edits and re-planning. | — | `[CURRENT]` |
| **PR-ROOM-004** | Room architecture — walls, doors, windows — MUST be preserved in the final scene. | It is their actual room, not a generic one. | P0 | The built scene's architecture matches the room definition. | PR-SPATIAL-001 | `[CURRENT]` |

### 36.4 PR-ELEMENT

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-ELEMENT-001** | The product MUST identify the elements the room should contain and present them as a reviewable list. | The person sees what Allure thinks exists before it is built. | P0 | An inventory lists every element with its kind and instance count. | — | `[CURRENT]` |
| **PR-ELEMENT-002** | Repeated identical pieces MUST be presented as one kind with N instances. | "3 matching bar stools" is how people think. | P0 | Three identical stools appear as one row reading "3 matching". | PR-IDENTITY-001 | `[CURRENT]` |
| **PR-ELEMENT-003** | Every element MUST show its state: detected, validated, rejected or unresolved. | Principle 9. | P1 | Each element row shows one of the four states. | PR-UNCERTAINTY-003 | **`[V4 REQUIRED]`** |
| **PR-ELEMENT-004** | Elements the person owns and keeps MUST be marked and MUST NOT be regenerated. | J3. | P1 | A kept piece is labelled "yours" and consumes no generation. | PR-INPUT-005 | **`[PARTIAL]`** |
| **PR-ELEMENT-005** | An element MUST NOT be silently deleted; rejection MUST be visible with a reason. | An unexplained absence is unexplainable to a reviewer. | P0 | Every element absent from the final design has a recorded reason visible to the person. | — | `[CURRENT]` data; **`[V4 REQUIRED]`** UI |
| **PR-ELEMENT-006** | Element counts shown MUST come from the engine, not be recomputed in the browser. | Two numbers that disagree is worse than one. | P2 | Displayed counts equal engine counts in every view. | — | **`[V4 REQUIRED]`** (G10) |

### 36.5 PR-IDENTITY

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-IDENTITY-001** | Identical pieces MUST resolve to one kind sharing one 3D model. | Three stools cost one generation, not three. | P0 | 3 identical stools consume exactly 1 generation. | — | `[CURRENT]` |
| **PR-IDENTITY-002** | Distinct pieces MUST NOT be merged into one. | Losing a piece silently is worse than an extra one. | P0 | Two visibly different side tables remain two kinds. | — | `[CURRENT]` |
| **PR-IDENTITY-003** | An element's identity MUST persist from proposal to final render. | Principle 4; the basis of provenance and editing. | P1 | Every object in the final render names the element it came from. | PR-PROVENANCE-001 | **`[V4 REQUIRED]`** (G3) |
| **PR-IDENTITY-004** | Re-running a step MUST NOT re-charge for a piece already built. | The person must never pay twice for the same thing. | P1 | Re-running after a change issues zero new generations for unchanged pieces. | — | **`[V4 REQUIRED]`** (G5) |
| **PR-IDENTITY-005** | Internal identifiers MUST NOT appear in the primary interface. | They mean nothing to a homeowner. | P1 | No screen shows a raw id; support surfaces may. | — | `[CURRENT]` |

### 36.6 PR-ASSET

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-ASSET-001** | No 3D model may be generated for a piece the person has not approved. | The spend gate. | P0 | A skipped piece consumes nothing. | PR-SECURITY-003 | `[CURRENT]` |
| **PR-ASSET-002** | Generated models MUST be presented as approximations of the pictured piece. | Principle 9; §45. | P1 | The 3D step states that models approximate the pictured piece. | PR-TRUST-002 | **`[V4 REQUIRED]`** |
| **PR-ASSET-003** | A piece that cannot be built MUST appear as a **visibly labelled** stand-in. | Silent substitution is a trust failure. | P0 | A failed piece shows a stand-in badge in the inventory and viewer. | — | **`[V4 REQUIRED]`** |
| **PR-ASSET-004** | Models built for one person's project MUST NOT be offered to another. | Their furniture is not a library. | P0 | A cross-project query returns no generated assets. | PR-PRIVACY-004 | `[CURRENT]` |
| **PR-ASSET-005** | A model whose shape contradicts its type MUST NOT be used. | A "rug" that is a table ruins the room. | P1 | A contradicting mesh is rejected before placement. | — | `[CURRENT]` |

### 36.7 PR-MOODBOARD

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-MOODBOARD-001** | The moodboard MUST be generated from the approved pieces. | It shows *their* design, not a generic room. | P0 | Every prominent piece in the moodboard corresponds to an approved element. | PR-ELEMENT-001 | `[CURRENT]` |
| **PR-MOODBOARD-002** | The moodboard MUST be free and repeatable. | Exploration must not cost money. | P0 | Regenerating incurs no external charge. | — | `[CURRENT]` |
| **PR-MOODBOARD-003** | The product MUST NOT imply moodboard positions are final geometry. | They are not, and the 3D scene will differ. | P1 | The moodboard is framed as direction; the difference is explained before the 3D step. | — | **`[V4 REQUIRED]`** |
| **PR-MOODBOARD-004** | Regenerating the moodboard MUST NOT lose element approvals or built models. | Exploration must be safe. | P1 | Approvals and bound models survive regeneration. | PR-IDENTITY-004 | **`[PARTIAL]`** |

### 36.8 PR-3D

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-3D-001** | Approved pieces MUST be converted into 3D models, reusing one model across identical pieces. | The scene is built from their design. | P0 | Every approved kind has a model or a labelled stand-in. | PR-IDENTITY-001 | `[CURRENT]` |
| **PR-3D-002** | Objects MUST appear at correct physical scale. | A wrongly-sized room is worthless for judgement. | P0 | Every object's rendered size matches its stated dimensions within tolerance. | PR-ROOM-001 | `[CURRENT]` |
| **PR-3D-003** | Objects MUST be oriented sensibly. | Chairs facing walls destroy credibility instantly. | P1 | Seating faces into the room or its intended focus. | PR-SPATIAL-001 | `[PARTIAL]` |

### 36.9 PR-SPATIAL

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-SPATIAL-001** | The system MUST produce a scene in which furniture does not violate room boundaries or defined clearance constraints. | The design must physically fit. | P0 | The final scene passes spatial validation with zero violations. | — | `[CURRENT]` |
| **PR-SPATIAL-002** | Walkways and door swings MUST remain usable. | A room you cannot move through is not designed. | P0 | Clearance checks pass at the configured standards. | PR-SPATIAL-001 | `[CURRENT]` |
| **PR-SPATIAL-003** | Final placement MUST be decided by deterministic geometry, never by a generative model. | Principle 5. | P0 | No code path lets a model's output become a final position. | — | `[CURRENT]` |
| **PR-SPATIAL-004** | A piece that cannot be placed MUST be reported by name with the reason. | An unexplained absence is a defect. | P0 | Unplaceable pieces produce a named, reasoned message. | PR-FAILURE-002 | `[CURRENT]` data; **`[V4 REQUIRED]`** UI |
| **PR-SPATIAL-005** | Spatial trade-offs MUST be explained in plain language with options. | The person can choose; the system should not decide alone. | P1 | A conflict produces a plain statement and at least two options. | — | **`[V4 REQUIRED]`** |

### 36.10 PR-RENDER

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-RENDER-001** | The render MUST be produced from the validated 3D scene. | It is a photograph of the design, not an impression of it. | P0 | Every rendered object corresponds to a scene object. | PR-SPATIAL-001 | `[CURRENT]` |
| **PR-RENDER-002** | Render quality settings MUST be applied **and verified applied**. | The product has under-delivered on its central promise without knowing. | P0 | A post-render assertion confirms the requested settings took effect; failure is loud. | — | **`[V4 REQUIRED]`** (G4) |
| **PR-RENDER-003** | The render MUST communicate architecture, furniture, materials, colours, lighting, scale and atmosphere. | It is the emotional judgement surface. | P0 | A reviewer can identify the room and every major piece. | PR-RENDER-001 | `[PARTIAL]` |
| **PR-RENDER-004** | Multiple viewpoints MUST be available. | One angle hides problems. | P1 | At least four viewpoints are produced per room. | — | `[CURRENT]` |
| **PR-RENDER-005** | A render MUST NOT be presented as a photograph of a built room. | §45, §46. | P0 | The interface labels renders as visualizations. | PR-TRUST-003 | **`[V4 REQUIRED]`** |

### 36.11 PR-VALIDATION

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-VALIDATION-001** | Every design MUST be independently checked against the scene it was solved from. | Principle 7 — the product's core differentiator. | P0 | Every completed design carries a verification result. | PR-RENDER-001 | **`[V4 REQUIRED]`** (G2) |
| **PR-VALIDATION-002** | A check that could not run MUST NOT be reported as a pass. | A false "verified" is worse than none. | P0 | If verification cannot complete, the design shows as *unverified*. | — | **`[V4 REQUIRED]`** |
| **PR-VALIDATION-003** | Validation results MUST be shown in plain language. | "Constraint C-104 failed" helps nobody. | P0 | No validation message contains a code or internal identifier. | — | **`[V4 REQUIRED]`** |
| **PR-VALIDATION-004** | The person MUST be able to see what was checked. | Transparency converts a claim into evidence. | P1 | A "what we checked" view lists the checks and their outcomes. | PR-VALIDATION-001 | **`[V4 REQUIRED]`** |

### 36.12 PR-REVIEW, PR-EDIT, PR-VERSION

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-REVIEW-001** | A dedicated review surface MUST present render, 3D scene, inventory, assumptions, validation status and issues. | One place to judge the design. | P0 | All six are present on one screen. | PR-VALIDATION-001 | **`[V4 REQUIRED]`** |
| **PR-REVIEW-002** | Approve / Edit / Regenerate / Reject MUST always be available. | Principle 8. | P0 | All four actions are reachable from review. | — | **`[V4 REQUIRED]`** |
| **PR-REVIEW-003** | An assumptions panel MUST list what the system decided on its own. | Principle 9 made concrete. | P1 | Every inferred attribute appears, editable. | PR-INTENT-002 | **`[V4 REQUIRED]`** |
| **PR-REVIEW-004** | Rejection MUST NOT delete work. | They may change their mind; it is also evidence. | P0 | A rejected design remains retrievable. | PR-VERSION-001 | **`[V4 REQUIRED]`** |
| **PR-EDIT-001** | The person MUST be able to change approvals or dimensions and re-run without losing accepted work or paying twice. | J6 minimum viable form. | P1 | A re-run after an edit preserves the accepted version and issues no duplicate generations. | PR-IDENTITY-004 | **`[V4 REQUIRED]`** |
| **PR-EDIT-002** | A local change MUST NOT regenerate the whole scene or move objects the person did not ask to move. | Surprise changes destroy confidence. | P1 | After a single-element change, unaffected objects keep their positions. | PR-IDENTITY-003 | **`[V4 REQUIRED]`** |
| **PR-EDIT-003** | Natural-language editing MUST be supported. | J6 in full. | P3 | "Move the sofa closer to the TV" produces that change and nothing else. | PR-EDIT-002 | `[FUTURE]` |
| **PR-VERSION-001** | An accepted design MUST NOT be lost to a later experiment. | The relationship-ending failure. | P0 | After creating and discarding a new version, the accepted one is recoverable exactly. | — | **`[V4 REQUIRED]`** |
| **PR-VERSION-002** | A project MUST support multiple design versions the person can revert to. | J7. | P1 | At least two versions coexist and either can be made current. | PR-VERSION-001 | **`[V4 REQUIRED]`** |
| **PR-VERSION-003** | Versions MUST be comparable side by side. | Comparison is how people choose. | P2 | Two versions render side by side with differences listed. | PR-VERSION-002 | `[FUTURE]` |

### 36.13 PR-PROVENANCE, PR-TRUST, PR-UNCERTAINTY

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-PROVENANCE-001** | Every object in the final render MUST be traceable to the input that caused it. | The trust backbone; the designer handoff; Rahul's proof. | P1 | For every rendered object, the chain to a source photo, reference or brief statement resolves. | PR-IDENTITY-003 | **`[V4 REQUIRED]`** (G3) |
| **PR-PROVENANCE-002** | Selecting an object in the viewer MUST show what it is and where it came from. | Makes provenance usable, not theoretical. | P1 | Selection shows name, dimensions, material, kept-or-new, and origin. | PR-PROVENANCE-001 | **`[V4 REQUIRED]`** |
| **PR-TRUST-001** | Stated facts MUST be visually distinguishable from inferences throughout. | Principle 6 and 9. | P0 | Every inferred value carries a marker in every surface that shows it. | PR-INTENT-002 | **`[V4 REQUIRED]`** |
| **PR-TRUST-002** | The product MUST NOT claim physical accuracy it has not verified. | §46. | P0 | No copy claims measurement accuracy, code compliance or construction readiness. | — | **`[V4 REQUIRED]`** |
| **PR-TRUST-003** | User edits MUST NOT be silently discarded or overridden. | Principle 1 and 8. | P0 | Any stated value survives every later stage, or the person is told why it could not. | PR-INTENT-005 | **`[V4 REQUIRED]`** |
| **PR-UNCERTAINTY-001** | Estimated dimensions MUST be marked wherever shown. | They may buy furniture on these numbers. | P0 | Every estimated dimension carries a marker. | PR-ROOM-001 | **`[V4 REQUIRED]`** |
| **PR-UNCERTAINTY-002** | Inferred design attributes MUST be marked and editable. | Principle 9. | P0 | Each inferred attribute is labelled and changeable. | PR-INTENT-002 | **`[V4 REQUIRED]`** |
| **PR-UNCERTAINTY-003** | Unresolved elements MUST be visible, not hidden or silently dropped. | Hidden uncertainty becomes a surprise later. | P1 | Unresolved elements appear flagged in the inventory. | PR-ELEMENT-003 | **`[V4 REQUIRED]`** |
| **PR-UNCERTAINTY-004** | The product MUST ask only when ambiguity materially changes the output and cannot be resolved safely. | Over-asking offloads the product's job onto the user. | P1 | Question count per project is measured; §25.3's three conditions gate every prompt. | — | **`[V4 REQUIRED]`** |

### 36.14 PR-FAILURE, PR-REPAIR

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-FAILURE-001** | No failure may lose uploads, approvals, accepted designs or purchased models. | The person's investment is protected. | P0 | After any injected failure, all four survive. | — | `[CURRENT]` |
| **PR-FAILURE-002** | Every failure MUST produce an understandable message and a next step. | Principle 8. | P0 | No raw error, stack trace or code reaches the interface. | — | **`[V4 REQUIRED]`** |
| **PR-FAILURE-003** | Partial completion MUST NOT be presented as success. | §23.4 generalised. | P0 | A partially completed stage reports as partial. | PR-VALIDATION-002 | **`[V4 REQUIRED]`** |
| **PR-FAILURE-004** | A long-running step MUST be leavable and resumable. | Some steps take minutes. | P1 | Closing the browser and returning shows current state and resumes. | — | `[CURRENT]` |
| **PR-REPAIR-001** | Automatic repair MUST be bounded at **2 attempts**, then human review or explicit failure. | No infinite progress state. | P0 | A design that cannot be repaired in 2 attempts reaches human review. | — | **`[V4 REQUIRED]`** |
| **PR-REPAIR-002** | Repair attempts MUST be visible as "attempt N of 2". | A bounded loop the person cannot see looks hung. | P1 | The count is displayed during repair. | PR-REPAIR-001 | **`[V4 REQUIRED]`** |
| **PR-REPAIR-003** | Automatic repair MUST NOT resolve design ambiguity by guessing. | Guessing is the failure being prevented. | P0 | Ambiguity routes to a question, never to an automatic choice. | PR-UNCERTAINTY-004 | **`[V4 REQUIRED]`** |

### 36.15 PR-VIEWER, PR-MARKETPLACE, PR-DESIGNER, PR-EXECUTION

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-VIEWER-001** | The person MUST be able to orbit, pan, zoom and move through the space. | Exploration is how spatial understanding forms. | P0 | All four interactions work in a browser. | — | `[CURRENT]` |
| **PR-VIEWER-002** | The viewer MUST render the solved scene without re-arranging anything. | One spatial truth. | P0 | Viewer object positions equal scene positions. | PR-SPATIAL-003 | `[CURRENT]` |
| **PR-VIEWER-003** | Object selection MUST reveal identity, dimensions, material and origin. | The highest-leverage trust surface in V4. | P1 | Clicking an object shows all four. | PR-PROVENANCE-002 | **`[V4 REQUIRED]`** |
| **PR-VIEWER-004** | The scene MUST be shareable by link. | Design decisions are made with other people. | P1 | A share link opens the scene without an account. | PR-SECURITY-004 | `[CURRENT]` |
| **PR-MARKETPLACE-001** | Matchmaking MUST NOT block or delay the design pipeline. | The core product must stand alone. | P0 | Disabling matchmaking leaves the pipeline unaffected. | — | `[CURRENT]` |
| **PR-DESIGNER-001** | Designer connection MUST either function or be labelled a preview. | The interface must not assert something untrue. | P0 | Either requests are stored and delivered, or the step is marked a preview and the button does not claim a request was sent. | — | **`[PARTIAL]`** (§34.2) |
| **PR-DESIGNER-002** | Marketplace recommendations MUST NOT imply guaranteed work. | Protects both parties from a false promise. | P0 | No copy promises matching, allocation, timing or price. | — | **`[V4 REQUIRED]`** |
| **PR-EXECUTION-001** | The product MUST NOT describe its output as construction-ready. | §35.2, §46. | P0 | No interface or export claims construction readiness. | PR-TRUST-002 | **`[V4 REQUIRED]`** |

### 36.16 PR-SECURITY, PR-PRIVACY

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-SECURITY-001** | A person MUST have an account, and projects MUST belong to their owner. | Their home photos are private. | P0 | An unauthenticated request for a project is refused. | — | **`[V4 REQUIRED]`** (G1) |
| **PR-SECURITY-002** | One person MUST NOT access another's project or files. | Basic tenancy. | P0 | A cross-user request is refused for projects, renders and uploads. | PR-SECURITY-001 | **`[V4 REQUIRED]`** |
| **PR-SECURITY-003** | Paid generation MUST require authentication and MUST respect a spend limit. | Prevents an open endpoint draining the owner's credits. | P0 | An unauthenticated generation request spends nothing; a limit halts generation and preserves the project. | PR-SECURITY-001 | **`[V4 REQUIRED]`** |
| **PR-SECURITY-004** | Share links MUST be unguessable, revocable and limited to viewing. | Sharing must not grant control. | P0 | A share link grants view-only access and can be revoked. | — | **`[V4 REQUIRED]`** |
| **PR-SECURITY-005** | Uploads MUST be validated and stored safely, with the original filename discarded. | Uploads are an attack surface. | P0 | Type, size and count are enforced; no user-supplied filename reaches storage. | — | `[CURRENT]` |
| **PR-SECURITY-006** | Actions affecting a project MUST be attributable to a person. | Accountability for overrides. | P1 | An audit record names the actor for every mutating action. | PR-SECURITY-001 | **`[V4 REQUIRED]`** |
| **PR-PRIVACY-001** | Consent for producing a design MUST be separate from consent for improving Allure's models. | Home interiors are sensitive; blanket consent is not informed consent. | P0 | Two distinct, independently withdrawable consents exist. | — | **`[V4 REQUIRED]`** |
| **PR-PRIVACY-002** | The person MUST be able to delete their project and everything derived from it. | Their home, their data. | P0 | After deletion, no upload, render, model or record remains except a deletion audit entry. | PR-SECURITY-001 | **`[V4 REQUIRED]`** |
| **PR-PRIVACY-003** | Retention periods MUST be defined and enforced automatically. | Data minimisation. | P0 | A scheduled process deletes data past its window and records what it removed. | — | **`[V4 REQUIRED]`** |
| **PR-PRIVACY-004** | One person's data MUST NOT influence another's design. | Their furniture is not a shared library. | P0 | No cross-project reuse of generated assets or project data. | PR-ASSET-004 | `[CURRENT]` |
| **PR-PRIVACY-005** | Photos containing identifiable people MUST be flaggable and excludable from retention. | Additional sensitivity. | P1 | A flagged photo is excluded from any retained dataset by default. | PR-PRIVACY-001 | **`[V4 REQUIRED]`** |

### 36.17 PR-PERFORMANCE, PR-ACCESSIBILITY, PR-ANALYTICS

| PR-ID | Requirement | User Value | Pri | Acceptance Criteria | Deps | Status |
|---|---|---|---|---|---|---|
| **PR-PERFORMANCE-001** | Upload feedback MUST be immediate. | Silence reads as breakage. | P0 | A thumbnail or progress indicator appears on selection. | — | `[CURRENT]` |
| **PR-PERFORMANCE-002** | Every long-running stage MUST show live progress with its current activity. | Trust during waiting. | P0 | Each stage streams status; no stage shows an unchanging spinner beyond a defined threshold. | — | `[PARTIAL]` |
| **PR-PERFORMANCE-003** | Time to first visual and time to validated design MUST be measured and published internally. | Cannot be improved unmeasured. | P1 | Both metrics recorded per project. Baseline `[UNKNOWN]` (§38). | — | **`[V4 REQUIRED]`** |
| **PR-PERFORMANCE-004** | The 3D viewer MUST load on a mid-range laptop and degrade gracefully elsewhere. | The viewer is the trust surface. | P1 | Load succeeds or shows a clear limitation message. | PR-VIEWER-001 | `[PARTIAL]` |
| **PR-ACCESSIBILITY-001** | Core flows MUST be keyboard navigable with visible focus. | Basic access. | P1 | Project creation, upload, element review and review actions complete by keyboard. | — | **`[V4 REQUIRED]`** |
| **PR-ACCESSIBILITY-002** | Status MUST NOT be conveyed by colour alone. | Colour-blind users cannot read colour-only state. | P1 | Every status carries a label or icon as well as colour. | — | **`[V4 REQUIRED]`** |
| **PR-ACCESSIBILITY-003** | Progress and errors MUST be announced to assistive technology. | Long async flows are invisible otherwise. | P1 | Stage changes and errors use live regions. | — | **`[V4 REQUIRED]`** |
| **PR-ACCESSIBILITY-004** | Text MUST meet contrast standards. | Legibility. | P1 | Contrast checks pass on primary surfaces. | — | `[UNKNOWN]` |
| **PR-ANALYTICS-001** | Journey events MUST be recorded from creation to acceptance. | Cannot improve what is unmeasured. | P1 | §44's event list is emitted with project and stage identifiers. | — | **`[V4 REQUIRED]`** |
| **PR-ANALYTICS-002** | Analytics MUST NOT collect unnecessary personal information. | Minimisation. | P0 | No event payload contains photos, briefs, addresses or prompt text. | PR-PRIVACY-003 | **`[V4 REQUIRED]`** |
| **PR-ANALYTICS-003** | Cost per completed project MUST be computable. | Unit economics and pricing. | P1 | A per-project cost breakdown exists. Baseline `[UNKNOWN]`. | — | **`[V4 REQUIRED]`** |

---

## 37. Acceptance Criteria

### 37.1 How acceptance criteria are written

| Rejected | Accepted |
|---|---|
| "User gets a good design." | "The final scene contains the expected validated element instances and passes geometry and clearance validation." |
| "Render is realistic." | "The render is generated from the validated 3D scene and passes the defined visual verification criteria." |
| "The product is easy to use." | "A person with only photos and one sentence reaches a rendered design without entering a measurement." |
| "Uncertainty is communicated." | "Every inferred value carries a visible marker in every surface that displays it." |
| "Failures are handled well." | "After any injected failure, uploads, approvals, accepted designs and purchased models all survive." |

### 37.2 Product-level acceptance — V4 ships when all pass

| # | Criterion | Verified by |
|---|---|---|
| A1 | A project created with only name, type, description and photos reaches a rendered, verified design | Golden journey 1 |
| A2 | Three identical pieces appear as one kind with three instances and consume one generation | Golden journey 3 |
| A3 | A piece the person marks as kept appears in the final scene and consumes no generation | Golden journey 2 |
| A4 | Every object in the final render resolves to the input that caused it | Golden journey 10 |
| A5 | The final scene passes geometry and clearance validation with zero violations | All journeys |
| A6 | The render is produced from the validated scene and passes verification | All journeys |
| A7 | Verification that cannot complete reports *unverified*, never *verified* | Journey 8 |
| A8 | An injected collision is repaired within 2 attempts or escalates with a plain explanation | Journey 8 |
| A9 | An accepted design survives a later discarded experiment, byte-identical | Journey 9 |
| A10 | An unauthenticated request cannot open a project or trigger paid generation | Security test |
| A11 | Every inferred value is visibly marked and editable | Journeys 1, 7 |
| A12 | No raw error, code or internal identifier appears in the interface | All journeys |
| A13 | No failure loses uploads, approvals, accepted designs or purchased models | Journey 8 |
| A14 | A person can delete their project and everything derived from it | Privacy test |
| A15 | Cost per completed project is computable | Journey 1 |

---

## 38. Product Metrics

**No targets are invented.** Where no baseline exists, it is `BASELINE = UNKNOWN` with a stated measurement method.

### 38.1 North Star

**Validated Design Projects (VDP)** — the count of projects that reach a design the person accepted **and** that passed verification.

A project counts **only** when all hold:

| # | Condition |
|---|---|
| 1 | Required inputs present (name, type, description, ≥1 photo) |
| 2 | Structured design intent exists |
| 3 | Elements resolved, with the person's approvals recorded |
| 4 | A 3D scene exists |
| 5 | The scene passes spatial validation |
| 6 | A render exists, produced from that scene |
| 7 | **Verification ran and passed** (or the person accepted a stated limitation) |
| 8 | The person reached the accepted state |

**A generated image alone never counts.** Neither does a beautiful render that failed verification.

`BASELINE = UNKNOWN` — no project has yet passed condition 7, because verification does not exist.

### 38.2 Funnel metrics

| Metric | Measurement | Baseline |
|---|---|---|
| Project completion rate | projects reaching accepted ÷ projects created | `UNKNOWN` |
| Input completion rate | projects with ≥1 photo and a description ÷ created | `UNKNOWN` |
| Element confirmation rate | elements approved ÷ elements presented | `UNKNOWN` |
| Time to first visual | creation → first moodboard shown | `UNKNOWN` |
| Time to validated design | creation → verification passed | `UNKNOWN` |
| Project abandonment | projects with no activity for 30 days, by last stage | `UNKNOWN` |

### 38.3 Quality metrics

| Metric | Measurement | Baseline |
|---|---|---|
| Element identity accuracy | hand-labelled sample vs system output | `UNKNOWN` |
| Instance count accuracy | hand-counted vs reported | `UNKNOWN` |
| False merge rate | distinct pieces collapsed into one | `UNKNOWN` |
| False split rate | one piece appearing as two kinds | `UNKNOWN` |
| Asset reuse rate | generations ÷ instances | `UNKNOWN` |
| Spatial validation pass rate | scenes with zero violations ÷ scenes | `UNKNOWN` |
| Render verification pass rate | renders passing ÷ renders verified | `UNKNOWN` |
| Placement accuracy | measured on the benchmark project: 91% within 1.0 m, 55% within 0.5 m | **`MEASURED`** (single project, N=1 — not a rate) |
| Orientation accuracy | 100% on that same single project | **`MEASURED`** (N=1) |
| Coverage | 100% on that same single project | **`MEASURED`** (N=1) |

> **Statistical honesty:** the three `MEASURED` rows are **single-project observations**, not rates. They must be reported with N=1 until measured across a sample (§37.1's discipline applied to metrics).

### 38.4 Reliability and control metrics

| Metric | Measurement | Baseline |
|---|---|---|
| Automatic repair success rate | repairs resolved within 2 attempts ÷ repairs triggered | `UNKNOWN` |
| Human escalation rate | projects escalating ÷ projects | `UNKNOWN` — **a rate approaching 100% is a failure** (§32.3) |
| User edit rate | projects with ≥1 edit ÷ projects | `UNKNOWN` |
| Regeneration rate | regenerations ÷ projects | `UNKNOWN` |
| Design acceptance rate | accepted ÷ designs reviewed | `UNKNOWN` |
| Question rate | clarifying questions asked ÷ project | `UNKNOWN` — **high is a failure** (PR-UNCERTAINTY-004) |
| 3D viewer engagement | projects where the viewer was opened and interacted with | `UNKNOWN` |

### 38.5 Business and economics

| Metric | Measurement | Baseline |
|---|---|---|
| Designer handoff rate | projects reaching a designer connection ÷ accepted designs | `UNKNOWN` |
| Marketplace conversion | connections leading to engagement | `UNKNOWN` `[FUTURE]` |
| **Cost per completed project** | AI + image generation + 3D models + GPU + render + storage, per accepted project | `UNKNOWN` |

### 38.6 Metric honesty rules

| Rule |
|---|
| Every published metric states its measurement method, date and **N** |
| A single-project result is reported as an observation, never as a rate |
| `UNKNOWN` is published as `UNKNOWN`, never omitted or estimated |
| No metric target is set before a baseline exists |

---

## 39. Golden User Journeys

Ten journeys that define "working." Each states input, expected behaviour, output, failure conditions and acceptance.

### Journey 1 — Simple living room *(the default path)*

| | |
|---|---|
| **Input** | Name, "living room", "warm modern living room for my family", 5 phone photos. No dimensions, no floor plan, no references. |
| **Expected** | Room understood; dimensions **estimated and marked**; elements proposed; person approves; moodboard; 3D models; layout solved; render; verified. |
| **Output** | Verified 3D space, inventory, render, assumptions panel listing every estimate. |
| **Failure conditions** | Any dimension presented as fact · verification skipped but reported as verified · person blocked for lacking measurements. |
| **Acceptance** | Reaches accepted state with zero measurements entered; every estimated value carries a marker. |

### Journey 2 — Existing furniture preservation *(Rahul)*

| | |
|---|---|
| **Input** | Photos including a TV unit and sofa; brief: "keep the TV unit and sofa"; marked as *keep*. |
| **Expected** | Both identified as existing, **not regenerated**, designed around, present in the final scene. |
| **Output** | Scene containing both, each labelled "yours", consuming zero generations. |
| **Failure conditions** | Either replaced by a generated model · either missing · either silently restyled. |
| **Acceptance** | Both present, labelled kept, zero generations consumed; provenance resolves each to the photo showing it. |

### Journey 3 — Repeated elements

| | |
|---|---|
| **Input** | A kitchen counter with 3 identical bar stools. |
| **Expected** | One kind, three instances, **one** 3D model shared across three placements. |
| **Output** | Inventory reading "Bar stool · 3 matching · 1 model shared". |
| **Failure conditions** | 3 kinds created · 3 generations consumed · only 1 stool placed · stools merged into one. |
| **Acceptance** | Exactly 1 generation; exactly 3 placements; the inventory states both. |

### Journey 4 — Mixed variants

| | |
|---|---|
| **Input** | 2 dark wood stools + 1 light wood stool. |
| **Expected** | **Two** kinds: one with 2 instances, one with 1. Two models. |
| **Output** | Inventory showing both kinds distinctly. |
| **Failure conditions** | All three merged into one kind (**false merge** — the light stool disappears) · three separate kinds (**false split** — paid three times). |
| **Acceptance** | Exactly 2 kinds, 2 generations, 3 placements. |

### Journey 5 — Reference-heavy project

| | |
|---|---|
| **Input** | 4 room photos + 10 inspiration images. |
| **Expected** | **Every** reference read individually; each influence attributable; none silently dropped. |
| **Output** | Design intent naming which reference drove which attribute. |
| **Failure conditions** | Any reference silently ignored · influences unattributable. |
| **Acceptance** | 10 references produce 10 results or 10 explained failures; provenance names the source of each major attribute. |

### Journey 6 — Floor-plan-driven project *(Meera)*

| | |
|---|---|
| **Input** | A floor plan, exact dimensions, photos. |
| **Expected** | Stated dimensions used **verbatim**; room shape from the plan **or** a clear message that plans are unsupported. |
| **Output** | Scene matching the stated dimensions exactly. |
| **Failure conditions** | Stated dimensions overwritten by estimates · **floor plan silently ignored** (the current behaviour, G6). |
| **Acceptance** | Every stated dimension is byte-identical in the final scene; the floor plan is either used or explicitly declined. |

### Journey 7 — Ambiguous input

| | |
|---|---|
| **Input** | "Make it nice", 2 blurry photos, no other information. |
| **Expected** | The product proceeds with heavily-marked inference, asking **at most** for what materially matters (room type, if unclear). |
| **Output** | A design with a prominent assumptions panel. |
| **Failure conditions** | Refusal to proceed · a barrage of questions · confident output with hidden guesses. |
| **Acceptance** | Reaches a design; assumptions panel lists every inference; question count ≤ 2. |

### Journey 8 — Intentional failure and repair

| | |
|---|---|
| **Input** | A valid project, with a deliberate collision injected after solving. |
| **Expected** | Detected → repair attempt 1 (visible) → resolved, **or** attempt 2 → escalation with a plain explanation and options. |
| **Output** | Either a repaired verified scene, or a human-review item with the trade-off stated. |
| **Failure conditions** | Infinite progress · silent acceptance of the collision · a raw error · lost work. |
| **Acceptance** | Repair never exceeds 2 attempts; attempts are visible; escalation is in plain language; all prior work survives. |

### Journey 9 — User edits an existing scene

| | |
|---|---|
| **Input** | An accepted design; the person changes an element approval and re-runs. |
| **Expected** | Only the affected part changes; unchanged pieces keep their positions and models; **the accepted version is preserved**. |
| **Output** | A new design version alongside the accepted one. |
| **Failure conditions** | Whole scene regenerated · re-charged for unchanged pieces · accepted version lost · unrelated objects moved. |
| **Acceptance** | Zero new generations for unchanged pieces; the accepted version is recoverable byte-identical; unaffected object positions unchanged. |

### Journey 10 — Validated project → designer handoff

| | |
|---|---|
| **Input** | A verified, accepted design. |
| **Expected** | A structured design artifact containing rooms, dimensions with their kind, elements with counts and dimensions, materials, kept pieces, layout and provenance. |
| **Output** | A package a designer can act on — not a render. |
| **Failure conditions** | Handoff is an image only · provenance missing · estimated dimensions unmarked · claims construction readiness. |
| **Acceptance** | The artifact contains all listed sections; every object resolves to its source; no construction-ready claim appears. |

---

## 40. Edge Cases

| Case | Expected product behaviour | Status |
|---|---|---|
| **No floor plan** | Proceed from photos; estimate and mark | `[CURRENT]` |
| **No dimensions** | Estimate and mark; never block | `[CURRENT]` |
| **Poor room photos** | Proceed with lower confidence, marked; ask only if room type is unclear | `[PARTIAL]` |
| **Multiple rooms** | Support per-room design within one project | `[CURRENT]` |
| **Mirrors** | Treat as a wall-mounted element; do not treat the reflection as a second room | `[PARTIAL]` |
| **Glass / transparent furniture** | Represent as an element; approximate material; flag as approximate | `[PARTIAL]` |
| **Built-in furniture** | Treat as architecture, not movable furniture; preserve | `[PARTIAL]` |
| **Partially visible furniture** | Identify with reduced confidence; mark; ask if it materially matters | `[PARTIAL]` |
| **Occluded objects** | Do not fabricate what cannot be seen; record as unresolved | `[V4 REQUIRED]` |
| **Duplicate detections of one object** | Merge only on type **and** overlap; mark, never delete | `[CURRENT]` |
| **Unusual furniture** | Accept as an element with the person's own description | `[PARTIAL]` |
| **Custom furniture** | Treat as a candidate for generation; flag as approximate | `[CURRENT]` |
| **Ambiguous reference** | Attribute what is clear; mark the rest unresolved | `[PARTIAL]` |
| **Conflicting references** | Surface the conflict; ask if it materially matters | `[V4 REQUIRED]` |
| **Missing 3D model** | Labelled stand-in; never silent | `[V4 REQUIRED]` |
| **Unsupported material** | Nearest registry material; **mark as substituted** | `[V4 REQUIRED]` |
| **Very small room** | Solve honestly; if furniture cannot fit, say so with options | `[CURRENT]` solver; `[V4 REQUIRED]` messaging |
| **Very large room** | Solve; avoid sparse unusable layouts | `[PARTIAL]` |
| **Unusual room geometry** | Support non-rectangular boundaries | `[PARTIAL]` |
| **Open-plan spaces** | Treat as one space with zones | `[PARTIAL]` |
| **Curved walls** | `[UNKNOWN]` — behaviour not established; must be determined before launch | `[UNKNOWN]` |
| **Multiple doors** | All respected for clearance | `[CURRENT]` |
| **Windows** | Respected; not blocked by tall furniture | `[CURRENT]` |
| **Columns** | Treated as obstacles | `[PARTIAL]` |
| **Existing architectural features** (cornice, wainscot, panelled doors) | Recorded and preserved | `[CURRENT]` |

`[V4 REQUIRED]` Every `[UNKNOWN]` and `[PARTIAL]` row above must have a defined behaviour before launch — **even if that behaviour is "not supported, told plainly."** An undefined edge case becomes an unexplained failure in front of a customer.

---

## 41. Accessibility

| Requirement | Detail | Pri | Status |
|---|---|---|---|
| Keyboard navigation | Project creation, upload, element approval, review actions, viewer controls | P1 | `[V4 REQUIRED]` |
| Visible focus | Every interactive element | P1 | `[V4 REQUIRED]` |
| Screen reader support | Labelled controls; meaningful image alternatives; announced stage changes | P1 | `[V4 REQUIRED]` |
| Non-colour status | Every state carries a label or icon as well as colour | P1 | `[V4 REQUIRED]` |
| Contrast | Meets standard contrast ratios on primary surfaces | P1 | `[UNKNOWN]` |
| Progress announcement | Long-running stages announced to assistive technology | P1 | `[V4 REQUIRED]` |
| Error announcement | Errors announced, not only shown | P1 | `[V4 REQUIRED]` |
| Motion | Respect reduced-motion preferences in the viewer | P2 | `[UNKNOWN]` |
| 3D alternative | A person who cannot use the 3D viewer can still review via renders and the inventory | P1 | `[V4 REQUIRED]` |

**The last row matters most.** The viewer is the trust surface (§22.2); a person who cannot operate it must still be able to judge the design.

---

## 42. Privacy

### 42.1 Why this is unusually sensitive

Allure holds **photographs of the inside of people's homes**. These may show possessions, layout, security arrangements, and other people. This is more sensitive than most consumer product data, and the product must treat it that way.

### 42.2 Requirements

| Requirement | Detail | Pri | Status |
|---|---|---|---|
| Purpose separation | Consent to produce a design ≠ consent to improve Allure's models | P0 | `[V4 REQUIRED]` |
| Granular consent | Training consent is separately opt-in and withdrawable | P0 | `[V4 REQUIRED]` |
| Retention | Defined per data type and enforced automatically | P0 | `[V4 REQUIRED]` |
| Deletion | Removes uploads, derived crops, models, renders and records | P0 | `[V4 REQUIRED]` |
| Access control | Only the owner and those they share with | P0 | `[V4 REQUIRED]` |
| Tenancy | One person's data never influences another's design | P0 | `[CURRENT]` for assets; `[V4 REQUIRED]` elsewhere |
| Encryption | In transit and at rest | P0 | `[V4 REQUIRED]` |
| People in photos | Flaggable; excluded from retention by default | P1 | `[V4 REQUIRED]` |
| Data export | The person can obtain what is held about their project | P1 | `[V4 REQUIRED]` |
| Address data | Collected only if needed for matchmaking, and separately consented | P1 | `[FUTURE]` |

### 42.3 The rule on training data

**PR-PRIVACY-001 · P0:** *Allure must not train on a person's home photographs because they used the product.*

Producing a design and improving a model are different purposes. Bundling them into one acceptance is not informed consent, and for photographs of a home it would be a serious breach of the relationship the product depends on.

---

## 43. Product Security

| Requirement | User-facing meaning | Pri | Status |
|---|---|---|---|
| Authentication | You have an account; your projects are yours | P0 | `[V4 REQUIRED]` (G1) |
| Authorization | Nobody else can open your project | P0 | `[V4 REQUIRED]` |
| Project isolation | Your files are not reachable by others | P0 | `[V4 REQUIRED]` |
| Safe uploads | A malicious file cannot harm the service | P0 | `[CURRENT]` |
| Safe asset access | Your renders are not publicly enumerable | P0 | `[V4 REQUIRED]` |
| API protection | Rate-limited against abuse | P0 | `[V4 REQUIRED]` |
| **Spend protection** | Nobody can spend Allure's or your credits without authorization | P0 | `[V4 REQUIRED]` |
| Audit logging | Actions on a project are attributable | P1 | `[V4 REQUIRED]` |
| Share-link safety | Sharing grants viewing, not control, and is revocable | P0 | `[V4 REQUIRED]` |

**The current state, stated plainly:** anyone who can reach the application can open any project and trigger paid 3D generation. **The product cannot be exposed beyond a trusted machine until this is closed.** This single gap gates launch regardless of every other capability.

---

## 44. Product Analytics

### 44.1 Events

```
project_created            input_uploaded            input_rejected
analysis_started           analysis_completed        intent_confirmed
intent_edited              element_reviewed          element_approved
element_skipped            element_corrected         moodboard_generated
moodboard_regenerated      asset_generation_started  asset_generated
asset_failed               scene_ready               render_ready
validation_started         validation_passed         validation_failed
repair_triggered           repair_succeeded          repair_exhausted
human_review_opened        human_review_resolved     design_approved
design_rejected            design_edited             version_created
version_reverted           viewer_opened             object_selected
share_link_created         designer_match_requested  project_deleted
```

### 44.2 What each event carries

| Carries | Never carries |
|---|---|
| Project identifier | Photographs or crops |
| Stage and timestamp | Brief text or prompt text |
| Outcome | Addresses or personal details |
| Duration | Model outputs |
| Counts (elements, instances, generations) | Anything identifying a person |
| Cost figures | — |

**PR-ANALYTICS-002 · P0:** analytics measure **the journey**, not the content. A product that holds home photographs must be disciplined about what leaves it.

### 44.3 What analytics must answer

| Question | Events |
|---|---|
| Where do people stop? | funnel from `project_created` to `design_approved` |
| Do people trust the output? | `design_approved` vs `design_rejected` vs `design_edited` |
| Is verification working? | `validation_passed` / `validation_failed` / `repair_*` |
| Are we asking too much? | question count per project; `element_corrected` rate |
| Is reuse working? | generations ÷ instances |
| Are we escalating too often? | `human_review_opened` ÷ projects |
| What does a project cost? | cost events per project |
| Does the viewer matter? | `viewer_opened`, `object_selected` vs acceptance rate |

---

## 45. AI Transparency

### 45.1 The stance

Allure does not hide that it uses AI, and does not make AI the story. The person needs to know **what was decided for them** and **how much to trust it** — not which model produced it.

### 45.2 What is communicated, and what is not

| Communicate | Do not communicate |
|---|---|
| "We estimated this dimension" | Which model estimated it |
| "This was inferred from your reference photo" | The confidence score |
| "3D models approximate the pictured piece" | The mesh provider's name |
| "We checked this design" | That a separate verification model exists |
| "We're correcting the layout" | That an orchestration system decided to |
| "A designer should review this before you build" | Internal reasoning |

### 45.3 Required disclosures

| When | Disclosure | Pri |
|---|---|---|
| A value was inferred | Marked inferred, editable | P0 |
| A dimension was estimated | Marked estimated wherever shown | P0 |
| Confidence is low on something important | Flagged, correction invited | P0 |
| A 3D model was generated | Stated as an approximation | P1 |
| A stand-in was substituted | Clearly labelled | P0 |
| Verification could not complete | Stated as unverified | P0 |
| A material was substituted | Stated | P1 |
| The design is a visualization | Present at the point of review | P0 |
| Professional review is advisable before building | Present at handoff | P0 |

### 45.4 Language the product must not use

| Never | Because |
|---|---|
| "AI magically understands your home" | It does not, and the claim invites misplaced trust |
| "Perfect visualization" | Nothing here is perfect |
| "100% accurate" | Accuracy is measured, bounded and partly unknown |
| "Construction-ready" | §35.2 |
| "Guaranteed to fit" | The scene is validated against *stated or estimated* dimensions |
| "Photorealistic" used to imply *photographically true to the built result* | It is true to the **validated scene**, which is the checkable claim |

---

## 46. Product Safety Boundaries

### 46.1 The ladder Allure must not blur

```
VISUALIZATION          ← Allure produces this
DESIGN ASSISTANCE      ← Allure produces this
SPATIAL VALIDATION     ← Allure produces this, within stated standards
─────────────────────────────────────────────
PROFESSIONAL DESIGN    ← a qualified designer
ENGINEERING            ← a qualified engineer
CONSTRUCTION           ← a qualified builder
```

**Everything above the line is Allure. Everything below it is a person with a qualification.** The product must never let a user believe it has crossed that line.

### 46.2 What Allure must never present its output as

| Never | Why |
|---|---|
| Structural engineering | Loads, spans and structure require an engineer |
| Guaranteed building-code compliance | Codes are jurisdictional and change |
| Construction documentation | Requires professional detailing |
| Safety certification | Requires a qualified authority |
| A guarantee that furniture will fit the real room | Validated against **stated or estimated** dimensions, which may be wrong |

### 46.3 What Allure may honestly claim

| May claim | Precise form |
|---|---|
| The design fits the room **as described** | "Fits the dimensions you provided" / "the dimensions we estimated" |
| Clearances follow common standards | "Laid out using standard residential clearances" — not "code compliant" |
| The render matches the validated scene | "This image was produced from the design we checked" |
| Elements are traceable | "Every piece here traces back to something you gave us" |
| The design is a starting point for a professional | "Take this to a designer" |

### 46.4 The safety requirement

**PR-TRUST-002 · P0:** *The product must not claim physical accuracy, code compliance or construction readiness it has not verified.*

This is not legal caution. It is the same principle as §23.4: **converting uncertainty into confidence is the specific harm this product exists to prevent.** A person who over-trusts an Allure output and builds from it has been failed by the product, however good the render looked.

---

## 47. Performance Requirements

**No numeric targets are invented.** Each has a measurement method; targets are set after baselines exist.

| Experience | Requirement | Baseline | Target | Measurement |
|---|---|---|---|---|
| Upload feedback | Immediate visual acknowledgement | `[CURRENT]` acceptable | — | Time to thumbnail |
| Project creation | Completes without a perceptible wait | `[CURRENT]` acceptable | — | Request duration |
| Progress visibility | Every stage streams its current activity | `[PARTIAL]` | No stage silent beyond a defined threshold | Time between status updates |
| **Time to first visual** | Person sees something of their design | `UNKNOWN` | Set after baseline | creation → first moodboard |
| **Time to validated design** | Person reaches a verified design | `UNKNOWN` | Set after baseline | creation → verification passed |
| 3D model generation | Bounded, resumable, leavable | `[CURRENT]` minutes | — | Job duration |
| Layout solving | Bounded | `[CURRENT]` ~2 min observed | — | Job duration |
| Scene assembly | Bounded | `[MEASURED 2026-09-21]` **29.7 s mean, N=3 projects / N=6 runs** (15.8–39.4). ~~40–60 s~~ was N=1. | — | Job duration |
| Render | Bounded | `[CURRENT]` seconds per view observed | — | Job duration |
| Viewer load | Loads on a mid-range laptop | `[PARTIAL]` | Set after baseline | Time to interactive |
| Editing response | A local change is faster than a full run | `[V4 REQUIRED]` | Set after baseline | Edit → updated render |
| Recovery | Resume after interruption without rework | `[CURRENT]` | — | Resume correctness |

**The one hard rule:** no stage may present a progress indicator it cannot complete (§31.3). Latency is tolerable; a lie about progress is not.

---

## 48. Product Cost

### 48.1 What costs money

| Cost | Incurred when | Visible to person |
|---|---|---|
| Design understanding (AI inference) | Every analysis | No — absorbed |
| Element and moodboard images | Every moodboard | No — **badged free** |
| **3D model generation** | Approved pieces only | **Yes — badged paid** |
| GPU time | Image generation, rendering | No |
| Scene assembly and rendering | Every build | No |
| Storage | Continuously | No |
| Bandwidth | Viewing and sharing | No |

### 48.2 Requirements

| Requirement | Pri | Status |
|---|---|---|
| The paid step is clearly marked before it runs | P0 | `[CURRENT]` |
| Free steps are marked free and repeatable | P0 | `[CURRENT]` |
| The person sees the cost implication of their approvals before generating | P1 | `[V4 REQUIRED]` |
| Re-running never re-charges for unchanged pieces | P1 | `[V4 REQUIRED]` |
| A spend limit halts generation and preserves the project | P0 | `[V4 REQUIRED]` |
| **Cost per completed project is computable** | P1 | `[V4 REQUIRED]` |
| Cost is attributable to stage and provider | P1 | `[V4 REQUIRED]` |

### 48.3 Why this matters to product, not just finance

The approval gate (§17.4) is a **cost control the person operates**. It only works if they understand what they are approving. `[V4 REQUIRED]` Showing "8 models to build" before the paid step converts an abstract charge into an informed decision — and makes the free/paid split the honest thing it is currently designed to be.

`BASELINE = UNKNOWN` for every cost figure. Pricing decisions must wait for measurement.

---

## 49. Release Gates

Each gate has explicit acceptance. A gate does not pass partially.

### GATE 0 — Product definition complete
**Accepts when:** this PRD is reviewed and agreed; scope, non-goals and invariants signed off; every `[UNKNOWN]` edge case has an owner.
**Status:** this document.

### GATE 1 — Input and intent
**Accepts when:** a project is creatable with name, type and description alone · photos, references and dimensions upload with validation and individual removal · intent is structured and shown back for confirmation · **stated and inferred values are visually distinguishable** · floor plans are either read or explicitly declined.
**Blocks on:** PR-INPUT-004, PR-INTENT-002, PR-TRUST-001.

### GATE 2 — Element-first pipeline
**Accepts when:** elements identified with instance counts · "3 matching bar stools" presented as one kind · element states visible · **kept furniture marked and preserved** · approval gates spend · shortfalls explainable.
**Blocks on:** PR-ELEMENT-003, PR-ELEMENT-004.

### GATE 3 — 3D asset pipeline
**Accepts when:** approved pieces become 3D models · identical pieces share one model · **re-running never re-charges** · failures produce **labelled** stand-ins · generated models stay project-scoped.
**Blocks on:** PR-IDENTITY-004, PR-ASSET-003.

### GATE 4 — Spatially valid scene
**Accepts when:** the scene passes geometry and clearance validation with zero violations · unplaceable pieces reported by name with reasons · trade-offs explained in plain language with options · placement is deterministic.
**Blocks on:** PR-SPATIAL-004, PR-SPATIAL-005.

### GATE 5 — Photorealistic render
**Accepts when:** the render is produced from the validated scene · **quality settings are verified applied** · materials come from the design · scale is correct · multiple viewpoints exist · renders are labelled visualizations.
**Blocks on:** PR-RENDER-002 — *the defect that has degraded every render to date.*

### GATE 6 — Independent verification
**Accepts when:** every design carries a verification result · results are plain language · **a check that could not run reports unverified** · the person can see what was checked.
**Blocks on:** PR-VALIDATION-001, PR-VALIDATION-002.

### GATE 7 — Repair loop
**Accepts when:** automatic repair is bounded at 2 attempts · attempts are visible as "attempt N of 2" · exhaustion escalates with a plain explanation · **no infinite progress state exists** · ambiguity is never resolved by guessing.
**Blocks on:** PR-REPAIR-001, PR-REPAIR-003.

### GATE 8 — Human review
**Accepts when:** a review surface presents render, scene, inventory, assumptions, validation and issues · approve / edit / regenerate / reject all work · **rejection preserves work** · an accepted design survives a later experiment · escalations route correctly between homeowner and operations.
**Blocks on:** PR-REVIEW-001, PR-VERSION-001.

### GATE 9 — End-to-end benchmark
**Accepts when:** **all ten golden journeys pass** their acceptance criteria, including journey 8's injected failure and journey 9's edit-and-preserve.
**Blocks on:** §39 in full.

### GATE 10 — Production security and observability
**Accepts when:** accounts and project ownership enforced · **paid generation requires authentication and respects a spend limit** · share links are view-only and revocable · deletion is complete · retention automated · journey analytics emitted · **cost per project computable** · no raw errors reach the interface.
**Blocks on:** PR-SECURITY-001, PR-SECURITY-003, PR-PRIVACY-002.

**Gates 5, 6 and 10 are the ones most likely to be under-estimated.** Gate 5 looks cosmetic and is not — it is the product's central visual promise, silently broken. Gate 6 is the differentiator. Gate 10 is the reason the product cannot currently be shown to anyone outside a trusted machine.

---

## 50. V4 Definition of Done

V4 is complete when **every** box is true, with evidence:

### The journey
- [ ] A person can create a residential project
- [ ] A person can provide intent in natural language
- [ ] A person can upload room images
- [ ] A person can optionally provide a floor plan or dimensions — **and if a floor plan is accepted, it is used**
- [ ] A person can provide style references
- [ ] **The system distinguishes stated facts from inferences, visibly, everywhere**
- [ ] The system identifies design elements
- [ ] The system identifies element instances
- [ ] **Identity persists from proposal to final render**
- [ ] Canonical assets are reused across identical pieces
- [ ] A moodboard is generated from the approved pieces
- [ ] 3D assets are generated or reused, **without ever re-charging for unchanged pieces**
- [ ] The Spatial Engine solves the scene
- [ ] The scene is spatially valid
- [ ] Blender produces the scene
- [ ] A photorealistic render is generated **with quality settings verified applied**
- [ ] **The render is independently verified against the scene**
- [ ] Failures are automatically repaired within **2 attempts**, visibly
- [ ] Human review exists and routes correctly
- [ ] A person can edit the design without starting over
- [ ] **Design versions are preserved; an accepted design survives an experiment**
- [ ] **Provenance resolves every rendered object to its source**
- [ ] The final output is a validated 3D design artifact, not only an image

### The product around it
- [ ] Accounts, project ownership and **spend protection** are enforced
- [ ] Privacy: separate consent, automated retention, complete deletion
- [ ] Journey analytics are emitted, without collecting content
- [ ] **Cost per completed project is computable**
- [ ] No raw error, code or internal identifier appears in the interface
- [ ] No route in the application returns an error page
- [ ] The designer step either functions or is honestly labelled a preview
- [ ] Accessibility: keyboard, focus, non-colour status, announced progress
- [ ] **All ten golden journeys pass**

### The honesty conditions
- [ ] No claim of perfect accuracy, code compliance or construction readiness
- [ ] Every estimated dimension is marked wherever it appears
- [ ] Verification that could not run reports **unverified**, never verified
- [ ] Stand-ins are visibly labelled
- [ ] Every published metric states its method, date and **N**

---

# 51. Product Invariants

**These must never be violated. A change that breaks one is a change to the product, not a refinement of it.**

### 1. User intent is the starting point
The person's stated intent is what the system is accountable to. It is never replaced by the system's preference.

### 2. User edits are never silently discarded
A stated value survives every later stage, or the person is told why it could not.

### 3. AI inference must not be presented as confirmed fact
Inferred and estimated values are visibly marked in every surface that shows them.

### 4. The final scene must be spatially validated
No design reaches the person without passing geometry and clearance validation.

### 5. A photorealistic render is not automatically considered correct
Beauty is not correctness. The render is correct when it corresponds to the validated scene.

### 6. Element identity must persist
An element is identifiable from proposal to final render.

### 7. Repeated elements must support multiple instances
Three identical stools are three things, not one and not three kinds.

### 8. Multiple instances may share a canonical asset
Three identical stools cost one generation.

### 9. Moodboard position is not authoritative 3D position
A moodboard shows direction. The scene shows truth.

### 10. The Spatial Engine owns final spatial truth
Nothing that guesses places furniture.

### 11. Blender renders the validated scene
It executes; it never re-solves, re-positions or re-scales.

### 12. Validation is independent from generation
The system that checks is not the system that produced.

### 13. The product must communicate meaningful uncertainty
Not every internal number — the ones that change what the person should do.

### 14. Automatic repair must be bounded
Two attempts, visibly counted, then a human. **No infinite progress state, ever.**

### 15. Human review must exist for unresolved critical ambiguity
Where the system cannot decide safely, a person decides.

### 16. Users must be able to revise their design
Review, correct, reject, refine — always available.

### 17. Design versions must be recoverable
An accepted design is never lost to a later experiment.

### 18. Marketplace recommendations must not imply guaranteed work
For the homeowner or the professional.

### 19. Allure must not present visualization as engineering certification
Visualization, design assistance and spatial validation are above the line. Professional design, engineering and construction are below it.

### 20. The final product artifact is a validated, photorealistic 3D representation of the user's residential design intent
Not a picture. A checked, traceable, spatially valid space.

---

*End of Product Requirements Document.*
*Technical requirements: `TRD.md` · internal architecture: `design.md` · implementation roadmap: `plan.md` · current-state evidence: `AUDIT_CODEBASE.md`.*
