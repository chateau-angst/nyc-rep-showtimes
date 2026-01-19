name: Fetch Film Forum

on:
  workflow_dispatch:
  schedule:
    - cron: "15 10 * * *" # daily 10:15 UTC

permissions:
  contents: write

jobs:
  fetch:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          persist-credentials: true
          fetch-depth: 0

      - name: Debug repo layout
        run: |
          pwd
          ls -la
          ls -la scripts || true
          ls -la docs || true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Fetch Film Forum JSON
        env:
          FILMFORUM_SOURCE_URL: "https://filmforum.org/now_playing"
        run: |
          python scripts/fetch_filmforum.py

      - name: Commit and push updated JSON
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"

          git add docs/filmforum.json

          # If nothing changed, exit cleanly
          git diff --cached --quiet && echo "No changes to commit" && exit 0

          git commit -m "Update Film Forum showtimes"

          # Push to the branch that triggered the workflow
          git push origin HEAD:${GITHUB_REF_NAME}
