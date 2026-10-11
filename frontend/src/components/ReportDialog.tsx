import { useState } from 'react'
import { useToast } from '../contexts/ToastContext'
import { api } from '../services/api'
import { Field, Modal } from './ui'

const REASONS = [
  ['spam', 'Spam or advertising'],
  ['offensive', 'Offensive or abusive'],
  ['misleading', 'Misleading information'],
  ['fraud', 'Possible scam'],
  ['spoilers', 'Unmarked spoilers'],
  ['off_topic', 'Off topic'],
  ['other', 'Something else'],
] as const

export function ReportDialog({ open, onClose, endpoint, what }: { open: boolean; onClose: () => void; endpoint: string; what: string }) {
  const toast = useToast()
  const [reason, setReason] = useState<string>('spam')
  const [details, setDetails] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit() {
    setBusy(true)
    try {
      await api.post(endpoint, { reason, details: details.trim() || null })
      toast.success('Report sent. A moderator will review it.')
      onClose()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title={`Report ${what}`}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-danger" onClick={submit} disabled={busy}>Send report</button></>}>
      <div className="space-y-4">
        <fieldset>
          <legend className="label">Reason</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {REASONS.map(([value, label]) => (
              <label key={value} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm has-[:checked]:border-ink-soft has-[:checked]:bg-parchment">
                <input type="radio" name="reason" value={value} checked={reason === value} onChange={() => setReason(value)} />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Details (optional)" htmlFor="report-details">
          <textarea id="report-details" className="input" rows={3} maxLength={500} value={details} onChange={(e) => setDetails(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}
