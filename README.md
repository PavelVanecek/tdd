# TDD Pair Programmer Agent

This project is a simple local AI agent acting as your pair programmer for Test-Driven Development (TDD). It uses LangChain to connect to a local LLM running on [Ollama](https://ollama.com/), reads your current source and test files (TypeScript / TSX), and writes a new failing test (the RED phase of TDD).

## Prerequisites

1. Python 3.9+
2. Node.js
3. [Ollama](https://ollama.com/) installed and running locally.
4. You need to have an Ollama model pulled. By default, the script uses `qwen2.5:7b`, but you can use `codellama`, `phi3`, etc.
   ```bash
   ollama pull llama3
   ```

## Setup

A Python virtual environment is highly recommended. The dependencies include `langchain` and `langchain-community`.

```bash
# 1. Create a virtual environment
python3 -m venv venv

# 2. Activate the virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## How It Works

1. The script accepts two paths: your source file and your test file.
2. It sends the contents of both files to the local LLM.
3. The LLM is instructed to write **exactly one new failing test**.
4. The script parses the output, appends the generated test to the test file, and runs tests via `npm test`.
5. If the new test **fails**, the script stops and lets you know a new RED test is ready for you to make green.
6. If the new test **passes**, the script keeps the passing test (as it is still valuable), reports that the model wrote a passing test, and tries again for a failing one (up to 5 iterations).
7. If the model outputs something unexpected or malformed, the agent aborts immediately.

## Usage

Create your basic files first. For example:

`MathOps.ts`:
```typescript
export function add(a: number, b: number) {
    return a + b;
}
```

`MathOps.test.ts`:
```typescript
import { test, expect } from 'vitest';
import { add } from './MathOps';

test('adds numbers correctly', () => {
    expect(add(1, 2)).toBe(3);
});
```

Then, run the agent:

```bash
# Activate your virtual environment first!
source venv/bin/activate
```

```bash
# Run the agent
python tdd_agent.py \
  --project_home="${HOME}/github/recharts" \
  --source_file='src/animation/RechartsAnimation.ts' \
  --test_file='test/animation/RechartsAnimation.spec.ts'
```

### Optional Arguments
You can specify a different Ollama model using the `--model` flag:
```bash
python tdd_agent.py \
  --project_home="${HOME}/github/recharts" \
  --source_file='src/animation/RechartsAnimation.ts' \
  --test_file='test/animation/RechartsAnimation.spec.ts' \
  --model='codellama:7b'
```
