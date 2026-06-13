from github import Github
import os
import requests

token = os.environ.get("GITHUB_TOKEN")
if not token:
    print("No GITHUB_TOKEN")
    exit(1)

g = Github(token)
repo = g.get_repo("recharts/recharts")
prs = repo.get_pulls(state='open')

for pr in prs:
    labels = [l.name for l in pr.labels]
    if "dependencies" in labels:
        print(f"PR #{pr.number}: {pr.title}")
        commit = pr.get_commits().reversed[0]
        check_runs = commit.get_check_runs()
        for cr in check_runs:
            if cr.conclusion == "failure" and cr.name not in ["Merge VR Reports", "CodeQL Analysis"]:
                print(f"Failed check: {cr.name} ID: {cr.id}")
                # Try getting logs
                url = f"https://api.github.com/repos/recharts/recharts/actions/jobs/{cr.id}/logs"
                headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
                res = requests.get(url, headers=headers, allow_redirects=True)
                print(res.status_code)
                if res.status_code == 200:
                    print(res.text[:200])
                exit(0)
