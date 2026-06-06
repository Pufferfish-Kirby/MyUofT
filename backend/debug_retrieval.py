from scoring import search_by_message, _extract_interests_from_text, courses

QUERIES = [
    "system design",
    "machine learning",
    "ethics",
    "linear algebra",
    "shakespeare",
]

for query in QUERIES:
    extracted = _extract_interests_from_text(query)
    results = search_by_message(query, courses, top_n=10)
    print(f"\n{'='*60}")
    print(f"Query: \"{query}\"")
    print(f"Extracted terms: {extracted}")
    print("-"*60)
    if not results:
        print("  (no results)")
    for course, score in results:
        print(f"  {score:5.2f}  {course.get_course_code():<12}  {course.get_name()}")
