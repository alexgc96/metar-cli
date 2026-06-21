# Contributing to metar-cli
 
Thanks for your interest in contributing! metar-cli is a small open-source tool and contributions of all kinds are welcome.
 
---
 
## Before You Start
 
Please open an issue before submitting a PR. This keeps things from going sideways — if you spend time on something that turns out to be out of scope or already in progress, that's a waste for everyone. A quick issue first lets us align before you write any code.
 
---
 
## Bug Reports
 
If you found a bug, open an issue and include:
 
- Your OS and Python version
- The metar-cli version (`metar-cli --version`)
- The ICAO station code you were querying, if relevant
- The full error output or unexpected behavior
- Steps to reproduce
The more specific you are, the faster it gets fixed.
 
---
 
## Code Contributions
 
1. Open an issue describing what you want to change and why
2. Wait for a response before starting work — this avoids duplicate effort
3. Fork the repo and create a branch from `master`
4. Make your changes, keeping the code style consistent with the rest of the project
5. Test your changes locally — set up a virtualenv and install in editable mode:
```
   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -e .
```
   Changes to the source are reflected immediately without reinstalling.

6. Open a PR referencing the issue number
 
Keep PRs focused — one fix or feature per PR makes review much easier.
 
---
 
## Documentation Improvements
 
Typos, unclear instructions, missing examples — all fair game. For small fixes you can open a PR directly without an issue first.
 
---
 
## Code Style
 
- Follow [PEP 8](https://peps.python.org/pep-0008/)
- Keep the CLI feel consistent — this is a terminal tool for aviation nerds, not a web app
- Avoid adding heavy dependencies; `rich`, `requests`, and `prompt_toolkit` are already in scope
---
 
## Questions
 
Not sure if something is a bug or a feature? Just open an issue and ask. No formal process required for questions.
