# Database schema

SQLAlchemy 2.0 models live in `backend/app/models/`. Tables are created by
`python scripts/setup/init_db.py` (or automatically at API start-up when
`AUTO_CREATE_TABLES=true`). Enum columns are stored as `VARCHAR(32)` with a
CHECK constraint so the same schema works on SQLite and PostgreSQL. All
timestamps are UTC.

```mermaid
erDiagram
    USERS ||--o{ ALERTS : acknowledges
    USERS ||--o{ SYSTEM_LOGS : performs
    LOCATIONS ||--o{ CAMERAS : hosts
    LOCATIONS ||--o{ INCIDENTS : "occurs at"
    CAMERAS ||--o{ INCIDENTS : observes
    CAMERAS ||--o{ DETECTIONS : produces
    INCIDENTS ||--o{ DETECTIONS : "supported by"
    INCIDENTS ||--o{ ALERTS : raises
    INCIDENTS ||--o{ RESPONSE_ACTIONS : recommends

    USERS {
        int id PK
        string name
        string email UK
        string password_hash
        enum role "ADMIN|OPERATOR|VIEWER"
        bool is_active
        datetime created_at
    }
    LOCATIONS {
        int id PK
        string name UK
        string address
        float latitude "CHECK -90..90"
        float longitude "CHECK -180..180"
        datetime created_at
    }
    CAMERAS {
        int id PK
        string name UK
        enum source_type "FILE|WEBCAM|RTSP"
        string source_uri "masked in API output"
        int location_id FK
        enum status "UNKNOWN|ONLINE|OFFLINE|ERROR"
        datetime last_seen_at
        string last_error
        datetime created_at
        datetime updated_at
    }
    INCIDENTS {
        int id PK
        enum incident_type
        enum severity
        float risk_score "NULL for manual"
        enum status
        enum source "AI_MODEL|DEMO_HEURISTIC|MANUAL"
        int camera_id FK
        int location_id FK
        text description
        string source_label
        datetime detection_timestamp
        datetime last_detection_at
        float peak_confidence
        int frames_observed
        datetime created_at
        datetime updated_at
    }
    DETECTIONS {
        int id PK
        int incident_id FK
        int camera_id FK
        string object_class
        string raw_label
        float confidence
        json bbox "x1,y1,x2,y2"
        int frame_number
        float video_time_s
        bool is_demo
        datetime timestamp
    }
    ALERTS {
        int id PK
        int incident_id FK
        enum alert_type
        enum severity
        text message
        string channel "DASHBOARD"
        enum status "UNACKNOWLEDGED|ACKNOWLEDGED"
        datetime created_at
        datetime acknowledged_at
        int acknowledged_by FK
    }
    RESPONSE_ACTIONS {
        int id PK
        int incident_id FK
        string recommended_department
        text recommended_action
        enum priority "P1..P4"
        enum status
        string dispatch_status "NOT_DISPATCHED"
        datetime created_at
        datetime updated_at
    }
    SYSTEM_LOGS {
        int id PK
        int user_id FK
        string action
        string module
        enum status
        text message
        string entity_type
        int entity_id
        datetime timestamp
    }
```

## Additions beyond the specification (and why)

| Column | Reason |
|---|---|
| `users.is_active` | disable an account without deleting its audit history |
| `cameras.source_type`, `last_seen_at`, `last_error` | validate sources and explain camera status |
| `incidents.source` | separates trained-model, demo-heuristic and manual incidents |
| `incidents.last_detection_at`, `frames_observed`, `peak_confidence`, `source_label` | duplicate prevention and escalation |
| `detections.raw_label`, `video_time_s`, `is_demo` | traceability back to the model output |
| `alerts.severity`, `channel`, `acknowledged_by` | filtering and accountability |
| `response_actions.dispatch_status` | always `NOT_DISPATCHED` - makes the advisory nature explicit |
| `system_logs.entity_type`, `entity_id` | per-incident history timeline |

## Referential actions

* Deleting an incident cascades to its detections, alerts and response actions.
* Deleting a camera or location sets `camera_id` / `location_id` to NULL so incident history survives.

## Indexes

`users.email` (unique), `cameras.status`, `cameras.location_id`, `incidents.incident_type`,
`incidents.severity`, `incidents.status`, `incidents.location_id`, `incidents.created_at`,
composite `ix_incident_dedup (camera_id, incident_type, status, last_detection_at)`,
`detections.incident_id`, `detections.camera_id`, `alerts.incident_id`, `alerts.status`,
`response_actions.incident_id`, `system_logs.timestamp`, `ix_log_entity (entity_type, entity_id)`.

## PostgreSQL

Set `DATABASE_URL=postgresql+psycopg://user:password@host:5432/sentinel` and
`pip install "psycopg[binary]"`. For schema changes after the first release,
introduce Alembic migrations instead of `create_all`.
