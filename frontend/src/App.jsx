import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

// Replace with your real Google Form URL when ready.
const FEEDBACK_FORM_URL = 'https://docs.google.com/forms/d/e/1FAIpQLSeV9gY2k3tNVYtPfNwnnKFm97lkWSVtfrh_iTqfFMHJx6_gGA/viewform?usp=dialog'

// Reads the backend URL from a Vite env var so the same build can point at
// localhost or the deployed Railway backend. Falls back to localhost so local
// dev works with zero setup.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Gives each browser a stable anonymous id (a UUID cached in localStorage),
// sent as the X-Device-Id header so the backend can keep chat history private
// per visitor. Used instead of real accounts because Phase 1 has no login yet.
function getDeviceId() {
  let id = localStorage.getItem('myuoft_device_id')
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem('myuoft_device_id', id)
  }
  return id
}
const DEVICE_ID = getDeviceId()

// Fixes a bug where Claude sometimes puts a bullet marker alone on its own line
// with a blank line before its content, which CommonMark renders as an orphaned
// empty bullet. Collapses the marker back onto its content and turns literal "•"
// characters into real "-" markers so remark treats them as list items.
function normalizeMarkdownLists(text) {
  return text.replace(
    /^([ \t]*)(?:[-*+]|•)[ \t]*\r?\n(?:[ \t]*\r?\n)*(?=[ \t]*\S)/gm,
    '$1- '
  )
}

// ── Shared markdown render config ───────────────────────────────────────────
// One component map shared by both the typewriter reveal and the settled render.
// Defined once at module scope so finished messages don't visibly restyle the
// instant the animation completes.
const MARKDOWN_COMPONENTS = {
  p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
  h1: ({ children }) => <h1 className="font-bold text-base mt-2 mb-1">{children}</h1>,
  h2: ({ children }) => <h2 className="font-semibold text-sm mt-2 mb-1">{children}</h2>,
  h3: ({ children }) => <h3 className="font-medium text-sm mt-1 mb-0.5">{children}</h3>,
  code: ({ children }) => <code className="bg-white/10 rounded px-1 py-0.5 text-xs font-mono">{children}</code>,
  // Skips list items with no printable content, which remark-gfm can emit for
  // trailing "- " or whitespace-only lines and would otherwise show as blank
  // dots. Coerces children to a string first to handle nested React elements.
  li: ({ children }) => {
    const text = typeof children === 'string' ? children : Array.isArray(children) ? children.join('') : String(children ?? '')
    if (!text.trim()) return null
    return <li>{children}</li>
  },
}

// ── TypewriterMarkdown ──────────────────────────────────────────────────────
// Renders an assistant reply either instantly (animate false, for history) or
// with a ChatGPT-style word-by-word reveal (animate true, for fresh replies).
// The reveal shows plain text mid-stream and switches to real markdown only
// once complete, since partial markdown (an open ** or half a list) would flicker.
function TypewriterMarkdown({ content, animate, onReveal }) {
  // visibleCount = how many words of `content` are currently shown.
  // Start fully revealed when not animating so static messages paint at once.
  const words = content.split(/(\s+)/) // keep whitespace tokens so spacing survives
  const [visibleCount, setVisibleCount] = useState(animate ? 0 : words.length)
  const [done, setDone] = useState(!animate)

  useEffect(() => {
    if (!animate) return // history / already-settled: nothing to schedule

    let count = 0
    // Reveals 8 words every 25ms. The reveal runs after the full response has
    // already arrived, so its time adds directly to perceived latency — the
    // slower original 3/40 pace tacked ~20s of animation onto long replies.
    const CHUNK = 8
    const TICK_MS = 25
    const timer = setInterval(() => {
      count += CHUNK
      if (count >= words.length) {
        setVisibleCount(words.length)
        setDone(true)
        clearInterval(timer)
      } else {
        setVisibleCount(count)
      }
      // Notify the parent each tick so it can keep the view scrolled to the
      // bottom as the text grows — `messages` doesn't change during typing, so
      // its normal scroll effect wouldn't fire on its own.
      onReveal?.()
    }, TICK_MS)

    // Clear the interval on unmount (e.g. user switches sessions mid-type) so
    // we don't setState on an unmounted component or leak a timer.
    return () => clearInterval(timer)
    // Deps are stable per bubble, so this effect runs once per fresh reply.
  }, [content, animate, words.length])

  // Once fully revealed, render the real markdown so final styling is exact.
  // We normalize here because both render paths (history restores and the
  // post-animation settle) funnel through this spot, covering both at once.
  if (done) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {normalizeMarkdownLists(content)}
      </ReactMarkdown>
    )
  }

  // Mid-reveal: show the plain-text prefix plus a blinking caret.
  return (
    <span className="whitespace-pre-wrap">
      {words.slice(0, visibleCount).join('')}
      <span className="typewriter-cursor">▍</span>
    </span>
  )
}

// Workload maps weekly effort preference to the 1–5 integer scale the backend uses.
// 1 = very light, 5 = very heavy — stored as numbers so they feed directly into scoring.
const WORKLOAD_OPTIONS = [
  { value: '', label: 'Select a workload...' },
  { value: 2, label: 'Light' },
  { value: 3, label: 'Standard' },
  { value: 5, label: 'Heavy' },
]

// Difficulty maps how challenging the student wants courses to the 1–10 scale the backend uses.
const DIFFICULTY_OPTIONS = [
  { value: '', label: 'Select a difficulty...' },
  { value: 2, label: 'Easy' },
  { value: 5, label: 'Medium' },
  { value: 8, label: 'Hard' },
]

