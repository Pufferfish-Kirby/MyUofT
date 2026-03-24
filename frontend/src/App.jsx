import { useState } from 'react'
import './App.css'

// Workload options map course-load intensity to a human-readable label.
// These will eventually feed into the AI planner's constraint system.
const WORKLOAD_OPTIONS = [
  { value: '', label: 'Select a workload...' },
  { value: 'light', label: 'Light (3–4 courses/semester)' },
  { value: 'standard', label: 'Standard (5 courses/semester)' },
  { value: 'heavy', label: 'Heavy (6 courses/semester)' },
]

function App() {
  // Form field state — kept flat because this form is simple enough
  // that a single object would just add boilerplate.
  const [interests, setInterests] = useState('')
  const [workload, setWorkload] = useState('')

  // Submitted snapshot — null until the user hits "Generate Plan".
  // Separating "live form state" from "submitted state" prevents the
  // output panel from updating on every keystroke.
  const [submitted, setSubmitted] = useState(null)

  // courses holds the array returned by the backend, e.g. ["CSC108", "MAT137"].
  // Kept separate from `submitted` so we can show a loading state between
  // the form submit and the API response arriving.
  const [courses, setCourses] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    // Prevent the default browser form navigation
    e.preventDefault()

    // Parse interests into a clean array — trim whitespace and drop empties
    // so "  math,  cs,  " becomes ["math", "cs"] instead of a messy list.
    const parsedInterests = interests
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    setSubmitted({ interests: parsedInterests, workload })
    setCourses(null)
    setError(null)
    setLoading(true)

    try {
      // POST to the FastAPI backend running on port 8000.
      // The body shape must match the RequestData Pydantic model in main.py.
      const response = await fetch('http://localhost:8000/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interests: parsedInterests, workload }),
      })

      if (!response.ok) {
        // Surface the HTTP error text so it's visible during development
        throw new Error(`Server error: ${response.status}`)
      }

      const data = await response.json()
      // data.courses is the array from the backend, e.g. ["CSC108", "MAT137"]
      setCourses(data.courses)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    // Full-height dark-blue background — this is UofT's primary brand colour (#002A5C)
    <div className="min-h-screen bg-uoft-blue flex flex-col">

      {/* ── Navbar ── */}
      <header className="bg-uoft-blue border-b border-white/20 px-8 py-4 flex items-center gap-3">
        {/* The thick left border acts as a quick visual accent without needing an image */}
        <div className="w-1 h-8 bg-white rounded-full" />
        <h1 className="text-white text-xl font-semibold tracking-wide">MyUofT</h1>
        <span className="text-white/50 text-sm ml-1">/ Course Planner</span>
      </header>

      {/* ── Main content ── */}
      <main className="flex-1 flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-lg space-y-8">

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

            {/* Workload dropdown */}
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

              {/* Loading spinner — shown while waiting for the API response */}
              {loading && (
                <p className="text-white/60 text-sm italic">Loading...</p>
              )}

              {/* Error state — surface API/network errors visibly during dev */}
              {error && (
                <p className="text-red-300 text-sm">{error}</p>
              )}

              {/* Course chips — one per course code returned by the backend */}
              {courses && (
                <div className="flex flex-wrap gap-2">
                  {courses.map((course) => (
                    <span
                      key={course}
                      className="bg-white/20 text-white text-xs font-medium px-3 py-1 rounded-full"
                    >
                      {course}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

        </div>
      </main>
    </div>
  )
}

export default App
