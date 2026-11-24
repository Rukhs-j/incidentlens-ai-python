from typing import Literal
import hashlib
import re
from pydantic import Field
from core import InputModel, Problem, new_id, now, text

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
 ID TEXT PRIMARY KEY,FINGERPRINT TEXT UNIQUE,EXAMPLE TEXT,SEVERITY TEXT,
 OCCURRENCES INTEGER,STATUS TEXT,FIRST_SEEN TEXT,LAST_SEEN TEXT
);
CREATE TABLE IF NOT EXISTS incident_events (
 ID TEXT PRIMARY KEY,INCIDENT_ID TEXT REFERENCES incidents(ID),ACTOR TEXT,EVENT TEXT,CREATED_AT TEXT
);
"""


class LogInput(InputModel):
    lines: list[str] = Field(min_length=1, max_length=500)


class StatusInput(InputModel):
    status: Literal["OPEN", "INVESTIGATING", "RESOLVED"]


def seed(db, kb):
    if db.one("SELECT COUNT(*) AS TOTAL FROM documents")["TOTAL"] == 0:
        kb.add("public","Database connection timeout runbook",
               "For database connection timeout errors, inspect connection pool saturation, slow queries, and database reachability. Check metrics before increasing the pool size. A timeout alone does not prove a root cause.")
        kb.add("public","Python transaction runbook",
               "For a SQLite database locked error, inspect long-running write transactions, connection lifetime, and busy timeout. Keep external HTTP requests outside write transactions. Roll back failed business operations and add a regression test.")
        kb.add("public","Memory pressure runbook",
               "For MemoryError or OutOfMemoryError, inspect memory usage and authorized diagnostics. Look for unbounded caches and unexpectedly large inputs. Avoid blindly increasing memory without diagnosis.")


class Service:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def fingerprint(content: str):
        normalized = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "<id>", content.casefold())
        normalized = re.sub(r"\b\d+\b", "<n>", normalized)
        normalized = " ".join(normalized.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def event(connection, incident_id, actor, event):
        connection.execute("INSERT INTO incident_events VALUES(?,?,?,?,?)", (new_id(),incident_id,actor,event,now()))

    def ingest(self, lines: list[str], actor: str):
        if not lines or len(lines)>500:
            raise Problem(400, "Provide 1 to 500 log lines")
        ids = []
        with self.db.transaction() as connection:
            for line in lines:
                line = text(line,2000,"log line")
                fingerprint = self.fingerprint(line)
                found = connection.execute("SELECT ID FROM incidents WHERE FINGERPRINT=?", (fingerprint,)).fetchone()
                if found:
                    incident_id = found["ID"]
                    connection.execute("""
                        UPDATE incidents SET OCCURRENCES=OCCURRENCES+1,LAST_SEEN=?,
                        STATUS=CASE WHEN STATUS='RESOLVED' THEN 'OPEN' ELSE STATUS END WHERE ID=?
                    """, (now(),incident_id))
                else:
                    incident_id = new_id()
                    severity = "ERROR" if "ERROR" in line.upper() else "WARN"
                    connection.execute("INSERT INTO incidents VALUES(?,?,?,?,1,'OPEN',?,?)",
                                       (incident_id,fingerprint,line,severity,now(),now()))
                ids.append(incident_id)
                self.event(connection,incident_id,actor,"Ingested occurrence")
        return {"ingested": len(lines), "incidentIds": ids}

    def update(self, incident_id: str, status: str, actor: str):
        with self.db.transaction() as connection:
            changed = connection.execute("UPDATE incidents SET STATUS=? WHERE ID=?", (status,incident_id)).rowcount
            if changed != 1:
                raise Problem(404, "Incident not found")
            self.event(connection,incident_id,actor,"Status -> "+status)
        return {"updated": True}
