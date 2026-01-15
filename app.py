import time
from flask import Flask, render_template, request
from faker import Faker
import random
import requests
from typing import Optional, Dict, Any
import logging

app = Flask(__name__)
fake = Faker()

ACTIVITI_HOST_URL = "http://host.docker.internal"
QUERY_SERVICE_URL = f"{ACTIVITI_HOST_URL}/query/admin/v1"
RB_APPROVAL_WORKFLOW_SERVICE_URL = f"{ACTIVITI_HOST_URL}/rb-approval-workflow/admin/v1"


class OAuth2Manager:
    """
    Manages OAuth2 Client Credentials flow token lifecycle.
    Auto-refreshes token if expired.
    """

    def __init__(
        self, token_url: str, client_id: str, client_secret: str, scope: str = None
    ):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self._access_token = None
        self._token_expiry = 0

    def _fetch_new_token(self):
        """Fetches a new access token from the provider."""
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        if self.scope:
            payload["scope"] = self.scope

        try:
            response = requests.post(self.token_url, data=payload)
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            # Set expiry time (subtract 60s buffer to be safe)
            expires_in = data.get("expires_in", 3600)
            self._token_expiry = time.time() + expires_in - 60
            print("DEBUG: New OAuth2 token fetched successfully.")

        except requests.RequestException as e:
            print(f"ERROR: Failed to obtain OAuth2 token: {e}")
            raise

    def get_token(self) -> str:
        """Returns a valid access token, refreshing if necessary."""
        if not self._access_token or time.time() >= self._token_expiry:
            self._fetch_new_token()
        return self._access_token


auth_manager = OAuth2Manager(
    token_url=f"{ACTIVITI_HOST_URL}/auth/realms/activiti/protocol/openid-connect/token",
    client_id="core-workflow-service",
    client_secret="cf66490b-1ca0-42cb-b089-af4f9450f23d",
)


