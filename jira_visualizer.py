from flask import Flask, request, render_template, redirect, url_for, session
from jira import JIRA
import requests
from requests.auth import HTTPBasicAuth

app = Flask(__name__)
app.secret_key = 'temporary'  # Needed for session storage. TODO: move to env variable for security

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        # Get form data from POST body
        jira_server_url = request.form.get('Jira Server URL')
        jira_api_token = request.form.get('Jira API Token')
        auth_email = request.form.get('Auth User Email')
        project_key = request.form.get('Project Key')

        # Validate server-side
        if not all([jira_server_url, jira_api_token, auth_email, project_key]):
            return "All fields are required", 400

        # Store in session so we can reuse on refresh
        session['form_data'] = {
            'Jira Server URL': jira_server_url,
            'Jira API Token': jira_api_token,
            'Auth User Email': auth_email,
            'Project Key': project_key
        }

        return redirect(url_for('result'))
    return render_template('homepage-form.html')

@app.route('/result', methods=['GET', 'POST'])
def result():
    form_data = session.get('form_data')
    if not form_data:
        return redirect(url_for('home'))

    if request.method == 'POST':
        # On refresh, just re-render using existing session data
        return render_template('result.html', data=form_data)
    
    JIRA_BASE_URL = form_data['Jira Server URL']
    API_TOKEN = form_data['Jira API Token']
    PROJECT_KEY = form_data['Project Key']
    EMAIL = form_data['Auth User Email']
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    headers = {"Accept": "application/json"}

    # --- STEP 1: Get All of the Boards ---
    def get_boards(project_key):
        url = f"{JIRA_BASE_URL}/rest/agile/1.0/board?projectKeyOrId={project_key}"
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        boards = response.json()["values"]
        if not boards:
            raise Exception(f"No boards found for project {project_key}")
        return boards

    # --- STEP 2: Get All Sprints on the Board ---
    ## NOTE: all sprints will appear in the order they appear in Jira, which should be chronological from top to bottom.
    def get_sprints(board_id):
        url = f"{JIRA_BASE_URL}/rest/agile/1.0/board/{board_id}/sprint"
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        return response.json()["values"]

    # --- STEP 3: Get Issues for Each Sprint ---
    def get_issues_for_sprint(sprint_id):
        url = f"{JIRA_BASE_URL}/rest/agile/1.0/sprint/{sprint_id}/issue"
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        issues = response.json()["issues"]
        # print(issues)
        return [(issue["key"], issue["fields"]["summary"], issue['id'], issue) for issue in issues]
    
    def get_sprint_id(issue):
        sprint_field = issue["fields"].get("customfield_10007")
        # print(f'sprint field: {sprint_field}')
        if isinstance(sprint_field, list) and sprint_field:
            if isinstance(sprint_field[-1], dict):
                return sprint_field[-1].get("id")
            elif isinstance(sprint_field[-1], str):
                match = re.search(r"id=(\d+)", sprint_field[-1])
                if match:
                    return int(match.group(1))
        return None

    def add_sprint_order_to_map(sprints_from_board):
        """ there are two issues to account for here, and why we need to create this map: 
            1. jira users may not input sprint start and end dates for proper ordering
            2. jira users may rearrange sprints on a whim, which would break ordering by id
            luckily the order of the sprints in the board is the order the sprints are occurring
            so to check if an issue/task is in the correct order we need to map each sprint id to a value
            and the value will just be the order it appears in the sprint count."""
        sprint_order = 0
        for sprint in sprints_from_board:
            sprint_order_map[sprint['id']] = sprint_order
            issues = get_issues_for_sprint(sprint['id'])
            for issue in issues:
                # print(issue)
                issue_order_map[issue[2]] = (sprint_order, sprint['id'])
            sprint_order += 1

    sprint_table_data = {}
    conflict_table_data = {
        'conflicts': set(),
        'internal': set(),
        'external': set()
    }
    sprint_order_map = {}
    issue_order_map = {}
    
    boards_from_project = get_boards(PROJECT_KEY)
    # two loops through the boards are necessary:
    # loop 1 lets us see the order of the sprints
    # loop 2 will then allow us to add all our data, and figure out which issues are not in order
    for board in boards_from_project:
        board_id = board['id']
        sprints = get_sprints(board_id)
        add_sprint_order_to_map(sprints)

    for board in boards_from_project:
        board_id = board['id']
        board_name = board['name']
        # board_id_and_name = get_board_id_and_name(PROJECT_KEY)
        sprint_table_data[board_name] = {}

        sprints = get_sprints(board_id)
        # print(f"\nFound {len(sprints)} sprints:\n")

        for sprint in sprints:
            cur_sprint = []
            # print(f"Sprint: {sprint['name']} (ID: {sprint['id']})")
            issues = get_issues_for_sprint(sprint['id'])
            if not issues:
                cur_sprint.append("No issues.")
                # print("  No issues.")
            for key, summary, cur_issue_id, issue in issues:
                cur_issue_sprint_order, cur_issue_sprint_id = issue_order_map[cur_issue_id]
                # TODO: create a more detailed way of documenting the issue, might create a class here so that we can make "sticky notes" on the board with all relevant information
                cur_sprint.append(f"  - {key}: {summary}")
                # print(f"  - {key}: {summary}")

                for link in issue.get("fields", {}).get("issuelinks", []):
                    if "inwardIssue" in link:
                        # if there's an inward issue that means something comes before this
                        inward_issue_type = link['type']['inward']
                        blocker = link["inwardIssue"]
                        blocker_issue_id = blocker['id']
                        blocker_issue_sprint_order, blocker_issue_sprint_id = issue_order_map.get(blocker_issue_id, (float('inf'), float('inf')))

                        problem_tuple = (issue['key'], issue['fields']['summary'], cur_issue_id, cur_issue_sprint_order, cur_issue_sprint_id, inward_issue_type, blocker['key'], blocker['fields']['summary'], blocker_issue_id, blocker_issue_sprint_order, blocker_issue_sprint_id)
                        if blocker_issue_sprint_order == cur_issue_sprint_order:
                            if cur_issue_sprint_id == blocker_issue_sprint_id:
                                # same sprint means same board, so it's an internal dependency
                                conflict_table_data['internal'].add(problem_tuple)
                            else:
                                conflict_table_data['external'].add(problem_tuple)
                        elif blocker_issue_sprint_order > cur_issue_sprint_order:
                            conflict_table_data['conflicts'].add(problem_tuple)
        # # print(table_data)

    
    # return table_data
    return render_template("results.html", sprint_table_data=sprint_table_data, conflict_table_data=conflict_table_data) #sprint order map is placeholder, we'll fill up the conflict data soon, just testing that this works first

if __name__ == '__main__':
    app.run(debug=True)