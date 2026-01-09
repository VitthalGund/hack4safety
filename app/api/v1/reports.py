import logging
import io
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pymongo.database import Database
from app.db.session import get_mongo_db
from app.services.report_service import ReportService  # We will create this
from app.api.v1.auth import get_current_user
from app.models.user_schema import User

router = APIRouter()
log = logging.getLogger(__name__)


@router.get(
    "/generate-report",
    summary="Generate a dynamic PDF report based on user role",
    response_class=StreamingResponse,
)
async def generate_report_endpoint(
    role: str = Query(
        ..., description="Role to generate report for (e.g., 'sp', 'dgp', 'home')"
    ),
    db: Database = Depends(get_mongo_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generates a PDF report tailored to the user's role.
    - **sp**: Generates a district-level report (SP).
    - **dgp**: Generates a state-level strategic report (DGP).
    - **home**: Generates a policy and infrastructure report (Home Dept).
    """

    # Use the user's district if they are an SP
    user_district = None
    if role == "sp":
        # SP role is 'district' or 'police' in your schema
        if current_user.role in ("district", "police"):
            if not current_user.district:
                raise HTTPException(
                    status_code=403, detail="User has no district assigned."
                )
            user_district = current_user.district
        elif current_user.role != "admin":
            raise HTTPException(
                status_code=403, detail="User does not have permission for SP report."
            )

    try:
        service = ReportService(db)
        pdf_bytes = await service.generate_report_pdf(role, user_district)

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={role}_report_{datetime.now().strftime('%Y%m%d')}.pdf"
            },
        )

    except HTTPException as he:
        # Re-raise HTTP exceptions from the service
        raise he
    except Exception as e:
        log.error(f"Error generating report: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Internal server error while generating report."
        )
