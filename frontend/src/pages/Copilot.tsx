import { useState, type FormEvent } from 'react'
import { copilotApi, type AskQuestionResponse } from '../api/copilotApi'
import { Button } from '../components/ui/Button'

export function Copilot() {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState<AskQuestionResponse[]>([])
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!question.trim()) return
    setAsking(true)
    setError(null)
    try {
      const response = await copilotApi.ask(question)
      setHistory((prev) => [...prev, response])
      setQuestion('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The Copilot could not answer that.')
    } finally {
      setAsking(false)
    }
  }

  return (
    <div className="flex h-screen flex-col p-8">
      <h1 className="mb-1 font-display text-2xl text-ink">Copilot</h1>
      <p className="mb-6 text-sm text-ink-mid">Ask about your recovery performance in plain language.</p>

      <div className="flex-1 space-y-4 overflow-y-auto">
        {history.length === 0 && (
          <p className="text-sm text-ink-soft">
            Try: "Why did recovery rate drop last week?" or "Which failure reason costs us the most?"
          </p>
        )}
        {history.map((entry) => (
          <div key={entry.insight_id} className="space-y-1">
            <p className="text-sm font-medium text-ink">{entry.question}</p>
            <p className="text-sm text-ink-mid">{entry.answer}</p>
          </div>
        ))}
      </div>

      {error && <p className="mt-2 text-sm text-lost">{error}</p>}

      <form onSubmit={handleSubmit} className="mt-6 flex gap-2 border-t border-hairline pt-4">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about your recovery data…"
          className="flex-1 border border-hairline bg-surface px-3 py-2 text-sm outline-none focus:border-ink"
        />
        <Button type="submit" disabled={asking}>
          {asking ? 'Thinking…' : 'Ask'}
        </Button>
      </form>
    </div>
  )
}
