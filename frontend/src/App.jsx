import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

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
  // Which tab is active: 'planner' (the existing form) or 'chat'
  const [activeTab, setActiveTab] = useState('planner')

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
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, chatLoading])

  // Load the session list whenever the user switches to the chat tab.
  // WHY not load at mount: the planner tab is the default, so we'd be making
  // a network request for data the user may never need.  Lazy-loading on tab
  // activation keeps startup fast.
  //
  // WHY auto-create a session here: we want the user to land on a ready-to-type
  // blank chat (like Claude.ai) rather than a disabled input.  We only create a
  // session when currentSessionId is null so this never fires a second time once
  // a session is already active — the null-check acts as a one-shot guard.
  useEffect(() => {
    if (activeTab === 'chat') {
      fetch('http://localhost:8000/chats')
        .then(r => r.json())
        .then(async (sessions) => {
          setChatSessions(sessions)
          // Auto-start a blank session so the user lands ready to type.
          // Only create one if there isn't already an active session open.
          if (currentSessionId === null) {
            try {
              const res = await fetch('http://localhost:8000/chats', { method: 'POST' })
              if (!res.ok) throw new Error()
              const session = await res.json()
              setCurrentSessionId(session.id)
              setMessages([])
              // Prepend the new session so it appears at the top of the sidebar.
              setChatSessions(prev => [session, ...prev])
            } catch {
              // Non-fatal — the user can still click "+ New Chat" manually
            }
          }
        })
        .catch(() => {})
    }
  }, [activeTab, currentSessionId])

  // Ask the backend to create a new session row, then make it the active session.
  // Prepend to chatSessions so the new entry appears at the top of the sidebar
  // immediately without waiting for a full re-fetch.
  async function startNewChat() {
    try {
      const res = await fetch('http://localhost:8000/chats', { method: 'POST' })
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const session = await res.json()
      setCurrentSessionId(session.id)
      setMessages([])
      setChatSessions(prev => [session, ...prev])
    } catch (err) {
      setChatError(`Could not start a new chat: ${err.message}`)
    }
  }

  // Fetch persisted messages for a past session and restore them into the UI.
  // WHY replace messages outright instead of merging:
  //     Each session is its own isolated conversation — we never want turns
  //     from session A bleeding into session B's view.
  async function loadChat(session) {
    try {
      const res = await fetch(`http://localhost:8000/chats/${session.id}/messages`)
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      const msgs = await res.json()
      setCurrentSessionId(session.id)
      setMessages(msgs)
    } catch (err) {
      setChatError(`Could not load chat: ${err.message}`)
    }
  }

  async function handleChatSend(e) {
    e.preventDefault()
    const text = inputValue.trim()
    if (!text || chatLoading) return

    // Optimistically add the user message to the UI before the response arrives
    const userMsg = { role: 'user', content: text }
    const updatedHistory = [...messages, userMsg]
    setMessages(updatedHistory)
    setInputValue('')
    setChatError(null)
    setChatLoading(true)

    try {
      const response = await fetch('http://localhost:8000/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Send the full history so Claude can refer to earlier turns.
        // We exclude the just-added userMsg from history and pass it as `message`
        // to match the ChatRequest schema: { message, history: prior turns }.
        body: JSON.stringify({
          message: text,
          history: messages, // prior turns only, not the one we just added
          session_id: currentSessionId,
        }),
      })

      if (!response.ok) throw new Error(`Server error: ${response.status}`)

      const data = await response.json()
      setMessages([...updatedHistory, { role: 'assistant', content: data.response }])

      // Re-fetch the session list so the sidebar title updates after the first
      // message auto-renames the session from "New Chat" to a real snippet.
      fetch('http://localhost:8000/chats')
        .then(r => r.json())
        .then(setChatSessions)
        .catch(() => {})
    } catch (err) {
      setChatError(err.message)
    } finally {
      setChatLoading(false)
    }
  }

  async function handleSubmit(e) {
    // Prevent the default browser form navigation
    e.preventDefault()

    // Parse interests into a clean array — trim whitespace and drop empties
    // so "  math,  cs,  " becomes ["math", "cs"] instead of a messy list.
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
      const response = await fetch('http://localhost:8000/recommend', {
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
      const res = await fetch('http://localhost:8000/reviews', {
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
      const res = await fetch(`http://localhost:8000/reviews/${reviewLookupCode.trim().toUpperCase()}`)
      if (!res.ok) throw new Error(`Server error: ${res.status}`)
      setReviewResults(await res.json())
    } catch (err) {
      setReviewResults([])
    } finally {
      setReviewLookupLoading(false)
    }
  }

  return (
    // Full-height dark-blue background — this is UofT's primary brand colour (#002A5C)
    <div className="min-h-screen bg-uoft-blue flex flex-col">

      {/* ── Navbar ── */}
      <header className="bg-uoft-blue border-b border-white/20 px-8 py-4 flex items-center gap-3">
        <div className="w-1 h-8 bg-white rounded-full" />
        <h1 className="text-white text-xl font-semibold tracking-wide">MyUofT</h1>
        <span className="text-white/50 text-sm ml-1">/ Course Planner</span>

        {/* Tab switcher in the navbar — right-aligned */}
        <div className="ml-auto flex gap-1 bg-white/10 rounded-lg p-1">
          {['planner', 'chat', 'reviews'].map((tab) => (
            <button
              key={tab}
              onClick={() => {
                setActiveTab(tab)
              }}
              className={`
                px-4 py-1.5 rounded-md text-sm font-medium capitalize transition-all
                ${activeTab === tab
                  ? 'bg-white text-uoft-blue shadow'
                  : 'text-white/70 hover:text-white'}
              `}
            >
              {tab === 'chat' ? 'AI Advisor' : tab === 'reviews' ? 'Reviews' : 'Course Planner'}
            </button>
          ))}
        </div>
      </header>

      {/* ── Main content ── */}
      {/* WHY flex-col overflow-hidden instead of items-center justify-center:
          each tab now manages its own centering/scrolling so the chat panel can
          fill all remaining vertical space without fighting a fixed py-12 gutter. */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* WHY w-full with no max-w here: the chat tab needs the full width for its
            two-column layout; the planner tab constrains itself via its own wrapper. */}
        <div className="w-full flex-1 flex flex-col min-h-0">

        {/* ══════════════════════════════════════════
            CHAT TAB
            Two-column layout: session sidebar + chat panel.
            Shown when activeTab === 'chat'.
        ══════════════════════════════════════════ */}
        {activeTab === 'chat' && (
          <div className="flex-1 flex gap-4 min-h-0 w-full max-w-4xl mx-auto px-4 py-6">

            {/* ── Session sidebar ── */}
            <div className="w-52 flex flex-col gap-2 shrink-0">
              <button
                onClick={startNewChat}
                className="w-full bg-white text-uoft-blue font-semibold rounded-lg py-2 text-sm hover:bg-white/90 transition"
              >
                + New Chat
              </button>
              <div className="flex-1 overflow-y-auto space-y-1">
                {chatSessions.map(session => (
                  <button
                    key={session.id}
                    onClick={() => loadChat(session)}
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
              <div className="text-center mb-4">
                <h2 className="text-white text-2xl font-bold tracking-tight">AI Advisor</h2>
                <p className="text-white/60 mt-1 text-xs">
                  {currentSessionId ? 'Session active — messages are saved.' : 'Start a new chat or select a previous one.'}
                </p>
              </div>

              {/* Scrollable message list */}
              <div className="flex-1 overflow-y-auto space-y-3 pr-1 mb-4">
                {messages.length === 0 && (
                  <p className="text-white/40 text-sm text-center mt-8 italic">
                    {currentSessionId ? 'No messages yet — say hello!' : 'Click "+ New Chat" to begin.'}
                  </p>
                )}

                {messages.map((msg, idx) => (
                  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`
                      max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed
                      ${msg.role === 'user'
                        ? 'bg-white text-uoft-blue rounded-br-sm'
                        : 'bg-white/15 text-white rounded-bl-sm'}
                    `}>
                      {msg.role === 'assistant'
                        ? <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={{
                              p: ({children}) => <p className="mb-1 last:mb-0">{children}</p>,
                              strong: ({children}) => <strong className="font-semibold">{children}</strong>,
                              ul: ({children}) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
                              ol: ({children}) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
                              h1: ({children}) => <h1 className="font-bold text-base mt-2 mb-1">{children}</h1>,
                              h2: ({children}) => <h2 className="font-semibold text-sm mt-2 mb-1">{children}</h2>,
                              h3: ({children}) => <h3 className="font-medium text-sm mt-1 mb-0.5">{children}</h3>,
                              code: ({children}) => <code className="bg-white/10 rounded px-1 py-0.5 text-xs font-mono">{children}</code>,
                            }}
                          >
                            {msg.content}
                          </ReactMarkdown>
                        : msg.content
                      }
                    </div>
                  </div>
                ))}

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

              {/* Input bar — disabled until a session is active so messages always
                  have a home in the DB (avoids orphan messages with no session_id). */}
              <form onSubmit={handleChatSend} className="flex gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  placeholder={currentSessionId ? "Ask about courses, prerequisites, programs..." : "Start a new chat first"}
                  disabled={chatLoading || !currentSessionId}
                  className="
                    flex-1 rounded-xl border border-white/20 bg-white/10 text-white
                    placeholder-white/40 px-4 py-3 text-sm
                    focus:outline-none focus:ring-2 focus:ring-white/30
                    disabled:opacity-50 transition
                  "
                />
                <button
                  type="submit"
                  disabled={chatLoading || !inputValue.trim() || !currentSessionId}
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
            PLANNER TAB — existing form, unchanged.
            WHY max-w-lg here instead of on the outer wrapper:
                The chat tab needs the full viewport width for its two-column
                layout, so the outer div no longer carries max-w.  We restore
                the narrow constraint here so the planner form doesn't stretch.
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
          {/* White card sits on the dark blue background for contrast */}
          <form
            onSubmit={handleSubmit}
            className="bg-white rounded-2xl shadow-xl p-8 space-y-6"
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
                      className="bg-white/10 border border-white/20 rounded-xl px-4 py-3 flex items-start gap-4"
                    >
                      <div className="shrink-0 w-10 h-10 rounded-full bg-white/20 flex items-center justify-center">
                        <span className="text-white text-xs font-bold">{course.score}</span>
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
            <form onSubmit={handleSubmitReview} className="bg-white rounded-2xl shadow-xl p-8 space-y-5">
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
    </div>
  )
}

export default App