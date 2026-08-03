import React, { createContext, useContext, useEffect } from 'react';

/**
 * The studio is dark-only by design — there is no light mode and no toggle.
 * The `dark` class is also set on <html> in index.html so the first paint is
 * already dark; this provider just guarantees it stays that way.
 */
type Theme = 'dark';

interface ThemeContextType {
  theme: Theme;
}

const ThemeContext = createContext<ThemeContextType>({ theme: 'dark' });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.add('dark');
    // Clear the preference written by earlier builds that supported light mode.
    localStorage.removeItem('docany_theme');
  }, []);

  return (
    <ThemeContext.Provider value={{ theme: 'dark' }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
