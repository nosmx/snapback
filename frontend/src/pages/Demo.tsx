import { DemoControls } from '@/components/DemoPanel'
import { NavBar } from '@/components/shell'

export default function Demo() {
  return (
    <div>
      <NavBar title="Demo controls" back />
      <div className="px-4">
        <DemoControls />
        <p className="text-ink-3 mt-4 text-center text-[13px]">Press D or triple-tap “Snapback” on Home to open these anywhere.</p>
      </div>
    </div>
  )
}
