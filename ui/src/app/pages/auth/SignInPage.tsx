import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth'
import { ApiError, API_BASE } from '../../lib/api'
import { Button, Field, inputClass } from '../../components/ui'
import { ErrorState } from '../../components/States'
import AuthLayout from './AuthLayout'

/**
 * One-click sign-in for local testing.
 *
 * There is no anonymous session in the API — this signs in as the account
 * `scripts/seed_dev.py` creates, which is why it needs a real role rather than a
 * read-only one: a guest who cannot create a project or start an analysis cannot
 * test anything. Override the pair with VITE_GUEST_EMAIL / VITE_GUEST_PASSWORD.
 */
const GUEST = {
  email: (import.meta.env.VITE_GUEST_EMAIL as string | undefined) ?? 'admin@codelith.dev',
  password: (import.meta.env.VITE_GUEST_PASSWORD as string | undefined) ?? 'admin1234',
}

/**
 * Whether to offer it at all.
 *
 * On under `pnpm dev`, and otherwise only when somebody sets `VITE_GUEST_LOGIN=1` at
 * build time. It was keyed on `import.meta.env.DEV` alone, which reads as "local
 * only" and is not: `DEV` is false in every `pnpm build`, including the build the API
 * serves at its own root. So on the one machine where the button was wanted it was
 * the machine's build that removed it, and the button appeared to have been deleted.
 *
 * The flag stays opt-in because this is a *credentialled* button, not a guest
 * session. `APP_HOST` is `0.0.0.0` by default, so a build carrying it hands one-click
 * admin to anyone who can reach the port — which is the whole network, not the
 * person who built it.
 */
const GUEST_LOGIN =
  import.meta.env.DEV || ['1', 'true'].includes(String(import.meta.env.VITE_GUEST_LOGIN ?? ''))

export default function SignInPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/app'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'form' | 'guest' | null>(null)

  const enter = async (mail: string, pass: string, as: 'form' | 'guest') => {
    setBusy(as)
    setError(null)
    try {
      await signIn(mail, pass)
      navigate(from, { replace: true })
    } catch (err) {
      const rejected = err instanceof ApiError && (err.status === 401 || err.status === 400)
      setError(
        err instanceof ApiError
          ? rejected
            ? as === 'guest'
              ? `No account for ${mail}. Run \`make seed\` to create it.`
              : 'That email and password do not match an account.'
            : err.message
          : 'Could not sign in.',
      )
    } finally {
      setBusy(null)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void enter(email, password, 'form')
  }

  return (
    <AuthLayout
      index="01"
      title="Sign in"
      sub="Your session stays on this machine."
      footer={
        <>
          No account yet?{' '}
          <Link to="/register" className="font-semibold text-hot-ink hover:underline">
            Create one
          </Link>
          <span className="tag mt-3 block text-ink-dim">api · {API_BASE}</span>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        {error && <ErrorState message={error} compact />}

        <Field label="Email">
          <input
            type="email"
            required
            autoFocus
            autoComplete="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            className={inputClass}
          />
        </Field>

        <Field label="Password">
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            className={inputClass}
          />
        </Field>

        <Button type="submit" variant="hot" disabled={busy !== null} className="mt-1 w-full py-2.5">
          {busy === 'form' ? (
            <>
              <span className="anim-spin block size-[9px] rounded-full border border-current border-t-transparent" />
              signing in…
            </>
          ) : (
            'Sign in →'
          )}
        </Button>
      </form>

      {GUEST_LOGIN && (
        <div className="mt-5 border-t border-rule pt-4">
          <Button
            variant="ghost"
            disabled={busy !== null}
            onClick={() => void enter(GUEST.email, GUEST.password, 'guest')}
            className="w-full py-2.5"
          >
            {busy === 'guest' ? (
              <>
                <span className="anim-spin block size-[9px] rounded-full border border-current border-t-transparent" />
                signing in…
              </>
            ) : (
              'Sign in as guest'
            )}
          </Button>
          {/* The account, not the word "guest". It signs in with real credentials and
              real permissions, and a caption saying so is what keeps it from being
              read as an anonymous session. */}
          <p className="tag mt-2 text-center text-ink-dim">
            local testing · seeded account {GUEST.email}
          </p>
        </div>
      )}
    </AuthLayout>
  )
}
