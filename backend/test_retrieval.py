"""
Retrieval test script for semantic search validation.

Test different query formulations to compare results and understand
why some queries miss relevant courses. Includes:
  - Direct semantic search results with scores
  - Message-based search results
  - Side-by-side comparison of query variations
  - Course detail printing
"""

from scoring import (
    search_by_message, courses, _extract_interests_from_text, _strip_filler,
    _detect_year_level, _strip_year_phrases, _expand_query,
    _detect_breadth_categories, _detect_difficulty_bias,
)
from embeddings import semantic_search


def print_course_details(code: str) -> None:
    """Print detailed info about a single course."""
    course = next((c for c in courses if c.get_course_code() == code), None)
    if not course:
        print(f"  Course {code} not found in database")
        return

    print(f"  Code: {code}")
    print(f"  Name: {course.get_name()}")
    print(f"  Tags: {', '.join(course.tags)}")
    print(f"  Desc: {course.description[:100]}...")


def test_semantic_search(query: str, top_n: int = 10) -> None:
    """Test the embedding-based semantic search directly."""
    print(f"\n{'='*80}")
    print(f"SEMANTIC SEARCH: \"{query}\"")
    print(f"{'='*80}")

    results = semantic_search(query, top_n=top_n)

    if not results:
        print("  (no results)")
        return

    print(f"\n  {'Score':<8} {'Code':<12} {'Course Name'}")
    print(f"  {'-'*70}")
    for code, score in results:
        course = next((c for c in courses if c.get_course_code() == code), None)
        if course:
            name = course.get_name()[:50]
            print(f"  {score:6.3f}   {code:<12} {name}")

    # Show detailed info for top 3
    print(f"\n  Top 3 Course Details:")
    print(f"  {'-'*70}")
    for code, _ in results[:3]:
        print_course_details(code)
        print()


def test_message_search(message: str, top_n: int = 10) -> None:
    """Test the message-based search (semantic + code lookup + interest extraction)."""
    print(f"\n{'='*80}")
    print(f"MESSAGE SEARCH: \"{message}\"")
    print(f"{'='*80}")

    # Show extracted interests
    interests = _extract_interests_from_text(message)
    print(f"\n  Extracted interests: {interests if interests else '(none)'}")

    # Run search
    results = search_by_message(message, courses, top_n=top_n)

    if not results:
        print("  (no results)")
        return

    print(f"\n  {'Score':<8} {'Code':<12} {'Course Name'}")
    print(f"  {'-'*70}")
    for course, score in results:
        name = course.get_name()[:50]
        print(f"  {score:6.2f}   {course.get_course_code():<12} {name}")

    # Show detailed info for top 3
    print(f"\n  Top 3 Course Details:")
    print(f"  {'-'*70}")
    for course, _ in results[:3]:
        print_course_details(course.get_course_code())
        print()


def compare_queries(query_set: list[str], top_n: int = 10) -> None:
    """
    Compare multiple query formulations side-by-side.
    Shows which courses appear in each result and which are unique/common.
    """
    print(f"\n{'='*80}")
    print(f"QUERY COMPARISON (top {top_n} for each)")
    print(f"{'='*80}\n")

    all_results = {}
    all_codes = set()

    for query in query_set:
        results = semantic_search(query, top_n=top_n)
        codes = [code for code, _ in results]
        all_results[query] = codes
        all_codes.update(codes)

    # Print results per query
    for i, query in enumerate(query_set, 1):
        codes = all_results[query]
        print(f"{i}. Query: \"{query}\"")
        for j, code in enumerate(codes, 1):
            course = next((c for c in courses if c.get_course_code() == code), None)
            if course:
                print(f"   {j:2d}. {code:<12} {course.get_name()[:55]}")
        print()

    # Show coverage statistics
    print(f"Coverage Statistics:")
    print(f"  Total unique courses across all queries: {len(all_codes)}")

    # Find courses that appear in all vs. some queries
    code_freq = {}
    for codes in all_results.values():
        for code in set(codes):
            code_freq[code] = code_freq.get(code, 0) + 1

    appears_in_all = [code for code, count in code_freq.items() if count == len(query_set)]
    appears_in_some = [code for code, count in code_freq.items() if 1 < count < len(query_set)]
    appears_once = [code for code, count in code_freq.items() if count == 1]

    print(f"  Appear in ALL {len(query_set)} queries: {len(appears_in_all)}")
    if appears_in_all:
        for code in appears_in_all[:5]:
            course = next((c for c in courses if c.get_course_code() == code), None)
            if course:
                print(f"    - {code}: {course.get_name()[:50]}")

    print(f"  Appear in SOME queries: {len(appears_in_some)}")
    print(f"  Appear in ONLY ONE query: {len(appears_once)}")