function App() {
  // Which view is active. Defaults to 'home' so first-time visitors land on the
  // marketing/explainer page rather than being dropped straight into a form.
  // Values: 'home' | 'planner' | 'chat' | 'reviews'.
  const [activeTab, setActiveTab] = useState('home')

  // ── Planner tab state ──
  const [interests, setInterests] = useState('')
  const [workload, setWorkload] = useState('')
  const [difficulty, setDifficulty] = useState('')
  const [submitted, setSubmitted] = useState(null)
  const [courses, setCourses] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // ── Chat tab state ──
  // messages is the full conversation history shown in the UI and sent to /chat
  // so the backend can give context-aware responses across multiple turns.
  const [messages, setMessages] = useState([])
  const [inputValue, setInputValue] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatError, setChatError] = useState(null)

  // chatSessions is the list shown in the sidebar — loaded from SQLite via /chats.
  // currentSessionId tracks which session is open so we can tag outgoing messages
  // with the right session_id for server-side persistence.
  const [chatSessions, setChatSessions] = useState([])
  const [currentSessionId, setCurrentSessionId] = useState(null)

  // Tracks whether the mobile sidebar drawer is open. Below the md breakpoint
  // the sidebar and chat can't fit side by side, so it becomes an off-canvas
  // drawer; above md this flag is ignored (sidebar always shown via md:flex).
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // editingIndex is the array index of the message being edited (null if none).
  // editingText holds the live textarea value, kept separate from the message
  // so Cancel can discard changes without having mutated `messages`.
  const [editingIndex, setEditingIndex] = useState(null)
  const [editingText, setEditingText] = useState('')

  // ── Reviews tab state ──
  const [reviewCourseCode, setReviewCourseCode] = useState('')
  const [reviewRating, setReviewRating] = useState(5)
  const [reviewText, setReviewText] = useState('')
  const [reviewSubmitting, setReviewSubmitting] = useState(false)
  const [reviewSubmitMsg, setReviewSubmitMsg] = useState(null)
  const [reviewLookupCode, setReviewLookupCode] = useState('')
  const [reviewResults, setReviewResults] = useState(null)
  const [reviewLookupLoading, setReviewLookupLoading] = useState(false)

  // Ref to the bottom of the message list — we scroll to it after each new message
  // so the user always sees the latest response without manually scrolling.
  const messagesEndRef = useRef(null)
  // scrollTick is bumped by the typewriter each reveal tick, giving the scroll
  // effect a dep that changes during typing (when `messages` itself doesn't) so
  // the view keeps following the growing text.
  const [scrollTick, setScrollTick] = useState(0)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatLoading, scrollTick])

  // Load the session list lazily when the chat tab opens, rather than at mount,
  // to avoid a network request for data the user may never look at. The filter
  // to message_count > 0 hides empty sessions, since rows are created lazily on
  // the first message.
  useEffect(() => {
    if (activeTab === 'chat') refreshSessions()
  }, [activeTab])

  // Re-fetch the session list so the sidebar picks up new sessions and title
  // changes (the first message auto-renames one). Extracted so both send and
  // edit flows share the same filter condition.
  function refreshSessions() {
    fetch(`${API_URL}/chats`, { headers: { 'X-Device-Id': DEVICE_ID } })
      .then(r => r.json())
      .then(sessions => setChatSessions(sessions.filter(s => s.message_count > 0)))
      .catch(() => {})
  }

  // Reset to a blank chat state without touching the DB.
  // The session row is created lazily when the first message is sent.
  function startNewChat() {
    setCurrentSessionId(null)
    setMessages([])
    setEditingIndex(null)
  }

  // Fetch a past session's messages and restore them into the UI. Replaces the
  // message list outright rather than merging, so turns from one session never
  // bleed into another's view.
  async function loadChat(session) {
    try {
      const res = await fetch(`${API_URL}/chats/${session.id}/messages`, {
        headers: { 'X-Device-Id': DEVICE_ID },
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const msgs = await res.json()
      setCurrentSessionId(session.id)
      setMessages(msgs)
      setEditingIndex(null)
    } catch (err) {
      setChatError(`Could not load chat: ${err.message}`)
    }
  }

  // Shared POST to /chat for both new and edited/resent messages. Extracted so
  // both flows use one identical body shape and error handling, keeping the
  // request/response contract in a single place.
  async function postChatMessage(text, history, sessionId, editMessageId = null) {
    const response = await fetch(`${API_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Device-Id': DEVICE_ID },
      body: JSON.stringify({
        message: text,
        history,
        session_id: sessionId,
        edit_message_id: editMessageId,
      }),
    })
    if (!response.ok) throw new Error(`Server error: ${response.status}`)
    return response.json()
  }

  async function handleChatSend(e) {
    e.preventDefault()
    const text = inputValue.trim()
    if (!text || chatLoading) return

    // Create the DB session on the first message. Capture the id in a local
    // rather than reading currentSessionId after setState, since setState is
    // async and wouldn't be updated by the time we build the fetch body below.
    let sessionId = currentSessionId
    if (sessionId === null) {
      try {
        const res = await fetch(`${API_URL}/chats`, {
          method: 'POST',
          headers: { 'X-Device-Id': DEVICE_ID },
        })
        if (!res.ok) throw new Error()
        const session = await res.json()
        sessionId = session.id
        setCurrentSessionId(session.id)
      } catch {
        setChatError('Could not create chat session. Try again.')
        return
      }
    }

    // Optimistically add the user message to the UI before the response arrives
    const priorHistory = messages // turns before this new one, sent as `history`
    setMessages([...priorHistory, { role: 'user', content: text }])
    setInputValue('')
    setChatError(null)
    setChatLoading(true)

    try {
      const data = await postChatMessage(text, priorHistory, sessionId)
      // Tag the reply with animate:true so it types out, and tag both turns with
      // their DB ids so the user message can be edited later (editing needs a
      // real row id). History replies lack animate, so they never re-type.
      setMessages([
        ...priorHistory,
        { role: 'user', content: text, id: data.user_message_id },
        { role: 'assistant', content: data.response, animate: true, id: data.assistant_message_id },
      ])
      refreshSessions()
    } catch (err) {
      setChatError(err.message)
    } finally {
      setChatLoading(false)
    }
  }

  function cancelEdit() {
    setEditingIndex(null)
    setEditingText('')
  }

  // Edit a past user message and resend it, discarding every message after it
  // (locally and in the DB via edit_message_id) since the old reply no longer
  // applies. Mirrors ChatGPT's edit-and-resend rather than branching threads.
  async function handleEditMessage(idx) {
    const trimmed = editingText.trim()
    const original = messages[idx]
    if (!trimmed || chatLoading || !original || original.role !== 'user') return

    const priorHistory = messages.slice(0, idx) // turns strictly before the edited one
    const fullConversationBeforeEdit = messages // kept to restore on failure
    setMessages([...priorHistory, { role: 'user', content: trimmed, id: original.id }])
    setEditingIndex(null)
    setEditingText('')
    setChatError(null)
    setChatLoading(true)

    try {
      const data = await postChatMessage(trimmed, priorHistory, currentSessionId, original.id)
      setMessages([
        ...priorHistory,
        { role: 'user', content: trimmed, id: data.user_message_id },
        { role: 'assistant', content: data.response, animate: true, id: data.assistant_message_id },
      ])
      refreshSessions()
    } catch (err) {
      setChatError(err.message)
      // Restore the pre-edit conversation so a failed resend doesn't silently
      // delete the user's original message and its reply from the view.
      setMessages(fullConversationBeforeEdit)
    } finally {
      setChatLoading(false)
    }
  }

  async function handleSubmit(e) {
    // Prevent the default browser form navigation
    e.preventDefault()

    // Split interests into a clean array, trimming whitespace and dropping
    // empties so "  math,  cs,  " becomes ["math", "cs"].
    const parsedInterests = interests
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    setSubmitted({ interests: parsedInterests, workload, difficulty })
    setCourses(null)
    setError(null)
    setLoading(true)

    try {
      // POST to the FastAPI backend running on port 8000.
      // The body shape must match the RequestData Pydantic model in main.py:
      //   interests (list[str]), preferred_difficulty (int), preferred_workload (int)
      const response = await fetch(`${API_URL}/recommend`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          interests: parsedInterests,
          preferred_difficulty: Number(difficulty),
          preferred_workload: Number(workload),
          completed_courses: [],
        }),
      })

      if (!response.ok) {
        // Surface the HTTP error text so it's visible during development
        throw new Error(`Server error: ${response.status}`)
      }

      const data = await response.json()
      // Backend returns the array directly: [{ name, score, explanation }, ...]
      setCourses(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmitReview(e) {
    e.preventDefault()
    if (!reviewCourseCode.trim()) return
    setReviewSubmitting(true)
    setReviewSubmitMsg(null)
    try {
      const res = await fetch(`${API_URL}/reviews`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          course_code: reviewCourseCode.trim().toUpperCase(),
          rating: reviewRating,
          review_text: reviewText,
        }),
      })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setReviewSubmitMsg('Review submitted!')
      setReviewCourseCode('')
      setReviewRating(5)
      setReviewText('')
    } catch (err) {
      setReviewSubmitMsg(`Error: ${err.message}`)
    } finally {
      setReviewSubmitting(false)
    }
  }

  async function handleLookupReviews(e) {
    e.preventDefault()
    if (!reviewLookupCode.trim()) return
    setReviewLookupLoading(true)
    setReviewResults(null)
    try {
      const res = await fetch(`${API_URL}/reviews/${reviewLookupCode.trim().toUpperCase()}`)
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setReviewResults(await res.json())
    } catch (err) {
      setReviewResults([])
    } finally {
      setReviewLookupLoading(false)
    }
  }

  return (
    // Full-height background in UofT's brand blue (#002A5C). Uses min-h-dvh, not
    // min-h-screen (100vh), so it tracks the visible viewport as mobile toolbars
    // resize — 100vh is fixed to the largest viewport and left a white gap on phones.
    <div className="min-h-dvh bg-uoft-blue flex flex-col">

      {/* ── Navbar ──
          Slightly translucent + blurred so content scrolling beneath it gives a
          subtle sense of depth, and a hairline border to separate it cleanly. */}
      <header className="sticky top-0 z-20 bg-uoft-blue/95 backdrop-blur border-b border-white/10 px-6 sm:px-8 py-3.5 flex items-center gap-3">
        {/* Logo is a real button: clicking "MyUofT" returns to the landing page,
            the conventional behaviour users expect from a product wordmark. */}
        <button
          onClick={() => setActiveTab('home')}
          className="group flex items-center gap-2.5 focus:outline-none"
          aria-label="Go to home"
        >
          {/* The accent bar carries UofT gold on hover to tie the wordmark to the
              brand accent without shouting. */}
          <span className="w-1 h-7 rounded-full bg-white group-hover:bg-uoft-accent transition-colors" />
          <span className="text-white text-xl font-semibold tracking-wide">
            My<span className="text-uoft-accent">UofT</span>
          </span>
        </button>

        {/* Tab switcher in the navbar — right-aligned. 'home' is intentionally
            omitted here; the logo is the canonical way back home, keeping the
            switcher focused on the three working tools. */}
        <nav className="ml-auto flex gap-1 bg-white/10 rounded-xl p-1 ring-1 ring-white/10">
          {['chat', 'planner', 'reviews'].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`
                px-3.5 sm:px-4 py-1.5 rounded-lg text-sm font-medium transition-all
                ${activeTab === tab
                  ? 'bg-white text-uoft-blue shadow-sm'
                  : 'text-white/65 hover:text-white hover:bg-white/5'}
              `}
            >
              {tab === 'chat' ? 'AI Advisor' : tab === 'reviews' ? 'Reviews' : 'Planner'}
            </button>
          ))}
        </nav>
      </header>

      {/* ── Main content ── */}
      {/* Uses flex-col overflow-hidden so each tab handles its own centering and
          scrolling, letting the chat panel fill the remaining height. No max-w
          here because the chat tab needs full width; other tabs constrain themselves. */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="w-full flex-1 flex flex-col min-h-0">

        {/* ══════════════════════════════════════════
            HOME / LANDING VIEW
            The default view. A marketing hero + a three-card "how it works"
            strip that maps directly onto the three working tabs. Shown when
            activeTab === 'home'.
        ══════════════════════════════════════════ */}
        {activeTab === 'home' && (
          // relative + overflow-hidden so the ambient gradient glows are clipped
          // to this section and can't trigger page-level horizontal scroll.
          <div className="relative flex-1 overflow-y-auto overflow-x-hidden">

            {/* Ambient background: two soft radial glows over the flat blue give
                the hero depth/atmosphere instead of a dead solid fill. They sit
                behind content (-z) and drift slowly for a living feel. */}
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -top-32 -left-24 w-136 h-136 rounded-full blur-3xl opacity-40 animate-glow-drift"
              style={{ background: 'radial-gradient(circle, #1d4f8c 0%, transparent 70%)' }}
            />
            <div
              aria-hidden="true"
              className="pointer-events-none absolute top-40 -right-32 w-120 h-120 rounded-full blur-3xl opacity-30 animate-glow-drift"
              style={{ background: 'radial-gradient(circle, #4BA3F5 0%, transparent 70%)', animationDelay: '4s' }}
            />

            <div className="relative max-w-5xl mx-auto px-6 py-16 sm:py-24">

              {/* ── Hero ── */}
              <div className="text-center max-w-3xl mx-auto">
                {/* Eyebrow pill. animate-fade-rise with no delay leads the
                    staggered entrance; each following element delays a little
                    more so the hero assembles top-to-bottom. */}
                <span className="animate-fade-rise inline-flex items-center gap-2 rounded-full bg-white/10 ring-1 ring-white/15 px-4 py-1.5 text-xs font-medium tracking-wide text-white/80">
                  <span className="w-1.5 h-1.5 rounded-full bg-uoft-accent" />
                  AI course planning for University of Toronto
                </span>

                <h2
                  className="animate-fade-rise mt-7 text-4xl sm:text-6xl font-bold tracking-tight text-white leading-[1.05]"
                  style={{ animationDelay: '0.08s' }}
                >
                  Turn a 20-minute conversation
                  <br className="hidden sm:block" />{' '}
                  into a <span className="text-uoft-accent">4-year plan</span>
                </h2>

                <p
                  className="animate-fade-rise mt-6 text-base sm:text-lg leading-relaxed text-white/70"
                  style={{ animationDelay: '0.16s' }}
                >
                  UofT students face thousands of courses, minors, majors and specialist
                  programs across the Faculty of Arts and Science. Parsing
                  the Academic Calendar to figure out what to take can take weeks. MyUofT
                  understands your interests, goals and degree requirements, then builds a
                  personalized long-term plan in minutes.
                </p>

                {/* CTAs: primary (white, high-contrast) routes to the Planner;
                    secondary (outlined) routes to the AI Advisor chat. */}
                <div
                  className="animate-fade-rise mt-9 flex flex-col sm:flex-row gap-3 justify-center"
                  style={{ animationDelay: '0.24s' }}
                >
                  <button
                    onClick={() => setActiveTab('planner')}
                    className="
                      group inline-flex items-center justify-center gap-2
                      bg-white text-uoft-blue font-semibold rounded-xl px-7 py-3.5 text-sm
                      shadow-lg shadow-black/20 hover:shadow-xl hover:-translate-y-0.5
                      active:translate-y-0 transition-all
                    "
                  >
                    Get Started
                    <span className="transition-transform group-hover:translate-x-0.5">→</span>
                  </button>
                  <button
                    onClick={() => setActiveTab('chat')}
                    className="
                      inline-flex items-center justify-center gap-2
                      bg-white/5 text-white font-semibold rounded-xl px-7 py-3.5 text-sm
                      ring-1 ring-white/25 hover:bg-white/10 hover:ring-white/40
                      transition-all
                    "
                  >
                    Talk to the AI Advisor
                  </button>
                </div>
              </div>

              {/* ── "How it works" / features strip ── */}
              <div
                className="animate-fade-rise mt-20 grid gap-5 sm:grid-cols-3"
                style={{ animationDelay: '0.32s' }}
              >
                {/* Each card maps one-to-one to a working tab and is clickable so
                    the strip doubles as secondary navigation. Defined inline as
                    an array so the markup stays DRY. */}
                {[
                  {
                    tab: 'chat',
                    title: 'AI Advisor',
                    desc: 'Chat through prerequisites, programs and degree planning, one question at a time.',
                    icon: (
                      // Speech bubble — represents conversation.
                      <path d="M4 5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-4 4v-4H5a1 1 0 0 1-1-1V5Z" />
                    ),
                  },
                  {
                    tab: 'planner',
                    title: 'Course Planner',
                    desc: 'Share your interests and effort level — get ranked course picks with reasons.',
                    icon: (
                      // Clipboard / checklist — represents building a plan.
                      <path d="M9 4h6a1 1 0 0 1 1 1v1h2a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h2V5a1 1 0 0 1 1-1Zm0 2v1h6V6H9Zm-1 6h2m-2 4h2m4-4h2m-2 4h2" />
                    ),
                  },
                  {
                    tab: 'reviews',
                    title: 'Course Reviews',
                    desc: 'See what other students said, and share your own take on a course.',
                    icon: (
                      // Star — represents ratings/reviews.
                      <path d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.3-4.8-2.5-4.8 2.5.9-5.3L4.2 9.7l5.4-.8L12 4Z" />
                    ),
                  },
                ].map((card) => (
                  <button
                    key={card.tab}
                    onClick={() => setActiveTab(card.tab)}
                    className="
                      group text-left rounded-2xl p-6
                      bg-white/6 ring-1 ring-white/10
                      hover:bg-white/10 hover:ring-white/25 hover:-translate-y-1
                      shadow-lg shadow-black/10 transition-all
                    "
                  >
                    {/* Icon tile in a faint gold wash so each card has a warm focal point. */}
                    <span className="inline-flex items-center justify-center w-11 h-11 rounded-xl bg-uoft-accent/15 ring-1 ring-uoft-accent/25 text-uoft-accent">
                      <svg
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="w-5 h-5"
                      >
                        {card.icon}
                      </svg>
                    </span>
                    <h3 className="mt-4 text-white font-semibold text-base">{card.title}</h3>
                    <p className="mt-1.5 text-white/60 text-sm leading-relaxed">{card.desc}</p>
                    <span className="mt-4 inline-flex items-center gap-1 text-xs font-medium text-white/50 group-hover:text-uoft-accent transition-colors">
                      Open
                      <span className="transition-transform group-hover:translate-x-0.5">→</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ══════════════════════════════════════════
            CHAT TAB
            Two-column layout: session sidebar + chat panel.
            Shown when activeTab === 'chat'.
        ══════════════════════════════════════════ */}
        {activeTab === 'chat' && (
          <div className="flex-1 flex gap-4 min-h-0 w-full max-w-4xl mx-auto px-4 py-6">

            {/* Backdrop behind the sidebar drawer on mobile only — tapping it
                closes the drawer, same as tapping outside a modal. */}
            {sidebarOpen && (
              <div
                className="fixed inset-0 bg-black/50 z-30 md:hidden"
                onClick={() => setSidebarOpen(false)}
              />
            )}

            {/* ── Session sidebar ──
                Uses an off-canvas drawer (fixed + hidden md:flex) below md rather
                than stacking above the chat, which would push the message input
                below the fold. The toggle button keeps past chats reachable. */}
            <div className={`
              ${sidebarOpen ? 'flex' : 'hidden'} md:flex
              fixed md:static inset-y-0 left-0 z-40 md:z-auto
              w-64 md:w-52 flex-col gap-2 shrink-0
              bg-uoft-blue md:bg-transparent p-4 md:p-0
              shadow-2xl md:shadow-none
            `}>
              <div className="flex items-center justify-between md:hidden mb-1">
                <span className="text-white/70 text-xs font-semibold uppercase tracking-wide">Chats</span>
                <button
                  onClick={() => setSidebarOpen(false)}
                  aria-label="Close chat list"
                  className="text-white/60 hover:text-white p-1 rounded-lg hover:bg-white/10 transition"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
                    <path d="M18 6 6 18" /><path d="M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <button
                onClick={() => { startNewChat(); setSidebarOpen(false) }}
                className="w-full bg-white text-uoft-blue font-semibold rounded-lg py-2 text-sm hover:bg-white/90 transition"
              >
                + New Chat
              </button>
              <div className="flex-1 overflow-y-auto space-y-1">
                {chatSessions.map(session => (
                  <button
                    key={session.id}
                    onClick={() => { loadChat(session); setSidebarOpen(false) }}
                    className={`
                      w-full text-left px-3 py-2 rounded-lg text-xs truncate transition
                      ${session.id === currentSessionId
                        ? 'bg-white text-uoft-blue font-medium'
                        : 'bg-white/10 text-white/70 hover:bg-white/20 hover:text-white'}
                    `}
                  >
                    {/* Use 'or' fallback so an empty title never renders a blank button */}
                    {session.title || 'New Chat'}
                  </button>
                ))}
                {chatSessions.length === 0 && (
                  <p className="text-white/30 text-xs text-center mt-4 italic">No chats yet</p>
                )}
              </div>
            </div>

            {/* ── Chat panel ── */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="mb-4">
                <div className="flex items-center gap-2 md:justify-center">
                  {/* Hamburger toggle — md:hidden because the sidebar is
                      always visible side-by-side once there's room for it. */}
                  <button
                    onClick={() => setSidebarOpen(true)}
                    aria-label="Open chat list"
                    className="md:hidden shrink-0 text-white/70 hover:text-white p-1.5 -ml-1.5 rounded-lg hover:bg-white/10 transition"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
                      <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
                    </svg>
                  </button>
                  <h2 className="text-white text-2xl font-bold tracking-tight">AI Advisor</h2>
                </div>
                <p className="text-white/60 mt-1 text-xs text-center">
                  {currentSessionId ? 'Session active — messages are saved.' : 'Type a message to start a new session.'}
                </p>
              </div>

              {/* Scrollable message list */}
              <div className="flex-1 overflow-y-auto space-y-3 pr-1 mb-4">
                {messages.length === 0 && (
                  <p className="text-white/40 text-sm text-center mt-8 italic">
                    Ask about courses, programs, prerequisites, or degree planning.
                  </p>
                )}

                {messages.map((msg, idx) => {
                  const isUser = msg.role === 'user'
                  const isEditingThis = isUser && editingIndex === idx

                  if (isEditingThis) {
                    return (
                      <div key={idx} className="flex justify-end">
                        <div className="max-w-[80%] w-full flex flex-col items-end gap-1.5">
                          <textarea
                            autoFocus
                            value={editingText}
                            onChange={(e) => setEditingText(e.target.value)}
                            onKeyDown={(e) => {
                              // Enter resends, Shift+Enter adds a newline, Escape cancels.
                              if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault()
                                handleEditMessage(idx)
                              } else if (e.key === 'Escape') {
                                cancelEdit()
                              }
                            }}
                            rows={2}
                            className="
                              w-full rounded-2xl rounded-br-sm bg-white text-uoft-blue text-sm
                              leading-relaxed px-4 py-2.5 resize-none shadow-sm
                              focus:outline-none focus:ring-2 focus:ring-white/50
                            "
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={cancelEdit}
                              className="text-xs text-white/60 hover:text-white px-2 py-1 transition"
                            >
                              Cancel
                            </button>
                            <button
                              onClick={() => handleEditMessage(idx)}
                              disabled={!editingText.trim()}
                              className="
                                text-xs font-semibold bg-white text-uoft-blue rounded-lg px-3 py-1
                                hover:bg-white/90 disabled:opacity-40 transition
                              "
                            >
                              Save &amp; resend
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  }

                  return (
                    <div key={idx} className={`group flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                      <div className={`flex items-center gap-1 max-w-[80%] ${isUser ? 'flex-row-reverse' : ''}`}>
                        {/* Subtle shadow on both bubble types lifts the thread off
                            the flat blue and improves message separation. */}
                        <div className={`
                          rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm
                          ${isUser
                            ? 'bg-white text-uoft-blue rounded-br-sm'
                            : 'bg-white/15 ring-1 ring-white/10 text-white rounded-bl-sm'}
                        `}>
                          {msg.role === 'assistant'
                            ? <TypewriterMarkdown
                                content={msg.content}
                                // Only fresh replies carry animate:true; history
                                // messages lack it and render instantly. Coerced to
                                // boolean so undefined becomes a clean false.
                                animate={!!msg.animate}
                                onReveal={() => setScrollTick((t) => t + 1)}
                              />
                            : msg.content
                          }
                        </div>

                        {/* Edit button — only on user messages that have a real DB
                            id (a failed save has no id to truncate from), and hidden
                            until hover so the thread stays uncluttered. */}
                        {isUser && (
                          <button
                            onClick={() => { setEditingIndex(idx); setEditingText(msg.content) }}
                            disabled={chatLoading || !msg.id}
                            title="Edit message"
                            className="
                              opacity-0 group-hover:opacity-100 transition-opacity
                              shrink-0 p-1.5 rounded-full text-white/50
                              hover:text-white hover:bg-white/10 disabled:opacity-0
                            "
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5Z" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}

                {/* Typing indicator — shown while waiting for Claude's response */}
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="bg-white/15 text-white/60 rounded-2xl rounded-bl-sm px-4 py-2.5 text-sm italic">
                      Thinking...
                    </div>
                  </div>
                )}

                {chatError && <p className="text-red-300 text-xs text-center">{chatError}</p>}

                {/* Invisible anchor we scroll into view after each message */}
                <div ref={messagesEndRef} />
              </div>

              {/* Input bar — always enabled; the session is created lazily on first send */}
              <form onSubmit={handleChatSend} className="flex gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder="Ask about courses, prerequisites, programs..."
                  disabled={chatLoading}
                  className="
                    flex-1 rounded-xl border border-white/20 bg-white/10 text-white
                    placeholder-white/40 px-4 py-3 text-sm
                    focus:outline-none focus:ring-2 focus:ring-white/30
                    disabled:opacity-50 transition
                  "
                />
                <button
                  type="submit"
                  disabled={chatLoading || !inputValue.trim()}
                  className="
                    bg-white text-uoft-blue font-semibold rounded-xl px-5 py-3 text-sm
                    hover:bg-white/90 active:scale-[0.97] transition-all
                    disabled:opacity-40 disabled:cursor-not-allowed
                  "
                >
                  Send
                </button>
              </form>
            </div>
          </div>
        )}

        {/* ══════════════════════════════════════════
            PLANNER TAB
            The max-w-lg lives here, not on the outer wrapper, because the chat
            tab needs full width; this restores a narrow constraint for the form.
        ══════════════════════════════════════════ */}
        {activeTab === 'planner' && (
        <div className="flex-1 flex items-start justify-center px-4 py-12 overflow-y-auto">
        <div className="w-full max-w-lg space-y-8">
        <>

          {/* Page heading */}
          <div className="text-center">
            <h2 className="text-white text-3xl font-bold tracking-tight">
              Plan Your Degree
            </h2>
            <p className="text-white/60 mt-2 text-sm">
              Tell us your interests and how hard you want to work — we'll handle the rest.
            </p>
          </div>

          {/* ── Input form ── */}
          {/* White card on the dark blue background. shadow-2xl + ring give it
              the strongest depth on the page, since the planner is the main CTA. */}
          <form
            onSubmit={handleSubmit}
            className="bg-white rounded-2xl shadow-2xl ring-1 ring-black/5 p-8 space-y-6"
          >

            {/* Interests field */}
            <div className="space-y-2">
              <label
                htmlFor="interests"
                className="block text-sm font-semibold text-uoft-blue"
              >
                Interests
              </label>
              <input
                id="interests"
                type="text"
                value={interests}
                onChange={(e) => setInterests(e.target.value)}
                placeholder="e.g. machine learning, philosophy, economics"
                // Required so the browser blocks submission if left empty
                required
                className="
                  w-full rounded-lg border border-gray-200 px-4 py-3
                  text-sm text-gray-800 placeholder-gray-400
                  focus:outline-none focus:ring-2 focus:ring-uoft-blue/40 focus:border-uoft-blue
                  transition
                "
              />
              <p className="text-xs text-gray-400">
                Separate multiple interests with commas
              </p>
            </div>

            {/* Difficulty dropdown — maps to a 1–10 int for the scoring engine */}
            <div className="space-y-2">
              <label
                htmlFor="difficulty"
                className="block text-sm font-semibold text-uoft-blue"
              >
                Preferred difficulty
              </label>
              <select
                id="difficulty"
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                required
                className="
                  w-full rounded-lg border border-gray-200 px-4 py-3
                  text-sm text-gray-800
                  focus:outline-none focus:ring-2 focus:ring-uoft-blue/40 focus:border-uoft-blue
                  transition appearance-none bg-white
                "
              >
                {DIFFICULTY_OPTIONS.map(({ value, label }) => (
                  <option key={value} value={value} disabled={value === ''}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            {/* Workload dropdown — maps to a 1–5 int for the scoring engine */}
            <div className="space-y-2">
              <label
                htmlFor="workload"
                className="block text-sm font-semibold text-uoft-blue"
              >
                Workload preference
              </label>
              <select
                id="workload"
                value={workload}
                onChange={(e) => setWorkload(e.target.value)}
                required
                className="
                  w-full rounded-lg border border-gray-200 px-4 py-3
                  text-sm text-gray-800
                  focus:outline-none focus:ring-2 focus:ring-uoft-blue/40 focus:border-uoft-blue
                  transition appearance-none bg-white
                "
              >
                {WORKLOAD_OPTIONS.map(({ value, label }) => (
                  <option key={value} value={value} disabled={value === ''}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            {/* Submit */}
            <button
              type="submit"
              className="
                w-full bg-uoft-blue text-white font-semibold rounded-lg
                py-3 text-sm tracking-wide
                hover:bg-uoft-blue/90 active:scale-[0.98]
                transition-all duration-150
                focus:outline-none focus:ring-2 focus:ring-uoft-blue/40
              "
            >
              Generate Plan →
            </button>
          </form>

          {/* ── Output panel ──
              Shown after first submit. Displays loading state, errors, and
              eventually the course list returned by the backend. */}
          {submitted && (
            <div className="bg-white/10 border border-white/20 rounded-2xl p-6 space-y-4">
              <h3 className="text-white font-semibold text-sm uppercase tracking-widest">
                Recommended Courses
              </h3>

              {loading && (
                <p className="text-white/60 text-sm italic">Loading...</p>
              )}

              {error && (
                <p className="text-red-300 text-sm">{error}</p>
              )}

              {courses && (
                <div className="space-y-3">
                  {courses.map((course) => (
                    <div
                      key={course.name}
                      className="bg-white/[0.07] ring-1 ring-white/15 rounded-xl px-4 py-3 flex items-start gap-4 hover:bg-white/10 hover:ring-white/25 transition-colors"
                    >
                      {/* Score badge in gold so the headline metric pops against
                          the blue and reuses the brand accent. */}
                      <div className="shrink-0 w-10 h-10 rounded-full bg-uoft-accent/15 ring-1 ring-uoft-accent/30 flex items-center justify-center">
                        <span className="text-uoft-accent text-xs font-bold">{course.score}</span>
                      </div>

                      <div className="min-w-0 flex-1">
                        <p className="text-white font-semibold text-sm">{course.name}</p>

                        {course.reasons && course.reasons.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5 mt-2">
                            {course.reasons.map((reason, idx) => (
                              <span
                                key={idx}
                                className={`
                                  inline-block rounded-full px-2.5 py-0.5 text-xs font-medium
                                  ${reason.positive
                                    ? 'bg-green-500/20 text-green-200'
                                    : 'bg-amber-500/20 text-amber-200'}
                                `}
                              >
                                {reason.message}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-white/60 text-xs mt-0.5">No specific reasons found.</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
        </div>
        </div>)}
        {/* end activeTab === 'planner' */}

        {/* ══════════════════════════════════════════
            REVIEWS TAB
            Two sections: submit a review + browse reviews by course code.
            Shown when activeTab === 'reviews'.
        ══════════════════════════════════════════ */}
        {activeTab === 'reviews' && (
        <div className="flex-1 flex items-start justify-center px-4 py-12 overflow-y-auto">
          <div className="w-full max-w-2xl space-y-8">

            <div className="text-center">
              <h2 className="text-white text-3xl font-bold tracking-tight">Course Reviews</h2>
              <p className="text-white/60 mt-2 text-sm">
                Share your experience or browse what other students said.
              </p>
            </div>

            {/* Submit a review */}
            <form onSubmit={handleSubmitReview} className="bg-white rounded-2xl shadow-2xl ring-1 ring-black/5 p-8 space-y-5">
              <h3 className="text-uoft-blue font-bold text-base">Leave a Review</h3>

              <div className="space-y-2">
                <label className="block text-sm font-semibold text-uoft-blue">Course Code</label>
                <input
                  type="text"
                  value={reviewCourseCode}
                  onChange={e => setReviewCourseCode(e.target.value)}
                  placeholder="e.g. CSC207H1"
                  required
                  className="w-full rounded-lg border border-gray-200 px-4 py-3 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-uoft-blue/40 transition"
                />
              </div>

              <div className="space-y-2">
                <label className="block text-sm font-semibold text-uoft-blue">Rating (1–5)</label>
                <div className="flex gap-2">
                  {[1,2,3,4,5].map(n => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setReviewRating(n)}
                      className={`
                        w-10 h-10 rounded-full text-sm font-bold transition-all
                        ${reviewRating >= n
                          ? 'bg-uoft-blue text-white'
                          : 'bg-gray-100 text-gray-400 hover:bg-gray-200'}
                      `}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="block text-sm font-semibold text-uoft-blue">Your Review</label>
                <textarea
                  value={reviewText}
                  onChange={e => setReviewText(e.target.value)}
                  placeholder="What did you think of this course?"
                  rows={3}
                  className="w-full rounded-lg border border-gray-200 px-4 py-3 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-uoft-blue/40 transition resize-none"
                />
              </div>

              <button
                type="submit"
                disabled={reviewSubmitting}
                className="w-full bg-uoft-blue text-white font-semibold rounded-lg py-3 text-sm hover:bg-uoft-blue/90 transition disabled:opacity-50"
              >
                {reviewSubmitting ? 'Submitting...' : 'Submit Review'}
              </button>

              {reviewSubmitMsg && (
                <p className={`text-sm text-center ${reviewSubmitMsg.startsWith('Error') ? 'text-red-500' : 'text-green-600'}`}>
                  {reviewSubmitMsg}
                </p>
              )}
            </form>

            {/* Look up reviews */}
            <div className="bg-white/10 border border-white/20 rounded-2xl p-6 space-y-4">
              <h3 className="text-white font-bold text-sm uppercase tracking-widest">Browse Reviews</h3>
              <form onSubmit={handleLookupReviews} className="flex gap-2">
                <input
                  type="text"
                  value={reviewLookupCode}
                  onChange={e => setReviewLookupCode(e.target.value)}
                  placeholder="Enter course code (e.g. MAT237H1)"
                  className="flex-1 rounded-xl border border-white/20 bg-white/10 text-white placeholder-white/40 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-white/30 transition"
                />
                <button
                  type="submit"
                  disabled={reviewLookupLoading}
                  className="bg-white text-uoft-blue font-semibold rounded-xl px-5 py-3 text-sm hover:bg-white/90 transition disabled:opacity-50"
                >
                  Search
                </button>
              </form>

              {reviewLookupLoading && <p className="text-white/60 text-sm italic">Loading...</p>}

              {reviewResults && reviewResults.length === 0 && (
                <p className="text-white/40 text-sm italic">No reviews yet for this course.</p>
              )}

              {reviewResults && reviewResults.length > 0 && (
                <div className="space-y-3">
                  {reviewResults.map(r => (
                    <div key={r.id} className="bg-white/10 rounded-xl px-4 py-3 space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-white font-semibold text-sm">{r.course_code}</span>
                        <span className="text-yellow-300 font-bold text-sm">{'★'.repeat(r.rating)}{'☆'.repeat(5 - r.rating)}</span>
                      </div>
                      {r.review_text && <p className="text-white/80 text-xs">{r.review_text}</p>}
                      <p className="text-white/40 text-xs">{new Date(r.created_at).toLocaleDateString()}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        </div>
        )}

        </div>
      </main>

      {/* Floating feedback button — fixed to the viewport so it's reachable from
          any tab. Hidden on mobile while the chat tab is open because it would
          overlap the Send button there; it's still one tap away via other tabs. */}
      <a
        href={FEEDBACK_FORM_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={`
          ${activeTab === 'chat' ? 'hidden md:flex' : 'flex'}
          fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-50
          items-center gap-2
          bg-uoft-accent text-uoft-blue font-semibold
          rounded-full p-3 sm:px-4 sm:py-2.5 text-sm
          shadow-lg shadow-black/30
          hover:brightness-110 hover:-translate-y-0.5
          active:translate-y-0 transition-all
        `}
      >
        {/* Pencil icon. Shrinks to icon-only below sm because the full "Feedback"
            pill was wide enough to cover the review-search bar on phone widths. */}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5Z" />
        </svg>
        <span className="hidden sm:inline">Feedback</span>
      </a>
    </div>
  )
}

export default App