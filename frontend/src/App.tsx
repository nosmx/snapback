import { useRef, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { PhoneFrame, Scroller, StatusBar, TABS, TabBar, ToastProvider, type TabKey } from '@/components/shell'
import { DecisionSheetProvider } from '@/components/DecisionSheet'
import { DemoPanel } from '@/components/DemoPanel'
import { ActivityPanel } from '@/components/ActivityPanel'
import { useMediaQuery } from '@/lib/hooks'
import Home from '@/pages/Home'
import Snap from '@/pages/Snap'
import Activity from '@/pages/Activity'
import Rules from '@/pages/Rules'
import TaskDetail from '@/pages/TaskDetail'
import Inbox from '@/pages/Inbox'
import Demo from '@/pages/Demo'
import { cn } from '@/lib/utils'

const tabOf = (p: string): TabKey => (p.startsWith('/activity') ? 'activity' : p.startsWith('/rules') ? 'rules' : p.startsWith('/snap') ? 'snap' : 'home')
const isPush = (p: string) => p.startsWith('/tasks/') || p === '/inbox' || p === '/demo'

const TAB_SCREENS: Record<TabKey, ReactNode> = { home: <Home />, snap: <Snap />, activity: <Activity />, rules: <Rules /> }

function Screens() {
  const loc = useLocation()
  const push = isPush(loc.pathname)
  // The tab under a pushed screen stays where it was (e.g. Activity → task → back to Activity).
  const under = useRef<TabKey>(tabOf(loc.pathname))
  if (!push) under.current = tabOf(loc.pathname)
  const active = under.current

  return (
    <>
      <StatusBar />
      {/* Every tab stays mounted in its own scroll container, so each keeps its scroll position.
          z-0 gives each tab its own stacking context, so its sticky nav bar can't sit above (and steal taps from) a pushed screen. */}
      {TABS.map((t) => (
        <div key={t.key} aria-hidden={active !== t.key} className={cn('absolute inset-0 z-0', active !== t.key && 'pointer-events-none invisible')}>
          <Scroller>{TAB_SCREENS[t.key]}</Scroller>
        </div>
      ))}
      <AnimatePresence initial={false}>
        {push && (
          <motion.div
            key={loc.pathname}
            className="bg-bg absolute inset-0 z-20"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.32, ease: [0.32, 0.72, 0, 1] }}
          >
            <Scroller>
              <Routes location={loc}>
                <Route path="/tasks/:id" element={<TaskDetail />} />
                <Route path="/inbox" element={<Inbox />} />
                <Route path="/demo" element={<Demo />} />
              </Routes>
            </Scroller>
          </motion.div>
        )}
      </AnimatePresence>
      <TabBar active={active} />
      <DemoPanel />
    </>
  )
}

function Root() {
  // The "Agent activity" panel only exists on wide screens (it's never mounted on phones).
  const wide = useMediaQuery('(min-width: 1100px)')
  return (
    <PhoneFrame aside={wide ? <ActivityPanel /> : null}>
      <ToastProvider>
        <DecisionSheetProvider>
          <Screens />
        </DecisionSheetProvider>
      </ToastProvider>
    </PhoneFrame>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Root />
    </BrowserRouter>
  )
}
