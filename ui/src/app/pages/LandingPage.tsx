import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router';
import {
  Github, Terminal, ArrowRight, Eye, EyeOff, GitBranch, Boxes,
  Workflow, Network, FileCode2, ServerCog,
} from 'lucide-react';
import { useAuth } from '../lib/auth';
import { toast } from 'sonner';

const REPO_URL = 'https://github.com/NaumanHSA/document-anything';

/** Mirrors the real graph order in app/workflows/documentation_workflow.py. */
const PIPELINE = [
  { agent: 'coordinator',        msg: 'Resolving job scope and sources' },
  { agent: 'repo_analyzer',      msg: 'Walked 142 files across 23 modules' },
  { agent: 'code_understanding', msg: 'Embedded 1,284 chunks → pgvector' },
  { agent: 'architecture',       msg: 'Mapped module boundaries and data flow' },
  { agent: 'planner',            msg: 'Drafted outline — 6 sections' },
  { agent: 'strategy',           msg: 'Assigned depth + audience per section' },
  { agent: 'writer',             msg: 'Writing sections (fan-out ×6)' },
  { agent: 'diagram',            msg: 'Generated 4 Mermaid diagrams' },
  { agent: 'qa',                 msg: 'Verified claims against source' },
  { agent: 'formatter',          msg: 'Rendered Markdown + MkDocs site' },
  { agent: 'publisher',          msg: 'Published 6 documents' },
];

// ─── Background ───────────────────────────────────────────────────────────────

function Backdrop() {
  const gridMask = 'radial-gradient(ellipse 75% 60% at 50% 0%, #000 55%, transparent 100%)';
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)',
          backgroundSize: '56px 56px',
          maskImage: gridMask,
          WebkitMaskImage: gridMask,
        }}
      />
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(58% 44% at 18% -6%, rgba(79,142,247,0.20), transparent 68%), radial-gradient(48% 40% at 88% 4%, rgba(167,139,250,0.14), transparent 70%)',
        }}
      />
    </div>
  );
}

// ─── Animated pipeline terminal ───────────────────────────────────────────────

