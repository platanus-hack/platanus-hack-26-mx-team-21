# City Infrastructure Reporting & Optimization System

A system for **detecting, prioritizing, and acting on urban infrastructure issues**
(potholes, open sewers, broken lights, missing signage, etc.) by combining
street-level video capture, vision models, and external risk datasets into a
single **priority map** that helps city stakeholders spend their budget where it
matters most.

> This document lays out the **context and components** only. It intentionally
> does **not** decide tech stack, frameworks, data formats, or implementation
> details — those are deferred and will be chosen per component.

---

## Premise

1. **Capture.** Monitoring cameras are deployed across the city on different
   routes and cadences — ad-hoc routes, or opportunistically by attaching
   cameras to existing fleets such as trash trucks. They record street video
   tagged with **geolocalised, discretised timestamps**, and stream it to a
   storage server for **offline** processing.

2. **Detect.** A vision model runs over the stored video to detect urban
   infrastructure issues and produce **issue instances** with locations
   (e.g. potholes, open sewers, broken lights).

3. **Prioritize.** Issue locations alone are not actionable. The system computes
   a **priority** for each instance using **external signals** such as car-crash
   datasets and crime activity. The result is a **priority map**.

4. **Surface latent issues.** The same priority map is a driver for finding
   issues that the detector *didn't* flag. Where external risk is high but no
   issues were detected (e.g. a zone with many car crashes but no potholes),
   that's a signal of a **latent problem** — missing lighting, missing transit
   signals, etc. These candidates are investigated by running a **VLM** over the
   video timestamps captured while passing through those **regions of interest
   (ROIs)**.

5. **Decide.** The priority map gives stakeholders (e.g. government) the
   information to make informed decisions and **optimize their budget**.

6. **Interact simply.** The application is meant to be simple, driven mostly by
   **natural-language interactions and events** — for example, prompting the
   system to start reviewing a new *type* of issue.

---

## Components

Each component is intended to be developed **in parallel and independently**.
The descriptions below define *what each part is responsible for* and *what it
consumes/produces* — not how it's built.

### 1. Capture & Streaming
- Deploys cameras on routes/cadences (ad-hoc routes, trash-truck-mounted, etc.).
- Produces street video annotated with **geolocalised, discretised timestamps**.
- Streams captured media to the storage layer for offline processing.

### 2. Storage
- Receives and stores **raw video plus capture metadata** (location, time,
  route/platform).
- Serves as the source of truth that downstream offline processing reads from.

### 3. Issue Detection (Vision)
- Runs a vision model over stored video.
- Produces **issue instances**: typed infrastructure problems with a location,
  a confidence, and a reference back to the source video/frame.

### 4. Priority Engine
- Ingests **external signals** (car-crash datasets, crime activity, etc.).
- Combines detected issues with external risk to compute a **priority map**
  over the city.

### 5. Latent Issue Detection
- Uses the priority map to find **high-risk zones with few/no detected issues**.
- Selects those zones as **ROIs** and runs a **VLM** over the corresponding
  video timestamps to hypothesize **latent issues** (missing lighting, missing
  transit signals, etc.).

### 6. Application (Monitoring & Decisions)
- A **simple** interface for stakeholders to review detected issues and the
  priority map.
- Driven primarily by **natural-language interactions and events** (e.g. a
  prompt to begin reviewing a new issue type).
- Supports informed, budget-optimizing decisions.

---

## Data Flow (conceptual)

```
Cameras (routes / trash trucks)
        │  geolocalised, discretised, timestamped video (streamed)
        ▼
     Storage  ──────────────────────────────────────────────┐
        │                                                     │
        │ video + capture metadata                            │
        ▼                                                     │
 Issue Detection (vision)                                     │
        │ issue instances (typed, located, scored)            │
        ▼                                                     │
 Priority Engine ◀── external signals (car crashes, crime)    │
        │ priority map                                        │
        ├──────────────► Application (review, decide, prompt) │
        ▼                                                     │
 Latent Issue Detection ── selects ROIs ─────────────────────┘
        │ runs VLM over ROI video timestamps
        ▼ latent issue hypotheses
   (back into priority map / application)
```

---

## Repository Principles

Because components are built **in parallel and independently**, the repo is
organized to **counter interface drift across modules**:

- **Monorepo.** All components live in one repository so changes that cross
  module boundaries are visible and reviewable together.
- **Modular development.** Each component is self-contained, owns its own
  responsibilities, and can be developed, run, and tested on its own.
- **Shared contracts.** The data passed *between* modules (e.g. capture
  metadata, issue instances, external signals, priority map, ROIs, latent
  hypotheses) should be defined in a **single shared place** that every module
  depends on — so independent teams stay aligned and interfaces don't silently
  drift apart.

> The concrete monorepo layout, languages, tooling, and the format of the shared
> contracts are **not decided here** — they will be chosen as components come
> online.
