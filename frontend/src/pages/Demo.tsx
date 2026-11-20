import { DemoControls } from '@/components/DemoPanel'
import { PageHeader } from '@/components/shell'
import { USE_MOCK } from '@/lib/api'

export default function Demo() {
  return (
    <div>
      <PageHeader title="Demo controls" subtitle={USE_MOCK ? 'Mock data · in-browser' : 'Live backend'} />
      <div className="px-4 pt-2">
        <DemoControls />
        <p className="text-faint mt-4 text-center text-[13px]">Tip: press D or triple-tap the logo on any screen.</p>
      </div>
    </div>
  )
}