function PipelineTerminal() {
  const [done, setDone] = useState(0);
  const holdRef = useRef(0);

  useEffect(() => {
    const id = setInterval(() => {
      setDone(n => {
        if (n < PIPELINE.length) return n + 1;
        // Linger on the finished run before looping.
        holdRef.current += 1;
        if (holdRef.current > 6) {
          holdRef.current = 0;
          return 0;
        }
        return n;
      });
    }, 620);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="rounded-xl border border-border bg-card/70 backdrop-blur overflow-hidden shadow-2xl shadow-black/40">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-secondary/40">
        <span className="w-2.5 h-2.5 rounded-full bg-[#ef4444]/70" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#fbbf24]/70" />
        <span className="w-2.5 h-2.5 rounded-full bg-[#34d399]/70" />
        <span
          className="ml-2 text-muted-foreground"
          style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
        >
          job #42 — langgraph pipeline
        </span>
      </div>

      <div className="p-4 space-y-1.5" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}>
        {PIPELINE.map((step, i) => {
          const state = i < done ? 'done' : i === done ? 'active' : 'idle';
          return (
            <div
              key={step.agent}
              className="flex items-start gap-2.5 transition-all duration-500"
              style={{
                opacity: state === 'idle' ? 0.22 : 1,
                transform: state === 'idle' ? 'translateY(2px)' : 'none',
              }}
            >
              <span className="w-3.5 shrink-0 pt-px">
                {state === 'done' ? (
                  <span className="text-[#34d399]">✓</span>
                ) : state === 'active' ? (
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand animate-pulse" />
                ) : (
                  <span className="text-muted-foreground">·</span>
                )}
              </span>
              <span className="shrink-0 text-brand" style={{ minWidth: '9.5rem' }}>
                {step.agent}
              </span>
              <span className="text-muted-foreground">{step.msg}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Auth card ────────────────────────────────────────────────────────────────

const isDev = Boolean((import.meta as { env: Record<string, unknown> }).env.DEV);

function AuthCard() {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const switchMode = (next: 'login' | 'register') => {
    setMode(next);
    setError('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (mode === 'login') {
        await login(email, password);
        toast.success('Welcome back');
      } else {
        await register(fullName, email, password);
        toast.success('Account created');
      }
      navigate('/app');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setLoading(false);
    }
  };

  const inputClass =
    'w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition-all';

  return (
    <div
      id="get-started"
      className="rounded-2xl border border-border bg-card/80 backdrop-blur p-6 shadow-2xl shadow-black/50"
    >
      <div className="flex p-1 rounded-lg bg-secondary/60 mb-6">
        {(['login', 'register'] as const).map(m => (
          <button
            key={m}
            type="button"
            onClick={() => switchMode(m)}
            className="flex-1 py-2 rounded-md transition-all"
            style={{
              fontSize: '0.875rem',
              fontWeight: 500,
              background: mode === m ? 'var(--card)' : 'transparent',
              color: mode === m ? 'var(--foreground)' : 'var(--muted-foreground)',
              boxShadow: mode === m ? '0 1px 2px rgba(0,0,0,0.4)' : 'none',
            }}
          >
            {m === 'login' ? 'Sign in' : 'Create account'}
          </button>
        ))}
      </div>

      {error && (
        <div
          className="mb-4 p-3 rounded-lg bg-destructive/10 border border-destructive/25 text-destructive"
          style={{ fontSize: '0.8125rem' }}
        >
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-3.5">
        {mode === 'register' && (
          <div>
            <label className="block text-foreground mb-1.5" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
              Full name
            </label>
            <input
              type="text"
              value={fullName}
              onChange={e => setFullName(e.target.value)}
              required
              placeholder="Ada Lovelace"
              className={inputClass}
              style={{ fontSize: '0.9rem' }}
            />
          </div>
        )}

        <div>
          <label className="block text-foreground mb-1.5" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            placeholder="you@example.com"
            className={inputClass}
            style={{ fontSize: '0.9rem' }}
          />
        </div>

        <div>
          <label className="block text-foreground mb-1.5" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>
            Password
          </label>
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              placeholder="••••••••"
              className={`${inputClass} pr-10`}
              style={{ fontSize: '0.9rem' }}
            />
            <button
              type="button"
              onClick={() => setShowPassword(s => !s)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 rounded-lg bg-brand text-brand-foreground hover:opacity-90 transition-opacity disabled:opacity-60 flex items-center justify-center gap-2"
          style={{ fontSize: '0.9375rem', fontWeight: 600 }}
        >
          {loading ? (
            <>
              <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
              {mode === 'login' ? 'Signing in…' : 'Creating account…'}
            </>
          ) : (
            <>
              {mode === 'login' ? 'Sign in' : 'Create account'}
              <ArrowRight size={16} />
            </>
          )}
        </button>
      </form>

      {isDev && mode === 'login' && (
        <button
          type="button"
          onClick={() => {
            setEmail('admin@docany.dev');
            setPassword('admin1234');
          }}
          className="mt-3 w-full text-muted-foreground hover:text-foreground transition-colors"
          style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}
        >
          fill seeded admin credentials
        </button>
      )}
    </div>
  );
}

// ─── Sections ─────────────────────────────────────────────────────────────────

function Nav() {
  return (
    <nav className="relative z-10 flex items-center justify-between px-6 py-5 max-w-6xl mx-auto">
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-brand/15 border border-brand/30 flex items-center justify-center">
          <Terminal size={15} className="text-brand" />
        </div>
        <span
          className="text-foreground"
          style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '0.95rem' }}
        >
          document-anything
        </span>
      </div>

      <div className="flex items-center gap-2">
        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          style={{ fontSize: '0.8125rem' }}
        >
          <Github size={15} />
          <span className="hidden sm:inline">GitHub</span>
        </a>
        <a
          href="#get-started"
          className="px-3.5 py-2 rounded-lg bg-foreground text-background hover:opacity-90 transition-opacity"
          style={{ fontSize: '0.8125rem', fontWeight: 600 }}
        >
          Get started
        </a>
      </div>
    </nav>
  );
}

function Hero() {
  return (
    <section className="relative z-10 max-w-6xl mx-auto px-6 pt-10 pb-16">
      <div className="grid lg:grid-cols-[1.1fr_0.9fr] gap-12 lg:gap-16 items-start">
        {/* Left — the pitch */}
        <div>
          <div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border bg-secondary/50 text-muted-foreground mb-6"
            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-[#34d399]" />
            open source · self-hosted · runs offline
          </div>

          <h1
            className="text-foreground mb-5"
            style={{
              fontSize: 'clamp(2rem, 4.6vw, 3.15rem)',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              lineHeight: 1.12,
              letterSpacing: '-0.02em',
            }}
          >
            Documentation that
            <br />
            <span className="text-brand">reads your code</span> first.
          </h1>

          <p className="text-muted-foreground mb-8 max-w-xl" style={{ fontSize: '1.0625rem', lineHeight: 1.65 }}>
            Point it at a repository. A pipeline of eleven specialised agents clones it,
            reads it, maps the architecture, then writes the docs — with diagrams, and a
            QA pass that checks every claim back against the source.
          </p>

          <ul className="space-y-2.5">
            {[
              'Your code never leaves your machine — any OpenAI-compatible endpoint',
              'Markdown, DOCX, MkDocs and Docusaurus output',
              'Every run traced step by step, on disk',
            ].map(item => (
              <li key={item} className="flex items-start gap-2.5 text-muted-foreground">
                <span className="text-brand mt-0.5 shrink-0" style={{ fontSize: '0.8rem' }}>▸</span>
                <span style={{ fontSize: '0.9375rem' }}>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Right — auth */}
        <div>
          <AuthCard />
          <p className="text-center text-muted-foreground mt-4" style={{ fontSize: '0.75rem' }}>
            Self-hosted — your account lives in your own database.
          </p>
        </div>
      </div>

      {/* Full-width so the run reads like a real log, not a sidebar widget */}
      <div className="mt-14">
        <PipelineTerminal />
      </div>
    </section>
  );
}

const FEATURES = [
  {
    icon: Workflow,
    title: 'Multi-agent pipeline',
    body: 'A LangGraph state machine coordinates eleven agents, fanning out one writer per section and rejoining for review.',
  },
  {
    icon: GitBranch,
    title: 'Reads real repositories',
    body: 'Clones from GitHub, GitLab or Bitbucket, or ingests local folders and files across a dozen languages.',
  },
  {
    icon: Network,
    title: 'Grounded in your code',
    body: 'pgvector semantic search over embedded chunks, plus a Neo4j graph of how code entities actually relate.',
  },
  {
    icon: ServerCog,
    title: 'Fully offline',
    body: 'Talks to LM Studio, vLLM, Ollama — anything OpenAI-compatible. No third-party API, no data leaving your box.',
  },
  {
    icon: FileCode2,
    title: 'Publishable output',
    body: 'Ships Markdown, DOCX, and ready-to-deploy MkDocs and Docusaurus sites — not just a wall of text.',
  },
  {
    icon: Boxes,
    title: 'Built to self-host',
    body: 'FastAPI, Postgres, Redis and Celery in Docker Compose, with Kubernetes manifests when you outgrow it.',
  },
];

function Features() {
  return (
    <section className="relative z-10 max-w-6xl mx-auto px-6 py-16 border-t border-border">
      <h2
        className="text-foreground mb-3"
        style={{
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          fontSize: 'clamp(1.35rem, 2.4vw, 1.75rem)',
        }}
      >
        What's under the hood
      </h2>
      <p className="text-muted-foreground mb-10" style={{ fontSize: '0.9375rem' }}>
        No magic and no lock-in — every piece is something you can run and inspect yourself.
      </p>

      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {FEATURES.map(f => (
          <div
            key={f.title}
            className="group p-5 rounded-xl border border-border bg-card/50 hover:bg-card hover:border-brand/40 transition-all"
          >
            <div className="w-9 h-9 rounded-lg bg-brand/10 border border-brand/20 flex items-center justify-center mb-4 group-hover:bg-brand/20 transition-colors">
              <f.icon size={16} className="text-brand" />
            </div>
            <h3 className="text-foreground mb-2" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>
              {f.title}
            </h3>
            <p className="text-muted-foreground" style={{ fontSize: '0.85rem', lineHeight: 1.6 }}>
              {f.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

const STACK = [
  'FastAPI', 'LangGraph', 'PostgreSQL', 'pgvector', 'Redis',
  'Celery', 'Neo4j', 'MinIO', 'React', 'Docker',
];

function Stack() {
  return (
    <section className="relative z-10 max-w-6xl mx-auto px-6 py-14 border-t border-border">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5">
        <span
          className="text-muted-foreground mr-2"
          style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
        >
          built with
        </span>
        {STACK.map(s => (
          <span
            key={s}
            className="px-2.5 py-1 rounded-md border border-border bg-secondary/40 text-muted-foreground"
            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem' }}
          >
            {s}
          </span>
        ))}
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="relative z-10 border-t border-border">
      <div className="max-w-6xl mx-auto px-6 py-8 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <Terminal size={14} className="text-muted-foreground" />
          <span
            className="text-muted-foreground"
            style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}
          >
            document-anything
          </span>
        </div>

        <div className="flex items-center gap-5">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
            style={{ fontSize: '0.8125rem' }}
          >
            <Github size={14} />
            Source
          </a>
          <a
            href={`${REPO_URL}/issues`}
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground transition-colors"
            style={{ fontSize: '0.8125rem' }}
          >
            Issues
          </a>
          <a
            href="#get-started"
            className="text-muted-foreground hover:text-foreground transition-colors"
            style={{ fontSize: '0.8125rem' }}
          >
            Get started
          </a>
        </div>
      </div>
    </footer>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LandingPage() {
  return (
    <div className="relative min-h-screen bg-background">
      <Backdrop />
      <Nav />
      <Hero />
      <Features />
      <Stack />
      <Footer />
    </div>
  );
}
