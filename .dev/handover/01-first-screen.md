> **How to use:** paste this whole file. See [README.md](README.md) for what to attach
> (optional for this one). This is the fast direction check — one screen, judged in
> minutes, before anyone designs the other nine.

---

# Design the front door for Document Anything

I need one screen designed, quickly, so I can decide whether I like where this is going
before we redesign an entire application. Design it well enough that I can judge the
direction from it alone.

## What the product is

**Document Anything** is an open-source tool that reads a codebase and writes real
technical documentation from it — architecture guides, API references, getting-started
guides, module docs. Not doc-comment scraping: it analyses the repository, builds a
knowledge base of what the system actually is, and then writes prose from that.

It runs **entirely on your own machine** against a local LLM. No API keys, no cloud, no
code leaving the box. For anyone who cannot paste proprietary source into a hosted
model, that is the whole reason the project exists.

It is free and open source. It is not a SaaS product and has no pricing.

## The screen

The public front door, for a visitor who has just landed on the project — plus the way
in for someone who already has an account. Whether that is one page or two, and whether
signing in is a route, a panel or an overlay, is your call.

By the time a visitor leaves this screen they should understand:

1. **What it does** — you point it at a repository and it writes the documentation.
2. **That it runs locally and offline.** Nothing is uploaded. This is the strongest
   thing we have to say and it should not be buried in a feature list.
3. **How it actually works** — and this is the part worth designing around, because it
   is what makes the product different from a wrapper around a chat model:

   > **First it analyses.** It clones the repo, extracts the facts (routes, entry
   > points, dependencies, config, data stores), summarises every module and works out
   > the architecture. That becomes a **knowledge base**, tied to the commit.
   >
   > **Then you choose what to write.** Because the analysis already happened, the tool
   > can tell you what is worth writing — it offers an API Reference only if it actually
   > found HTTP routes, and says *"28 routes detected"* as the reason.
   >
   > **Then it composes**, pulling the right slice of the knowledge base for every
   > section. Analyse once, write as many documents as you want.

   Analyse → knowledge base → choose → compose. That sequence is the product.

4. **That it is open source**, with a way to reach the repository.

And they must be able to **sign in** or **create an account**, without hunting for it.

Nothing else belongs on this screen. No pricing, no enterprise tier, no testimonials, no
customer logos, no fabricated statistics, no newsletter capture.

## What I want from the design

Modern, striking, and clearly built in this decade. I would like someone to open it and
stop for a second.

Move, if movement earns its place. Entrance choreography, scroll-driven reveals,
something alive in the hero, an interface that responds to the cursor — whatever you
think makes it land. I am not asking for restraint. I am asking that anything that
moves has a reason, respects `prefers-reduced-motion`, and never delays someone who just
wants to sign in.

**The visual language is entirely your call.** Layout, type, composition, imagery,
depth, texture, illustration, motion, how you visualise the analyse→compose flow — all
yours. I have deliberately not described a layout, because I want your idea rather than
my own played back to me. Do not reach for the default developer-tool landing page
(centred hero, three feature cards, logo strip). If your first instinct is the layout
every AI dev tool already ships, discard it and find the second one.

Two hard constraints, and only two:

- **Light theme.** This is a light-first product. A dark theme comes later, so build
  your tokens so it can be added — but design light, and make light look deliberate,
  not like a dark design with the colours flipped.
- **Orange is the accent.** Which orange, how saturated, how often, and what it pairs
  with is up to you. It should feel like a considered brand choice rather than a hue
  applied to buttons.

Assume the rest of the application inherits whatever you establish here: a knowledge
base panel dense with extracted facts, a live progress view for a multi-stage job that
runs for minutes, a long-form document reader. Choose a system that can carry that, not
just a poster.

## Deliverable

**A single self-contained `.html` file** I can open in a browser — all CSS and JS
inline, no build step, no external requests (no CDN scripts, no Google Fonts, no remote
images; inline SVG and system or embedded fonts only). It must be responsive and it must
render as an interactive page, not a static mock.

Alongside it, briefly:

- **The tokens you chose** — colour ramps, type scale, radii, shadows, motion
  durations and easing, as CSS custom properties in the file. Everything else in the
  product will be built on these, so name them as a system rather than one-off values.
- **Two or three sentences** on the idea behind the direction, so I can tell whether I
  am rejecting the concept or just the execution.

Show me one direction, fully committed — not three safe variations.
