#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "🚀 Starting Local Environment Setup for Databricks Lakehouse..."

# 1. Create Python Virtual Environment
if [ ! -d ".venv" ]; then
    echo "📦 Creating .venv..."
    python3 -m venv .venv
else
    echo "✅ .venv already exists."
fi

# 2. Activate Virtual Environment and Install Dependencies
echo "🐍 Activating .venv and installing dependencies..."
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

# 3. Create Project Directory Structure
echo "📂 Creating standard folder structure..."
mkdir -p terraform
mkdir -p databricks/src/bronze databricks/src/silver databricks/src/gold

# 4. Create .env from template if it doesn't exist
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

