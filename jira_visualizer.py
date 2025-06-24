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
        return [(issue["key"], issue["fields"]["summary"]) for issue in issues]

    # --- MAIN FLOW ---
    table_data = {}

    # right now we're only getting one board, but I want to switch it to look for all boards eventually
    boards_from_project = get_boards(PROJECT_KEY)
    for board in boards_from_project:
        board_id = board['id']
        board_name = board['name']
        # board_id_and_name = get_board_id_and_name(PROJECT_KEY)
        # result_string = f"Board ID: {board_id_and_name[0]}<br>"
        table_data[board_name] = {}

        sprints = get_sprints(board_id)
        # result_string += f"<br>Found {len(sprints)} sprints:<br>"
        # print(f"\nFound {len(sprints)} sprints:\n")

        for sprint in sprints:
            cur_sprint = []
            # result_string += f"<br>Sprint: {sprint['name']} (ID: {sprint['id']})<br>"
            # print(f"Sprint: {sprint['name']} (ID: {sprint['id']})")
            issues = get_issues_for_sprint(sprint['id'])
            if not issues:
                cur_sprint.append("No issues.")
                # print("  No issues.")
            for key, summary in issues:
                cur_sprint.append(f"  - {key}: {summary}")
                # print(f"  - {key}: {summary}")
            table_data[board_name][sprint['name']] = cur_sprint
        # print(table_data)

    
    # return table_data
    return render_template("results.html", table_data=table_data)

if __name__ == '__main__':
    app.run(debug=True)