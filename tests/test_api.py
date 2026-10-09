import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import app.main as app_module

client = TestClient(app_module.app)


def reset_db():
    app_module.db.attendance_logs.delete_many({})
    app_module.db.employees.delete_many({})
    app_module.db.employees.insert_many([
        {
            "emp_code": "EMP0001",
            "name": "Asha Rao",
            "email": "asha@example.com",
            "department": "Engineering",
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-01-05",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        },
        {
            "emp_code": "EMP0002",
            "name": "Vikram Shah",
            "email": "vikram@example.com",
            "department": "Engineering",
            "shift_start": "09:30",
            "shift_end": "18:30",
            "joined_on": "2026-07-13",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        },
    ])


def test_health():
    reset_db()
    with TestClient(app_module.app) as startup_client:
        resp = startup_client.get('/health')
        assert resp.status_code == 200


def test_create_employee_and_list():
    reset_db()
    resp = client.post('/employees', json={
        'emp_code': 'EMP0003',
        'name': 'Neha Iyer',
        'email': 'neha@example.com',
        'department': 'Sales',
        'shift_start': '09:30',
        'shift_end': '18:30',
        'joined_on': '2026-07-01',
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data['emp_code'] == 'EMP0003'
    resp = client.get('/employees')
    assert resp.status_code == 200
    assert resp.json()['total'] >= 3


def test_punch_in_and_out():
    reset_db()
    ts = datetime.datetime(2026, 7, 6, 3, 58, tzinfo=datetime.timezone.utc).timestamp() * 1000
    resp = client.post('/attendance/punch-in', json={'emp_code': 'EMP0001', 'punched_at': int(ts), 'status': 'PRESENT'})
    assert resp.status_code == 201
    out_ts = datetime.datetime(2026, 7, 6, 13, 5, tzinfo=datetime.timezone.utc).timestamp() * 1000
    resp = client.post('/attendance/punch-out', json={'emp_code': 'EMP0001', 'punched_at': int(out_ts)})
    assert resp.status_code == 200
    assert resp.json()['status'] == 'PRESENT'


@pytest.mark.parametrize(
    ('seconds_after_start', 'expected_late_minutes'),
    [(600, 0), (601, 10), (2759, 45)],
)
def test_late_grace_period_boundary(seconds_after_start, expected_late_minutes):
    from app.main import compute_late_minutes

    punch_in = datetime.datetime(2026, 7, 6, 4, 0, tzinfo=datetime.timezone.utc)
    punch_in += datetime.timedelta(seconds=seconds_after_start)

    assert compute_late_minutes(punch_in, '09:30', '18:30') == expected_late_minutes


def test_work_hours_round_half_up_and_half_day_uses_rounded_value():
    from app.main import compute_work_hours, recompute_derived_fields

    start = datetime.datetime(2026, 7, 6, 4, 0, tzinfo=datetime.timezone.utc)
    assert compute_work_hours(start, start + datetime.timedelta(seconds=3618)) == 1.01
    record = {
        'date': '2026-07-06',
        'status': 'PRESENT',
        'punch_in': start,
        'punch_out': start + datetime.timedelta(hours=4, minutes=29, seconds=59),
    }
    employee = {'shift_start': '09:30', 'shift_end': '18:30'}

    recompute_derived_fields(record, employee)

    assert record['work_hours'] == 4.50
    assert record['half_day'] is False


def test_punch_out_updates_seeded_open_record_without_version():
    reset_db()
    punch_in = datetime.datetime(2026, 7, 6, 3, 58, tzinfo=datetime.timezone.utc)
    app_module.db.attendance_logs.insert_one({
        'emp_code': 'EMP0001',
        'date': '2026-07-06',
        'status': 'PRESENT',
        'punch_in': punch_in,
        'punch_out': None,
        'work_hours': None,
        'late_minutes': 0,
        'overtime_minutes': 0,
        'half_day': False,
        'history': [],
    })
    punched_at = int(datetime.datetime(2026, 7, 6, 13, 5, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    resp = client.post('/attendance/punch-out', json={
        'emp_code': 'EMP0001',
        'punched_at': punched_at,
    })

    assert resp.status_code == 200
    assert resp.json()['work_hours'] == 9.12


def test_concurrent_duplicate_punch_ins_have_one_winner():
    reset_db()
    timestamp = int(datetime.datetime(2026, 7, 6, 4, 0, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    def punch_in():
        with TestClient(app_module.app) as request_client:
            return request_client.post('/attendance/punch-in', json={
                'emp_code': 'EMP0001',
                'punched_at': timestamp,
            }).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: punch_in(), range(2)))

    assert sorted(results) == [201, 409]


def test_concurrent_duplicate_employee_creates_have_one_winner():
    reset_db()
    payload = {
        'emp_code': 'EMP0003',
        'name': 'Neha Iyer',
        'email': 'neha@example.com',
        'department': 'Sales',
        'joined_on': '2026-07-01',
    }

    def create_employee():
        with TestClient(app_module.app) as request_client:
            return request_client.post('/employees', json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_employee(), range(2)))

    assert sorted(results) == [201, 409]


def test_overnight_shift_keeps_attendance_date_and_counts_overtime():
    reset_db()
    app_module.db.employees.update_one(
        {'emp_code': 'EMP0001'},
        {'$set': {'shift_start': '22:00', 'shift_end': '06:00'}},
    )
    punch_in = int(datetime.datetime(2026, 7, 6, 19, 30, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    punch_out = int(datetime.datetime(2026, 7, 7, 1, 15, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    in_resp = client.post('/attendance/punch-in', json={
        'emp_code': 'EMP0001',
        'punched_at': punch_in,
    })
    out_resp = client.post('/attendance/punch-out', json={
        'emp_code': 'EMP0001',
        'punched_at': punch_out,
    })

    assert in_resp.status_code == 201
    assert in_resp.json()['date'] == '2026-07-06'
    assert in_resp.json()['late_minutes'] == 180
    assert out_resp.status_code == 200
    assert out_resp.json()['work_hours'] == 5.75
    assert out_resp.json()['overtime_minutes'] == 45


def test_employee_monthly_summary(monkeypatch):
    reset_db()
    def aggregate(pipeline):
        assert pipeline[0]['$match'] == {
            'emp_code': 'EMP0001',
            'date': {'$gte': '2026-07-01', '$lt': '2026-08-01'},
        }
        return iter([{
            '_id': None,
            'present_days': 1,
            'leave_days': 0,
            'late_count': 0,
            'total_late_minutes': 0,
            'total_overtime_minutes': 0,
        }])

    monkeypatch.setattr(app_module.db.attendance_logs, 'aggregate', aggregate)
    resp = client.get('/analytics/employees/EMP0001/monthly?month=2026-07')
    assert resp.status_code == 200
    assert resp.json()['emp_code'] == 'EMP0001'
    assert resp.json()['present_days'] == 1


def test_employee_code_matches_contract():
    resp = client.post('/employees', json={
        'emp_code': 'EMP1234567',
        'name': 'Too Long',
        'email': 'long@example.com',
        'department': 'Sales',
        'joined_on': '2026-07-01',
    })
    assert resp.status_code == 422


def test_punch_rejects_float_epoch_milliseconds():
    reset_db()
    resp = client.post('/attendance/punch-in', json={
        'emp_code': 'EMP0001',
        'punched_at': 1783312500000.0,
    })
    assert resp.status_code == 422


def test_month_bounds_do_not_include_the_next_month():
    from app.main import month_bounds

    assert month_bounds('2026-07') == ('2026-07-01', '2026-08-01')


def test_trend_pipeline_uses_mongo_gap_filling_and_window():
    from app.main import department_trend_pipeline

    pipeline = department_trend_pipeline('Engineering', '2026-07-06', '2026-07-12')

    assert '$documents' in pipeline[0]
    assert any('$densify' in stage for stage in pipeline)
    assert any('$setWindowFields' in stage for stage in pipeline)


def test_aggregation_explain_uses_execution_stats(monkeypatch):
    calls = []

    def command(*args, **kwargs):
        calls.append((args, kwargs))
        return {'queryPlanner': {}, 'executionStats': {}}

    monkeypatch.setattr(app_module.db, 'command', command)

    result = app_module.explain_aggregation('attendance_logs', [{'$match': {'emp_code': 'EMP0001'}}])

    assert result['executionStats'] == {}
    assert calls[0][0][0] == 'explain'
    assert calls[0][0][1]['aggregate'] == 'attendance_logs'
    assert calls[0][1]['verbosity'] == 'executionStats'


def test_regularization_history_stores_dates_as_bson_datetimes():
    reset_db()
    app_module.db.attendance_logs.insert_one({
        'emp_code': 'EMP0001',
        'date': '2026-07-06',
        'status': 'PRESENT',
        'punch_in': datetime.datetime(2026, 7, 6, 4, 35, tzinfo=datetime.timezone.utc),
        'punch_out': datetime.datetime(2026, 7, 6, 13, 40, tzinfo=datetime.timezone.utc),
        'work_hours': 9.08,
        'late_minutes': 35,
        'overtime_minutes': 40,
        'half_day': False,
        'history': [],
    })
    earlier_punch_in = int(datetime.datetime(2026, 7, 6, 3, 58, tzinfo=datetime.timezone.utc).timestamp() * 1000)

    resp = client.patch('/attendance/EMP0001/2026-07-06', json={
        'punch_in': earlier_punch_in,
        'reason': 'Correct punch time',
        'regularized_by': 'HR',
    })

    assert resp.status_code == 200
    history = resp.json()['history'][0]['changes']
    assert history['punch_in']['from'] == 1783312500000
    assert history['punch_in']['to'] == 1783310280000
    stored = app_module.db.attendance_logs.find_one({'emp_code': 'EMP0001'})
    assert isinstance(stored['history'][0]['changes']['punch_in']['from'], datetime.datetime)


@pytest.mark.parametrize(
    ('seconds_after_shift_end', 'expected_overtime'),
    [(1799, 0), (1800, 30), (1859, 30)],
)
def test_overtime_minimum_threshold(seconds_after_shift_end, expected_overtime):
    from app.main import recompute_derived_fields

    punch_in = datetime.datetime(2026, 7, 6, 4, 0, tzinfo=datetime.timezone.utc)
    shift_end = datetime.datetime(2026, 7, 6, 13, 0, tzinfo=datetime.timezone.utc)
    punch_out = shift_end + datetime.timedelta(seconds=seconds_after_shift_end)
    record = {
        'date': '2026-07-06',
        'status': 'PRESENT',
        'punch_in': punch_in,
        'punch_out': punch_out,
    }

    recompute_derived_fields(record, {'shift_start': '09:30', 'shift_end': '18:30'})

    assert record['overtime_minutes'] == expected_overtime


def test_attendance_list_filters_and_paginates():
    reset_db()
    app_module.db.attendance_logs.insert_many([
        {'emp_code': 'EMP0001', 'date': '2026-07-06', 'status': 'PRESENT', 'history': []},
        {'emp_code': 'EMP0001', 'date': '2026-07-07', 'status': 'PRESENT', 'history': []},
        {'emp_code': 'EMP0001', 'date': '2026-07-08', 'status': 'LEAVE', 'history': []},
        {'emp_code': 'EMP0002', 'date': '2026-07-07', 'status': 'PRESENT', 'history': []},
    ])

    resp = client.get(
        '/attendance?emp_code=EMP0001&date_from=2026-07-06&date_to=2026-07-07'
        '&status=PRESENT&page=2&page_size=1'
    )

    assert resp.status_code == 200
    assert resp.json()['total'] == 2
    assert resp.json()['items'][0]['date'] == '2026-07-06'


def test_attendance_list_rejects_reversed_date_range():
    resp = client.get('/attendance?date_from=2026-07-08&date_to=2026-07-06')

    assert resp.status_code == 422


def test_missing_employee_and_record_return_not_found():
    reset_db()

    assert client.post('/attendance/punch-in', json={'emp_code': 'EMP9999'}).status_code == 404
    assert client.get('/analytics/employees/EMP9999/monthly?month=2026-07').status_code == 404
    assert client.patch(
        '/attendance/EMP0001/2026-07-06',
        json={'reason': 'Correct attendance', 'regularized_by': 'HR'},
    ).status_code == 404


def test_analytics_pipelines_preserve_headcount_and_competition_ranks():
    from app.main import department_summary_pipeline, late_leaderboard_pipeline, mongo_round_half_up

    summary_pipeline = department_summary_pipeline('2026-07-01', '2026-08-01', 'Engineering')
    assert summary_pipeline[0] == {
        '$match': {'joined_on': {'$lt': '2026-08-01'}, 'department': 'Engineering'},
    }
    assert summary_pipeline[1]['$lookup']['from'] == 'attendance_logs'
    default_metrics = summary_pipeline[2]['$set']['metrics']['$ifNull'][1]
    assert default_metrics['present_days'] == 0
    assert default_metrics['leave_count'] == 0

    leaderboard_pipeline = late_leaderboard_pipeline('2026-07-01', '2026-08-01', 2)
    rank_index = next(i for i, stage in enumerate(leaderboard_pipeline) if '$setWindowFields' in stage)
    assert leaderboard_pipeline[rank_index]['$setWindowFields']['sortBy'] == {'total_late_minutes': -1}
    assert leaderboard_pipeline[rank_index + 1] == {'$match': {'rank': {'$lte': 2}}}
    assert leaderboard_pipeline[-1]['$sort'] == {'total_late_minutes': -1, 'emp_code': 1}
    assert mongo_round_half_up(1, 4)['$divide'][0]['$floor']['$add'][1] == {'$toDecimal': '0.5'}


def test_explain_route_uses_employee_monthly_pipeline(monkeypatch):
    calls = []

    def explain(collection, pipeline):
        calls.append((collection, pipeline))
        return {'executionStats': {}}

    from app.api.routers import admin as admin_router

    monkeypatch.setattr(admin_router, 'explain_aggregation', explain)

    resp = client.get('/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07')

    assert resp.status_code == 200
    assert resp.json()['collection'] == 'attendance_logs'
    assert calls[0][0] == 'attendance_logs'
    assert calls[0][1][0]['$match'] == {
        'emp_code': 'EMP0001',
        'date': {'$gte': '2026-07-01', '$lt': '2026-08-01'},
    }
    assert client.get('/admin/explain/employee_monthly').status_code == 422


def test_department_trend_validates_range_and_department():
    reset_db()

    too_long = client.get(
        '/analytics/departments/Engineering/trend?from=2026-01-01&to=2026-04-03',
    )
    unknown_department = client.get(
        '/analytics/departments/Unknown/trend?from=2026-07-01&to=2026-07-02',
    )

    assert too_long.status_code == 422
    assert unknown_department.status_code == 404
