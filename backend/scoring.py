# ok this is where we will define our scoring system
class Course:

    name: str
    description: str
    prerequisites: list[str]
    corequisites: list[str]
    credits: int
    workload: str
    difficulty: int
    rating: float
    reviews: list[str]
    def __init__(self, name: str, description: str, prerequisites: list[str] = None, corequisites: list[str] = None, credits: float = 0.5, workload: int = 3, difficulty: int = 5, rating: float = None, reviews: list[str] = None) -> None:
        self.name = name
        self.description = description
        self.prerequisites = prerequisites if prerequisites is not None else []
        self.corequisites = corequisites if corequisites is not None else []
        self.credits = credits
        self.workload = workload
        self.difficulty = difficulty
        self.rating = rating
        self.reviews = reviews if reviews is not None else []
    
    def get_name(self) -> str:
        return self._name
    def get_prerequisites(self) -> list[str]:
        return self._prerequisites
    def get_corequisites(self) -> list[str]:
        return self._corequisites
    def get_credits(self) -> float:
        return self._credits

courses = [
    Course(name="CSC108H1", description="Introduction to Computer Science", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT137Y1", description="Calculus with Proofs", prerequisites=[], corequisites=[], credits=1.0, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="PSY100H1", description="Introduction to Psychology", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT135H1", description="Calculus I", prerequisites=[], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
    Course(name="MAT136H1", description="Calculus II", prerequisites=["MAT135H1"], corequisites=[], credits=0.5, workload=3, difficulty=5, rating=None, reviews=None),
]

