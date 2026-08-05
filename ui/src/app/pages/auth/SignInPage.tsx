import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth'
import { ApiError, API_BASE } from '../../lib/api'
import { Button, Field, inputClass } from '../../components/ui'
import { ErrorState } from '../../components/States'
import AuthLayout from './AuthLayout'

export default function SignInPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/app'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.status === 401 || err.status === 400
            ? 'That email and password do not match an account.'
            : err.message
          : 'Could not sign in.',
      )
    } finally {
      setBusy(false)
    }
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

        <Button type="submit" variant="hot" disabled={busy} className="mt-1 w-full py-2.5">
          {busy ? (
            <>
              <span className="anim-spin block size-[9px] rounded-full border border-current border-t-transparent" />
              signing in…
            </>
          ) : (
            'Sign in →'
          )}
        </Button>
      </form>
    </AuthLayout>
  )
}
