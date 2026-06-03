# AI Code Review Assistant

An AI-powered developer tool that automatically reviews GitHub pull requests, analyzes code diffs using Google's Gemini models, identifies potential bugs, security vulnerabilities, performance concerns, and code quality issues, then posts structured review feedback directly on the pull request.

## Features

* GitHub Pull Request webhook integration
* Automated code diff analysis
* AI-generated review comments using Gemini
* Structured issue categorization
* Security vulnerability detection
* Bug and edge-case identification
* PostgreSQL-backed review history
* Alembic database migrations
* FastAPI backend architecture
* Extensible review pipeline for future dashboard and analytics support

## Tech Stack

### Backend

* FastAPI
* Python
* SQLAlchemy
* PostgreSQL
* Alembic
* Pydantic

### AI

* Google Gemini 2.5 Flash
* LangChain

### Integrations

* GitHub Webhooks
* GitHub REST API

## Workflow

GitHub Pull Request → Webhook Trigger → Diff Extraction → AI Analysis → Database Storage → GitHub Review Comment

This project aims to streamline code reviews by providing instant AI-powered feedback to developers during the pull request process.