def make_secure_request(
    method: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> requests.Response:
    """
    Generic function to make HTTP calls with automatic OAuth2 Bearer Token attachment.

    Args:
        method (str): HTTP method (GET, POST, PUT, DELETE, etc.)
        endpoint (str): Full URL or relative path.
        params (dict): Query parameters.
        payload (dict): JSON body for POST/PUT.
        headers (dict): Custom headers.
        timeout (int): Request timeout in seconds.

    Returns:
        requests.Response: The response object.
    """

    # 1. Get Valid Token
    try:
        token = auth_manager.get_token()
    except Exception as e:
        raise RuntimeError(f"Authentication failed: {str(e)}")

    # 2. Prepare Headers
    if headers is None:
        headers = {}

    # Attach Bearer Token
    headers["Authorization"] = f"Bearer {token}"

    # Ensure Content-Type is JSON if payload exists and not set otherwise
    if payload and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    # 3. Execute Request
    try:
        response = requests.request(
            method=method.upper(),
            url=endpoint,
            params=params,
            json=payload,  # Using 'json' parameter automatically serializes dict
            headers=headers,
            timeout=timeout,
        )

        # Optional: Raise error for 4xx or 5xx status codes immediately
        # response.raise_for_status()

        return response

    except requests.RequestException as e:
        print(f"HTTP Request failed: {e}")
        raise


class ActivitiService:
    def get_process_instance(self, process_instance_id):
        display_keys = [
            "id",
            "appName",
            "processDefinitionKey",
            "processDefinitionName",
            "processDefinitionVersion",
            "status",
            "startDate",
            "lastModified",
        ]
        try:
            response = make_secure_request(
                method="GET",
                endpoint=f"{QUERY_SERVICE_URL}/process-instances/{process_instance_id}",
            )
            data = response.json()
            return {k: v for k, v in data.items() if k in display_keys}
        except Exception as e:
            print(f"Error fetching process instance: {e}")
            return None

    def get_variables(self, parent_id, scope="process"):
        display_keys = ["name", "type", "value", "createTime", "lastUpdatedTime"]
        # Note that value can be a string, number or a JSON object
        try:
            response = make_secure_request(
                method="GET",
                endpoint=(
                    f"{QUERY_SERVICE_URL}/process-instances/{parent_id}/variables?size=1000"
                    if scope == "process"
                    else f"{QUERY_SERVICE_URL}/tasks/{parent_id}/variables?size=1000"
                ),
            )
            data = response.json().get("_embedded", {}).get("variables", [])
            return [{k: v for k, v in d.items() if k in display_keys} for d in data]
        except Exception as e:
            print(f"Error fetching variables: {e}")
            return None

    def get_user_tasks(self, process_instance_id):
        display_keys = [
            "id",
            "name",
            "taskDefinitionKey",
            "status",
            "assignee",
            "createdDate",
            "lastModified",
        ]
        try:
            response = make_secure_request(
                method="GET",
                endpoint=f"{QUERY_SERVICE_URL}/tasks?size=1000&processInstanceId={process_instance_id}",
            )
            data = response.json().get("_embedded", {}).get("tasks", [])
            return [{k: v for k, v in d.items() if k in display_keys} for d in data]
        except Exception as e:
            print(f"Error fetching user tasks: {e}")
            return None

    def get_subprocesses(self, process_instance_id):
        display_keys = [
            "id",
            "appName",
            "processDefinitionKey",
            "processDefinitionVersion",
            "status",
            "startDate",
            "lastModified",
        ]
        try:
            response = make_secure_request(
                method="GET",
                endpoint=f"{ACTIVITI_HOST_URL}/query/v1/process-instances/{process_instance_id}/subprocesses?size=1000",
            )
            data = response.json().get("_embedded", {}).get("processInstances", [])
            return [{k: v for k, v in d.items() if k in display_keys} for d in data]
        except Exception as e:
            print(f"Error fetching subprocesses: {e}")
            return None

    def get_events(self, parent_id, filter_text=""):
        display_keys = ["id", "entityId", "sequenceNumber", "eventType", "entity"]
        try:
            endpoint = f"{ACTIVITI_HOST_URL}/audit/v1/events?size=1000&sort=timestamp,sequenceNumber&search=processInstanceId:{parent_id}"
            if filter_text:
                endpoint += f"&search={filter_text}"
            response = make_secure_request(
                method="GET",
                endpoint=endpoint,
            )
            print(endpoint)
            data = response.json().get("_embedded", {}).get("events", [])
            return [{k: v for k, v in d.items() if k in display_keys} for d in data]
        except Exception as e:
            print(f"Error fetching events: {e}")
            return None


service = ActivitiService()

# --- ROUTES ---


@app.route("/")
def index():
    return render_template("index.html")


# 1. Process Instance Routes
@app.route("/api/process-instance/search")
def search_process():
    process_instance_id = request.args.get("processId")
    is_nested = request.args.get("nested", "false").lower() == "true"
    if not process_instance_id:
        return '<div class="alert alert-warning">Please enter a Process ID</div>'

    data = service.get_process_instance(process_instance_id)
    return render_template(
        "fragments/process_card.html", process=data, nested=is_nested
    )


@app.route("/api/process-instance/<pid>/variables")
def get_process_variables(pid):
    vars = service.get_variables(pid, "process")
    return render_template(
        "fragments/variable_list.html", variables=vars, parent_id=pid, scope="Process"
    )


@app.route("/api/process-instance/<pid>/subprocesses")
def get_subprocesses(pid):
    subs = service.get_subprocesses(pid)
    return render_template(
        "fragments/subprocess_list.html", subprocesses=subs, parent_id=pid
    )


@app.route("/api/process-instance/<pid>/tasks")
def get_process_tasks(pid):
    tasks = service.get_user_tasks(pid)
    return render_template("fragments/task_list.html", tasks=tasks, parent_id=pid)


# 2. Task Routes
@app.route("/api/tasks/<tid>/variables")
def get_task_variables(tid):
    vars = service.get_variables(tid, "task")
    return render_template(
        "fragments/variable_list.html", variables=vars, parent_id=tid, scope="Task"
    )


# 3. Generic Event Route (Used by both Process and Task)
@app.route("/api/<scope>/<id>/events")
def get_events(scope, id):
    # HTMX sends inputs inside the enclosing form/div as parameters.
    # We look for 'filter_text'
    filter_val = request.args.get("filter_text", "")
    events = service.get_events(id, filter_val)
    return render_template(
        "fragments/event_list.html",
        events=events,
        parent_id=id,
        filter_val=filter_val,
        scope=scope,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
