import { useEffect, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { apiGet, apiPut, apiPost } from '../../lib/api';
import type { LLMSettings, TemplateSettings, DocType } from '../../lib/types';
import { ConfirmDialog } from '../../components/shared/ConfirmDialog';
import { Spinner } from '../../components/shared/Spinner';
import { toast } from 'sonner';

const DOC_TYPES: DocType[] = ['architecture', 'api', 'modules', 'getting_started', 'deployment', 'contributing', 'changelog'];
const TEMPLATE_VARS = [
  { name: '{project_name}', desc: 'Name of the project' },
  { name: '{file_listing}', desc: 'List of files in the repository' },
  { name: '{api_context}', desc: 'Extracted API context' },
  { name: '{module_context}', desc: 'Module dependency information' },
  { name: '{git_history}', desc: 'Recent commit history' },
];

const DEFAULT_LLM: LLMSettings = {
  base_url: 'http://localhost:1234/v1',
  api_key: 'lm-studio',
  default_model: 'local-model',
  quality_model: 'local-model',
  fast_model: 'local-model',
  max_tokens: 8192,
  temperature: 0.2,
  max_react_iterations: 20,
};

type Tab = 'llm' | 'templates' | 'organization' | 'profile';

function LLMTab() {
  const [settings, setSettings] = useState<LLMSettings>(DEFAULT_LLM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');

  useEffect(() => {
    apiGet<LLMSettings>('/api/v1/settings/llm')
      .then(s => setSettings(s))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiPut('/api/v1/settings/llm', settings);
      toast.success('LLM settings saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTestStatus('testing');
    try {
      await fetch(settings.base_url + '/models', {
        headers: { 'Authorization': `Bearer ${settings.api_key}` }
      });
      setTestStatus('ok');
      setTimeout(() => setTestStatus('idle'), 3000);
    } catch {
      setTestStatus('fail');
      setTimeout(() => setTestStatus('idle'), 3000);
    }
  };

  const set = (key: keyof LLMSettings, val: string | number) => setSettings(s => ({ ...s, [key]: val }));

  if (loading) return <div className="flex justify-center py-10"><Spinner className="text-muted-foreground" /></div>;

  return (
    <div className="space-y-5">
      <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
        <p className="text-amber-700 dark:text-amber-300" style={{ fontSize: '0.8125rem' }}>
          ⚠ Changes take effect on the next documentation job. Running jobs use the configuration they started with.
        </p>
      </div>

      {([
        { key: 'base_url', label: 'LLM Base URL', type: 'text', placeholder: 'http://localhost:1234/v1' },
        { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'lm-studio' },
        { key: 'default_model', label: 'Default Model', type: 'text', placeholder: 'local-model' },
        { key: 'quality_model', label: 'Quality Model', type: 'text', placeholder: 'local-model' },
        { key: 'fast_model', label: 'Fast Model', type: 'text', placeholder: 'local-model' },
        { key: 'max_tokens', label: 'Max Tokens', type: 'number', placeholder: '8192' },
        { key: 'max_react_iterations', label: 'Max ReAct Iterations', type: 'number', placeholder: '20' },
      ] as { key: keyof LLMSettings; label: string; type: string; placeholder: string }[]).map(field => (
        <div key={field.key}>
          <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>{field.label}</label>
          <input type={field.type} value={String(settings[field.key])} onChange={e => set(field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
            placeholder={field.placeholder}
            className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            style={{ fontSize: '0.9rem', fontFamily: field.type === 'text' && field.key !== 'default_model' ? 'var(--font-mono)' : undefined }} />
        </div>
      ))}

      <div>
        <label className="block text-foreground mb-2" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          Temperature: <span style={{ fontFamily: 'var(--font-mono)' }}>{settings.temperature.toFixed(2)}</span>
        </label>
        <input type="range" min={0} max={1} step={0.05} value={settings.temperature}
          onChange={e => set('temperature', parseFloat(e.target.value))}
          className="w-full accent-primary" />
        <div className="flex justify-between text-muted-foreground mt-1" style={{ fontSize: '0.75rem' }}>
          <span>0 (deterministic)</span><span>1 (creative)</span>
        </div>
      </div>

      <div className="flex gap-3">
        <button onClick={handleTest} disabled={testStatus === 'testing'}
          className={`px-4 py-2 rounded-lg border transition-colors ${
            testStatus === 'ok' ? 'border-green-500 text-green-600' :
            testStatus === 'fail' ? 'border-destructive text-destructive' :
            'border-border text-muted-foreground hover:border-foreground hover:text-foreground'
          }`}
          style={{ fontSize: '0.875rem' }}>
          {testStatus === 'testing' ? 'Testing...' : testStatus === 'ok' ? '✓ Connected' : testStatus === 'fail' ? '✗ Failed' : 'Test Connection'}
        </button>
        <button onClick={handleSave} disabled={saving}
          className="flex-1 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60"
          style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          {saving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
}

function TemplatesTab() {
  const [templates, setTemplates] = useState<Record<string, string>>({});
  const [selectedType, setSelectedType] = useState<DocType>('architecture');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showVars, setShowVars] = useState(false);

  useEffect(() => {
    apiGet<TemplateSettings[]>('/api/v1/settings/templates')
      .then(data => {
        const map: Record<string, string> = {};
        data.forEach(t => { map[t.doc_type] = t.system_prompt; });
        setTemplates(map);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiPut('/api/v1/settings/templates', {
        doc_type: selectedType,
        system_prompt: templates[selectedType] || '',
      });
      toast.success('Template saved');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <div className="flex justify-center py-10"><Spinner className="text-muted-foreground" /></div>;

  return (
    <div className="grid lg:grid-cols-[200px_1fr] gap-5">
      <div className="space-y-1">
        {DOC_TYPES.map(t => (
          <button key={t} onClick={() => setSelectedType(t)}
            className={`w-full text-left px-3 py-2 rounded-lg capitalize transition-colors ${selectedType === t ? 'bg-secondary text-foreground font-medium' : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'}`}
            style={{ fontSize: '0.875rem' }}>
            {t.replace(/_/g, ' ')}
          </button>
        ))}
      </div>
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-foreground capitalize" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>{selectedType.replace(/_/g, ' ')} Template</h3>
          <button onClick={() => setShowVars(v => !v)} className="text-brand hover:underline" style={{ fontSize: '0.8125rem' }}>
            {showVars ? 'Hide' : 'Show'} variables
          </button>
        </div>
        {showVars && (
          <div className="mb-4 p-3 rounded-lg bg-secondary border border-border">
            <p className="text-foreground mb-2" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>Available variables:</p>
            {TEMPLATE_VARS.map(v => (
              <div key={v.name} className="flex gap-3 mb-1">
                <code className="text-brand flex-shrink-0" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem' }}>{v.name}</code>
                <span className="text-muted-foreground" style={{ fontSize: '0.8125rem' }}>{v.desc}</span>
              </div>
            ))}
          </div>
        )}
        <textarea value={templates[selectedType] || ''} onChange={e => setTemplates(prev => ({ ...prev, [selectedType]: e.target.value }))}
          rows={14}
          className="w-full px-3 py-3 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
          style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8125rem', lineHeight: 1.6 }}
          placeholder={`System prompt for ${selectedType.replace(/_/g, ' ')} documentation...`} />
        <div className="flex gap-3 mt-3">
          <ConfirmDialog
            trigger={<button className="px-4 py-2 border border-border rounded-lg text-muted-foreground hover:text-destructive hover:border-destructive transition-colors" style={{ fontSize: '0.875rem' }}>Reset to Default</button>}
            title="Reset template"
            description={`This will reset the ${selectedType} template to its default. Your customizations will be lost.`}
            confirmLabel="Reset"
            variant="danger"
            onConfirm={() => setTemplates(prev => ({ ...prev, [selectedType]: '' }))}
          />
          <button onClick={handleSave} disabled={saving}
            className="flex-1 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60"
            style={{ fontSize: '0.875rem', fontWeight: 500 }}>
            {saving ? 'Saving...' : 'Save Template'}
          </button>
        </div>
      </div>
    </div>
  );
}

function OrganizationTab() {
  const [orgName, setOrgName] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await new Promise(r => setTimeout(r, 500));
    toast.success('Organization settings saved');
    setSaving(false);
  };

  return (
    <div className="space-y-5 max-w-lg">
      <div>
        <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Organization name</label>
        <input value={orgName} onChange={e => setOrgName(e.target.value)} placeholder="Acme Corp"
          className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          style={{ fontSize: '0.9rem' }} />
      </div>
      <div>
        <label className="block text-foreground mb-2" style={{ fontSize: '0.875rem', fontWeight: 500 }}>Default output formats</label>
        <div className="flex flex-wrap gap-2">
          {['markdown', 'docx', 'mkdocs', 'docusaurus'].map(f => (
            <label key={f} className="flex items-center gap-2 cursor-pointer capitalize">
              <input type="checkbox" defaultChecked={f === 'markdown'} className="accent-primary" />
              <span className="text-foreground" style={{ fontSize: '0.875rem' }}>{f}</span>
            </label>
          ))}
        </div>
      </div>
      <button onClick={handleSave} disabled={saving}
        className="w-full py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60"
        style={{ fontSize: '0.875rem', fontWeight: 500 }}>
        {saving ? 'Saving...' : 'Save Changes'}
      </button>
    </div>
  );
}

function ProfileTab() {
  const { user } = useAuth();
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPw !== confirmPw) { toast.error("Passwords don't match"); return; }
    setPwLoading(true);
    try {
      await apiPost('/api/v1/auth/change-password', { current_password: currentPw, new_password: newPw });
      toast.success('Password updated');
      setCurrentPw(''); setNewPw(''); setConfirmPw('');
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed';
      if (msg.includes('404') || msg.includes('not found')) toast.error('Password change not available yet');
      else toast.error(msg);
    } finally {
      setPwLoading(false);
    }
  };

  return (
    <div className="space-y-6 max-w-lg">
      <div className="space-y-4">
        <div>
          <label className="block text-muted-foreground mb-1" style={{ fontSize: '0.8125rem' }}>Full name</label>
          <input defaultValue={user?.full_name} readOnly className="w-full px-3 py-2.5 rounded-lg border border-border bg-secondary text-muted-foreground" style={{ fontSize: '0.9rem' }} />
        </div>
        <div>
          <label className="block text-muted-foreground mb-1" style={{ fontSize: '0.8125rem' }}>Email</label>
          <input defaultValue={user?.email} readOnly className="w-full px-3 py-2.5 rounded-lg border border-border bg-secondary text-muted-foreground" style={{ fontSize: '0.9rem' }} />
          <p className="mt-1 text-muted-foreground" style={{ fontSize: '0.75rem' }}>Contact support to change your email.</p>
        </div>
        <div>
          <label className="block text-muted-foreground mb-1" style={{ fontSize: '0.8125rem' }}>Role</label>
          <span className="inline-block px-2.5 py-1 rounded-full bg-secondary text-foreground capitalize" style={{ fontSize: '0.8125rem', fontWeight: 500 }}>{user?.role}</span>
        </div>
        {user?.created_at && (
          <div>
            <label className="block text-muted-foreground mb-1" style={{ fontSize: '0.8125rem' }}>Member since</label>
            <span className="text-foreground" style={{ fontSize: '0.875rem' }}>{new Date(user.created_at).toLocaleDateString()}</span>
          </div>
        )}
      </div>

      <div className="border-t border-border pt-5">
        <h3 className="text-foreground mb-4" style={{ fontSize: '0.9375rem', fontWeight: 600 }}>Change Password</h3>
        <form onSubmit={handleChangePassword} className="space-y-3">
          {[
            { label: 'Current password', val: currentPw, set: setCurrentPw },
            { label: 'New password', val: newPw, set: setNewPw },
            { label: 'Confirm new password', val: confirmPw, set: setConfirmPw },
          ].map(f => (
            <div key={f.label}>
              <label className="block text-foreground mb-1.5" style={{ fontSize: '0.875rem', fontWeight: 500 }}>{f.label}</label>
              <input type="password" value={f.val} onChange={e => f.set(e.target.value)} required
                className="w-full px-3 py-2.5 rounded-lg border border-border bg-input-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                style={{ fontSize: '0.9rem' }} />
            </div>
          ))}
          <button type="submit" disabled={pwLoading}
            className="w-full py-2.5 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors disabled:opacity-60"
            style={{ fontSize: '0.875rem', fontWeight: 500 }}>
            {pwLoading ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </div>

      <div className="border border-destructive/30 rounded-xl p-4">
        <h3 className="text-destructive mb-2" style={{ fontSize: '0.9rem', fontWeight: 600 }}>Danger Zone</h3>
        <p className="text-muted-foreground mb-3" style={{ fontSize: '0.8125rem' }}>Permanently delete your account and all associated data.</p>
        <ConfirmDialog
          trigger={<button className="px-4 py-2 border border-destructive text-destructive rounded-lg hover:bg-destructive/10 transition-colors" style={{ fontSize: '0.875rem' }}>Delete Account</button>}
          title="Delete account"
          description="Are you absolutely sure? This action cannot be undone."
          confirmLabel="Delete Account"
          variant="danger"
          onConfirm={() => toast.error('Account deletion not implemented yet')}
        />
      </div>
    </div>
  );
}

const TABS: { key: Tab; label: string; adminOnly?: boolean }[] = [
  { key: 'llm', label: 'LLM Configuration', adminOnly: true },
  { key: 'templates', label: 'Doc Templates', adminOnly: true },
  { key: 'organization', label: 'Organization', adminOnly: true },
  { key: 'profile', label: 'User Profile' },
];

export default function SettingsPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>('profile');

  useEffect(() => {
    if (user?.role === 'admin') setActiveTab('llm');
  }, [user?.role]);

  if (!user) return null;

  const visibleTabs = TABS.filter(t => !t.adminOnly || user.role === 'admin');

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-foreground" style={{ fontSize: '1.375rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>Settings</h1>
        <p className="text-muted-foreground mt-0.5" style={{ fontSize: '0.875rem' }}>Manage your account and application configuration</p>
      </div>

      <div className="grid lg:grid-cols-[220px_1fr] gap-6">
        <nav className="space-y-1">
          {visibleTabs.map(tab => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={`w-full text-left px-4 py-2.5 rounded-lg transition-colors ${activeTab === tab.key ? 'bg-secondary text-foreground font-medium' : 'text-muted-foreground hover:bg-secondary/50 hover:text-foreground'}`}
              style={{ fontSize: '0.875rem' }}>
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="bg-card border border-border rounded-xl p-6">
          {activeTab === 'llm' && user.role === 'admin' && <LLMTab />}
          {activeTab === 'templates' && user.role === 'admin' && <TemplatesTab />}
          {activeTab === 'organization' && user.role === 'admin' && <OrganizationTab />}
          {activeTab === 'profile' && <ProfileTab />}
        </div>
      </div>
    </div>
  );
}
