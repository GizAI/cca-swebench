from confucius.analects.code.tasks import get_task_definition


def test_task_definition_includes_cwd() -> None:
    task = get_task_definition(
        current_time="2026-02-18T13:00:00",
        current_working_directory="/home/user/ark",
    )
    assert "Current time: 2026-02-18T13:00:00" in task
    assert "Current working directory: /home/user/ark" in task
    assert "{current_working_directory}" not in task
