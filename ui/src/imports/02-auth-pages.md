# Auth Pages Prompt

**Reference**: `00-design-system-and-context.md`

Two pages: Sign In (`/auth/login`) and Register (`/auth/register`).

---

## Layout Shell (shared)

Both pages use the same centered card layout:
- Full-page background: `brand-900` (dark navy) with a subtle radial gradient glow in `brand-500` opacity-10
- Centered card: `bg-white rounded-2xl shadow-xl p-10`, max-width `440px`, centered vertically and horizontally
- Top of card: logo icon + "document-anything" wordmark
- Below logo: page-specific content

---

## Sign In Page `/auth/login`

**Card content (top to bottom):**

1. **Heading**: "Welcome back" (24px bold)
2. **Subtext**: "Sign in to your account" (muted gray)
3. **Form fields**:
   - Email input (type=email, placeholder="you@example.com", label="Email")
   - Password input (type=password, placeholder="••••••••", label="Password") + show/hide toggle eye icon
4. **"Forgot password?"** link aligned right below password field (placeholder, no page needed)
5. **Sign In button**: full-width, primary style, "Sign In"
6. **Divider**: `── or ──`
7. **Register link**: "Don't have an account? **Get started free →**" → `/auth/register`

**API call on submit:**
```
POST /api/v1/auth/login
Body: { "email": "...", "password": "..." }
Response: { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

- Store `access_token` in `localStorage` as `docany_token`
- Store `refresh_token` in `localStorage` as `docany_refresh`
- On success → redirect to `/app` (dashboard)
- On error (401) → show inline error: "Invalid email or password"
- Show loading spinner on the button while request is in flight

---

## Register Page `/auth/register`

**Card content:**

1. **Heading**: "Create your account" (24px bold)
2. **Subtext**: "Free forever. No credit card required."
3. **Form fields**:
   - Full name (text, placeholder="Jane Smith", label="Full name")
   - Email (type=email)
   - Password (type=password, min 8 chars) + strength indicator bar below the field
   - Confirm password (type=password)
4. **Terms checkbox**: "I agree to the Terms of Service and Privacy Policy" (both placeholder links)
5. **Create Account button**: full-width primary
6. **Sign in link**: "Already have an account? **Sign in →**" → `/auth/login`

**API call on submit:**
```
POST /api/v1/auth/register
Body: { "email": "...", "password": "...", "full_name": "..." }
Response: { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

- Validate: passwords match, email format valid, terms checked
- On success → store tokens → redirect to `/app`
- On error (409 email exists) → "An account with this email already exists"

---

## Auth State Management

Create an `AuthContext` (or Zustand store) that:
- Reads `docany_token` from localStorage on app init
- Exposes `user`, `isAuthenticated`, `login()`, `logout()`, `refreshToken()`
- On every page load inside `/app/**`, verify token is present; if not → redirect to `/auth/login`

**Get current user after login:**
```
GET /api/v1/auth/me
Headers: Authorization: Bearer <token>
Response: { "id": 1, "email": "...", "full_name": "...", "role": "admin" }
```

Store user object globally. Use `role` to show/hide admin-only UI sections.

**Token refresh:**
```
POST /api/v1/auth/refresh
Body: { "refresh_token": "..." }
Response: { "access_token": "..." }
```

Intercept all API calls — if any returns 401, attempt one refresh, retry original request, then logout if refresh also fails.

---

## Password Strength Indicator

Below the password field on register:
- 4-segment bar, fills left to right
- Segment 1 (red): any input
- Segment 2 (orange): 8+ chars
- Segment 3 (yellow): has number or symbol
- Segment 4 (green): has uppercase + lowercase + number + symbol
- Text label: "Weak" / "Fair" / "Good" / "Strong"
