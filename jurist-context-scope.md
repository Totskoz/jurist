# Jurist — Project Context and Scope

## Context

This is a portfolio project I'm building in preparation for an interview at DAS (Dutch rechtsbijstandsverzekeraar) for an AI engineer role. It is a demo artifact, not production software. The purpose is to show how I think about building multi-agent AI systems in a legal domain. The audience is senior AI engineers who will judge design reasoning and execution quality in a live walkthrough.

## What I Want to Build

A multi-agent system that answers Dutch legal questions with grounded citations, backed by a knowledge graph of statutes and a vector store of case law. The system's reasoning is visible — the frontend shows the KG animating as the system traverses it, and the agents stream their thinking live as they work. One legal question comes in, a grounded answer comes out with clickable citations, and the interviewer can watch the reasoning unfold.

The agents I have in mind:
- A **decomposer** that breaks the question into legal concepts and sub-questions.
- A **statute retriever** that traverses the knowledge graph to find relevant wetsartikelen.
- A **case retriever** that does vector search over past rechtspraak.
- A **synthesizer** that composes a grounded answer in Dutch with inline citations.

Two Dutch legal data sources: **wetten.overheid.nl** for statutes (BWB XML, article-level granularity, cross-references) and **rechtspraak.nl** for case law (ECLI-indexed uitspraken from huurcommissie and rechtbanken).

## Target Demo Flow

One question is locked as the north star: *"Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"*

What the interviewer should see, in order:
1. KG panel renders huurrecht articles as nodes with cross-references as edges.
2. User submits the question.
3. Decomposer streams its thinking into a trace panel.
4. Statute retriever activates — KG nodes light up as articles are traversed (art. 7:248 BW and related), edges animate as cross-references are followed.
5. Case retriever runs vector search — top-3 similar rechtspraak appear with ECLI numbers and similarity scores.
6. Synthesizer produces a structured Dutch answer: *korte conclusie → relevante wetsartikelen → vergelijkbare uitspraken → aanbeveling.* Citations are clickable and resolve to the source.
7. Total runtime under ~30 seconds.

Every citation in the output must resolve to a real indexed document. No hallucinated artikel-nummers, no invented ECLIs.

## In Scope

- One rechtsgebied: **huurrecht**. Boek 7 Titel 4 BW plus directly relevant regelingen (Uitvoeringswet huurprijzen woonruimte, etc.).
- Four agents chained end-to-end.
- Real knowledge graph built from wetten.overheid.nl BWB XML.
- Real vector store of huurrecht case law from rechtspraak.nl — on the order of a few hundred recent cases, not exhaustive.
- Two-panel frontend: KG on one side, streaming agent trace on the other. Final synthesis rendered below with clickable citation links.
- Local dev only.

## Out of Scope

- Other rechtsgebieden (arbeidsrecht, consumentenrecht, verkeersrecht).
- A real **validator agent** — stub it, return valid always. Interface stays so it can be built in v2.
- A **KG maintainer agent** — the KG is built by an offline ingestion script, not a live agent. Do not frame the ingestion script as an agent.
- User auth, accounts, query history, persistence of past queries.
- Evaluation harness / golden dataset.
- Deployment. Local only.
- Multiple demo questions. One question drives v1; a second can come in polish if time allows.

## Non-Goals

- This is not a production legal tool. One small footer disclaimer is enough; do not bureaucratize the UI.
- This is not an agent framework exploration. Direct LLM calls with structured outputs. No LangChain / LangGraph / CrewAI / AutoGen.
- This is not a general legal assistant. Huurrecht only.

## Working Principles

- **End-to-end first.** A hardcoded path from question → fake agents → fake KG → rendered answer must work before any real integration. Replace fakes one at a time.
- **The locked demo question is the north star.** If a decision doesn't serve this one question, it's v2.
- **Ship ugly.** Default styling is fine. Polish comes last.
- **Ask before expanding scope.** If something outside the "in scope" list looks necessary, stop and surface it. Do not silently add.
- **Don't mock what you should integrate.** Real LLM API, real data sources, real vector DB. Only the validator is a stub by design.

## What I Want From You

Before writing code, propose the full structure:
- Tech stack choices with brief reasoning.
- Repository and file layout.
- Agent contracts / interfaces.
- How you'd sequence the work into milestones, with a clear definition of "done" for v1.
- Any open questions or assumptions you'd want me to confirm.

I'd rather argue about the plan up front than rewrite later. Surface choices explicitly so I can push back before you start implementing.
