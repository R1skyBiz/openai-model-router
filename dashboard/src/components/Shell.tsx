import { Activity, ChartNoAxesCombined, CircleDollarSign, GitBranch, HeartPulse, ListTree, Menu, Moon, Sun, SunMoon, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useDashboard, type ThemeChoice } from '../state'
import { FilterBar } from './FilterBar'

const navigation = [
  { to: '/', label: 'Overview', icon: Activity },
  { to: '/spend', label: 'Spend', icon: CircleDollarSign },
  { to: '/routing', label: 'Routing', icon: GitBranch },
  { to: '/efficacy', label: 'Efficacy', icon: ChartNoAxesCombined },
  { to: '/health', label: 'Health', icon: HeartPulse },
  { to: '/tasks', label: 'Tasks', icon: ListTree },
]

export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setOpen(false), [location.pathname])

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <button className="mobile-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? <X /> : <Menu />}</button>
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`} aria-label="Model Router sidebar">
      <div className="brand"><div className="brand-mark" aria-hidden="true"><span /><span /><span /></div><div><strong>Model Router</strong><small><i /> Local dataset</small></div></div>
      <nav aria-label="Primary">{navigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'}><Icon size={18} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</nav>
      <ThemeControl />
    </aside>
    {open && <button className="scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <main id="main-content" tabIndex={-1}>
      <FilterBar />
      <div className="content">{children}</div>
    </main>
  </div>
}

function ThemeControl() {
  const { theme, setTheme } = useDashboard()
  const values: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
    { value: 'system', label: 'System', icon: SunMoon }, { value: 'light', label: 'Light', icon: Sun }, { value: 'dark', label: 'Dark', icon: Moon },
  ]
  return <div className="theme-control" aria-label="Appearance">{values.map(({ value, label, icon: Icon }) => <button key={value} aria-label={`${label} theme`} aria-pressed={theme === value} onClick={() => setTheme(value)} title={label}><Icon size={15} /></button>)}</div>
}
