#!/bin/bash

# ==============================================================================
# Local dev bootstrapper.
#
# Creates TWO isolated environments because their dependencies conflict:
#   .venv          — the local test/CI environment (requirements-dev.txt:
#                    real pyspark + pytest + ruff). This is what the Makefile
#                    and `make test` use.
#   .venv-connect  — OPTIONAL (--connect flag): the Databricks Connect
#                    environment (requirements.txt). databricks-connect shadows
#                    a plain pyspark install, so it must never share an env
#                    with the test suite.
# ==============================================================================

set -e

echo "🚀 Starting Local Environment Setup for the Fleet Risk Lakehouse..."

# 1. Test/CI environment (.venv) — what `make test` / `make check` use.
if [ ! -d ".venv" ]; then
    echo "📦 Creating .venv (local test environment)..."
    python3 -m venv .venv
else
    echo "✅ .venv already exists."
fi
echo "🐍 Installing test dependencies (requirements-dev.txt) into .venv..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements-dev.txt
echo "   ℹ️  Local Spark tests need Java 17 on PATH (see docs/TESTING.md)."

# 2. Optional Databricks Connect environment (.venv-connect), kept separate.
if [ "$1" == "--connect" ]; then
    if [ ! -d ".venv-connect" ]; then
        echo "📦 Creating .venv-connect (Databricks Connect environment)..."
        python3 -m venv .venv-connect
    fi
    echo "🐍 Installing Databricks tooling (requirements.txt) into .venv-connect..."
    .venv-connect/bin/python -m pip install --quiet --upgrade pip
    .venv-connect/bin/python -m pip install --quiet -r requirements.txt
else
    echo "⏭️  Skipping the Databricks Connect env (run './setup.sh --connect' to create it)."
fi

# 3. Create .env from template if it doesn't exist
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "📝 Creating .env from template (.env.example)..."
        cp .env.example .env
        echo "⚠️  Action Required: Open your .env file and fill in your real credentials!"
    else
        echo "❌ Error: .env.example file not found. Cannot create .env!"
    fi
else
    echo "✅ .env file already exists."
fi

echo "✅ Setup complete. Try: make check"
