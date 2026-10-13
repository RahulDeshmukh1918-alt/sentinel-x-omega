"""Seed demo locations and cameras (no fake incidents are inserted).

    python scripts/setup/seed_demo.py

Creates:
  * two example locations in Pune (coordinates are illustrative)
  * "Demo Feed - Synthetic" : FILE camera playing data/sample_videos/synthetic_fire_demo.mp4
  * "Lab Webcam"            : WEBCAM camera on device 0 (works only if a webcam exists)

Incidents only appear after you run detection (dashboard -> Live monitoring -> Start).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.enums import SourceType  # noqa: E402
from backend.app.database.connection import get_session_factory, init_db  # noqa: E402
from backend.app.models import Camera, Location  # noqa: E402
from scripts.setup.generate_sample_video import generate  # noqa: E402

LOCATIONS = [
    ("College Campus - Main Gate", "Example address, Pune", 18.5204, 73.8567),
    ("Electrical Substation Yard", "Example address, Pune", 18.5310, 73.8446),
]


def main() -> int:
    settings = get_settings()
    video = settings.sample_video_path / "synthetic_fire_demo.mp4"
    if not video.exists():
        generate(video)
        print(f"generated {video.relative_to(ROOT) if video.is_relative_to(ROOT) else video}")
    init_db()
    with get_session_factory()() as s:
        locs = {}
        for name, address, lat, lon in LOCATIONS:
            loc = s.scalars(select(Location).where(Location.name == name)).first()
            if loc is None:
                loc = Location(name=name, address=address, latitude=lat, longitude=lon)
                s.add(loc)
                s.flush()
                print(f"location: {name}")
            locs[name] = loc
        cameras = [
            ("Demo Feed - Synthetic", SourceType.FILE, video.name, LOCATIONS[0][0]),
            ("Lab Webcam", SourceType.WEBCAM, "0", LOCATIONS[1][0]),
        ]
        for name, stype, uri, loc_name in cameras:
            if s.scalars(select(Camera).where(Camera.name == name)).first() is None:
                s.add(Camera(name=name, source_type=stype, source_uri=uri, location_id=locs[loc_name].id))
                print(f"camera: {name} ({stype.value} {uri})")
        s.commit()
    print("done - start the server and open http://localhost:8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
