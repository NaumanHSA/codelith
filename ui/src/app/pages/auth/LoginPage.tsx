import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { Eye, EyeOff, FileText } from 'lucide-react';
import { useAuth } from '../../lib/auth';
import { toast } from 'sonner';

export default function LoginPage() {
  const [email, setEmail] = useState('admin@docany.dev');
  const [password, setPassword] = useState('admin1234');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login, loginDemo } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      toast.success('Welcome back!');
      navigate('/app');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid credentials');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
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
            Welcome back
          </h1>
          <p className="text-muted-foreground mt-1" style={{ fontSize: '0.875rem' }}>
            Sign in to your account
          </p>
        </div>

        {/* Card */}
        <div className="bg-card border border-border rounded-xl p-7 shadow-sm">
          {error && (
            <div className="mb-5 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive" style={{ fontSize: '0.875rem' }}>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                required
                placeholder="you@example.com"
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition-all"
                style={{ fontSize: '0.9rem' }}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-foreground" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Password</label>
                <a href="#" className="text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>Forgot password?</a>
              </div>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  placeholder="••••••••"
                  className="w-full px-3 py-2.5 pr-10 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent transition-all"
                  style={{ fontSize: '0.9rem' }}
                />
                <button type="button" onClick={() => setShowPassword(s => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
              {loading ? (
                <>
                  <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  Signing in...
                </>
              ) : 'Sign in'}
            </button>
          </form>

          <div className="mt-4">
            <div className="relative flex items-center gap-3 mb-4">
              <div className="flex-1 h-px bg-border" />
              <span className="text-muted-foreground" style={{ fontSize: '0.75rem' }}>or</span>
              <div className="flex-1 h-px bg-border" />
            </div>
            <button
              type="button"
              onClick={() => { loginDemo(); navigate('/app'); }}
              className="w-full py-2.5 border border-border rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              style={{ fontSize: '0.875rem' }}>
              Continue with Demo Account
            </button>
          </div>

          <div className="mt-5 pt-5 border-t border-border text-center">
            <p className="text-muted-foreground" style={{ fontSize: '0.875rem' }}>
              Don't have an account?{' '}
              <Link to="/auth/register" className="text-brand hover:underline font-medium">Create one</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
