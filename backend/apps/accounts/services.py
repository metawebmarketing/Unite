from apps.accounts.tasks import generate_algorithm_profile


def queue_profile_generation(profile_id: int, region_code: str = "global") -> None:
    try:
        generate_algorithm_profile.delay(profile_id, region_code)
    except Exception:
        # Fallback for local/dev environments without running workers.
        generate_algorithm_profile(profile_id, region_code)
