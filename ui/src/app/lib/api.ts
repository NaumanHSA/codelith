const BASE_URL = (import.meta as { env: Record<string, string> }).env.VITE_API_URL || 'http://localhost:8000';

let isRefreshing = false;
let refreshSubscribers: Array<(token: string) => void> = [];

function onRefreshed(token: string) {
  refreshSubscribers.forEach(cb => cb(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('docany_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (response.status === 401 && !path.includes('/auth/refresh') && !path.includes('/auth/login')) {
    if (isRefreshing) {
      return new Promise((resolve) => {
        addRefreshSubscriber(async (newToken) => {
          headers['Authorization'] = `Bearer ${newToken}`;
          resolve(await fetch(`${BASE_URL}${path}`, { ...options, headers }));
        });
      });
    }

    isRefreshing = true;
    const refreshToken = localStorage.getItem('docany_refresh');
    if (!refreshToken) {
      logout();
      throw new Error('Session expired');
    }

    try {
      const refreshRes = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!refreshRes.ok) {
        logout();
        throw new Error('Session expired');
      }

      const data = await refreshRes.json();
      const newToken = data.access_token;
      localStorage.setItem('docany_token', newToken);
      isRefreshing = false;
      onRefreshed(newToken);

      headers['Authorization'] = `Bearer ${newToken}`;
      return fetch(`${BASE_URL}${path}`, { ...options, headers });
    } catch {
      isRefreshing = false;
      logout();
      throw new Error('Session expired');
    }
  }

  return response;
}

function logout() {
  localStorage.removeItem('docany_token');
  localStorage.removeItem('docany_refresh');
  window.location.href = '/auth/login';
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: 'PATCH',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const res = await apiFetch(path, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
}

export function getStreamUrl(jobId: string): string {
  const token = localStorage.getItem('docany_token') || '';
  return `${BASE_URL}/api/v1/jobs/${jobId}/stream?token=${encodeURIComponent(token)}`;
}
