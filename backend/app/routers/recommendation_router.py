from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_admin, require_staff
from ..database import get_db
from ..models import User
from ..services import recommendation_service as rec

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("")
def list_recommendations(user: User = Depends(require_staff), db: Session = Depends(get_db)):
    items = rec.build(db)
    log = rec.activity(db)
    return {
        "items": items,
        "open": sum(1 for r in items if not r["dismissed"]),
        "activity": [{"action": a.action, "summary": a.summary, "actor_email": a.actor_email, "autopilot": a.autopilot,
                      "created_at": a.created_at} for a in log],
    }


@router.post("/{key}/run")
def run_recommendation(key: str, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    return rec.execute(db, key, user)


@router.post("/{key}/dismiss")
def dismiss_recommendation(key: str, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    rec.dismiss(db, key)
    return {"key": key, "dismissed": True}


@router.post("/{key}/restore")
def restore_recommendation(key: str, user: User = Depends(require_staff), db: Session = Depends(get_db)):
    rec.restore(db, key)
    return {"key": key, "dismissed": False}


@router.post("/autopilot")
def run_autopilot(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Run every low-risk action (reminders, follow-ups, confirming drafts, billing). Admin only."""
    done = rec.autopilot(db, admin)
    return {"actions": done}
