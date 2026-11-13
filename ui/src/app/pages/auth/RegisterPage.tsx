import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth'
import { ApiError } from '../../lib/api'
import { Button, Field, inputClass } from '../../components/ui'
import { ErrorState } from '../../components/States'
import AuthLayout from './AuthLayout'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const tooShort = password.length > 0 && password.length < 8

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (tooShort) return
    setBusy(true)
    setError(null)
    try {
      await register(email, password, fullName)
      navigate('/app', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create the account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      index="02"
      title="Create an account"
      sub="First account on a fresh install becomes the admin."
      footer={
        <>
          Already have one?{' '}
          <Link to="/sign-in" className="font-semibold text-hot-ink hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={submit} className="flex flex-col gap-3">
        {error && <ErrorState message={error} compact />}

        <Field label="Full name">
          <input
            required
            autoFocus
            autoComplete="name"
            value={fullName}
            onChange={e => setFullName(e.target.value)}
            placeholder="Ada Lovelace"
            className={inputClass}
          />
        </Field>

        <Field label="Email">
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="you@example.com"
            className={inputClass}
          />
        </Field>

        <Field
          label="Password"
          help="At least 8 characters."
          error={tooShort ? 'At least 8 characters.' : null}
        >
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="••••••••"
            className={inputClass}
          />
        </Field>

        <Button
          type="submit"
          variant="hot"
          disabled={busy || tooShort}
          className="mt-1 w-full py-2.5"
        >
          {busy ? (
            <>
              <span className="anim-spin block size-[9px] rounded-full border border-current border-t-transparent" />
              Creating…
            </>
          ) : (
            'Create account'
          )}
        </Button>
      </form>
    </AuthLayout>
  )
}
