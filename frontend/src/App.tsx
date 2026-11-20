import { useEffect, useRef, type ReactNode } from 'react'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { PhoneFrame, StatusBar, TabBar, ToastProvider } from '@/components/shell'
import { DecisionSheetProvider } from '@/components/DecisionSheet'
import { DemoPanel } from '@/components/DemoPanel'
import Home from '@/pages/Home'
import Inbox from '@/pages/Inbox'
import Activity from '@/pages/Activity'
import Rules from '@/pages/Rules'
import TaskDetail from '@/pages/TaskDetail'
import Snap from '@/pages/Snap'
import Demo from '@/pages/Demo'

function Page({ children, full }: { children: ReactNode; full?: boolean }) {
  return (
    <motion.div
      className={full ? 'h-full' : 'min-h-full'}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, transition: { duration: 0.1 } }}
      transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  )
}

function Screens() {
  const location = useLocation()
  const scroller = useRef<HTMLElement>(null)
  const fullScreen = location.pathname.startsWith('/snap')

  useEffect(() => {
    scroller.current?.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <>
      <StatusBar />
      <main
        ref={scroller}
        className="no-scrollbar absolute inset-x-0 bottom-0 overflow-x-hidden overflow-y-auto overscroll-contain"
        style={{ top: 'var(--top-inset)', paddingBottom: fullScreen ? 0 : 'calc(var(--tabbar-h) + 28px)' }}
      >
        <AnimatePresence mode="wait" initial={false}>
          <Routes location={location} key={location.pathname}>
            <Route path="/" element={<Page><Home /></Page>} />
            <Route path="/inbox" element={<Page><Inbox /></Page>} />
            <Route path="/activity" element={<Page><Activity /></Page>} />
            <Route path="/rules" element={<Page><Rules /></Page>} />
            <Route path="/tasks/:id" element={<Page><TaskDetail /></Page>} />
            <Route path="/snap" element={<Page full><Snap /></Page>} />
            <Route path="/demo" element={<Page><Demo /></Page>} />
            <Route path="*" element={<Page><Home /></Page>} />
          </Routes>
        </AnimatePresence>
      </main>
      {!fullScreen && <TabBar />}
      <DemoPanel />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <PhoneFrame>
        <ToastProvider>
          <DecisionSheetProvider>
            <Screens />
          </DecisionSheetProvider>
        </ToastProvider>
      </PhoneFrame>
    </BrowserRouter>
  )
}
