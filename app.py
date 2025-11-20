import time
from flask import Flask, render_template, request
from faker import Faker
import random

app = Flask(__name__)
fake = Faker()


# --- MOCK DATA SERVICE (Simulates a Process Engine DB) ---
class MockDataService:
    def get_process_instance(self, p_id):
        # Simulate DB fetch
        return {
            "id": p_id,
            "name": f"Order_Processing_{p_id}",
            "status": random.choice(["ACTIVE", "COMPLETED", "SUSPENDED"]),
            "startTime": fake.iso8601(),
            "businessKey": fake.bothify(text="ORD-####-????"),
        }

    def get_variables(self, parent_id, scope="process"):
        # Generate 3-5 random variables
        return [
            {"name": "amount", "value": random.randint(100, 5000), "type": "Integer"},
            {"name": "customerName", "value": fake.name(), "type": "String"},
            {
                "name": "isPriority",
                "value": random.choice(["true", "false"]),
                "type": "Boolean",
            },
            {
                "name": "riskLevel",
                "value": random.choice(["Low", "Medium", "High"]),
                "type": "String",
            },
        ]

    def get_user_tasks(self, process_id):
        # Generate 2-4 tasks
        return [
            {
                "id": fake.uuid4(),
                "name": random.choice(
                    ["Approve Order", "Check Inventory", "Validate Fraud", "Ship Goods"]
                ),
                "assignee": fake.first_name(),
                "created": fake.iso8601(),
            }
            for _ in range(random.randint(2, 4))
        ]

    def get_subprocesses(self, process_id):
        # Generate 0-2 subprocesses
        if random.random() > 0.5:
            return []
        return [{"id": fake.uuid4(), "name": "Payment_Subprocess", "status": "ACTIVE"}]

    def get_events(self, parent_id, filter_text=""):
        # Generate list of events
        all_events = [
            {
                "id": fake.uuid4(),
                "type": "PROCESS_STARTED",
                "timestamp": fake.iso8601(),
                "details": "Start event triggered",
            },
            {
                "id": fake.uuid4(),
                "type": "VARIABLE_UPDATED",
                "timestamp": fake.iso8601(),
                "details": "Amount changed",
            },
            {
                "id": fake.uuid4(),
                "type": "USER_TASK_CREATED",
                "timestamp": fake.iso8601(),
                "details": "Task created",
            },
            {
                "id": fake.uuid4(),
                "type": "SERVICE_TASK_FAIL",
                "timestamp": fake.iso8601(),
                "details": "Timeout exception",
            },
        ]

        if filter_text:
            return [
                e
                for e in all_events
                if filter_text.lower() in e["type"].lower()
                or filter_text.lower() in e["details"].lower()
            ]
        return all_events


service = MockDataService()

# --- ROUTES ---


@app.route("/")
def index():
    return render_template("index.html")


# 1. Process Instance Routes
@app.route("/api/process-instance/search")
def search_process():
    p_id = request.args.get("processId")
    if not p_id:
        return '<div class="alert alert-warning">Please enter a Process ID</div>'

    data = service.get_process_instance(p_id)
    return render_template("fragments/process_card.html", process=data)


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
