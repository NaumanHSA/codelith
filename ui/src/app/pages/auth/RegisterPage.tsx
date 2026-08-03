import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Eye, EyeOff, FileText } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { toast } from 'sonner';

function getPasswordStrength(password: string): { score: number; label: string; color: string } {
  let score = 0;
  if (password.length >= 8) score++;
  if (/[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password)) score++;
  if (/[^A-Za-z0-9]/.test(password)) score++;
  const levels = [
    { label: '', color: '' },
    { label: 'Weak', color: '#ef4444' },
    { label: 'Fair', color: '#f59e0b' },
    { label: 'Good', color: '#eab308' },
    { label: 'Strong', color: '#22c55e' },
  ];
  return { score, ...levels[score] };
}

export default function RegisterPage() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { register } = useAuth();
  const navigate = useNavigate();

  const strength = getPasswordStrength(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirm) { setError('Passwords do not match'); return; }
    if (!agreed) { setError('You must agree to the terms'); return; }
    setLoading(true);
    try {
      await register(fullName, email, password);
      toast.success('Account created! Welcome aboard.');
      navigate('/app');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <Link to="/" className="inline-flex items-center gap-2 mb-6">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <FileText size={16} className="text-primary-foreground" />
            </div>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1rem', color: 'var(--foreground)' }}>
              doc-anything
            </span>
          </Link>
          <h1 className="text-foreground" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            Create your account
          </h1>
          <p className="text-muted-foreground mt-1" style={{ fontSize: '0.875rem' }}>
            Start documenting your code today
          </p>
        </div>

        <div className="bg-card border border-border rounded-xl p-7 shadow-sm">
          {error && (
            <div className="mb-5 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive" style={{ fontSize: '0.875rem' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Full name</label>
              <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} required
                placeholder="Jane Smith"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                style={{ fontSize: '0.9rem' }} />
            </div>

            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                style={{ fontSize: '0.9rem' }} />
            </div>

            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Password</label>
              <div className="relative">
                <input type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} required
                  placeholder="Min. 8 characters"
                  className="w-full px-3 py-2.5 pr-10 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all"
                  style={{ fontSize: '0.9rem' }} />
                <button type="button" onClick={() => setShowPassword(s => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {password && (
                <div className="mt-2">
                  <div className="flex gap-1 mb-1">
                    {[1, 2, 3, 4].map(i => (
                      <div key={i} className="flex-1 h-1 rounded-full transition-all"
                        style={{ backgroundColor: i <= strength.score ? strength.color : 'var(--border)' }} />
                    ))}
                  </div>
                  {strength.label && (
                    <p style={{ fontSize: '0.75rem', color: strength.color }}>{strength.label} password</p>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Confirm password</label>
              <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required
                placeholder="••••••••"
                className={`w-full px-3 py-2.5 rounded-lg border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-all ${confirm && confirm !== password ? 'border-destructive' : 'border-border'}`}
                style={{ fontSize: '0.9rem' }} />
              {confirm && confirm !== password && (
                <p className="mt-1 text-destructive" style={{ fontSize: '0.75rem' }}>Passwords don't match</p>
              )}
            </div>

            <label className="flex items-start gap-2.5 cursor-pointer">
              <input type="checkbox" checked={agreed} onChange={e => setAgreed(e.target.checked)}
                className="mt-0.5 accent-primary" />
              <span className="text-muted-foreground" style={{ fontSize: '0.8125rem', lineHeight: 1.5 }}>
                I agree to the{' '}
                <a href="#" className="text-brand hover:underline">Terms of Service</a>
                {' '}and{' '}
                <a href="#" className="text-brand hover:underline">Privacy Policy</a>
              </span>
            </label>

            <button type="submit" disabled={loading}
              className="w-full py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  Creating account...
                </>
              ) : 'Create account'}
            </button>
          </form>

          <div className="mt-5 pt-5 border-t border-border text-center">
            <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>
              Already have an account?{' '}
              <Link to="/auth/login" className="text-brand hover:underline font-medium">Sign in</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
