# Landing Page Prompt

**Reference**: `00-design-system-and-context.md` for all colors, typography, and component styles.

Build a high-converting SaaS marketing landing page for **document-anything** at route `/` (or `index.html`).  
The page is public — no auth required. The only navigable action is **Sign In** / **Get Started**.

---

## Page Sections (top to bottom)

### 1. Navbar

- Logo left: dark blue document icon + "document-anything" wordmark in bold
- Nav links center (desktop): Features · How it Works · Formats · Pricing (placeholder link, no page needed)
- Right: "Sign In" button (secondary style) + "Get Started Free" button (primary, brand blue)
- Sticky on scroll, with a subtle `backdrop-blur` + `border-b` that appears after scrolling 80px
- Mobile: hamburger menu with slide-down drawer

**Sign In button** → navigates to `/auth/login`  
**Get Started Free** → navigates to `/auth/register`

---

### 2. Hero Section

Full-width, dark background (`brand-900`), white text.

**Layout**: Two-column on desktop (text left, visual right), single column centered on mobile.

**Left column — copy:**
- **Eyebrow tag**: small pill badge — "AI-Powered · Open Source" in `accent-500` color
- **H1** (56px bold): "Turn Any Codebase Into Beautiful Documentation"
- **Subtitle** (20px, neutral-300 color): "Drop a GitHub repo, upload files, or point to a local project. Our 12-agent AI pipeline reads your code, understands it, and writes production-grade docs — automatically."
- **CTA buttons** (row):
  - Primary: "Generate Docs Free" → `/auth/register`
  - Secondary (outline, white border): "Watch Demo" → opens a placeholder YouTube embed modal
- **Social proof line** (small text, muted): "✦ Works with GitHub · GitLab · Bitbucket · Local repos · PDF files"

**Right column — visual:**
A dark terminal/editor card mockup (`rounded-2xl`, `bg-neutral-800`, subtle inner glow). Show a fake but realistic animated sequence:
- A progress indicator with 4 steps: "Cloning repo → Analyzing code → 12 agents writing → Docs ready ✓"
- Below it, a snippet preview showing markdown output (fake content is fine, styled like a doc page)
- A subtle animated gradient border on the card (blue → purple shimmer)

---

### 3. Social Proof Strip

Light gray background strip (`neutral-100`).  
Centered text: "Documentation for any stack" followed by a horizontal row of technology logos (just name text pills if no logos available):

`Python` · `TypeScript` · `Go` · `Rust` · `Java` · `React` · `FastAPI` · `Django` · `Next.js` · `Kubernetes`

---

### 4. Features Grid

White background, section heading: "Everything your team needs to ship great docs"

**3-column grid** (single column on mobile), **6 feature cards**:

| Icon | Title | Body |
|---|---|---|
| 🤖 | 12 Specialized AI Agents | Planner, architect, writer, validator, reviewer, publisher — each agent has a specific role so docs are structured, accurate, and peer-reviewed by AI before you see them. |
| 🔍 | ReAct Intelligence | Agents don't just read prompts — they explore your repo using filesystem and Git tools, search semantically across your codebase, and verify every claim against source code. |
| 📄 | 4 Output Formats | Export as Markdown, DOCX, a full MkDocs site, or a Docusaurus site — all generated simultaneously from the same run. |
| 🔗 | Any Source | Connect GitHub, GitLab, Bitbucket repos or upload a local folder or PDF. Multiple sources per project supported. |
| ✅ | Human-in-the-Loop | Flag documentation jobs for human review before publishing. Reviewers approve or reject with comments. Full audit trail on every action. |
| 📊 | Live Progress Monitoring | Watch your 12 agents work in real time. See which agent is running, read its logs line by line, and track the documentation plan as it unfolds. |

Each card: white, `rounded-xl`, `border`, subtle `shadow-sm`, icon in a colored square, title bold, body muted gray text.

---

### 5. How It Works

