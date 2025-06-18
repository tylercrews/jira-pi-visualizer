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

    # --- STEP 1: Get Board ID ---
    def get_board_id(project_key):
        url = f"{JIRA_BASE_URL}/rest/agile/1.0/board?projectKeyOrId={project_key}"
        response = requests.get(url, headers=headers, auth=auth)
        response.raise_for_status()
        boards = response.json()["values"]
        if not boards:
            raise Exception(f"No boards found for project {project_key}")
        return boards[0]["id"]

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
    board_id = get_board_id(PROJECT_KEY)
    result_string = f"Board ID: {board_id}<br>"
    # print(f"Board ID: {board_id}")

    sprints = get_sprints(board_id)
    result_string += f"<br>Found {len(sprints)} sprints:<br>"
    # print(f"\nFound {len(sprints)} sprints:\n")

    for sprint in sprints:
        result_string += f"<br>Sprint: {sprint['name']} (ID: {sprint['id']})<br>"
        # print(f"Sprint: {sprint['name']} (ID: {sprint['id']})")
        issues = get_issues_for_sprint(sprint['id'])
        if not issues:
            result_string += "  No issues.<br>"
            # print("  No issues.")
        for key, summary in issues:
            result_string += f"  - {key}: {summary}<br>"
            # print(f"  - {key}: {summary}")
        # print()

    
    # temporary return
    return result_string

    # work in progress - we'll be using a template and formatted data as we figure that out
    # return render_template('result.html', data=form_data)

if __name__ == '__main__':
    app.run(debug=True)