def dump_all_coding_courses() -> None:
    """For reference: list all courses with 'coding' or 'programming' in their description."""
    print(f"\n{'='*80}")
    print(f"ALL COURSES WITH 'CODING' OR 'PROGRAMMING' IN DESCRIPTION")
    print(f"{'='*80}\n")

    coding_courses = []
    for course in courses:
        text = (course.get_name() + " " + course.description).lower()
        if "coding" in text or "programming" in text:
            coding_courses.append(course)

    coding_courses.sort(key=lambda c: c.get_course_code())

    print(f"Found {len(coding_courses)} courses:\n")
    for course in coding_courses:
        print(f"  {course.get_course_code():<12} {course.get_name()}")

    return coding_courses


def test_full_pipeline(message: str, top_n: int = 5) -> None:
    """
    Show every intermediate transformation in the retrieval pipeline, then the results.

    WHY this transparency matters:
        Each step — year detection, stop-word stripping, year-phrase stripping,
        query expansion — changes what the embedding model sees. When results are
        surprising, printing the intermediate state immediately shows which step
        is responsible without needing a debugger. A developer can see:

          Step 1: what year (if any) was captured and filtered on
          Step 2: what tokens survived stop-word stripping
          Step 3: whether the year phrase was successfully erased
          Step 4: what the embedding model actually receives

        Without this function, you'd have to add print statements inside scoring.py
        and re-run — this surfaces the whole chain in one call.
    """
    print(f"\n{'='*80}")
    print(f"PIPELINE TEST: \"{message}\"")
    print(f"{'='*80}")

    # Step 1: year detection (must run on raw message, before any stripping)
    year = _detect_year_level(message)
    print(f"\n  1. Detected year level   : {year if year is not None else '(none — no year filter applied)'}")

    # Breadth-category and difficulty-bias detection also run on the raw
    # message, before any stripping — printed here alongside year for the
    # same "see every intermediate transformation" reason this function exists.
    breadth = _detect_breadth_categories(message)
    print(f"  1b. Detected breadth cats : {breadth if breadth is not None else '(none — no breadth filter applied)'}")
    difficulty_bias = _detect_difficulty_bias(message)
    print(f"  1c. Detected difficulty  : {difficulty_bias if difficulty_bias is not None else '(none — no difficulty re-ranking)'}")

    # Step 2: stop-word stripping
    stripped = _strip_filler(message)
    print(f"  2. After stop-word strip : {repr(stripped)}")

    # Step 3: year-phrase stripping (only meaningful when a year was detected)
    if year is not None:
        after_year_strip = _strip_year_phrases(stripped)
        print(f"  3. After year-phrase strip: {repr(after_year_strip)}")
    else:
        after_year_strip = stripped
        print(f"  3. Year-phrase strip     : (skipped — no year detected)")

    # Step 4: query expansion
    expanded = _expand_query(after_year_strip)
    if expanded != after_year_strip:
        print(f"  4. After expansion       : {repr(expanded)}")
    else:
        print(f"  4. After expansion       : (no expansions triggered)")

    # Final results via the full pipeline
    results = search_by_message(message, courses, top_n=top_n)
    print(f"\n  Results (top {top_n}):")
    print(f"  {'Score':<8} {'Code':<14} Course Name")
    print(f"  {'-'*65}")
    if not results:
        print("  (no results)")
    else:
        for course, score in results:
            name = course.get_name()[:45]
            print(f"  {score:6.3f}   {course.get_course_code():<14} {name}")


PIPELINE_QUERIES = [
    "coding courses first year",
    "introductory programming",
    "second year ML courses",
    "first year math",
    "easy breadth 2 courses",
    "challenging breadth 2 and 4 courses",
    "introductory breadth category 1",
]


if __name__ == "__main__":
    print("\n" + "="*80)
    print("FULL PIPELINE TESTS — YEAR FILTERING + QUERY EXPANSION")
    print("="*80)

    for q in PIPELINE_QUERIES:
        test_full_pipeline(q, top_n=5)
