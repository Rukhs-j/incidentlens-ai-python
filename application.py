from fastapi import Depends
from core import User, Problem, current_user
from factory import make_application
from services import SCHEMA, Service, LogInput, StatusInput, seed


def register(app, db, kb, service):
    @app.post("/api/logs")
    def ingest(body: LogInput, user: User = Depends(current_user)):
        user.require_staff()
        return service.ingest(body.lines,user.username)

    @app.get("/api/incidents")
    def incidents(user: User = Depends(current_user)):
        user.require_staff()
        return db.rows("SELECT * FROM incidents ORDER BY OCCURRENCES DESC,LAST_SEEN DESC LIMIT 200")

    @app.patch("/api/incidents/{incident_id}")
    def update(incident_id: str, body: StatusInput, user: User = Depends(current_user)):
        user.require_staff()
        return service.update(incident_id,body.status,user.username)

    @app.post("/api/incidents/{incident_id}/explain")
    def explain(incident_id: str, user: User = Depends(current_user)):
        user.require_staff()
        incident = db.one("SELECT * FROM incidents WHERE ID=?", (incident_id,))
        if not incident:
            raise Problem(404,"Incident not found")
        return {"diagnosisConfirmed": False, "result": kb.ask("public",incident["EXAMPLE"])}

    @app.get("/api/incidents/{incident_id}/history")
    def history(incident_id: str, user: User = Depends(current_user)):
        user.require_staff()
        return db.rows("SELECT * FROM incident_events WHERE INCIDENT_ID=? ORDER BY CREATED_AT", (incident_id,))


def create_app(db_path=None, ai_mode=None, enable_worker=True, ai_client=None):
    return make_application("IncidentLens AI Python", SCHEMA, register, seed, Service,
                            db_path, ai_mode, enable_worker, ai_client)


app = create_app()
