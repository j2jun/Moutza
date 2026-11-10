# Moutza

Share and find useful resources about universities and student organizations:
scholarships, clubs, housing guides, course tips, and more.

It looks like a campus corkboard: every resource is a pinned paper flyer, colored by its topic.

- **Pin a flyer**: share a link with a title, school, tags, and description.
- **Search** with relevance ranking (local TF-IDF, no external AI service, no cost), and filter by school.
- **Tear-off tabs** on each flyer open its link, and **Pinned nearby** suggests similar flyers.
- **Surprise me** opens a random flyer.
- Works on phones, in dark mode, and with reduced motion.

## Run

Python 3.9+ only, no dependencies.

```sh
python3 app.py          # http://localhost:8000  (python3 app.py 9000 for another port)
python3 -m unittest -v  # tests
```

Data is stored in `moutza.db` (SQLite) in the current directory.
