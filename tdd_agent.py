import argparse
import subprocess
import sys
import re
import os
from langchain_ollama import OllamaLLM

def extract_code(text):
    """Extracts code from markdown code blocks or returns the text itself."""
    match = re.search(r'```(?:typescript|tsx|ts|javascript|js)?\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()

def run_tests(current_working_dir, test_file):
    """Runs tests on the specified test file, streaming output. Returns True if tests FAILED."""
    # We pass CI=true to prevent test runners like vitest or jest from entering watch mode and hanging
    env = dict(os.environ)
    env["CI"] = "true"
    
    process = subprocess.Popen(
        ["npm", "test", test_file, '--prefix', current_working_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env
    )
    
    output_lines = []
    # Stream output line by line
    for line in process.stdout:
        print(line, end="", flush=True)
        output_lines.append(line)
        
    process.wait()
    return process.returncode != 0, "".join(output_lines)


def append_new_test(test_file_path, new_test):
    """
    Appends the new test to the test file.
    It smartly detects the ending brackets '});' of a describe/suite block 
    and inserts the new test right before it.
    """
    with open(test_file_path, 'r') as f:
        content = f.read()

    # Regex to detect the ending '});' (semicolon optional) and optional whitespace at the end of the file
    match = re.search(r'(\}\s*\);?\s*)$', content)
    
    # Check if there is a describe/suite block wrapper to avoid nesting tests 
    # inside a basic top-level test() block like those shown in the README.
    has_wrapper = re.search(r'(?:describe|suite)\s*\(', content)

    if match and has_wrapper:
        closing_sequence = match.group(1)
        # Insert the new test right before the closing sequence
        new_content = content[:-len(closing_sequence)] + "\n\n" + new_test + "\n" + closing_sequence
        with open(test_file_path, 'w') as f:
            f.write(new_content)
    else:
        # Fallback: append at the end of the file
        with open(test_file_path, 'a') as f:
            f.write("\n\n" + new_test + "\n")

    # now that it's appended, run prettier that will reformat the file
    subprocess.run(["npx", "prettier", "--write", test_file_path], capture_output=True, text=True)

def get_prompt(source_code, test_code):
    """Returns a formatted string prompt for the LLM based on the current source and test code."""

    return f"""
    You are an expert Test-Driven Development (TDD) pair programmer.
    Here is the current source code:
    ```typescript
    {source_code}
    ```
    
    Here is the current test code:
    ```typescript
    {test_code}
    ```
    
    Your task is to write exactly ONE new unit test function that tests a new feature, edge case, or logical next step.
    The test is expected to fail with the current source code (the RED phase of TDD).
    How to decide what test to write:
    - Observe the source code carefully; if it has code comments, or a JSDoc comment describing the intended behavior, use that to identify untested behavior.
    - If there are existing tests, look at what they are testing and identify a logical next test that is not yet covered.
    Output ONLY the TypeScript/TSX code for the new test function (e.g., `it('should do something', () => {{ ... }});`).
    Do not include imports or existing code. Do not provide explanations or extra text.
    """

def main():
    parser = argparse.ArgumentParser(description="TDD Pair Programmer Local Agent")
    parser.add_argument("--source_file", help="Path to the source code file")
    parser.add_argument("--test_file", help="Path to the test code file")
    parser.add_argument("--project_home", help="Path to the project home directory (where package.json is located)")
    parser.add_argument("--model", default="qwen2.5:7b", help="Local Ollama model to use (default: qwen2.5:7b)")
    args = parser.parse_args()
    # Basic validation of input files - allow for relative paths
    current_working_dir = args.project_home if args.project_home else os.getcwd()
    source_file_path = os.path.join(current_working_dir, args.source_file)
    test_file_path = os.path.join(current_working_dir, args.test_file)

    if not os.path.exists(source_file_path):
        print("Error: Source file does not exist. Could not find:", source_file_path)
        sys.exit(1)

    if not os.path.exists(test_file_path):
        print("Error: Test file does not exist. Could not find:", test_file_path)
        sys.exit(1)

    # Initialize LangChain Ollama wrapper
    llm = OllamaLLM(model=args.model)

    MAX_ITERATIONS = 5

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- Iteration {iteration}/{MAX_ITERATIONS} ---")
        
        with open(source_file_path, 'r') as f:
            source_code = f.read()
        with open(test_file_path, 'r') as f:
            test_code = f.read()

        prompt = get_prompt(source_code, test_code)
        
        print(f"Asking {args.model} to write a new failing test...")
        try:
            response = llm.invoke(prompt)
        except Exception as e:
            print(f"Error communicating with local Ollama LLM: {e}")
            sys.exit(1)

        new_test = extract_code(response)
        
        # Check if the output looks like a valid test block
        if "test(" not in new_test and "it(" not in new_test:
            print("Unexpected output from LLM. It did not output a valid test function.")
            print("Raw Output:\n", response)
            sys.exit(1)

        print("Received test. Appending to test file and running suite...")
        
        # Append the new test smartly
        append_new_test(test_file_path, new_test)

        # Run tests to check if it's actually red
        print("\nRunning tests...")
        failed, output = run_tests(current_working_dir, test_file_path)

        if failed:
            print("\n✅ Success! A new RED (failing) test is ready for you to implement.")
            sys.exit(0)
        else:
            print("❌ The generated test PASSED with the current code. We need a failing test.")
            print("Keeping the passing test and trying again for a failing one...")
    
    print(f"\nReached maximum of {MAX_ITERATIONS} iterations. The model failed to generate a failing test.")
    sys.exit(1)


if __name__ == "__main__":
    main()