Light background (`neutral-50`). Section heading: "From repo to docs in minutes"

**4-step horizontal stepper** (vertical on mobile):

```
Step 1               Step 2                  Step 3              Step 4
[ Paste URL ]    [ Agents explore ]     [ Review & approve ]  [ Download or deploy ]
Connect your     12 AI agents clone     Optionally review     Export Markdown, DOCX,
repo or upload   your code, map the     the generated         MkDocs, or Docusaurus.
files. Pick the  architecture, and      docs before           Deploy with one click.
doc types you    write documentation    publishing.
want.            for every section.
```

Between each step, a connecting arrow (`→`).  
Each step has: a numbered circle (brand blue), a short title, 2-3 lines of body text.

---

### 6. Output Formats Showcase

Dark background (`brand-900`), white text. Section heading: "Pick your format. We generate all of them."

**Tabbed component** with 4 tabs: Markdown · DOCX · MkDocs · Docusaurus

Each tab shows:
- A mockup screenshot or ASCII visual of what that format looks like (fake content OK)
- A short description of when to use it
- A "Download example" button (disabled, just for show — or link to a real example .md file)

---

### 7. Feature Highlight — Live Agent Monitoring

Two-column section (alternating layout from the "How It Works" pattern):
- **Left**: description text
  - Heading: "Watch your AI team work — live"
  - Body: "Every documentation job streams logs in real time. See which of the 12 agents is currently running, what files it's reading, what decisions it's making. Full execution trace saved to JSON for debugging."
  - CTA: "See it in action →" → `/auth/register`
- **Right**: a mock live-log terminal card, dark background, showing scrolling fake agent log lines like:
  ```
  [planner_agent]     info  Documentation plan created — 5 sections
  [architecture]      info  ReAct loop: reading app/config.py...
  [writer_agent]      info  Writing "API Reference" section...
  [validator_agent]   info  Verifying 12 claims against source...
  [publisher_agent]   info  Saved 5 documents ✓
  ```

---

### 8. Pricing Section (Placeholder)

Centered, white background. Section heading: "Simple, transparent pricing"

Three pricing cards side by side:

| Free | Pro | Enterprise |
|---|---|---|
| $0/mo | $29/mo | Custom |
| 3 projects | Unlimited projects | On-premise |
| 5 jobs/mo | 100 jobs/mo | Unlimited |
| Markdown only | All formats | All formats |
| Community support | Email support | Dedicated support |
| Get Started | Start Free Trial | Contact Us |

Middle card (Pro) should have a brand-blue highlighted border and a "Most Popular" badge.  
All buttons → `/auth/register` (no actual billing implemented).

---

### 9. CTA Banner

Full-width brand-blue background (`brand-500`).  
Centered:
- Heading (white, 36px bold): "Stop writing docs manually."
- Subtext (white, slightly transparent): "Let 12 AI agents do it while you ship features."
- Primary button (white background, brand text): "Generate Your First Docs Free"
- Links to `/auth/register`

---

### 10. Footer

Dark background (`brand-900`), white text.

**4-column grid**:
- **Col 1** — Logo + tagline + "© 2025 document-anything"
- **Col 2** — Product: Features · How it works · Formats · Changelog
- **Col 3** — Developers: API Docs · GitHub · Self-host Guide
- **Col 4** — Company: About · Blog · Contact

All links are `href="#"` placeholders unless they point to `/auth/login` or `/auth/register`.

---

## Animations & Polish

- Hero section: fade-in + slide-up on page load (staggered: eyebrow → H1 → subtitle → buttons)
- Feature cards: fade-in on scroll (IntersectionObserver or Framer Motion)
- Step indicators in "How it works": draw connecting line animation on scroll
- Pricing cards: subtle scale on hover
- Navbar CTA button: pulse glow animation to draw attention
- Color scheme: predominantly white/light with dark hero and dark CTA banner (contrast-first design)
