import argparse
import json
import os
import sys
import subprocess

import github.Auth
import requests
import re
from github import Github
from langchain_ollama import OllamaLLM

def extract_bash(text):
    """Extracts bash code from markdown code blocks."""
    match = re.search(r'```(?:bash|sh)\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""

def get_job_logs(token, repo_name, job_id):
    """Fetches job logs from GitHub API."""
    url = f"https://api.github.com/repos/{repo_name}/actions/jobs/{job_id}/logs"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
    res = requests.get(url, headers=headers, allow_redirects=True)
    if res.status_code == 200:
        return res.text
    else:
        return ""

def run_bash_script(script, cwd):
    """Runs a bash script in a subprocess and returns (returncode, stdout)."""
    process = subprocess.Popen(
        ["bash", "-c", script],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    stdout, _ = process.communicate()
    return process.returncode, stdout

def summarize_logs(llm, logs):
    """Asks the LLM to summarize the build logs."""
    tail_logs = "\n".join(logs.split("\n")[-500:])
    prompt = f"Summarize the following build logs and identify the error that caused the failure:\n\n```\n{tail_logs}\n```\nProvide a concise summary."
    return llm.invoke(prompt)

def read_npm_scripts(project_home):
    """Reads the npm scripts from package.json."""
    package_json_path = os.path.join(project_home, "package.json")
    if not os.path.exists(package_json_path):
        return ""
    with open(package_json_path, 'r') as f:
        package_json = json.load(f)
        return json.dumps(package_json.get("scripts", {}), indent=2)

def generate_reproduction_steps(llm, summary, developing_md, npm_scripts):
    """Asks the LLM to provide a step-by-step guide to reproduce the failure."""
    prompt = f"""
The following is a summary of a CI build failure:
{summary}

Here are the contents of DEVELOPING.md for reference:
```
{developing_md}
```

You are now in the project home directory, with `package.json` available. The appropriate branch is checked out and dependencies are freshly installed.
Here are all available npm scripts:
{npm_scripts}
Provide a shell command that allows us to reproduce the build failure locally.
Output EXACTLY one bash script inside a ```bash ... ``` code block that reproduces the failure (e.g. running a specific npm build or test command). The command must return a non-zero exit code if the issue is reproduced.
Do not include any interactive commands.

Example output 1:
```bash
npm run build
```

Example output 2:
```bash
npm run test -- test/util/createChartHelpers.spec.tsx
```

Example output 3:
```bash
npm run check-types
```
"""
    return llm.invoke(prompt)

def generate_fix_suggestions(llm, summary, reproduction_output):
    """Asks the LLM to provide a bash script to fix the issue."""
    prompt = f"""
The issue was reproduced locally.
Summary of the failure: {summary}
Output of the reproduction step:
```
{reproduction_output}
```

Generate a bash script to fix the build. You must use tools like `sed`, `awk`, or `echo` to modify the local repository code. 
Output EXACTLY one bash script inside a ```bash ... ``` code block that fixes the issue.
Do not include any interactive commands.
"""
    return llm.invoke(prompt)

def setup_worktree(project_home, branch_name):
    """Creates a new git worktree for the given branch."""
    worktree_path = os.path.join(project_home, f"worktree-{branch_name}")
    if os.path.exists(worktree_path):
        subprocess.run(["rm", "-rf", worktree_path])
        subprocess.run(["git", "worktree", "prune"], cwd=project_home)
    
    res = subprocess.run(["git", "worktree", "add", worktree_path, branch_name], cwd=project_home, capture_output=True, text=True)
    if res.returncode != 0:
        raise Exception(f"Failed to create worktree: {res.stderr}")
    return worktree_path

def get_dependabot_prs(repo):
    """Fetches open dependabot PRs from the repository."""
    prs = repo.get_pulls(state='open')
    dependabot_prs = []
    for pr in prs:
        labels = [l.name for l in pr.labels]
        if "dependencies" in labels or pr.user.login == "dependabot[bot]":
            dependabot_prs.append(pr)
    return dependabot_prs

def get_failed_check(pr):
    """Finds the first relevant failed check for the PR."""
    commit = pr.get_commits().reversed[0]
    check_runs = commit.get_check_runs()
    for cr in check_runs:
        if cr.conclusion == "failure" and cr.name not in ["Merge VR Reports", "CodeQL Analysis"]:
            return cr
    return None

def attempt_reproduction(llm, summary, developing_md, worktree_dir, npm_scripts):
    """Attempts to reproduce the failure locally."""
    for attempt in range(1, 4):
        print(f"Asking LLM for reproduction steps (Attempt {attempt}/3)...")
        response = generate_reproduction_steps(llm, summary, developing_md, npm_scripts)
        script = extract_bash(response)
        if not script:
            print("LLM did not provide a valid bash script.")
            continue
        
        print("Running reproduction script:")
        print(script)
        retcode, stdout = run_bash_script(script, worktree_dir)
        
        if retcode != 0:
            print("Failure reproduced locally!")
            return True, stdout, script
        else:
            print("Script exited with 0. The issue was NOT reproduced.")
            
    return False, "", ""

def attempt_fix(llm, summary, reproduction_script, reproduction_output, worktree_dir):
    """Attempts to fix the build locally."""
    for attempt in range(1, 4):
        print(f"\nAsking LLM for fix suggestions (Attempt {attempt}/3)...")
        response = generate_fix_suggestions(llm, summary, reproduction_output)
        fix_script = extract_bash(response)
        
        if not fix_script:
            print("LLM did not provide a valid bash script.")
            continue
        
        print("Applying fix script:")
        print(fix_script)
        run_bash_script(fix_script, worktree_dir)
        
        print("Running reproduction script again to verify fix...")
        retcode, stdout = run_bash_script(reproduction_script, worktree_dir)
        
        if retcode == 0:
            print("✅ Success! The build is fixed.")
            return True
        else:
            print("❌ The build is still failing. Trying another suggestion...")
            
    return False

def process_pr(pr, token, args, llm, developing_md, npm_scripts):
    """Processes a single PR."""
    print(f"\nProcessing PR #{pr.number}: {pr.title}")
    
    failed_cr = get_failed_check(pr)
    if not failed_cr:
        print("No relevant failed checks found.")
        return

    print(f"Found failed check: {failed_cr.name} (ID: {failed_cr.id})")
    logs = get_job_logs(token, args.repo, failed_cr.id)
    if not logs:
        print("Could not fetch logs for this check.")
        return
    
    print("Summarizing build logs...")
    summary = summarize_logs(llm, logs)
    print("--- SUMMARY ---")
    print(summary)
    print("---------------")

    print("Setting up worktree...")
    branch_name = pr.head.ref
    try:
        subprocess.run(["git", "fetch", "origin", f"pull/{pr.number}/head:{branch_name}"], cwd=args.project_home, capture_output=True)
        worktree_dir = setup_worktree(args.project_home, branch_name)
        # print the worktree directory
        print("Set up a new worktree in ", worktree_dir, " with branch ", branch_name, " and commit ", pr.head.sha, "")
    except Exception as e:
        print(f"Error setting up worktree: {e}")
        return

    try:
        print("Running npm install and npm run build in worktree...")
        subprocess.run(["npm", "install"], cwd=worktree_dir, capture_output=True, check=True)
        subprocess.run(["npm", "run", "build"], cwd=worktree_dir, capture_output=True)

        reproduced, reproduction_output, reproduction_script = attempt_reproduction(llm, summary, developing_md, worktree_dir, npm_scripts)
        
        if not reproduced:
            print("Could not reproduce the issue locally after 3 attempts.")
            return

        fixed = attempt_fix(llm, summary, reproduction_script, reproduction_output, worktree_dir)
        
        if not fixed:
            print("Could not fix the build after 3 suggestions.")
            return
            
    finally:
        print(f"Cleaning up worktree {worktree_dir}...")
        subprocess.run(["rm", "-rf", worktree_dir])
        subprocess.run(["git", "worktree", "prune"], cwd=args.project_home)

def parse_args():
    parser = argparse.ArgumentParser(description="Dependabot Build Failure Debugger")
    parser.add_argument("--project_home", required=True, help="Path to the root of the repository")
    parser.add_argument("--repo", default="recharts/recharts", help="GitHub repository name (e.g., recharts/recharts)")
    parser.add_argument("--model", default="qwen2.5:7b", help="Local Ollama model to use")
    return parser.parse_args()

def main():
    args = parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set.")
        sys.exit(1)

    auth = github.Auth.Token(token);
    g = Github(auth=auth)
    repo = g.get_repo(args.repo)
    print(f"Fetching open PRs for {args.repo}...")
    
    dependabot_prs = get_dependabot_prs(repo)
    if not dependabot_prs:
        print("No open dependabot PRs found.")
        sys.exit(0)

    llm = OllamaLLM(model=args.model)

    project_home = args.project_home

    developing_md = read_developing_md(project_home)

    npm_scripts = read_npm_scripts(project_home)

    for pr in dependabot_prs:
        process_pr(pr, token, args, llm, developing_md, npm_scripts)


def read_developing_md(project_home) -> str:
    """Reads the DEVELOPING.md file from the project home directory."""
    developing_md_path = os.path.join(project_home, "DEVELOPING.md")
    developing_md = ""
    if os.path.exists(developing_md_path):
        with open(developing_md_path, 'r') as f:
            developing_md = f.read()
    return developing_md


if __name__ == "__main__":
    main()
