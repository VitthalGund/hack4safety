import logging
import copy
import io
import base64
from datetime import datetime
from fastapi import HTTPException
from pymongo.database import Database
import jinja2
from weasyprint import HTML
import matplotlib.pyplot as plt
from typing import Optional, List, Dict, Any

# Import the logic functions from your existing analytics module
from app.api.v1.analytics import (
    get_avg_durations,
    get_performance_ranking,
    get_case_trends,
    get_chargesheet_comparison,
    CONVICTION_PIPELINE_STAGES,
)
from app.db.session import get_mongo_db

log = logging.getLogger(__name__)


class ReportService:
    def __init__(self, db: Database):
        self.db = db
        # Assumes 'templates' folder is in the root, parallel to 'app'
        self.template_loader = jinja2.FileSystemLoader(searchpath="./templates")
        self.template_env = jinja2.Environment(loader=self.template_loader)
        # Add a custom filter for rounding
        self.template_env.filters["round"] = lambda value, precision=1: round(
            value, precision
        )

    def _generate_bar_chart(
        self, labels: list, values: list, title: str, color: str = "#4A90E2"
    ) -> str:
        """
        Generates a simple horizontal bar chart and returns it as a base64 string.
        """
        if not labels or not values:
            return ""
        try:
            plt.switch_backend("Agg")  # Use non-interactive backend
            fig, ax = plt.subplots(figsize=(8, max(4, len(labels) * 0.5)))

            y_pos = range(len(labels))
            ax.barh(y_pos, values, align="center", color=color)
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels)
            ax.invert_yaxis()  # labels read top-to-bottom
            ax.set_xlabel("Total Cases")
            ax.set_title(title)

            # Save to a bytes buffer
            buf = io.BytesIO()
            plt.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)

            # Encode as base64
            img_base64 = base64.b64encode(buf.read()).decode("utf-8")
            return img_base64
        except Exception as e:
            log.error(f"Failed to generate chart: {e}")
            return ""

    async def _get_district_kpis(self, district: Optional[str] = None) -> dict:
        """Helper to get KPIs, filtered by district if provided."""
        pipeline = []
        if district:
            pipeline.append({"$match": {"District": district}})

        # Add duration stages from analytics.py
        pipeline.extend(
            [
                {
                    "$project": {
                        "date_reg": {"$toDate": "$Date_of_Registration"},
                        "date_cs": {"$toDate": "$Date_of_Chargesheet"},
                        "date_judge": {"$toDate": "$Date_of_Judgement"},
                    }
                },
                {
                    "$project": {
                        "investigation_duration_ms": {
                            "$subtract": ["$date_cs", "$date_reg"]
                        },
                        "trial_duration_ms": {"$subtract": ["$date_judge", "$date_cs"]},
                        "total_lifecycle_ms": {
                            "$subtract": ["$date_judge", "$date_reg"]
                        },
                    }
                },
                {
                    "$group": {
                        "_id": None,
                        "avg_investigation_days": {
                            "$avg": {
                                "$divide": [
                                    "$investigation_duration_ms",
                                    1000 * 60 * 60 * 24,
                                ]
                            }
                        },
                        "avg_trial_days": {
                            "$avg": {
                                "$divide": ["$trial_duration_ms", 1000 * 60 * 60 * 24]
                            }
                        },
                        "avg_lifecycle_days": {
                            "$avg": {
                                "$divide": ["$total_lifecycle_ms", 1000 * 60 * 60 * 24]
                            }
                        },
                    }
                },
            ]
        )

        result = list(self.db["conviction_cases"].aggregate(pipeline))
        if not result:
            return {
                "avg_investigation_days": 0,
                "avg_trial_days": 0,
                "avg_lifecycle_days": 0,
            }

        # Get conviction rate
        rate_pipeline = []
        if district:
            rate_pipeline.append({"$match": {"District": district}})

        rate_pipeline.extend(
            [
                {"$match": {"Result": {"$in": ["Convicted", "Acquitted"]}}},
                {
                    "$group": {
                        "_id": None,
                        "total_convictions": {
                            "$sum": {"$cond": [{"$eq": ["$Result", "Convicted"]}, 1, 0]}
                        },
                        "total_cases": {"$sum": 1},
                    }
                },
                {
                    "$project": {
                        "conviction_rate": {
                            "$cond": [
                                {"$eq": ["$total_cases", 0]},
                                0,
                                {"$divide": ["$total_convictions", "$total_cases"]},
                            ]
                        }
                    }
                },
            ]
        )

        rate_result = list(self.db["conviction_cases"].aggregate(rate_pipeline))
        final_result = result[0]
        final_result["conviction_rate"] = (
            (rate_result[0].get("conviction_rate", 0) * 100) if rate_result else 0
        )

        return final_result

    async def _get_sp_report_data(self, user_district: str) -> dict:
        """Fetches all data required for the SP report."""

        kpis = await self._get_district_kpis(user_district)

        # Get Rankings
        # This function needs to be adapted to accept a district filter
        # For now, we call it as-is, but this is a limitation.
        rankings = await get_performance_ranking(self.db, "Investigating_Officer", 0, 5)

        # Get Top Acquittal Reasons
        acquittal_pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)
        acquittal_pipeline[0]["$match"]["District"] = user_district
        acquittal_pipeline[1]["$group"]["_id"] = "$Delay_Reason"
        acquittal_pipeline[4]["$sort"] = {"total_acquittals": -1}
        acquittal_pipeline.append({"$limit": 5})

        acquittal_data = list(self.db["conviction_cases"].aggregate(acquittal_pipeline))

        chart_labels = [
            item.get("_id", "Unknown") or "Unknown" for item in acquittal_data
        ]
        chart_values = [item.get("total_acquittals", 0) for item in acquittal_data]
        acquittal_chart = self._generate_bar_chart(
            chart_labels, chart_values, "Top 5 Acquittal Reasons", color="#DC2626"
        )

        return {
            "title": f"Superintendent Report ({user_district})",
            "generation_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "district": user_district,
            "kpis": kpis,
            "rankings": rankings,
            "acquittal_chart_base64": acquittal_chart,
        }

    async def _get_dgp_report_data(self) -> dict:
        """Fetches all data required for the DGP report."""
        kpis = await self._get_district_kpis(None)  # State-level
        rankings = await get_performance_ranking(self.db, "District", 0, 10)

        # Generate chart for district rankings
        chart_labels = [item.get("police_station", "Unknown") for item in rankings]
        chart_values = [(item.get("conviction_rate", 0) * 100) for item in rankings]
        ranking_chart = self._generate_bar_chart(
            chart_labels, chart_values, "Top 10 Districts by Conviction Rate"
        )

        return {
            "title": "DGP Strategic Report",
            "generation_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "kpis": kpis,
            "ranking_chart_base64": ranking_chart,
        }

    async def _get_home_report_data(self) -> dict:
        """Fetches all data required for the Home Dept. report."""
        kpis = await self._get_district_kpis(None)  # State-level

        # Get bottleneck data
        bottleneck_pipeline = copy.deepcopy(CONVICTION_PIPELINE_STAGES)
        bottleneck_pipeline[1]["$group"]["_id"] = "$Court_Name"
        bottleneck_pipeline[4]["$sort"] = {"total_cases": -1}  # Sort by load
        bottleneck_pipeline.append({"$limit": 10})

        bottlenecks = list(self.db["conviction_cases"].aggregate(bottleneck_pipeline))

        return {
            "title": "Home Department Policy Report",
            "generation_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "kpis": kpis,
            "bottlenecks": bottlenecks,
        }

    async def generate_report_pdf(
        self, role: str, user_district: Optional[str]
    ) -> bytes:
        """
        Dynamically generates the correct PDF report based on user role.
        """
        template_name = ""
        context = {}

        if role == "sp":
            template_name = "sp_report.html"
            context = await self._get_sp_report_data(user_district)

        elif role == "dgp":
            template_name = "dgp_report.html"
            context = await self._get_dgp_report_data()

        elif role == "home":
            template_name = "home_report.html"
            context = await self._get_home_report_data()

        else:
            raise HTTPException(status_code=400, detail=f"Invalid report role: {role}")

        try:
            template = self.template_env.get_template(template_name)
            html_out = template.render(context)

            # Generate PDF
            pdf_bytes = HTML(string=html_out).write_pdf()
            return pdf_bytes
        except jinja2.TemplateNotFound:
            log.error(f"Report template not found: {template_name}")
            raise HTTPException(
                status_code=500, detail=f"Report template not found: {template_name}"
            )
        except Exception as e:
            log.error(f"PDF generation failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")
