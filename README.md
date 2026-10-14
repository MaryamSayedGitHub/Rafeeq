# Rafeeq · رفيق

A multi-agent learning copilot for students and teachers, Arabic-first with an English toggle. Built as an NTI AI capstone project.

Rafeeq combines a RAG tutor grounded in the course material, a student-modeling layer that predicts weak topics, agents for planning, quizzing and reporting, handwriting/photo recognition with hints (Snap & Ask), and a teacher dashboard.

## Features

- **Ask** — a tutor that answers only from the room's own material, with page citations, in Arabic or English.
- **Snap & Ask** — photograph a question or your own worked solution; a vision-language model reads it and the tutor answers or checks it.
- **Quiz** — generated per topic, graded automatically, feeding back into the student's profile.
- **My plan** — a "what to do next" suggestion based on weak topics.
- **Rooms** — a course room per teacher, with student uploads and (proposed) a personal study room with no teacher.
- **Teacher dashboard** — class-wide insights, a per-topic report, and an assistant that drafts replies for approval.

## Stack

FastAPI + Jinja2 + HTMX (one server-rendered app, no separate frontend build), Postgres with pgvector, Docker for local development, deployed on Render. Dependencies are managed with [uv](https://docs.astral.sh/uv/).

## Run it locally

```bash
uv sync
uv run uvicorn rafeeq.main:app --reload
```

Open http://127.0.0.1:8000 — you should see the Arabic home page.

**With Docker** (also starts Postgres):

```bash
docker compose up --build
```

## Run the tests

```bash
uv run pytest
```

This also checks that every file in `contracts/samples/` matches the API contract in `contracts/openapi.yaml`.

## Project structure

```
rafeeq/
├── main.py          # starts the app, plugs in every router
├── samples.py        # load_sample(name) — read an agreed example JSON
├── web/               # page frame, nav, the one app.css
├── platform/          # login, rooms, file uploads, database
├── copilot/           # routes a message to ask / quiz / check_work / plan
├── snap/               # photo → text (OpenCV + a vision-language model)
├── knowledge/          # indexing and search (hybrid retrieval, grounded answers, evaluation) -> knowledge/README.md
├── tutor/              # grounded answers, handwriting check
├── quiz/                # quiz generation, grading, student profile
└── teacher/            # teacher dashboard and reports
contracts/
├── openapi.yaml        # every route, and the JSON shape it sends/receives
└── samples/             # one real example per JSON file
tests/                   # automated checks
docs/knowledge/          # M2 evaluation reports (historical, written in the standalone project)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch workflow and how the team is organized.

## Status

In active development for the NTI AI capstone.

## Team

A five-member team built this for the NTI AI course capstone, Education domain.