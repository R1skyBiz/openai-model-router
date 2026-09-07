import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Filters } from './api-types'

export type ThemeChoice = 'system' | 'light' | 'dark'

interface DashboardState {
  filters: Filters
  setFilter: (key: keyof Filters, value: string) => void
  clearFilters: () => void
  theme: ThemeChoice
  setTheme: (theme: ThemeChoice) => void
}

const StateContext = createContext<DashboardState | null>(null)

function applyTheme(choice: ThemeChoice) {
  const resolved = choice === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : choice
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved
}

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>({})
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    const saved = localStorage.getItem('model-router-theme')
    return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system'
  })

  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem('model-router-theme', theme)
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = () => theme === 'system' && applyTheme(theme)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [theme])

  const value = useMemo<DashboardState>(() => ({
    filters,
    setFilter: (key, value) => setFilters((current) => {
      const next = { ...current }
      if (value) next[key] = value
      else delete next[key]
      return next
    }),
    clearFilters: () => setFilters({}),
    theme,
    setTheme: setThemeState,
  }), [filters, theme])

  return <StateContext.Provider value={value}>{children}</StateContext.Provider>
}

export function useDashboard() {
  const value = useContext(StateContext)
  if (!value) throw new Error('useDashboard must be used inside DashboardProvider')
  return value
}

export function filterKey(filters: Filters): string {
  return JSON.stringify(filters)
}
