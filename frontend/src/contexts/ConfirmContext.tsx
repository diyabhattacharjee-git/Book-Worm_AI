import { createContext, useCallback, useContext, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Modal } from '../components/ui'

interface ConfirmOptions {
  title: string
  message?: ReactNode
  confirmLabel?: string
  danger?: boolean
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>

interface PromptOptions {
  title: string
  label: string
  type?: 'text' | 'number'
  required?: boolean
  maxLength?: number
  confirmLabel?: string
}
type Prompt = (options: PromptOptions) => Promise<string | null>

const ConfirmContext = createContext<Confirm | null>(null)
const PromptContext = createContext<Prompt | null>(null)

function PromptDialog({ options, onDone }: { options: PromptOptions; onDone: (value: string | null) => void }) {
  const [value, setValue] = useState('')
  const invalid = !!options.required && !value.trim()
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!invalid) onDone(value.trim())
  }
  return (
    <Modal open onClose={() => onDone(null)} title={options.title}
      footer={<><button className="btn-ghost" onClick={() => onDone(null)}>Cancel</button><button className="btn-primary" form="prompt-form" disabled={invalid}>{options.confirmLabel ?? 'Save'}</button></>}>
      <form id="prompt-form" onSubmit={submit}>
        <label className="label" htmlFor="prompt-value">{options.label}</label>
        <input id="prompt-value" className="input" type={options.type ?? 'text'} maxLength={options.maxLength} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
      </form>
    </Modal>
  )
}

/** Styled replacement for window.confirm: `if (await confirm({ title })) { ... }`. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null)
  const resolver = useRef<((value: boolean) => void) | null>(null)
  const [promptOptions, setPromptOptions] = useState<PromptOptions | null>(null)
  const promptResolver = useRef<((value: string | null) => void) | null>(null)

  const prompt = useCallback<Prompt>((next) => {
    promptResolver.current?.(null)
    setPromptOptions(next)
    return new Promise<string | null>((resolve) => { promptResolver.current = resolve })
  }, [])

  function settlePrompt(value: string | null) {
    promptResolver.current?.(value)
    promptResolver.current = null
    setPromptOptions(null)
  }

  const confirm = useCallback<Confirm>((next) => {
    resolver.current?.(false)
    setOptions(next)
    return new Promise<boolean>((resolve) => { resolver.current = resolve })
  }, [])

  function settle(value: boolean) {
    resolver.current?.(value)
    resolver.current = null
    setOptions(null)
  }

  const value = useMemo(() => confirm, [confirm])
  return (
    <ConfirmContext.Provider value={value}>
      <PromptContext.Provider value={prompt}>{children}</PromptContext.Provider>
      {promptOptions && <PromptDialog options={promptOptions} onDone={settlePrompt} />}
      {options && (
        <Modal open onClose={() => settle(false)} title={options.title}
          footer={<>
            <button className="btn-ghost" onClick={() => settle(false)}>Cancel</button>
            <button className={options.danger ? 'btn-danger' : 'btn-primary'} onClick={() => settle(true)} autoFocus>{options.confirmLabel ?? 'Confirm'}</button>
          </>}>
          {options.message && <div className="text-sm text-ink-soft">{options.message}</div>}
        </Modal>
      )}
    </ConfirmContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePrompt(): Prompt {
  const ctx = useContext(PromptContext)
  if (!ctx) throw new Error('usePrompt must be used inside ConfirmProvider')
  return ctx
}

// eslint-disable-next-line react-refresh/only-export-components
export function useConfirm(): Confirm {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirm must be used inside ConfirmProvider')
  return ctx
}
