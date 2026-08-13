import app as app_module


class SuccessfulPoliceDataService:
    def get_forces(self):
        return [
            {"id": "metropolitan", "name": "Metropolitan Police Service"},
            {"id": "avon-and-somerset", "name": "Avon and Somerset Constabulary"},
        ]


class UnavailablePoliceDataService:
    def get_forces(self):
        return None


def test_list_forces_returns_the_service_result_as_json():
    application = app_module.create_app(
        police_service=SuccessfulPoliceDataService()
    )

    response = application.test_client().get("/api/forces")

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.get_json() == [
        {"id": "metropolitan", "name": "Metropolitan Police Service"},
        {"id": "avon-and-somerset", "name": "Avon and Somerset Constabulary"},
    ]


def test_list_forces_reports_when_the_police_service_is_unavailable():
    application = app_module.create_app(
        police_service=UnavailablePoliceDataService()
    )

    response = application.test_client().get("/api/forces")

    assert response.status_code == 502
    assert response.content_type == "application/json"
    assert response.get_json() == {
        "error": {
            "code": "upstream_unavailable",
            "message": "Police force data is temporarily unavailable.",
        }
    }
