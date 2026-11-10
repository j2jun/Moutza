# Moutza

Share and find useful resources about universities and student organizations:
scholarships, clubs, housing guides, course tips, and more.

- **Share** a link with a title, school, tags, and description.
- **Search** with relevance ranking (local TF-IDF, no external AI service, no cost).
- **Filter** by school, and see **similar resources** on every resource page.

## Run

Python 3.9+ only, no dependencies.

```sh
python3 app.py          # http://localhost:8000  (python3 app.py 9000 for another port)
python3 -m unittest -v  # tests
```

Data is stored in `moutza.db` (SQLite) in the current directory.
